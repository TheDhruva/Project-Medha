from __future__ import annotations

import json
import time

from app.core.deploy_lock import release_real_deploy, try_acquire_real_deploy
from tests.conftest import _deploy_payload


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] in {"ok", "degraded"}
    assert body["service"] == "medha-backend"
    assert body["database"] == "ok"


def test_create_deployment(client):
    response = client.post("/api/deploy", json=_deploy_payload())
    assert response.status_code == 202
    body = response.json()
    assert body["deployment_id"].startswith("dep_")
    assert body["status"] == "started"
    assert body["is_demo"] is True


def test_get_deployment(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]
    response = client.get(f"/api/deploy/{deployment_id}")
    assert response.status_code == 200
    body = response.json()
    assert body["deployment_id"] == deployment_id
    assert body["scenario"] == "PORT_CONFLICT"
    assert body["target"]["port"] == 8080


def test_deployment_not_found(client):
    response = client.get("/api/deploy/dep_missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_validation_error_missing_scenario(client):
    payload = _deploy_payload()
    payload.pop("scenario")
    response = client.post("/api/deploy", json=payload)
    assert response.status_code == 422


def test_validation_error_bad_host(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(target={"host": "example.com", "port": 8080}),
    )
    assert response.status_code == 422


def test_sqlite_persistence_across_reads(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]
    first = client.get(f"/api/deploy/{deployment_id}").json()
    second = client.get(f"/api/deploy/{deployment_id}").json()
    assert first["deployment_id"] == second["deployment_id"]
    assert first["created_at"] == second["created_at"]


def test_events_and_logs_generated(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]

    # Wait for demo workflow to finish.
    deadline = time.time() + 15
    status = "started"
    while time.time() < deadline:
        status = client.get(f"/api/deploy/{deployment_id}").json()["status"]
        if status in {"completed", "failed", "partial_recovery"}:
            break
        time.sleep(0.02)

    assert status == "completed"

    logs = client.get(f"/api/deploy/{deployment_id}/logs").json()
    assert logs["deployment_id"] == deployment_id
    assert len(logs["lines"]) >= 4
    types = {line["type"] for line in logs["lines"]}
    assert "deployment.created" in types
    assert "deployment.completed" in types
    assert "stage.started" in types
    assert "stage.completed" in types


def test_constraints_and_graph_populated_after_demo(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]

    deadline = time.time() + 10
    status = "started"
    while time.time() < deadline:
        status = client.get(f"/api/deploy/{deployment_id}").json()["status"]
        if status in {"completed", "failed", "partial_recovery"}:
            break
        time.sleep(0.02)

    assert status == "completed"
    constraints = client.get(f"/api/deploy/{deployment_id}/constraints").json()
    graph = client.get(f"/api/deploy/{deployment_id}/graph").json()
    assert len(constraints["constraints"]) >= 2
    assert constraints["negotiation"]["status"] == "resolved"
    assert len(graph["graph"]["nodes"]) >= 5
    assert len(graph["graph"]["edges"]) >= 4


def test_real_mode_accepted_for_planning(client):
    from pathlib import Path

    repo = str(
        (Path(__file__).resolve().parent / "fixtures" / "repos" / "node_api").resolve()
    )
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert response.status_code == 202
    assert response.json()["is_demo"] is False


def test_real_deploy_busy_returns_409(client):
    release_real_deploy()
    release_real_deploy("dep_busy_holder")
    try_acquire_real_deploy("dep_busy_holder")
    try:
        from pathlib import Path

        repo = str(
            (Path(__file__).resolve().parent / "fixtures" / "repos" / "node_api").resolve()
        )
        response = client.post(
            "/api/deploy",
            json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
        )
        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "DEPLOYMENT_BUSY"
        assert error["details"]["busy"] is True
        assert error["details"]["deployment_id"] == "dep_busy_holder"
    finally:
        release_real_deploy("dep_busy_holder")


def test_events_stream_not_found_uses_error_shape(client):
    response = client.get("/api/deploy/dep_missing/events")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_events_stream_replays_then_ends_on_terminal(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]

    deadline = time.time() + 15
    status = "started"
    while time.time() < deadline:
        status = client.get(f"/api/deploy/{deployment_id}").json()["status"]
        if status in {"completed", "failed", "partial_recovery"}:
            break
        time.sleep(0.02)
    assert status == "completed"

    with client.stream("GET", f"/api/deploy/{deployment_id}/events") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())
        events = [
            json.loads(line.removeprefix("data: ").strip())
            for line in body.split("\n\n")
            if line.strip().startswith("data: ")
        ]
    types = [event["type"] for event in events]
    assert "deployment.created" in types
    assert "deployment.completed" in types
    assert any(event.get("is_demo") is True for event in events)
    # Terminal event is included and the stream ends (no ping block).
    assert events[-1]["type"] == "deployment.completed"


def _wait_completed(client, deployment_id, timeout=15):
    deadline = time.time() + timeout
    status = "started"
    while time.time() < deadline:
        status = client.get(f"/api/deploy/{deployment_id}").json()["status"]
        if status in {"completed", "failed", "partial_recovery"}:
            break
        time.sleep(0.02)
    return status


def test_list_deployments_empty(client):
    response = client.get("/api/deploys")
    assert response.status_code == 200
    body = response.json()
    assert body["runs"] == []
    assert body["total"] == 0
    assert body["filters"] == {"status": None, "mode": None, "repository": None}


def test_list_deployments_returns_completed_run_summary(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]
    assert _wait_completed(client, deployment_id) == "completed"

    response = client.get("/api/deploys")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1
    run = next(r for r in body["runs"] if r["deployment_id"] == deployment_id)
    assert run["status"] == "completed"
    assert run["mode"] == "demo"
    assert run["is_demo"] is True
    assert run["label"] == "DEMO/MOCK"
    assert run["repository_url"] == "https://github.com/example/app"
    assert run["scenario"] == "PORT_CONFLICT"
    assert run["duration_seconds"] is not None
    assert run["duration_seconds"] >= 0.0
    assert run["risk"] in {"high", "medium", "low", "none", None}


def test_list_deployments_filters(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]
    assert _wait_completed(client, deployment_id) in {"completed", "failed", "partial_recovery"}

    demo = client.get("/api/deploys", params={"mode": "demo"}).json()
    assert demo["total"] >= 1
    assert all(r["mode"] == "demo" for r in demo["runs"])

    real = client.get("/api/deploys", params={"mode": "real"}).json()
    assert real["total"] == 0

    by_repo = client.get(
        "/api/deploys", params={"repository": "github.com/example/app"}
    ).json()
    assert by_repo["total"] >= 1
    assert all("github.com/example/app" in r["repository_url"] for r in by_repo["runs"])

    by_status = client.get("/api/deploys", params={"status": "completed"}).json()
    assert by_status["total"] >= 1
    assert all(r["status"] == "completed" for r in by_status["runs"])

    paginated = client.get("/api/deploys", params={"limit": 1, "offset": 0}).json()
    assert len(paginated["runs"]) == 1
    assert paginated["total"] >= 1


def test_list_deployments_invalid_mode(client):
    response = client.get("/api/deploys", params={"mode": "bogus"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_MODE"


def test_logs_include_stage_and_status(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]
    assert _wait_completed(client, deployment_id) in {"completed", "failed", "partial_recovery"}

    logs = client.get(f"/api/deploy/{deployment_id}/logs").json()
    assert len(logs["lines"]) >= 1
    entry = logs["lines"][0]
    assert "stage" in entry
    assert "status" in entry
    assert any(line.get("stage") is not None for line in logs["lines"])
