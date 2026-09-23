from __future__ import annotations

from app.agents.verifier import run_verifier
from app.agents.critic import run_critic
from app.ceg.rollback import apply_scope_to_graph, compute_rollback_scope
from app.execution.executor import SimulatorExecutor
from app.execution.plan_builder import build_ceg_from_plan, build_execution_plan
from app.models.domain import (
    ApplicationProfile,
    Constraint,
    ConstraintStatus,
    ConstraintType,
    InferredStack,
    NegotiationResult,
    Priority,
    ServiceHint,
)
from app.models.execution import CriticRecommendation, NodeStatus


def _profile(deployment_id: str = "dep_t") -> ApplicationProfile:
    return ApplicationProfile(
        deployment_id=deployment_id,
        repository_url="local",
        workspace_path=".",
        intent="Deploy the application securely",
        target_host="localhost",
        target_port=8080,
        inferred_stack=InferredStack(
            services=[
                ServiceHint(name="network", role="network"),
                ServiceHint(name="database", role="database"),
                ServiceHint(name="backend", role="api", suggested_port=8080),
                ServiceHint(name="frontend", role="web"),
                ServiceHint(name="analytics", role="service"),
            ],
            language_runtime="node",
            has_dockerfile=True,
            has_compose=True,
            package_managers=["npm"],
            suggested_ports=[8080],
            confidence=0.8,
            manifests_examined=["Dockerfile"],
        ),
    )


def _negotiation(deployment_id: str, constraints: list[Constraint]) -> NegotiationResult:
    return NegotiationResult(
        deployment_id=deployment_id,
        status="resolved",
        rounds_used=1,
        max_rounds=3,
        final_constraints=constraints,
    )


def test_verifier_schema_and_security_pass():
    profile = _profile()
    constraints = [
        Constraint(
            constraint_id="c_sec",
            type=ConstraintType.SECURITY_POLICY,
            priority=Priority.SECURITY,
            source_agent="Security Agent",
            payload={"rule": "no_privileged", "mode": "restricted"},
            status=ConstraintStatus.ACCEPTED,
        )
    ]
    fragments = {
        "docker": {
            "compose_fragment": {
                "services": {"backend": {"image": "medha/backend:local", "ports": ["8080:8080"]}}
            }
        },
        "env_present": {},
    }
    result = run_verifier(
        deployment_id="dep_t",
        profile=profile,
        constraints=constraints,
        negotiation=_negotiation("dep_t", constraints),
        config_fragments=fragments,
    )
    assert result.passed is True
    assert any(c.id == "schema" and c.status.value == "pass" for c in result.checks)


def test_verifier_privileged_fails():
    profile = _profile()
    constraints = [
        Constraint(
            constraint_id="c_sec",
            type=ConstraintType.SECURITY_POLICY,
            priority=Priority.SECURITY,
            source_agent="Security Agent",
            payload={"rule": "no_privileged"},
            status=ConstraintStatus.ACCEPTED,
        )
    ]
    fragments = {
        "docker": {
            "compose_fragment": {
                "services": {"backend": {"image": "x", "privileged": True}}
            }
        }
    }
    result = run_verifier(
        deployment_id="dep_t",
        profile=profile,
        constraints=constraints,
        negotiation=_negotiation("dep_t", constraints),
        config_fragments=fragments,
    )
    assert result.passed is False
    assert any(c.rule == "SEC-001" for c in result.checks)


def test_verifier_missing_env_and_replan_flag():
    profile = _profile()
    constraints = [
        Constraint(
            constraint_id="c_env",
            type=ConstraintType.ENV_VAR,
            priority=Priority.DEPENDENCY,
            source_agent="Docker Agent",
            payload={"key": "DATABASE_URL", "required": True},
            status=ConstraintStatus.ACCEPTED,
        ),
        Constraint(
            constraint_id="c_sec",
            type=ConstraintType.SECURITY_POLICY,
            priority=Priority.SECURITY,
            source_agent="Security Agent",
            payload={"rule": "no_privileged"},
            status=ConstraintStatus.ACCEPTED,
        ),
    ]
    fragments = {"docker": {"compose_fragment": {"services": {"backend": {"image": "x"}}}}}
    failed = run_verifier(
        deployment_id="dep_t",
        profile=profile,
        constraints=constraints,
        negotiation=_negotiation("dep_t", constraints),
        config_fragments=fragments,
    )
    assert failed.passed is False
    fixed = {
        **fragments,
        "env_present": {"DATABASE_URL": True},
        "docker": {
            "compose_fragment": {
                "services": {
                    "backend": {"image": "x", "environment": {"DATABASE_URL": "${DATABASE_URL}"}}
                }
            }
        },
    }
    passed = run_verifier(
        deployment_id="dep_t",
        profile=profile,
        constraints=constraints,
        negotiation=_negotiation("dep_t", constraints),
        config_fragments=fixed,
        replan_count=1,
    )
    assert passed.passed is True


