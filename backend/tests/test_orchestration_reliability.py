"""Reliability additions: acquire timeout, agent snapshots over HTTP, cancel idempotency.

Complements test_orchestration_phase2.py (specialist/analyzer timeouts,
single-cancel races, SSE replay). All pipeline tests drive the real
PlanningPipeline; only external slowness is injected via sleeping wrappers
that still delegate to real logic.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.core.config import get_settings
from tests.conftest import _deploy_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"

VALID_AGENT_STATUSES = {
    "idle", "running", "complete", "failed", "skipped",
    "cancelled", "timed_out",
}
EXPECTED_AGENT_IDS = [
    "preflight", "analyzer", "docker", "nginx", "security",
    "mediator", "verifier", "critic", "executor", "rollback",
]


def _wait_terminal(client, deployment_id: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def _logs(client, deployment_id: str) -> dict:
    return client.get(f"/api/deploy/{deployment_id}/logs",
                      params={"limit": 2000}).json()


def test_acquire_timeout_fails_closed(client, monkeypatch):
    import time as _time

    import app.workflow.planning as planning
    from app.execution.executor import SimulatorExecutor

    real_acquire = planning.acquire_repository

    def slow_acquire(*args, **kwargs):
        _time.sleep(5)
        return real_acquire(*args, **kwargs)

    monkeypatch.setattr(planning, "acquire_repository", slow_acquire)
    monkeypatch.setattr(get_settings(), "timeout_acquire_s", 0.1)
    calls = {"execute": 0}
    real_execute = SimulatorExecutor.execute

    def counting_execute(self, *args, **kwargs):
        calls["execute"] += 1
        return real_execute(self, *args, **kwargs)

    monkeypatch.setattr(SimulatorExecutor, "execute", counting_execute)
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "failed"
    assert "timed out" in (final.get("error_summary") or "")
    assert (final.get("result") or {}).get("code") == "TIMEOUT:acquire"
    assert calls["execute"] == 0


def test_logs_include_backend_agent_snapshot(client):
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    deployment_id = resp.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)
    assert final["status"] in {"completed", "failed", "partial_recovery"}

    body = _logs(client, deployment_id)
    agents = body.get("agents")
    assert isinstance(agents, list) and len(agents) == 10
    assert [row["id"] for row in agents] == EXPECTED_AGENT_IDS
    for row in agents:
        assert row["status"] in VALID_AGENT_STATUSES
        assert isinstance(row["activity"], str) and row["activity"]
        assert isinstance(row["deps"], list)
        assert row["durationMs"] is None or isinstance(row["durationMs"], (int, float))
        # No secrets or raw payloads in the snapshot surface.
        for banned in ("token", "secret", "password", "api_key", "private_key"):
            assert banned not in " ".join(str(k) for k in row.keys()).lower()
    # A finished run has no agent left running.
    assert all(row["status"] != "running" for row in agents)


def test_cancel_is_idempotent_single_terminal(client, monkeypatch):
    import time as _time

    import app.workflow.planning as planning
    from app.execution.executor import SimulatorExecutor

    real_analyze = planning.analyze_repository

    def slow_analyze(**kwargs):
        _time.sleep(3)
        return real_analyze(**kwargs)

    monkeypatch.setattr(planning, "analyze_repository", slow_analyze)
    calls = {"execute": 0}
    real_execute = SimulatorExecutor.execute

    def counting_execute(self, *args, **kwargs):
        calls["execute"] += 1
        return real_execute(self, *args, **kwargs)

    monkeypatch.setattr(SimulatorExecutor, "execute", counting_execute)
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    deployment_id = resp.json()["deployment_id"]
    deadline = time.time() + 15.0
    while time.time() < deadline:
        if client.get(f"/api/deploy/{deployment_id}").json()["status"] == "running":
            break
        time.sleep(0.05)

    first = client.post(f"/api/deploy/{deployment_id}/cancel")
    second = client.post(f"/api/deploy/{deployment_id}/cancel")
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "cancelled"
    # Second request is an idempotent repeat, never a state regression.
    assert second.json()["status"] == "cancelled"

    final = _wait_terminal(client, deployment_id)
    assert final["status"] == "cancelled"
    assert calls["execute"] == 0
    lines = _logs(client, deployment_id)["lines"]
    terminals = [ln for ln in lines if ln["type"] in {
        "deployment.completed", "deployment.failed", "deployment.cancelled"}]
    assert len(terminals) == 1
    assert terminals[0]["type"] == "deployment.cancelled"
    # The detached analyzer thread settles later; it must not flip the
    # terminal state or start execution.
    time.sleep(4)
    assert client.get(f"/api/deploy/{deployment_id}").json()["status"] == "cancelled"
    assert calls["execute"] == 0
