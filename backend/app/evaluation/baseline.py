"""GLOBAL_ROLLBACK baseline vs MEDHA scoped rollback (evaluation only)."""

from __future__ import annotations

from typing import Any

from app.ceg.rollback import compute_rollback_scope
from app.models.execution import ExecutionGraph, NodeStatus


def global_rollback_scope(graph: ExecutionGraph, failed_node_id: str) -> dict[str, Any]:
    """
    Baseline: on any critical failure, roll back all non-failed started/success nodes
    belonging to the deployment (except the failed node itself stays FAILED).
    """
    nodes = graph.node_map()
    if failed_node_id not in nodes:
        raise KeyError(failed_node_id)
    rollback = [
        n.node_id
        for n in graph.nodes
        if n.node_id != failed_node_id
        and n.status
        in {
            NodeStatus.SUCCESS.value,
            NodeStatus.RUNNING.value,
            NodeStatus.PENDING.value,
            NodeStatus.SKIPPED.value,
        }
    ]
    return {
        "strategy": "GLOBAL_ROLLBACK",
        "failed_node_id": failed_node_id,
        "nodes_to_rollback": rollback,
        "rollback_count": len(rollback),
        "preserved_nodes": [],
        "preserved_count": 0,
    }


def compare_rollback(graph: ExecutionGraph, failed_node_id: str) -> dict[str, Any]:
    """Compare MEDHA scoped rollback against GLOBAL_ROLLBACK baseline."""
    # Assume pre-failure successes for comparison: mark all as SUCCESS except failed
    working = ExecutionGraph(
        deployment_id=graph.deployment_id,
        nodes=[
            n.model_copy(
                update={
                    "status": NodeStatus.FAILED.value
                    if n.node_id == failed_node_id
                    else NodeStatus.SUCCESS.value
                }
            )
            for n in graph.nodes
        ],
        edges=list(graph.edges),
        is_demo=graph.is_demo,
    )
    medha = compute_rollback_scope(working, failed_node_id, is_demo=graph.is_demo)
    baseline = global_rollback_scope(working, failed_node_id)
    active = len(working.nodes)
    medha_count = len(medha.nodes_to_rollback)
    return {
        "failed_node_id": failed_node_id,
        "active_nodes": active,
        "medha": {
            "strategy": "MEDHA_SCOPED_ROLLBACK",
            "rollback_nodes": medha.nodes_to_rollback,
            "rollback_count": medha_count,
            "preserved_nodes": medha.nodes_preserved,
            "preserved_count": len(medha.nodes_preserved),
            "affected_nodes": medha.affected_nodes,
        },
        "baseline": baseline,
        "services_saved_vs_global": max(0, baseline["rollback_count"] - medha_count),
        "scope_efficiency": (medha_count / active) if active else None,
    }