def test_critic_scores_and_recommendations():
    profile = _profile()
    constraints = [
        Constraint(
            constraint_id="c_sec",
            type=ConstraintType.SECURITY_POLICY,
            priority=Priority.SECURITY,
            source_agent="Security Agent",
            payload={"rule": "no_privileged"},
            status=ConstraintStatus.ACCEPTED,
        )
    ]
    fragments = {
        "docker": {"compose_fragment": {"services": {"backend": {"image": "x"}}}},
        "env_present": {},
    }
    verification = run_verifier(
        deployment_id="dep_t",
        profile=profile,
        constraints=constraints,
        negotiation=_negotiation("dep_t", constraints),
        config_fragments=fragments,
    )
    critic = run_critic(
        deployment_id="dep_t",
        profile=profile,
        constraints=constraints,
        negotiation=_negotiation("dep_t", constraints),
        verification=verification,
        config_fragments=fragments,
    )
    assert 0 <= critic.score <= 100
    assert critic.recommendation in {
        CriticRecommendation.PASS,
        CriticRecommendation.WARN,
        CriticRecommendation.REPLAN,
        CriticRecommendation.ESCALATE,
    }


def test_ceg_creation_and_partial_rollback_scope():
    profile = _profile()
    plan = build_execution_plan(
        deployment_id="dep_t",
        profile=profile,
        constraints=[],
        config_fragments={},
        fail_service="backend",
    )
    graph = build_ceg_from_plan(plan)
    ids = {n.node_id for n in graph.nodes}
    assert "n_network" in ids
    assert "n_backend" in ids
    assert "n_frontend" in ids
    assert "n_analytics" in ids

    # Simulate success up to backend fail
    for n in graph.nodes:
        if n.service in {"network", "database", "analytics"}:
            n.status = NodeStatus.SUCCESS.value
        elif n.service == "backend":
            n.status = NodeStatus.FAILED.value
        elif n.service == "frontend":
            n.status = NodeStatus.SUCCESS.value

    scope = compute_rollback_scope(graph, "n_backend")
    assert scope.nodes_to_rollback == ["n_frontend"]
    assert "n_analytics" in scope.nodes_preserved
    assert "n_network" in scope.nodes_preserved
    assert "n_database" in scope.nodes_preserved
    assert "n_analytics" not in scope.nodes_to_rollback
    assert "n_network" not in scope.nodes_to_rollback

    applied = apply_scope_to_graph(graph, scope)
    by = {n.node_id: n for n in applied.nodes}
    assert by["n_backend"].status == "failed"
    assert by["n_frontend"].status == "rolled_back"
    assert by["n_analytics"].status == "preserved"
    assert by["n_network"].status == "preserved"
    assert by["n_database"].status == "preserved"


def test_ceg_fail_b_rolls_c_preserves_a_and_d():
    """Academic graph: A→B→C and independent D; fail B → rollback C, preserve A,D."""
    from app.models.execution import ExecutionEdge, ExecutionGraph, ExecutionNode

    graph = ExecutionGraph(
        deployment_id="dep_x",
        nodes=[
            ExecutionNode(node_id="A", action="a", service="a", status="success", parent_nodes=[]),
            ExecutionNode(
                node_id="B", action="b", service="b", status="failed", parent_nodes=["A"]
            ),
            ExecutionNode(
                node_id="C",
                action="c",
                service="c",
                status="success",
                parent_nodes=["B"],
                reversible=True,
                rollback_action={"type": "remove"},
            ),
            ExecutionNode(node_id="D", action="d", service="d", status="success", parent_nodes=[]),
        ],
        edges=[
            ExecutionEdge(id="e1", source="A", target="B"),
            ExecutionEdge(id="e2", source="B", target="C"),
        ],
    )
    # child links
    for n in graph.nodes:
        if n.node_id == "A":
            n.child_nodes = ["B"]
        if n.node_id == "B":
            n.child_nodes = ["C"]

    scope = compute_rollback_scope(graph, "B")
    assert scope.nodes_to_rollback == ["C"]
    assert "A" in scope.nodes_preserved
    assert "D" in scope.nodes_preserved
    assert "A" not in scope.nodes_to_rollback


def test_simulator_partial_failure_end_to_end():
    import asyncio

    profile = _profile()
    plan = build_execution_plan(
        deployment_id="dep_t",
        profile=profile,
        constraints=[],
        config_fragments={},
        fail_service="backend",
    )
    graph = build_ceg_from_plan(plan)
    executor = SimulatorExecutor(step_delay=0)

    out_graph, result, scope = asyncio.run(executor.execute(plan, graph))
    assert result.status == "PARTIAL_FAILURE"
    assert result.failed_services == ["backend"]
    assert "frontend" in result.rolled_back_services
    assert "analytics" in result.preserved_services
    assert "network" in result.preserved_services
    assert "database" in result.preserved_services
    assert scope is not None
    by = {n.service: n.status for n in out_graph.nodes}
    assert by["backend"] == "failed"
    assert by["frontend"] == "rolled_back"
    assert by["analytics"] == "preserved"
