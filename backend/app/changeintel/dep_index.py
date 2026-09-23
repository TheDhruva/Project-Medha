"""Dependency index: import/reference edges with concrete evidence (Phase 2).

Produces candidate CIG edges of the form (source artifact → target artifact),
where source depends on target. Every edge carries the provenance line
(`path:line <construct> <module>`) plus a confidence:
  HIGH      — Python `ast`-verified import resolved to a repository file
  MEDIUM    — config/JSON/YAML reference or heuristic file-pattern relationship
  HEURISTIC — regex-based JS/TS extraction (best effort)
Dependencies that cannot be resolved to a repository file are surfaced as
UnresolvedDependency entries — they are never invented as edges.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field

from app.changeintel.models import (
    Confidence,
    FileSymbols,
    ImpactEdge,
    Language,
    RelationshipType,
    UnresolvedDependency,
)
from app.changeintel.symbols import (
    resolve_import,
    source_files,
)

_SCHEMA_MARKERS = {"schema", "schemas", "models", "model", "db", "database", "persistence", "tables"}


@dataclass
class EdgeCandidate:
    source: str  # repo-relative path (or symbol id) that declares the dependency
    target: str  # repo-relative path it depends on
    relationship: RelationshipType
    confidence: Confidence
    evidence: str
    line: int = 0


@dataclass
class DependencyIndex:
    files: dict[str, FileSymbols] = field(default_factory=dict)
    contents: dict[str, str] = field(default_factory=dict)

    @property
    def py_files(self) -> set[str]:
        return {p for p, f in self.files.items() if f.language == Language.PYTHON}

    @property
    def js_files(self) -> set[str]:
        return {
            p
            for p, f in self.files.items()
            if f.language in {Language.JAVASCRIPT, Language.TYPESCRIPT}
        }

    def get(self, path: str) -> FileSymbols | None:
        return self.files.get(path)


def build_index(root, backend_paths: list[str] | None = None) -> DependencyIndex:
    """Parse all supported files under root into a DependencyIndex."""
    paths = backend_paths or source_files(root)
    index = DependencyIndex()
    for rel in sorted(paths):
        full = root / rel
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        index.contents[rel] = content
        index.files[rel] = _parse(rel, content)
    return index


def index_file(index: DependencyIndex, rel_path: str, content: str) -> FileSymbols:
    parsed = _parse(rel_path, content)
    index.files[rel_path] = parsed
    index.contents[rel_path] = content
    return parsed


def _parse(rel_path: str, content: str) -> FileSymbols:
    from app.changeintel.symbols import extract_file_symbols

    return extract_file_symbols(rel_path, content)


def is_test_file(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    if parts and parts[0] in {"tests", "test"}:
        return True
    name = parts[-1] if parts else path
    low = name.lower()
    return low.startswith("test_") or low.endswith("_test") or low.endswith(".test")


def is_config_file(path: str) -> bool:
    from app.changeintel.models import Language

    return path.endswith((".json", ".yml", ".yaml"))


def compute_dependency_edges(
    index: DependencyIndex,
    deleted_paths: set[str] | None = None,
) -> tuple[list[EdgeCandidate], list[UnresolvedDependency]]:
    """Analyze every indexed file and return declarable edges + unresolved deps."""
    edges: list[EdgeCandidate] = []
    unresolved: list[UnresolvedDependency] = []

    for path, file_symbols in sorted(index.files.items()):
        language = file_symbols.language
        if language == Language.PYTHON:
            _python_edges(path, file_symbols, index, edges, unresolved, deleted_paths or set())
        elif language in {Language.JAVASCRIPT, Language.TYPESCRIPT}:
            _js_edges(path, file_symbols, index, edges, unresolved)
        elif language in {Language.JSON, Language.YAML}:
            _config_edges(path, index, edges)

    edges.extend(compute_inheritance_edges(index, deleted_paths=deleted_paths))
    return _dedupe(edges), _dedupe_unresolved(unresolved)


def compute_inheritance_edges(index: DependencyIndex, deleted_paths: set[str] | None = None) -> list[EdgeCandidate]:
    """Python AST: class bases that reference imported names → INHERITS edges.

    Deterministic, source-verifiable: evidence is `path:line class X(Base)`.
    """
    import ast

    from app.changeintel.symbols import resolve_import

    edges: list[EdgeCandidate] = []
    for path, fs in sorted(index.files.items()):
        if fs.language != Language.PYTHON:
            continue
        content = index.contents.get(path, "")
        if not content:
            continue
        try:
            tree = ast.parse(content)
        except (SyntaxError, ValueError):
            continue
        imported: dict[str, str] = {}
        imported_module: set[str] = set()
        for imp in fs.imports:
            if imp.module.startswith("."):
                continue
            short = imp.module.split(".")[0]
            imported_module.add(short)
            for name in imp.names:
                imported[name] = imp.module
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef) or not node.bases:
                continue
            for base in node.bases:
                base_name = base.id if isinstance(base, ast.Name) else None
                if base_name is None:
                    continue
                module = imported.get(base_name)
                if module is None:
                    continue
                candidates = resolve_import(module, path, index.py_files, index.js_files)
                if not candidates:
                    if deleted_paths and _deleted_candidate(module, deleted_paths):
                        continue
                    continue
                target = _pick_candidate(path, candidates)
                edges.append(
                    EdgeCandidate(
                        source=path,
                        target=target,
                        relationship=RelationshipType.INHERITS,
                        confidence=Confidence.HIGH,
                        evidence=f"{path}:{node.lineno} class {node.name}({base_name})",
                        line=node.lineno,
                    )
                )
    return edges


def _deleted_candidate(module: str, deleted_paths: set[str]) -> bool:
    return module in deleted_paths or any(module == p.split(".")[0] for p in deleted_paths)


def _python_edges(
    path: str,
    fs: FileSymbols,
    index: DependencyIndex,
    edges: list[EdgeCandidate],
    unresolved: list[UnresolvedDependency],
    deleted_paths: set[str],
) -> None:
    test_source = is_test_file(path)
    for imp in fs.imports:
        candidates = resolve_import(imp.module, path, index.py_files, index.js_files)
        if not candidates:
            if _module_maps_to_deleted(imp.module, path, deleted_paths):
                unresolved.append(
                    UnresolvedDependency(
                        path=path,
                        line=imp.line,
                        target=imp.module,
                        kind="deleted-import",
                        reason="imported target was deleted by the change set",
                    )
                )
                continue
            elif is_stdlib_module(imp.module):
                # Standard library: a real, verifiable dependency that is not
                # part of this repository. Not a breakage signal.
                continue
            elif imp.module.startswith(".") or "." in imp.module or "/" in imp.module or "importlib" in imp.module:
                reason = (
                    "relative import could not be mapped to a repository file"
                    if imp.module.startswith(".")
                    else "import resolves outside the repository or via a dynamic name"
                )
            else:
                reason = "bare import could not be mapped to a repository file"
            unresolved.append(
                UnresolvedDependency(
                    path=path,
                    line=imp.line,
                    target=imp.module,
                    kind="import",
                    reason=reason,
                )
            )
            continue
        target = _pick_candidate(path, candidates)
        rel, confidence = _classify_import(path, target, test_source, confidence_seed=Confidence.HIGH)
        evidence = f"{path}:{imp.line} import {imp.module}"
        edges.append(
            EdgeCandidate(
                source=path,
                target=target,
                relationship=rel,
                confidence=confidence,
                evidence=evidence,
                line=imp.line,
            )
        )


def _module_maps_to_deleted(module: str, from_path: str, deleted_paths: set[str]) -> bool:
    if module.startswith("."):
        return False
    dotted = module.replace("/", ".")
    path_part = dotted.replace(".", "/")
    candidates = {f"{path_part}.py", f"{path_part}/__init__.py"}
    return any((c and c in deleted_paths) for c in candidates)


def is_stdlib_module(module: str) -> bool:
    """Deterministic check against the running interpreter's standard library."""
    top = module.split(".")[0]
    return top in getattr(sys, "stdlib_module_names", frozenset())


