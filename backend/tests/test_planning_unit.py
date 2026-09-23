from __future__ import annotations

from pathlib import Path

from app.agents.analyzer import analyze_repository
from app.agents.docker_agent import run_docker_agent
from app.agents.nginx_agent import run_nginx_agent
from app.agents.security_agent import run_security_agent
from app.cnp.engine import detect_conflicts, run_cnp
from app.models.domain import Constraint, ConstraintStatus, ConstraintType, Priority

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"


def test_analyze_node_api_fixture():
    root = FIXTURES / "node_api"
    profile, result = analyze_repository(
        deployment_id="dep_test",
        repository_url=str(root),
        workspace_path=root,
        target_host="localhost",
        target_port=8080,
        intent="Deploy the application securely",
    )
    assert result.ok
    assert profile.inferred_stack.has_dockerfile is True
    assert profile.inferred_stack.language_runtime == "node"
    assert "package.json" in profile.inferred_stack.manifests_examined
    assert 8080 in profile.inferred_stack.suggested_ports
    assert profile.inferred_stack.confidence >= 0.5


def test_analyze_compose_fixture():
    root = FIXTURES / "compose_app"
    profile, result = analyze_repository(
        deployment_id="dep_test",
        repository_url=str(root),
        workspace_path=root,
        target_host="localhost",
        target_port=8080,
    )
    assert result.ok
    assert profile.inferred_stack.has_compose is True
    names = {s.name for s in profile.inferred_stack.services}
    assert "backend" in names
    assert "database" in names


def test_specialists_emit_typed_constraints():
    root = FIXTURES / "compose_app"
    profile, _ = analyze_repository(
        deployment_id="dep_test",
        repository_url=str(root),
        workspace_path=root,
        target_host="localhost",
        target_port=8080,
        intent="Deploy unrestricted for convenience",
    )
    docker = run_docker_agent(profile)
    nginx = run_nginx_agent(profile)
    security = run_security_agent(profile)
    assert docker.ok and nginx.ok and security.ok
    assert any(c.type == ConstraintType.PORT_CLAIM for c in docker.constraints)
    assert any(c.type == ConstraintType.PORT_CLAIM for c in nginx.constraints)
    assert any(c.priority == Priority.SECURITY for c in security.constraints)
    assert "compose_fragment" in docker.artifacts
    assert "nginx_config" in nginx.artifacts


def test_cnp_port_conflict_alternative():
    constraints = [
        Constraint(
            constraint_id="c_port_a",
            type=ConstraintType.PORT_CLAIM,
            priority=Priority.RESOURCE,
            source_agent="Docker Agent",
            payload={"key": "host:8080", "port": 8080, "exclusive": True},
            alternatives=[{"port": 8081}],
        ),
        Constraint(
            constraint_id="c_port_b",
            type=ConstraintType.PORT_CLAIM,
            priority=Priority.RESOURCE,
            source_agent="Nginx Agent",
            payload={"key": "host:8080", "port": 8080, "exclusive": True},
            alternatives=[{"port": 8081}],
        ),
    ]
    preview = detect_conflicts(constraints)
    assert len(preview) == 1
    result = run_cnp("dep_x", constraints)
    assert result.status == "resolved"
    assert any(d.method == "alternative" for d in result.decisions)
    by_id = {c.constraint_id: c for c in result.final_constraints}
    assert by_id["c_port_a"].status == ConstraintStatus.ACCEPTED
    assert by_id["c_port_b"].status == ConstraintStatus.SUPERSEDED
    assert by_id["c_port_b"].payload["port"] == 8081


def test_cnp_security_priority_wins():
    constraints = [
        Constraint(
            constraint_id="c_pref",
            type=ConstraintType.NETWORK_POLICY,
            priority=Priority.PREFERENCE,
            source_agent="Docker Agent",
            payload={"rule": "external_access", "mode": "unrestricted"},
        ),
        Constraint(
            constraint_id="c_sec",
            type=ConstraintType.SECURITY_POLICY,
            priority=Priority.SECURITY,
            source_agent="Security Agent",
            payload={"rule": "external_access", "mode": "restricted"},
        ),
    ]
    result = run_cnp("dep_y", constraints)
    assert result.status == "resolved"
    assert any(d.method == "priority" for d in result.decisions)
    by_id = {c.constraint_id: c for c in result.final_constraints}
    assert by_id["c_sec"].status == ConstraintStatus.ACCEPTED
    assert by_id["c_pref"].status == ConstraintStatus.REJECTED


def test_cnp_round_cap_constant():
    from app.cnp.engine import MAX_ROUNDS

    assert MAX_ROUNDS == 3
