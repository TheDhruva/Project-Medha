"""Deterministic CEG / scoped-rollback evaluation scenarios."""

from __future__ import annotations

from app.models.execution import ExecutionEdge, ExecutionGraph, ExecutionNode, NodeStatus


def _node(nid: str, service: str, parents: list[str], children: list[str]) -> ExecutionNode:
    return ExecutionNode(
        node_id=nid,
        action="start_container" if service != "network" else "create_network",
        service=service,
        status=NodeStatus.SUCCESS.value,
        parent_nodes=parents,
        child_nodes=children,
        dependencies=parents,
        reversible=True,
        rollback_action={"type": "remove", "service": service},
    )


def _graph(deployment_id: str, nodes: list[ExecutionNode], edges: list[tuple[str, str]]) -> ExecutionGraph:
    return ExecutionGraph(
        deployment_id=deployment_id,
        nodes=nodes,
        edges=[
            ExecutionEdge(id=f"e_{a}_{b}", source=a, target=b, relation="depends_on")
            for a, b in edges
        ],
    )


def load_ceg_cases() -> list[dict]:
    # Graph: A → B → C ; D independent
    g1_nodes = [
        _node("n_a", "A", [], ["n_b"]),
        _node("n_b", "B", ["n_a"], ["n_c"]),
        _node("n_c", "C", ["n_b"], []),
        _node("n_d", "D", [], []),
    ]
    g1 = _graph("eval_g1", g1_nodes, [("n_a", "n_b"), ("n_b", "n_c")])

    # Network → Database → Backend → Frontend ; Analytics
    g2_nodes = [
        _node("n_network", "network", [], ["n_database", "n_analytics"]),
        _node("n_database", "database", ["n_network"], ["n_backend"]),
        _node("n_backend", "backend", ["n_database"], ["n_frontend"]),
        _node("n_frontend", "frontend", ["n_backend"], []),
        _node("n_analytics", "analytics", ["n_network"], []),
    ]
    g2 = _graph(
        "eval_g2",
        g2_nodes,
        [
            ("n_network", "n_database"),
            ("n_database", "n_backend"),
            ("n_backend", "n_frontend"),
            ("n_network", "n_analytics"),
        ],
    )

    # A → B ; C → D
    g3_nodes = [
        _node("n_a", "A", [], ["n_b"]),
        _node("n_b", "B", ["n_a"], []),
        _node("n_c", "C", [], ["n_d"]),
        _node("n_d", "D", ["n_c"], []),
    ]
    g3 = _graph("eval_g3", g3_nodes, [("n_a", "n_b"), ("n_c", "n_d")])

    return [
        {
            "case_id": "ceg_fail_b_preserve_a_d",
            "graph": g1,
            "fail_node": "n_b",
            "expected_rollback": ["n_c"],
            "expected_preserved": ["n_a", "n_d"],
            "expected_not_rollback": ["n_a"],
        },
        {
            "case_id": "ceg_partial_backend",
            "graph": g2,
            "fail_node": "n_backend",
            "expected_rollback": ["n_frontend"],
            "expected_preserved": ["n_network", "n_database", "n_analytics"],
            "expected_not_rollback": ["n_network", "n_database", "n_analytics"],
        },
        {
            "case_id": "ceg_fail_a_chain",
            "graph": g1,
            "fail_node": "n_a",
            "expected_rollback": ["n_b", "n_c"],
            "expected_preserved": ["n_d"],
            "expected_not_rollback": ["n_d"],
        },
        {
            "case_id": "ceg_independent_branches",
            "graph": g3,
            "fail_node": "n_a",
            "expected_rollback": ["n_b"],
            "expected_preserved": ["n_c", "n_d"],
            "expected_not_rollback": ["n_c", "n_d"],
        },
        {
            "case_id": "ceg_fail_frontend_only",
            "graph": g2,
            "fail_node": "n_frontend",
            "expected_rollback": [],
            "expected_preserved": ["n_network", "n_database", "n_backend", "n_analytics"],
            "expected_not_rollback": ["n_backend", "n_database"],
        },
    ]
