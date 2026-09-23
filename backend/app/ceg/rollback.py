"""Scoped rollback from CEG (Phase 9)."""

from __future__ import annotations

from collections import defaultdict, deque

from app.models.execution import ExecutionGraph, NodeStatus, RollbackScope


def compute_rollback_scope(
    graph: ExecutionGraph,
    failed_node_id: str,
    *,
    is_demo: bool = False,
) -> RollbackScope:
    """
    Downstream-only scoped rollback:

    - Identify failed node F
    - Find dependents of F (direct/transitive children)
    - Rollback reversible dependents that started
    - Preserve successful ancestors and independent branches
    - Do NOT rollback ancestors merely because F depends on them
    """
    nodes = graph.node_map()
    if failed_node_id not in nodes:
        raise KeyError(f"Unknown failed node: {failed_node_id}")

    children: dict[str, list[str]] = defaultdict(list)
    for edge in graph.edges:
        children[edge.source].append(edge.target)
    for n in graph.nodes:
        for c in n.child_nodes:
            if c not in children[n.node_id]:
                children[n.node_id].append(c)

    affected: list[str] = []
    q = deque(children.get(failed_node_id, []))
    seen: set[str] = set()
    while q:
        nid = q.popleft()
        if nid in seen:
            continue
        seen.add(nid)
        affected.append(nid)
        for nxt in children.get(nid, []):
            q.append(nxt)

    failed_node = nodes[failed_node_id]
    rollback_candidates: list[str] = []
    not_rollbackable: list[str] = []
    for nid in affected:
        node = nodes[nid]
        # Include started/succeeded/running AND pending dependents (cancelled before start)
        # so scoped-rollback demos show the affected branch clearly.
        if node.status == NodeStatus.SKIPPED.value and not node.reversible:
            continue
        if not node.reversible or node.rollback_action is None:
            if node.status not in {NodeStatus.PENDING.value, NodeStatus.SKIPPED.value}:
                not_rollbackable.append(nid)
            continue
        rollback_candidates.append(nid)

    order = _reverse_topo(rollback_candidates, children)

    preserved: list[str] = []
    for n in graph.nodes:
        if n.node_id == failed_node_id or n.node_id in affected:
            continue
        if n.status in {
            NodeStatus.SUCCESS.value,
            NodeStatus.RUNNING.value,
            NodeStatus.PRESERVED.value,
        }:
            preserved.append(n.node_id)

    rationale = (
        f"{failed_node.service} failed. MEDHA traced the dependency graph and will roll back "
        f"only the affected branch {[nodes[i].service for i in order]}. "
        f"Independent services {[nodes[i].service for i in preserved if i in nodes]} are preserved."
    )

    return RollbackScope(
        deployment_id=graph.deployment_id,
        failed_node_id=failed_node_id,
        failed_nodes=[failed_node_id],
        affected_nodes=affected,
        nodes_to_rollback=order,
        nodes_preserved=preserved,
        skipped_nodes=[
            n.node_id
            for n in graph.nodes
            if n.node_id in affected and n.status == NodeStatus.PENDING.value
        ],
        not_rollbackable=not_rollbackable,
        rationale=rationale,
        order=order,
        is_demo=is_demo,
    )


def apply_scope_to_graph(graph: ExecutionGraph, scope: RollbackScope) -> ExecutionGraph:
    nodes = []
    for n in graph.nodes:
        node = n.model_copy(deep=True)
        if node.node_id == scope.failed_node_id:
            node.status = NodeStatus.FAILED.value
            node.reason = node.reason or "Execution failed"
        elif node.node_id in scope.nodes_to_rollback:
            node.status = NodeStatus.ROLLED_BACK.value
            node.reason = "Dependent on failed node — reversed"
        elif node.node_id in scope.nodes_preserved and node.status in {
            NodeStatus.SUCCESS.value,
            NodeStatus.PRESERVED.value,
        }:
            node.status = NodeStatus.PRESERVED.value
            node.reason = node.reason or "Causally independent / upstream success retained"
        elif (
            node.node_id in scope.affected_nodes
            and node.node_id not in scope.nodes_to_rollback
            and node.status == NodeStatus.PENDING.value
        ):
            node.status = NodeStatus.SKIPPED.value
            node.reason = "Skipped due to upstream failure"
        nodes.append(node)
    return ExecutionGraph(
        deployment_id=graph.deployment_id,
        nodes=nodes,
        edges=list(graph.edges),
        is_demo=graph.is_demo,
    )


def _reverse_topo(candidates: list[str], children: dict[str, list[str]]) -> list[str]:
    cand = set(candidates)
    indeg = {n: 0 for n in candidates}
    for n in candidates:
        for c in children.get(n, []):
            if c in cand:
                indeg[c] = indeg.get(c, 0) + 1
    from collections import deque as _deque

    q = _deque([n for n, d in indeg.items() if d == 0])
    forward: list[str] = []
    while q:
        n = q.popleft()
        forward.append(n)
        for c in children.get(n, []):
            if c not in cand:
                continue
            indeg[c] -= 1
            if indeg[c] == 0:
                q.append(c)
    for n in candidates:
        if n not in forward:
            forward.append(n)
    return list(reversed(forward))
