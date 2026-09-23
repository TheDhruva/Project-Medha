"""Change Impact Graph builder and bounded traversal (Phase 2).

The CIG answers: "if these files/symbols changed, which repository artifacts
could be affected, and who depends on them?" It is computed deterministically
from ChangeSet + DependencyIndex and is strictly separate from the CEG.

Edge direction: source depends on target. Impact is computed by reverse
reachability (things that depend on changed artifacts), bounded by max_depth.
Deletions produce explicit deleted-import signal so broken dependents are
surfaced instead of guessed.
"""

from __future__ import annotations

from app.changeintel.dep_index import (
    DependencyIndex,
    compute_dependency_edges,
    compute_inheritance_edges,
    is_config_file,
    is_test_file,
)
from app.changeintel.models import (
    ChangedSymbol,
    ChangeSet,
    ChangeType,
    CigGraph,
    Confidence,
    Hunk,
    ImpactEdge,
    ImpactNode,
    ImpactTraversal,
    Language,
    NodeType,
    RelationshipType,
    Symbol,
    SymbolKind,
    UnresolvedDependency,
    new_edge,
)

MAX_DEPTH = 3


def detect_changed_symbols(
    changeset: ChangeSet,
    index: DependencyIndex,
    base_side: dict[str, Symbol],
) -> list[ChangedSymbol]:
    """Find symbols touched by the change set (hunk-overlap based)."""
    changed: list[ChangedSymbol] = []
    for fc in changeset.files:
        if fc.change_type == ChangeType.ADDED:
            fs = index.get(fc.path)
            symbols = fs.symbols if fs else []
            for s in symbols:
                changed.append(
                    ChangedSymbol(symbol=s, change_type=ChangeType.ADDED, lines_changed=fc.added_lines)
                )
        elif fc.change_type == ChangeType.DELETED:
            symbols = _symbols_for(fc.path, base_side)
            for s in symbols or [_synthetic_module_symbol(fc.path, Language.UNSUPPORTED)]:
                changed.append(
                    ChangedSymbol(symbol=s, change_type=ChangeType.DELETED, lines_changed=fc.deleted_lines)
                )
        elif fc.change_type == ChangeType.RENAMED:
            source_symbols = _symbols_for(fc.old_path or fc.path, base_side)
            moved: list[Symbol] = []
            for s in source_symbols or [_synthetic_module_symbol(fc.path, Language.UNSUPPORTED)]:
                moved.append(_remap_path(s, fc.path))
            for s in moved:
                changed.append(
                    ChangedSymbol(
                        symbol=s,
                        change_type=ChangeType.RENAMED,
                        lines_changed=max(1, fc.added_lines + fc.deleted_lines),
                    )
                )
        elif fc.change_type == ChangeType.MODIFIED:
            fs = index.get(fc.path)
            symbols = fs.symbols if fs else []
            target_fqns = {s.fqn for s in symbols}
            for s in symbols:
                if _symbol_in_hunks(s, fc.hunks):
                    changed.append(
                        ChangedSymbol(
                            symbol=s,
                            change_type=ChangeType.MODIFIED,
                            lines_changed=_overlap_lines(s, fc.hunks),
                        )
                    )
            for base_symbol in _symbols_for(fc.path, base_side):
                if base_symbol.fqn not in target_fqns:
                    changed.append(
                        ChangedSymbol(
                            symbol=base_symbol,
                            change_type=ChangeType.DELETED,
                            lines_changed=fc.deleted_lines,
                        )
                    )
    return changed


