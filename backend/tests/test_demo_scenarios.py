"""Demo removal contract (product): demo execution is unreachable via the API.

The deterministic demo engine (app.demo) remains importable for isolated
unit use, but no product route may create demo runs, list scenarios, or
serve demo fixtures. Historical DEMO/MOCK records keep their labels.
"""

from __future__ import annotations

import time

from tests.conftest import _deploy_payload


def _wait_terminal(client, deployment_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def test_demo_mode_rejected_with_gone(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="demo", scenario="PORT_CONFLICT"),
    )
    assert response.status_code in {410, 422}
    if response.status_code == 410:
        assert response.json()["error"]["code"] == "DEMO_REMOVED"


def test_demo_scenarios_route_gone(client):
    assert client.get("/api/demo/scenarios").status_code == 404


def test_demo_change_impact_fixture_gone(client):
    assert client.get("/api/change-impact/demo/fixture").status_code == 404


def test_unknown_scenario_rejected(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="demo", scenario="NOT_A_REAL_SCENARIO"),
    )
    assert response.status_code == 422


def test_demo_engine_still_importable_for_isolated_use():
    # Isolated fixture only: importable, never reachable from product routes.
    from app.demo.runner import DemoRunner  # noqa: F401
    from app.demo.scenarios import list_scenarios

    assert isinstance(list_scenarios(), list)


def test_real_run_has_no_demo_markers(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    final = _wait_terminal(client, created["deployment_id"])
    assert final["is_demo"] is False
    assert final.get("label") is None
    result = final.get("result") or {}
    assert result.get("is_demo") is False or "is_demo" not in result
    # No synthetic services in the real plan.
    assert result.get("synthetic_services", []) == []
    assert result.get("expanded_to_canonical") is False


def test_determinism_same_repo_twice(client):
    first = client.post("/api/deploy", json=_deploy_payload()).json()
    first_final = _wait_terminal(client, first["deployment_id"])
    second = client.post("/api/deploy", json=_deploy_payload()).json()
    second_final = _wait_terminal(client, second["deployment_id"])
    assert first_final["result"]["title"] == second_final["result"]["title"]
    c1 = client.get(f"/api/deploy/{first['deployment_id']}/constraints").json()
    c2 = client.get(f"/api/deploy/{second['deployment_id']}/constraints").json()
    assert c1["negotiation"]["method"] == c2["negotiation"]["method"]


def test_sse_stream_emits_json_events_phase3(client):
    created = client.post("/api/deploy", json=_deploy_payload()).json()
    deployment_id = created["deployment_id"]
    final = _wait_terminal(client, deployment_id)
    assert final["status"] in {"completed", "failed"}

    # Replay the persisted stream: the server closes on the terminal event,
    # so this read is bounded by construction (no live-wait).
    with client.stream("GET", f"/api/deploy/{deployment_id}/events") as response:
        assert response.status_code == 200
        collected: list[dict] = []
        for line in response.iter_lines():
            if not line or line.startswith(":"):
                continue
            if line.startswith("data: "):
                import json as _json

                collected.append(_json.loads(line.removeprefix("data: ")))
                if collected[-1]["type"] in {"deployment.completed", "deployment.failed"}:
                    break
        assert collected, "SSE replay delivered no events"
        assert any(item["type"] == "deployment.created" for item in collected)
        assert any(item["type"] == "stage.started" for item in collected)
        assert collected[-1]["type"] in {"deployment.completed", "deployment.failed"}
        assert all(item["is_demo"] is False for item in collected)
