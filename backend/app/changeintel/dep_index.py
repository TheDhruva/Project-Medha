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
    FileSymbols,
    Language as _Lang,
    resolve_import,
    source_files,
    _module_symbol,
    _fqn_for_path,
)
from app.core.repo_files import WalkBudget as _WB


_SCHEMA_MARKERS = {"schema", "schemas", "models", "model", "db", "database", "persistence", "tables"}


def _language_for_rel(path: str) -> Language:
    """Map a repo-relative path to a Language based on its suffix."""
    ext = Path(path).suffix.lower()
    if ext in {".py", ".pyi"}:
        return Language.PYTHON
    if ext in {".js", ".jsx", ".mjs", ".cjs"}:
        return Language.JAVASCRIPT
    if ext in {".ts", ".tsx"}:
        return Language.TYPESCRIPT
    if ext == ".json":
        return Language.JSON
    if ext in {".yml", ".yaml"}:
        return Language.YAML
    return Language.UNSUPPORTED


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


def build_index(root, backend_paths: list[str] | None = None, budget: WalkBudget | None = None) -> DependencyIndex:
    """Parse all supported files under root into a DependencyIndex.

    Uses the shared budget-aware walker so that the same traversal limits
    apply as in inventory and change-intel analysis.  When a budget is not
    supplied a sensible default for a change-intel index is used.

    Index coverage metadata is stored in ``index.coverage`` so callers can
    report truncation/skipping honestly.
    """
    from app.core.repo_files import WalkBudget as _WB, walk_files as _wf

    if budget is None:
        budget = _WB(
            max_files=20_000,
            max_total_bytes=200 * 1024 * 1024,
            max_file_bytes=1 * 1024 * 1024,
            max_depth=20,
            time_budget_s=120,
            extra_skip_dirs=frozenset({".git", "node_modules", ".venv", "venv",
                                         "__pycache__", ".next", "dist", "build"}),
        )

    result = _wf(root, budget)
    index = DependencyIndex()
    index.coverage = _IndexCoverage(
        files_seen=result.total_files,
        files_indexed=len(result.files),
        files_skipped=sum(result.skipped_reasons.values()),
        bytes_read=result.total_bytes,
        truncated=result.truncated,
        skipped_reasons=result.skipped_reasons,
        skipped_by_gitignore=result.skipped_by_gitignore,
        respected_depth=result.respected_depth,
        elapsed_s=result.elapsed_s,
    )

    for f in result.files:
        full = root / f.rel
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except OSError:
            content = ""
        index.contents[f.rel] = content
        # When needs_content was False the walker recorded the path but didn't
        # guarantee readable content; store a minimal FileSymbols with module-only
        # symbols so that import resolution has a path to look up, and record the
        # coverage note below.
        if not f.needs_content:
            index.files[f.rel] = FileSymbols(
                path=f.rel,
                language=_language_for_rel(f.rel),
                symbols=[_module_symbol(f.rel, _language_for_rel(f.rel))],
                imports=[],
                parse_error="content not parsed (file exceeds budget; see index coverage)",
            )
            continue
        index.files[f.rel] = _parse(f.rel, content)

    return index


class _IndexCoverage:
    """Lightweight coverage metadata attached to a DependencyIndex result.

    This is additive; existing code that accesses ``index.coverage`` will get a
    dict-like object with the fields below.  Front-end UI can render keys it
    knows and ignore the rest.
    """

    def __init__(
        self,
        files_seen: int,
        files_indexed: int,
        files_skipped: int,
        bytes_read: int,
        truncated: bool,
        skipped_reasons: dict[str, int],
        skipped_by_gitignore: int,
        respected_depth: int,
        elapsed_s: float,
    ):
        self.files_seen = files_seen
        self.files_indexed = files_indexed
        self.files_skipped = files_skipped
        self.bytes_read = bytes_read
        self.truncated = truncated
        self.skipped_reasons = skipped_reasons
        self.skipped_by_gitignore = skipped_by_gitignore
        self.respected_depth = respected_depth
        self.elapsed_s = elapsed_s

    def to_dict(self) -> dict[str, Any]:
        return {
            "files_seen": self.files_seen,
            "files_indexed": self.files_indexed,
            "files_skipped": self.files_skipped,
            "bytes_read": self.bytes_read,
            "truncated": self.truncated,
            "skipped_reasons": self.skipped_reasons,
            "skipped_by_gitignore": self.skipped_by_gitignore,
            "respected_depth": self.respected_depth,
            "elapsed_s": round(self.elapsed_s, 2),
        }


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
    """Config dependency edges using token-indexed lookups (Phase 2).

    Instead of iterating all candidate files for each config and doing O(N) substring
    probes, we tokenize the config content once and build a reverse map from tokens
    to candidate paths.  This prevents the O(files²) probe scan that could stress
    large repositories.

    Every edge carries ``Confidence.MEDIUM`` — these are heuristic references,
    not structurally verified imports.
    """
    content = index.contents.get(path, "")
    if not content:
        return

    # ------------------------------------------------------------------
    # Build a map from file-identifier tokens to candidate paths.
    # For each file in the index we record its path, fqn (path without ext),
    # and stem (filename without ext) as lookup keys.
    # ------------------------------------------------------------------
    token_to_candidate: dict[str, str] = {}
    for candidate in index.files:
        # The full repo-relative path
        if len(candidate) >= 3:
            token_to_candidate.setdefault(candidate, candidate)
        # File-quality name (path stem)
        fqn = _fqn_for(candidate)
        if len(fqn) >= 3:
            token_to_candidate.setdefault(fqn, candidate)
        # File stem (filename without extension)
        stem = _stem(candidate)
        if len(stem) >= 3:
            token_to_candidate.setdefault(stem, candidate)

    # Tokenize the config content: find every unique token >= 3 chars composed
    # of word chars, dots, slashes, at-signs, and hyphens.
    import re as _re
    tokens: set[str] = set(_re.findall(r"[\w./@-]{3,}", content))

    # For each token found in the config, look up the candidate path.
    refs: dict[str, int] = {}  # probe -> first position in content
    for token in tokens:
        if token in token_to_candidate:
            target = token_to_candidate[token]
            pos = content.find(token)
            if pos != -1:
                refs[token] = pos

    # Build edges from the collected references, sorted by position so that
    # evidence ordering is deterministic.
    for probe, pos in sorted(refs.items(), key=lambda item: item[1]):
        target = token_to_candidate.get(probe)
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