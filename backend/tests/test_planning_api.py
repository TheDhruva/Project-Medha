from __future__ import annotations

import time
from pathlib import Path

from tests.conftest import _deploy_payload

FIXTURE_REPO = str(
    (Path(__file__).resolve().parent / "fixtures" / "repos" / "compose_app").resolve()
)


def _wait_terminal(client, deployment_id: str, timeout: float = 30.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"Deployment did not finish: {body}")


def test_real_mode_full_success_pipeline(client):
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
    assert final["result"]["title"] == "SUCCESS"
    assert final["result"]["phase"] == "10-11"

    verification = client.get(f"/api/deploy/{deployment_id}/verification").json()
    assert verification["verification"]["passed"] is True
    assert verification["critic"]["score"] >= 0

    graph = client.get(f"/api/deploy/{deployment_id}/graph").json()
    assert len(graph["graph"]["nodes"]) >= 4


def test_real_mode_partial_failure_intent(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(
            mode="real",
            scenario=None,
            repository_url=FIXTURE_REPO,
            intent="Deploy securely with partial failure backend fail",
        ),
    )
    deployment_id = response.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)
    assert final["status"] == "partial_recovery"
    result = final["result"]
    assert result["title"] == "PARTIAL_FAILURE"
    assert "backend" in result["failed_services"]
    assert "frontend" in result["rolled_back_services"]
    assert "analytics" in result["preserved_services"]

    graph = client.get(f"/api/deploy/{deployment_id}/graph").json()
    nodes = {n["id"]: n for n in graph["graph"]["nodes"]}
    assert nodes["n_backend"]["status"] == "failed"
    assert nodes["n_frontend"]["status"] == "rolled_back"
    assert nodes["n_analytics"]["status"] == "preserved"
    assert graph["rollback"]["failed_node_id"] == "n_backend"


def test_real_mode_verification_replan(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(
            mode="real",
            scenario=None,
            repository_url=FIXTURE_REPO,
            intent="Deploy securely with force verification failure missing env",
        ),
    )
    deployment_id = response.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)
    # After bounded replan should succeed
    assert final["status"] in {"completed", "partial_recovery"}
    verification = client.get(f"/api/deploy/{deployment_id}/verification").json()
    assert verification["verification"]["passed"] is True
    assert verification["verification"].get("replan_count", 0) >= 1

    logs = client.get(f"/api/deploy/{deployment_id}/logs").json()["lines"]
    types = [line["type"] for line in logs]
    assert "verification.failed" in types
    assert "replan.started" in types
    assert "verification.passed" in types
