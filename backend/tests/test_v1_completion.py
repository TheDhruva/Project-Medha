"""V1 completion regression tests: URL hardening, canonical labelling, CIG gate."""

from __future__ import annotations

from pathlib import Path

from tests.conftest import _deploy_payload
from tests.test_planning_api import _wait_terminal, FIXTURE_REPO

from app.agents.verifier import run_verifier
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


def _profile() -> ApplicationProfile:
    return ApplicationProfile(
        deployment_id="dep_v1",
        repository_url="local",
        workspace_path=".",
        target_host="localhost",
        target_port=8080,
        inferred_stack=InferredStack(
            confidence=0.9,
            services=[ServiceHint(name="backend", role="api")],
        ),
    )


def _security_constraints() -> list[Constraint]:
    return [
        Constraint(
            constraint_id="c_sec_1",
            type=ConstraintType.SECURITY_POLICY,
            priority=Priority.SECURITY,
            source_agent="security",
            status=ConstraintStatus.ACCEPTED,
            payload={"rule": "no_privileged", "mode": "block"},
        )
    ]


def _negotiation() -> NegotiationResult:
    return NegotiationResult(
        deployment_id="dep_v1",
        status="resolved",
        rounds_used=1,
        conflicts=[],
        decisions=[],
        final_constraints=[],
    )


def test_verifier_has_change_impact_advisory_by_default():
    result = run_verifier(
        deployment_id="dep_v1",
        profile=_profile(),
        constraints=_security_constraints(),
        negotiation=_negotiation(),
        config_fragments={},
    )
    advisory = [c for c in result.checks if c.id == "change_impact"]
    assert len(advisory) == 1
    assert advisory[0].status.value == "pass"
    assert result.passed is True  # advisory never blocks


def test_verifier_change_impact_warns_with_requirements():
    result = run_verifier(
        deployment_id="dep_v1",
        profile=_profile(),
        constraints=_security_constraints(),
        negotiation=_negotiation(),
        config_fragments={},
        change_requirements=[
            {"executable": True, "requirement": "re-validate config"},
            {"executable": False, "requirement": "review deleted import"},
        ],
        change_risk="high",
    )
    advisory = next(c for c in result.checks if c.id == "change_impact")
    assert advisory.status.value == "warning"
    assert "HIGH" in advisory.message
    assert result.passed is True  # still advisory, never blocking


def test_deploy_rejects_dangerous_repository_urls(client):
    for bad in (
        "javascript:alert(1)",
        "http://169.254.169.254/latest/meta-data/",
        "https://user:secret@github.com/org/repo.git",
        "ftp://example.com/repo.git",
    ):
        response = client.post("/api/deploy", json=_deploy_payload(repository_url=bad))
        assert response.status_code == 422, (bad, response.text)


def test_deploy_accepts_github_and_local_urls(client):
    from app.core.deploy_lock import release_real_deploy

    response = client.post(
        "/api/deploy",
        json=_deploy_payload(repository_url="https://github.com/example/app"),
    )
    assert response.status_code == 202
    # V1 allows one real deployment at a time; release the in-flight lock
    # before asserting the second creation path (contract, not concurrency).
    release_real_deploy()
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(
            mode="real", scenario=None, repository_url=FIXTURE_REPO
        ),
    )
    assert response.status_code == 202


def test_change_impact_rejects_dangerous_url(client):
    response = client.post(
        "/api/change-impact/analyze",
        json={
            "repository_url": "http://169.254.169.254/x.git",
            "base_revision": "a",
            "target_revision": "b",
        },
    )
    assert response.status_code == 422


def test_real_pipeline_has_no_synthetic_services(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(
            mode="real",
            scenario=None,
            repository_url=FIXTURE_REPO,
            intent="Deploy the application securely",
        ),
    )
    assert response.status_code == 202
    deployment_id = response.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)
    assert final["status"] == "completed"
    result = final["result"]
    # compose_app fixture detects database/backend/frontend: the plan must
    # reflect exactly the discovered topology, with no injected services.
    assert result["expanded_to_canonical"] is False
    assert result["synthetic_services"] == []
    assert "synthetic" not in (result["message"] or "").lower()

    graph = client.get(f"/api/deploy/{deployment_id}/graph").json()
    services = {str(n["service"]).lower() for n in graph["graph"]["nodes"]}
    assert "analytics" not in services
    assert {"network", "database", "backend", "frontend"} <= services