def _js_edges(
    path: str,
    fs: FileSymbols,
    index: DependencyIndex,
    edges: list[EdgeCandidate],
    unresolved: list[UnresolvedDependency],
) -> None:
    test_source = is_test_file(path)
    for imp in fs.imports:
        candidates = resolve_import(imp.module, path, index.py_files, index.js_files)
        if not candidates:
            unresolved.append(
                UnresolvedDependency(
                    path=path,
                    line=imp.line,
                    target=imp.module,
                    kind="require",
                    reason=(
                        "relative module not found in repository"
                        if imp.module.startswith(".")
                        else "external package or unresolved bare specifier"
                    ),
                )
            )
            continue
        target = _pick_candidate(path, candidates)
        rel, _ = _classify_import(path, target, test_source, confidence_seed=Confidence.HEURISTIC)
        evidence = f"{path}:{imp.line} import/require {imp.module}"
        edges.append(
            EdgeCandidate(
                source=path,
                target=target,
                relationship=rel,
                confidence=Confidence.HEURISTIC,
                evidence=evidence,
                line=imp.line,
            )
        )


def _config_edges(path: str, index: DependencyIndex, edges: list[EdgeCandidate]) -> None:
    content = index.contents.get(path, "")
    if not content:
        return
    refs: dict[str, int] = {}
    for candidate, other in sorted(index.files.items()):
        if candidate == path:
            continue
        fqn = _fqn_for(candidate)
        for probe in {candidate, fqn, _stem(candidate)}:
            if probe and len(probe) >= 3 and probe in content:
                refs.setdefault(probe, content.find(probe))
                break
    for probe, pos in sorted(refs.items(), key=lambda item: item[1]):
        target = _probe_to_path(probe, index)
        if target is None:
            continue
        edges.append(
            EdgeCandidate(
                source=path,
                target=target,
                relationship=RelationshipType.CONFIGURATION_DEPENDENCY,
                confidence=Confidence.MEDIUM,
                evidence=f"{path} references {probe}",
                line=content.count("\n", 0, pos) + 1,
            )
        )


