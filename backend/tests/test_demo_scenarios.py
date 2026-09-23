from __future__ import annotations

import json
import time

from app.core.enums import ScenarioId
from tests.conftest import _deploy_payload


def _wait_terminal(client, deployment_id: str, timeout: float = 20.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery"}:
            return body
        time.sleep(0.02)
    raise AssertionError(f"Deployment did not finish: {body}")


def _start(client, scenario: str) -> str:
    created = client.post("/api/deploy", json=_deploy_payload(scenario=scenario)).json()
    return created["deployment_id"]


def test_successful_deployment(client):
    deployment_id = _start(client, "SUCCESSFUL_DEPLOYMENT")
    body = _wait_terminal(client, deployment_id)
    assert body["status"] == "completed"
    assert body["is_demo"] is True
    result = body["result"]
    assert result["kind"] == "success"
    assert result["title"] == "SUCCESS"
    assert result["is_demo"] is True
    services = {s["name"]: s["status"] for s in result["services"]}
    assert all(status == "success" for status in services.values())
    assert result["rollbackScope"] is None

    constraints = client.get(f"/api/deploy/{deployment_id}/constraints").json()
    assert constraints["negotiation"]["status"] == "resolved"
    assert constraints["negotiation"].get("method") == "VALIDATE"
    events = client.get(f"/api/deploy/{deployment_id}/logs").json()["lines"]
    types = {line["type"] for line in events}
    assert "deployment.completed" in types
    assert "constraint.conflict" not in types
    assert "rollback.started" not in types


def test_port_conflict(client):
    deployment_id = _start(client, "PORT_CONFLICT")
    body = _wait_terminal(client, deployment_id)
    assert body["status"] == "completed"
    result = body["result"]
    assert result["kind"] == "success"
    assert result["constraintsResolved"] == 1

    constraints = client.get(f"/api/deploy/{deployment_id}/constraints").json()
    by_id = {c["id"]: c for c in constraints["constraints"]}
    assert by_id["c_port_docker"]["status"] == "accepted"
    assert by_id["c_port_nginx"]["status"] == "superseded"
    assert by_id["c_port_nginx"]["payload"]["port"] == 8081
    assert constraints["negotiation"]["status"] == "resolved"
    assert constraints["negotiation"]["method"] == "ALTERNATIVE"

    events = client.get(f"/api/deploy/{deployment_id}/logs").json()["lines"]
    types = [line["type"] for line in events]
    assert "constraint.conflict" in types
    assert "negotiation.resolved" in types
    assert types.index("constraint.conflict") < types.index("negotiation.resolved")


def test_security_conflict(client):
    deployment_id = _start(client, "SECURITY_CONFLICT")
    body = _wait_terminal(client, deployment_id)
    assert body["status"] == "completed"
    result = body["result"]
    assert result["kind"] == "success"

    constraints = client.get(f"/api/deploy/{deployment_id}/constraints").json()
    by_id = {c["id"]: c for c in constraints["constraints"]}
    assert by_id["c_sec_restricted"]["status"] == "accepted"
    assert by_id["c_sec_restricted"]["priority"] == "SECURITY"
    assert by_id["c_net_open"]["status"] == "rejected"
    assert by_id["c_net_open"]["priority"] == "PREFERENCE"
    assert constraints["negotiation"]["method"] == "PRIORITY"

    events = client.get(f"/api/deploy/{deployment_id}/logs").json()["lines"]
    types = {line["type"] for line in events}
    assert "constraint.conflict" in types
    assert "negotiation.resolved" in types


def test_verification_failure(client):
    deployment_id = _start(client, "VERIFICATION_FAILURE")
    body = _wait_terminal(client, deployment_id)
    assert body["status"] == "completed"
    result = body["result"]
    assert result["kind"] == "success"

    verification = client.get(f"/api/deploy/{deployment_id}/verification").json()
    assert verification["verification"]["passed"] is True
    assert verification["verification"].get("replan_count") == 1

    events = client.get(f"/api/deploy/{deployment_id}/logs").json()["lines"]
    types = [line["type"] for line in events]
    assert "verification.failed" in types
    assert "replan.started" in types
    assert "verification.passed" in types
    assert types.index("verification.failed") < types.index("replan.started")
    assert types.index("replan.started") < types.index(
        [t for t in types if t == "verification.passed"][-1]
    )


def test_partial_failure(client):
    deployment_id = _start(client, "PARTIAL_FAILURE")
    body = _wait_terminal(client, deployment_id)
    assert body["status"] == "partial_recovery"
    result = body["result"]
    assert result["kind"] == "partial_recovery"
    assert result["title"] == "PARTIAL_FAILURE"
    assert result["failed_services"] == ["backend"]
    assert result["rolled_back_services"] == ["frontend"]
    assert set(result["preserved_services"]) == {"network", "database", "analytics"}

    graph = client.get(f"/api/deploy/{deployment_id}/graph").json()
    nodes = {n["id"]: n for n in graph["graph"]["nodes"]}
    assert nodes["n_backend"]["status"] == "failed"
    assert nodes["n_frontend"]["status"] == "rolled_back"
    assert nodes["n_network"]["status"] == "preserved"
    assert nodes["n_database"]["status"] == "preserved"
    assert nodes["n_analytics"]["status"] == "preserved"
    assert graph["rollback"]["failed_node_id"] == "n_backend"
    assert graph["rollback"]["nodes_to_rollback"] == ["n_frontend"]
    assert "n_analytics" in graph["rollback"]["nodes_preserved"]
    assert "n_analytics" not in graph["rollback"]["nodes_to_rollback"]

    events = client.get(f"/api/deploy/{deployment_id}/logs").json()["lines"]
    types = {line["type"] for line in events}
    assert "execution.failed" in types
    assert "rollback.completed" in types


def test_event_ordering_and_demo_labels(client):
    deployment_id = _start(client, "SUCCESSFUL_DEPLOYMENT")
    _wait_terminal(client, deployment_id)
    lines = client.get(f"/api/deploy/{deployment_id}/logs").json()["lines"]
    assert lines[0]["type"] == "deployment.created"
    assert lines[-1]["type"] == "deployment.completed"
    assert all(line["is_demo"] is True for line in lines)
    stages = [line["type"] for line in lines if line["type"] == "stage.started"]
    assert stages  # at least some stages emitted


def test_unknown_scenario_rejected(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(scenario="NOT_A_REAL_SCENARIO"),
    )
    assert response.status_code == 422


def test_scenario_list(client):
    response = client.get("/api/demo/scenarios")
    assert response.status_code == 200
    body = response.json()
    ids = {s["id"] for s in body["scenarios"]}
    assert ids == {s.value for s in ScenarioId}


def test_determinism_same_scenario_twice(client):
    first_id = _start(client, "PORT_CONFLICT")
    first = _wait_terminal(client, first_id)
    second_id = _start(client, "PORT_CONFLICT")
    second = _wait_terminal(client, second_id)
    assert first["result"]["title"] == second["result"]["title"]
    assert first["result"]["constraintsResolved"] == second["result"]["constraintsResolved"]
    c1 = client.get(f"/api/deploy/{first_id}/constraints").json()
    c2 = client.get(f"/api/deploy/{second_id}/constraints").json()
    assert c1["negotiation"]["method"] == c2["negotiation"]["method"]
    ports = [
        (c["id"], c["payload"].get("port"))
        for c in c1["constraints"]
        if c["id"] in {"c_port_docker", "c_port_nginx"}
    ]
    ports2 = [
        (c["id"], c["payload"].get("port"))
        for c in c2["constraints"]
        if c["id"] in {"c_port_docker", "c_port_nginx"}
    ]
    assert ports == ports2


def test_sse_stream_emits_json_events_phase3(client):
    created = client.post(
        "/api/deploy",
        json=_deploy_payload(scenario="SUCCESSFUL_DEPLOYMENT"),
    ).json()
    deployment_id = created["deployment_id"]

    with client.stream("GET", f"/api/deploy/{deployment_id}/events") as response:
        assert response.status_code == 200
        collected: list[dict] = []
        for line in response.iter_lines():
            if not line or line.startswith(":"):
                continue
            if line.startswith("data: "):
                collected.append(json.loads(line.removeprefix("data: ")))
                if collected[-1]["type"] in {"deployment.completed", "deployment.failed"}:
                    break
        assert any(item["type"] == "deployment.created" for item in collected)
        assert any(item["type"] == "stage.started" for item in collected)
        assert collected[-1]["type"] == "deployment.completed"
        assert all(item["is_demo"] is True for item in collected)