def build_cig(
    changeset: ChangeSet,
    changed_symbols: list[ChangedSymbol],
    index: DependencyIndex,
    base_side: dict[str, Symbol],
    max_depth: int = MAX_DEPTH,
) -> tuple[CigGraph, ImpactTraversal, list[UnresolvedDependency]]:
    changed_paths = {fc.path for fc in changeset.files}
    deleted_paths = {fc.path for fc in changeset.files if fc.change_type == ChangeType.DELETED}

    candidates, unresolved = compute_dependency_edges(index, deleted_paths=deleted_paths)
    # Deleted files cannot be imported from the target tree; make sure their own
    # (base-side) dependents aren't silently dropped.
    dependents: dict[str, list[tuple[str, RelationshipType, Confidence, str]]] = {}
    for e in candidates:
        if e.target == e.source:
            continue
        dependents.setdefault(e.target, []).append((e.source, e.relationship, e.confidence, e.evidence))

    # Reverse-reachable (affected) files from changed files.
    affected = _reverse_reach(changed_paths, dependents, max_depth)

    affected_paths = {p for p, dist in affected.items()}
    direct_paths = {p for p, dist in affected.items() if dist == 1}

    # Final node set: changed (+symbols), affected/test/config, context.
    nodes: dict[str, ImpactNode] = {}
    for fc in changeset.files:
        nodes[fc.path] = ImpactNode(
            id=fc.path,
            path=fc.path,
            node_type=NodeType.CHANGED,
            change_type=fc.change_type,
            language=_language_for(fc.path, index),
            direct=True,
        )
    for cs in changed_symbols:
        nodes[cs.symbol.symbol_id] = ImpactNode(
            id=cs.symbol.symbol_id,
            path=cs.symbol.path,
            node_type=NodeType.CHANGED,
            change_type=cs.change_type,
            symbol=cs.symbol.name,
            symbol_id=cs.symbol.symbol_id,
            kind=cs.symbol.kind,
            language=cs.symbol.language,
            direct=True,
            metadata={"lines_changed": cs.lines_changed},
        )

    for path in sorted(affected_paths):
        if path in nodes:
            continue
        ntype = NodeType.AFFECTED
        if is_test_file(path):
            ntype = NodeType.TEST
        elif is_config_file(path):
            ntype = NodeType.CONFIG
        nodes[path] = ImpactNode(
            id=path,
            path=path,
            node_type=ntype,
            language=_language_for(path, index),
            direct=path in direct_paths,
        )

    # Context: immediate dependencies of changed/affected artifacts.
    for e in candidates:
        if e.source not in affected_paths and e.source not in changed_paths:
            continue
        if e.target in affected_paths or e.target in changed_paths:
            continue
        ntype = NodeType.CONTEXT
        if is_test_file(e.target):
            ntype = NodeType.TEST
        elif is_config_file(e.target):
            ntype = NodeType.CONFIG
        nodes[e.target] = ImpactNode(
            id=e.target,
            path=e.target,
            node_type=ntype,
            language=_language_for(e.target, index),
            direct=False,
        )

    # Explicit edges.
    edges: list[ImpactEdge] = []
    seen_edges: set[tuple[str, str, str]] = set()
    for e in candidates:
        if e.source not in nodes and e.target not in nodes:
            continue
        if e.source not in nodes:
            continue
        edge = ImpactEdge(
            id=new_edge(),
            source=e.source,
            target=e.target,
            relationship=e.relationship,
            confidence=e.confidence,
            evidence=e.evidence,
            direct=e.source in changed_paths,
        )
        key = (edge.source, edge.target, edge.relationship.value)
        if key in seen_edges:
            continue
        seen_edges.add(key)
        edges.append(edge)

    # Symbol-level edges: a changed symbol depends on the same targets as its file.
    symbol_by_path: dict[str, list[str]] = {}
    for cs in changed_symbols:
        symbol_by_path.setdefault(cs.symbol.path, []).append(cs.symbol.symbol_id)
    for e in candidates:
        for symbol_id in symbol_by_path.get(e.source, []):
            key = (symbol_id, e.target, e.relationship.value)
            if key in seen_edges:
                continue
            seen_edges.add(key)
            edges.append(
                ImpactEdge(
                    id=new_edge(),
                    source=symbol_id,
                    target=e.target,
                    relationship=e.relationship,
                    confidence=e.confidence,
                    evidence=e.evidence,
                    direct=True,
                    note=f"edge inherited from {e.source}",
                )
            )

    graph = CigGraph(nodes=list(nodes.values()), edges=edges)
    traversal = _traversal_stats(affected, max_depth, dependents, changed_paths)
    return graph, traversal, unresolved


def _symbols_for(path: str, base_side: dict[str, Symbol]) -> list[Symbol]:
    syms: list[Symbol] = []
    for s in base_side.values():
        if s.path == path:
            syms.append(s)
    return _stable_order(syms)


