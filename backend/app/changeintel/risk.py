"""Deterministic risk classification for a Change Impact Graph (Phase 2).

Every risk factor is documented, code-keyed, and computed from observable
graph/changeset facts. Composite level = highest contributing factor level.
No probabilistic or LLM confidence is involved.
"""

from __future__ import annotations

from app.changeintel.models import (
    ChangeSet,
    ChangeType,
    CigGraph,
    ImpactRisk,
    NodeType,
    RelationshipType,
    RiskFactor,
    RiskLevel,
    UnresolvedDependency,
)


def assess_risk(
    changeset: ChangeSet,
    graph: CigGraph,
    changed_symbols,
    unresolved: list[UnresolvedDependency],
    traversal,
) -> ImpactRisk:
    factors: list[RiskFactor] = []

    # 1. Deleted source artifacts with live dependents in the target tree.
    broken_imports = [u for u in unresolved if u.kind == "deleted-import"]
    if any(cs.change_type == ChangeType.DELETED for cs in changed_symbols) or broken_imports:
        deleted_syms = [cs.symbol.fqn for cs in changed_symbols if cs.change_type == ChangeType.DELETED]
        if broken_imports:
            reason = (
                f"{len(broken_imports)} remaining import(s) reference modules "
                "removed by this change set"
            )
        else:
            reason = f"{len(deleted_syms)} symbol(s) removed ({', '.join(deleted_syms[:3])})"
        factors.append(
            RiskFactor(
                code="deleted_artifacts_with_dependents",
                level=RiskLevel.HIGH,
                reason=reason,
            )
        )

    # 2. Renamed artifacts — old paths may still be referenced.
    renamed = [fc for fc in changeset.files if fc.change_type == ChangeType.RENAMED]
    if renamed:
        factors.append(
            RiskFactor(
                code="renamed_artifacts",
                level=RiskLevel.MEDIUM,
                reason=f"{len(renamed)} path(s) renamed; obsolete references are a common breakage source",
            )
        )

    # 3. Affected breadth (direct + transitive impact set).
    breadth = len(traversal.direct_targets) + len(traversal.transitive_targets)
    if breadth >= 10:
        factors.append(
            RiskFactor(
                code="large_blast_radius",
                level=RiskLevel.HIGH,
                reason=f"{breadth} dependent artifacts affected",
            )
        )
    elif breadth >= 5:
        factors.append(
            RiskFactor(
                code="large_blast_radius",
                level=RiskLevel.MEDIUM,
                reason=f"{breadth} dependent artifacts affected",
            )
        )

    # 4. API boundary changes with consumers.
    api_edges = [e for e in graph.edges if e.relationship == RelationshipType.API_CONSUMER]
    if api_edges:
        factors.append(
            RiskFactor(
                code="api_contract_exposure",
                level=RiskLevel.MEDIUM,
                reason=f"{len(api_edges)} API consumer edge(s) in the impact graph",
            )
        )

    # 5. Schema/model consumers.
    schema_edges = [e for e in graph.edges if e.relationship == RelationshipType.SCHEMA_CONSUMER]
    if schema_edges:
        factors.append(
            RiskFactor(
                code="schema_consumers",
                level=RiskLevel.MEDIUM,
                reason=f"{len(schema_edges)} schema/model consumer edge(s) affected",
            )
        )

    # 6. Config mappings that depend on changed artifacts.
    config_present = any(n.node_type == NodeType.CONFIG for n in graph.nodes)
    if config_present:
        factors.append(
            RiskFactor(
                code="configuration_dependencies",
                level=RiskLevel.MEDIUM,
                reason="configuration references changed source artifacts",
            )
        )

    # 7. Unresolved dependencies (imports that could not be mapped).
    unresolved_count = len([u for u in unresolved if u.kind in {"import", "require"}])
    if unresolved_count:
        factors.append(
            RiskFactor(
                code="unresolved_dependencies",
                level=RiskLevel.MEDIUM,
                reason=f"{unresolved_count} import(s) could not be resolved inside the repository",
            )
        )

    # 8. Dependency cycles.
    if traversal.cycles_detected:
        factors.append(
            RiskFactor(
                code="dependency_cycle",
                level=RiskLevel.MEDIUM,
                reason=f"{len(traversal.cycles_detected)} cycle(s) detected in the dependency subgraph",
            )
        )

    # 9. Inheritance dependency modified.
    inherits_edges = [e for e in graph.edges if e.relationship == RelationshipType.INHERITS]
    changed_ids = {n.id for n in graph.nodes if n.node_type == NodeType.CHANGED}
    if any(e.target in changed_ids for e in inherits_edges):
        factors.append(
            RiskFactor(
                code="inheritance_base_modified",
                level=RiskLevel.MEDIUM,
                reason="a modified/base class is inherited by dependent classes",
            )
        )

    # 10. Test coverage gap on changed artifacts.
    test_targets = {
        e.target for e in graph.edges if e.relationship == RelationshipType.TEST_COVERS
    }
    changed_paths = {fc.path for fc in changeset.files}
    untested = changed_paths - test_targets
    if untested and changed_paths:
        factors.append(
            RiskFactor(
                code="test_coverage_gap",
                level=RiskLevel.LOW,
                reason=f"{len(untested)} changed artifact(s) have no TEST_COVERS edge",
            )
        )

    # 11. Very large change sets.
    if len(changeset.files) > 10:
        factors.append(
            RiskFactor(
                code="sizeable_changeset",
                level=RiskLevel.LOW,
                reason=f"{len(changeset.files)} files changed",
            )
        )

    if not factors:
        return ImpactRisk(level=RiskLevel.NONE, factors=[])

    levels = {f.level for f in factors}
    highest = RiskLevel.HIGH if RiskLevel.HIGH in levels else (
        RiskLevel.MEDIUM if RiskLevel.MEDIUM in levels else RiskLevel.LOW
    )
    factors.sort(key=lambda f: (f.level.value, f.code))
    return ImpactRisk(level=highest, factors=factors)