def _fqn_for(path: str) -> str:
    return path[: path.rfind(".")] if "." in path.rsplit("/", 1)[-1] else path


def _stem(path: str) -> str:
    return path.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _probe_to_path(probe: str, index: DependencyIndex):
    for candidate in index.files:
        if candidate == probe:
            return candidate
        fqn = _fqn_for(candidate)
        if fqn == probe:
            return candidate
        if _stem(candidate) == probe:
            return candidate
    return None


def _pick_candidate(from_path: str, candidates: list[str]) -> str:
    if len(candidates) == 1:
        return candidates[0]
    return min(candidates, key=lambda c: (c.count("/"), c))


def _classify_import(
    source: str,
    target: str,
    test_source: bool,
    confidence_seed: Confidence,
) -> tuple[RelationshipType, Confidence]:
    if test_source:
        return RelationshipType.TEST_COVERS, confidence_seed
    stem = _stem(target)
    if stem in _SCHEMA_MARKERS or any(p in target.split("/") for p in ("models", "db", "schema")):
        return RelationshipType.SCHEMA_CONSUMER, confidence_seed
    if _is_client(source) and _is_api_target(target):
        return RelationshipType.API_CONSUMER, confidence_seed
    return RelationshipType.IMPORT, confidence_seed


def _is_client(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    return any("client" in p or "consumer" in p or "sdk" in p for p in parts)


def _is_api_target(path: str) -> bool:
    parts = path.replace("\\", "/").split("/")
    if parts and parts[0] in {"api", "apis", "server", "servers"}:
        return True
    if parts and parts[0] == "app" and any(p in {"routes", "api", "endpoints"} for p in parts):
        return True
    return any(p in {"routes", "api", "endpoints"} for p in parts)


def _dedupe(edges: list[EdgeCandidate]) -> list[EdgeCandidate]:
    seen: set[tuple[str, str, str]] = set()
    out: list[EdgeCandidate] = []
    for e in sorted(edges, key=lambda e: (e.source, e.target, e.line, e.relationship.value)):
        key = (e.source, e.target, e.relationship.value)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def _dedupe_unresolved(items: list[UnresolvedDependency]) -> list[UnresolvedDependency]:
    seen: set[tuple[str, str, str]] = set()
    out: list[UnresolvedDependency] = []
    for u in sorted(items, key=lambda u: (u.path, u.line, u.target)):
        key = (u.path, u.target, u.kind)
        if key in seen:
            continue
        seen.add(key)
        out.append(u)
    return out