def _stable_order(symbols: list[Symbol]) -> list[Symbol]:
    return sorted(symbols, key=lambda s: (s.line, s.end_line, s.name))


def _synthetic_module_symbol(path: str, language: Language) -> Symbol:
    from pathlib import Path

    name = Path(path).stem or "module"
    return Symbol(
        symbol_id=f"{path}::module",
        name=name,
        fqn=path.rsplit(".", 1)[0].replace("/", "."),
        kind=SymbolKind.MODULE,
        path=path,
        line=1,
        end_line=1,
        language=language,
    )


def _remap_path(symbol: Symbol, new_path: str) -> Symbol:
    from pathlib import Path

    name = Path(new_path).stem or symbol.name
    return Symbol(
        symbol_id=f"{new_path}::{symbol.kind.value}:{name}",
        name=name,
        fqn=_fqn(new_path, name),
        kind=symbol.kind,
        path=new_path,
        line=symbol.line,
        end_line=symbol.end_line,
        language=symbol.language,
    )


def _fqn(new_path: str, name: str) -> str:
    stem = new_path.rsplit(".", 1)[0].replace("/", ".")
    if stem.endswith(".__init__"):
        stem = stem[: -len(".__init__")]
    return f"{stem}.{name}"


def _symbol_in_hunks(symbol: Symbol, hunks: list[Hunk]) -> bool:
    for h in hunks:
        if symbol.line <= h.new_end and h.new_start <= symbol.end_line:
            return True
    return False


def _overlap_lines(symbol: Symbol, hunks: list[Hunk]) -> int:
    total = 0
    for h in hunks:
        start = max(symbol.line, h.new_start)
        end = min(symbol.end_line, h.new_end)
        if start <= end:
            total += end - start + 1
    return total


def _language_for(path: str, index: DependencyIndex) -> Language:
    fs = index.get(path)
    return fs.language if fs else Language.UNSUPPORTED


def _reverse_reach(
    seeds: set[str],
    dependents: dict[str, list[tuple[str, RelationshipType, Confidence, str]]],
    max_depth: int,
) -> dict[str, int]:
    """Bounded BFS over reverse edges. Returns node -> distance (1..max_depth)."""
    from collections import deque

    visited: dict[str, int] = {}
    queue: deque[tuple[str, int]] = deque((s, 0) for s in sorted(seeds))
    for s in seeds:
        visited[s] = 0
    while queue:
        current, depth = queue.popleft()
        if depth >= max_depth:
            continue
        for depend, _rel, _conf, _evidence in dependents.get(current, []):
            if depend in visited:
                continue
            if is_test_file(depend) or is_config_file(depend):
                # still mark so test/config coverage is surfaced
                visited.setdefault(depend, depth + 1)
                continue
            visited[depend] = depth + 1
            queue.append((depend, depth + 1))
    return {k: v for k, v in visited.items() if v > 0}


def _traversal_stats(
    affected: dict[str, int],
    max_depth: int,
    dependents: dict[str, list[tuple[str, RelationshipType, Confidence, str]]],
    seeds: set[str],
) -> ImpactTraversal:
    direct = sorted(p for p, d in affected.items() if d == 1 and p not in seeds)
    transitive = sorted(p for p, d in affected.items() if d > 1)
    depth_used = max((d for d in affected.values()), default=0)
    cycles: list[tuple[str, str]] = []
    seen_back: set[tuple[str, str]] = set()
    for seed in sorted(seeds):
        stack_visited: set[str] = set()
        visiting: list[str] = []

        def dfs(node: str) -> None:
            visiting.append(node)
            for depend, _r, _c, _e in dependents.get(node, []):
                if depend in visiting[:-1]:
                    pair = (depend, node)
                    if pair not in seen_back:
                        seen_back.add(pair)
                        cycles.append(pair)
                    continue
                if depend not in visiting:
                    dfs(depend)
            visiting.pop()

        dfs(seed)
    return ImpactTraversal(
        max_depth=max_depth,
        direct_targets=direct,
        transitive_targets=transitive,
        cycles_detected=cycles,
        depth_used=depth_used,
    )