"""Phase 2 orchestration: timeouts, cancellation, terminal races, events.

Pipeline tests drive the real PlanningPipeline through the TestClient or
directly (asyncio.run) with real gates; only external slowness is
injected (sleeping wrappers that still delegate to real logic).
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from app.core import run_control
from app.core.config import get_settings
from tests.conftest import _deploy_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"


def _wait_terminal(client, deployment_id: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def _log_lines(client, deployment_id: str) -> list[dict]:
    return client.get(f"/api/deploy/{deployment_id}/logs",
                      params={"limit": 2000}).json()["lines"]


def _terminal_types(lines: list[dict]) -> list[str]:
    return [ln["type"] for ln in lines
            if ln["type"] in {"deployment.completed", "deployment.failed",
                              "deployment.cancelled", "proposal.ready"}]


# --- timeouts -------------------------------------------------------------------

def test_specialist_timeout_fails_closed(client, monkeypatch):
    import time as _time

    import app.workflow.planning as planning
    from app.execution.executor import SimulatorExecutor

    real_docker = planning.run_docker_agent

    def slow_docker(profile):
        _time.sleep(5)
        return real_docker(profile)

    monkeypatch.setattr(planning, "run_docker_agent", slow_docker)
    monkeypatch.setattr(get_settings(), "timeout_specialists_s", 0.1)
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
    assert calls["execute"] == 0
    lines = _log_lines(client, final["deployment_id"])
    assert sum(1 for ln in lines
               if ln["type"] == "agent.completed"
               and "stage time budget" in ln["message"]) == 3


def test_analyzer_timeout_fails_closed(client, monkeypatch):
    import time as _time

    import app.workflow.planning as planning

    real_analyze = planning.analyze_repository

    def slow_analyze(**kwargs):
        _time.sleep(5)
        return real_analyze(**kwargs)

    monkeypatch.setattr(planning, "analyze_repository", slow_analyze)
    monkeypatch.setattr(get_settings(), "timeout_analyze_s", 0.1)
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "failed"
    assert "TIMEOUT:analyze" in (final["result"] or {}).get("code", "") or \
        "timed out" in (final.get("error_summary") or "")


# --- cancellation -----------------------------------------------------------------

def test_explicit_cancel_during_run_then_rerun(client, monkeypatch):
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
    # Wait until the run is actually in flight, then cancel it.
    deadline = time.time() + 15.0
    while time.time() < deadline:
        if client.get(f"/api/deploy/{deployment_id}").json()["status"] == "running":
            break
        time.sleep(0.05)
    cancel = client.post(f"/api/deploy/{deployment_id}/cancel")
    assert cancel.status_code == 200
    final = _wait_terminal(client, deployment_id)
    assert final["status"] == "cancelled"
    assert calls["execute"] == 0
    # Exactly one terminal event despite the racing analyzer thread.
    assert len(_terminal_types(_log_lines(client, deployment_id))) == 1
    # Cancellation is idempotent; the single-flight lock is released.
    again = client.post(f"/api/deploy/{deployment_id}/cancel")
    assert again.json()["status"] == "cancelled"
    rerun = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert rerun.status_code == 202
    # Deterministic again: no artificial slowness on the second run.
    monkeypatch.undo()
    second = _wait_terminal(client, rerun.json()["deployment_id"])
    assert second["status"] == "completed"


def test_completed_run_not_cancellable(client):
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "completed"
    cancel = client.post(f"/api/deploy/{final['deployment_id']}/cancel")
    assert cancel.json().get("duplicate") is True
    assert cancel.json()["status"] == "completed"
    assert client.get(f"/api/deploy/{final['deployment_id']}").json()["status"] == "completed"


def test_cancel_unknown_run_404(client):
    resp = client.post("/api/deploy/dep_nope/cancel")
    assert resp.status_code == 404


def test_cancel_before_executor_gate_no_execution():
    """Pre-requested cancellation stops _run_verify_execute before any gate."""
    import app.workflow.planning as planning
    from app.agents.analyzer import analyze_repository
    from app.agents.docker_agent import run_docker_agent
    from app.agents.nginx_agent import run_nginx_agent
    from app.agents.security_agent import run_security_agent
    from app.cnp.engine import run_cnp
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.execution.executor import SimulatorExecutor
    from app.models.deployment import DeploymentRecord
    from app.workflow.planning import PlanningPipeline

    import tempfile
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "gate.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    src = FIXTURES / "compose_app"
    repo.create(DeploymentRecord(
        deployment_id="dep_gatecancel", repository_url=str(src),
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    profile, _ = analyze_repository(
        deployment_id="dep_gatecancel", repository_url=str(src),
        workspace_path=src, target_host="localhost", target_port=8080)
    docker, nginx, security = (run_docker_agent(profile),
                              run_nginx_agent(profile),
                              run_security_agent(profile))
    negotiation = run_cnp("dep_gatecancel",
                          [*docker.constraints, *nginx.constraints, *security.constraints])
    assert negotiation.status == "resolved"
    calls = {"execute": 0}
    real_execute = SimulatorExecutor.execute

    def counting_execute(self, *args, **kwargs):
        calls["execute"] += 1
        return real_execute(self, *args, **kwargs)

    orig = SimulatorExecutor.execute
    SimulatorExecutor.execute = counting_execute
    try:
        run_control.request_cancel("dep_gatecancel")
        asyncio.run(PlanningPipeline(repo=repo)._run_verify_execute(
            deployment_id="dep_gatecancel",
            profile=profile,
            negotiation=negotiation,
            ui_constraints=[c.to_ui() for c in negotiation.final_constraints],
            ui_negotiation=negotiation.to_ui(),
            config_fragments={"docker": docker.artifacts,
                              "nginx": nginx.artifacts,
                              "security": security.artifacts},
            constraints_resolved=len(negotiation.decisions),
            delay=0.0,
            intent=None,
        ))
    finally:
        SimulatorExecutor.execute = orig
        run_control.clear_run("dep_gatecancel")
    assert calls["execute"] == 0
    stored = repo.get("dep_gatecancel")
    assert stored is not None and stored.status == DeploymentStatus.CANCELLED


def test_timeout_cancel_race_single_terminal(client, monkeypatch):
    import threading
    import time as _time

    import app.workflow.planning as planning
    from app.core import run_control as _rc

    real_analyze = planning.analyze_repository

    def slow_analyze(**kwargs):
        _time.sleep(2)
        return real_analyze(**kwargs)

    monkeypatch.setattr(planning, "analyze_repository", slow_analyze)
    monkeypatch.setattr(get_settings(), "timeout_analyze_s", 30.0)
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    deployment_id = resp.json()["deployment_id"]
    timer = threading.Timer(0.3, _rc.request_cancel, args=(deployment_id,))
    timer.start()
    try:
        final = _wait_terminal(client, deployment_id)
    finally:
        timer.join()
    # Whoever wins, the run is terminal exactly once and never succeeds late.
    assert final["status"] in {"failed", "cancelled", "completed"}
    assert len(_terminal_types(_log_lines(client, deployment_id))) == 1
    if final["status"] == "cancelled":
        assert (final.get("result") or {}).get("kind") != "success"


def test_late_fail_after_cancel_is_dropped(tmp_path):
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord
    from app.workflow.planning import PlanningPipeline

    db = tmp_path / "late.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id="dep_late", repository_url="x",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    before = repo.list_events("dep_late", 500)
    repo.update_status(
        "dep_late", status=DeploymentStatus.CANCELLED,
        explain_simple="cancelled", explain_technical="test",
        updated_at=utc_now_iso(),
        allowed_from={DeploymentStatus.STARTED.value, DeploymentStatus.RUNNING.value},
    )
    asyncio.run(PlanningPipeline(repo=repo)._fail(
        "dep_late", "late failure", technical="LATE"))
    stored = repo.get("dep_late")
    assert stored is not None and stored.status == DeploymentStatus.CANCELLED
    after = repo.list_events("dep_late", 500)
    assert len(after) == len(before)
    run_control.clear_run("dep_late")


def test_claim_terminal_single_owner():
    run_control.clear_run("dep_claim")
    try:
        assert run_control.claim_terminal("dep_claim") is True
        assert run_control.claim_terminal("dep_claim") is False
    finally:
        run_control.clear_run("dep_claim")
        assert run_control.claim_terminal("dep_claim") is True
        run_control.clear_run("dep_claim")


# --- agent lifecycle + event contracts --------------------------------------------

def _read_sse_payloads(client, deployment_id: str,
                       params: dict | None = None) -> list[dict]:
    import json as _json

    text = client.get(f"/api/deploy/{deployment_id}/events",
                      params=params or {}).text
    out = []
    for chunk in text.split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                out.append(_json.loads(line[len("data: "):]))
    return out


def test_agent_lifecycle_events_real_transitions(client):
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "completed"
    events = _read_sse_payloads(client, final["deployment_id"])
    for agent in ("preflight", "analyzer", "docker", "nginx", "security",
                  "mediator", "verifier", "critic", "executor"):
        starts = [e for e in events
                  if e["type"] == "agent.started" and e["data"].get("agent") == agent]
        dones = [e for e in events
                 if e["type"] == "agent.completed" and e["data"].get("agent") == agent]
        assert starts, f"missing agent.started for {agent}"
        assert dones, f"missing agent.completed for {agent}"
        assert events.index(starts[0]) < events.index(dones[0])
        # Final completion carries the measured agent row, not invented
        # progress. (Verifier/critic legitimately show an earlier failed
        # round before the replan succeeds — real rounds, not noise.)
        state = dones[-1]["data"].get("agent_state") or {}
        assert state.get("id") == agent
        assert state.get("status") == "complete"
        assert isinstance(state.get("durationMs"), (int, float))
    verifier_rounds = [e for e in events
                       if e["type"] == "agent.completed"
                       and e["data"].get("agent") == "verifier"]
    assert any((e["data"].get("agent_state") or {}).get("status") == "failed"
               for e in verifier_rounds)
    assert (verifier_rounds[-1]["data"].get("agent_state") or {}).get("status") == "complete"
    # Stage transitions carry the full backend snapshot the dashboard renders.
    staged = [e for e in events if e["type"] == "stage.completed"]
    assert staged and isinstance(staged[0]["data"].get("agents"), list)
    assert {a["id"] for a in staged[0]["data"]["agents"]} >= {
        "preflight", "analyzer", "docker", "nginx", "security", "mediator",
        "verifier", "critic", "executor", "rollback"}
    assert len([e for e in events if e["type"] in {
        "deployment.completed", "deployment.failed",
        "deployment.cancelled", "proposal.ready"}]) == 1


def test_tracker_snapshot_shape():
    from app.workflow.stages import AGENT_DEFS, StageTracker

    tracker = StageTracker()
    rows = tracker.snapshot()
    assert [r["id"] for r in rows] == [aid for aid, _, _ in AGENT_DEFS]
    for row in rows:
        assert set(row) >= {"id", "name", "status", "activity", "lastEvent",
                            "durationMs", "startedAt", "finishedAt", "deps"}
        assert row["status"] == "idle"
        assert row["durationMs"] is None
    tracker.start("docker", "Working")
    tracker.finish("docker", "complete", activity="Done")
    row = tracker.snapshot_row("docker")
    assert row is not None and row["status"] == "complete"
    assert isinstance(row["durationMs"], float) and row["durationMs"] >= 0.0
    assert tracker.finish("nope", "complete") == 0.0
    assert tracker.snapshot_row("nope") is None
    # Unknown statuses degrade to failed, never leak through.
    tracker.start("nginx", "Working")
    tracker.finish("nginx", "bogus")
    assert tracker.snapshot_row("nginx")["status"] == "failed"
    tracker.start("security", "Working")
    tracker.cancel_remaining()
    assert tracker.snapshot_row("security")["status"] == "cancelled"
    assert tracker.snapshot_row("verifier")["status"] == "skipped"


# --- SSE replay / cursor / saturation -------------------------------------------------

def test_sse_replay_and_cursor(client):
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "completed"
    deployment_id = final["deployment_id"]

    def read_stream(params: dict | None = None) -> list[dict]:
        return _read_sse_payloads(client, deployment_id, params)

    full = read_stream()
    assert full
    assert full[-1]["type"] in {"deployment.completed", "deployment.failed",
                                "deployment.cancelled"}
    ids = [e["event_id"] for e in full]
    assert len(set(ids)) == len(ids)
    mid = ids[len(ids) // 2]
    tail = read_stream({"after": mid})
    assert tail
    assert [e["event_id"] for e in tail] == ids[ids.index(mid) + 1:]
    # Unknown cursor recovers from the head instead of stranding the client.
    head = read_stream({"after": "evt_doesnotexist"})
    assert [e["event_id"] for e in head] == ids


def test_sse_disconnect_does_not_cancel(client):
    import threading

    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    deployment_id = resp.json()["deployment_id"]
    # Disconnect mid-run from a helper thread: open the stream, read one
    # replayed event, then close it. The worker thread is bounded by join
    # timeouts so a stalled stream fails loudly instead of hanging the suite;
    # the deployment itself must still run to completion either way.
    outcome: dict = {}

    def _touch_stream() -> None:
        try:
            with client.stream("GET", f"/api/deploy/{deployment_id}/events") as stream:
                if stream.status_code != 200:
                    outcome["status"] = stream.status_code
                    return
                for line in stream.iter_lines():
                    if isinstance(line, bytes):
                        line = line.decode("utf-8", "replace")
                    if line.startswith("data: "):
                        outcome["first"] = True
                        break
        except Exception as exc:  # noqa: BLE001 - reported via outcome
            outcome["error"] = type(exc).__name__
        finally:
            outcome["done"] = True

    worker = threading.Thread(target=_touch_stream, daemon=True)
    worker.start()
    worker.join(timeout=60.0)
    if not outcome.get("done"):
        # Safety valve: a stalled stream would keep the TestClient portal
        # busy and hang fixture teardown forever. Cancel the run to force
        # the server to close the stream; the assertions below still fail
        # loudly if the stream never delivered its first event.
        client.post(f"/api/deploy/{deployment_id}/cancel")
        worker.join(timeout=15.0)
    assert outcome.get("done"), (
        "SSE stream touch did not finish in 60s; "
        f"outcome={outcome}"
    )
    assert outcome.get("error") is None, f"stream touch failed: {outcome}"
    assert outcome.get("first"), f"stream delivered no event: {outcome}"
    final = _wait_terminal(client, deployment_id)
    assert final["status"] == "completed"


def test_event_bus_saturation_drops_without_blocking():
    import time as _time

    from app.core.events import event_bus, make_event
    from app.core.perf import snapshot_counters

    async def scenario() -> int:
        queue = await event_bus.subscribe("dep_flood")
        try:
            before = snapshot_counters().get("sse.dropped", 0)
            t0 = _time.perf_counter()
            for i in range(300):
                await event_bus.publish(make_event(
                    deployment_id="dep_flood",
                    event_type="system.message",
                    message=f"flood {i}"))
            elapsed = _time.perf_counter() - t0
            after = snapshot_counters().get("sse.dropped", 0)
            assert elapsed < 5.0
            return after - before
        finally:
            await event_bus.unsubscribe("dep_flood", queue)

    dropped = asyncio.run(scenario())
    assert dropped > 0


# --- security: redaction on new paths --------------------------------------------------

def test_secret_redaction_across_replan_and_timeout(client, monkeypatch):
    import app.workflow.planning as planning

    secret = "sk-test-only-secret-9f8e7d6c5b4a"
    real_docker = planning.run_docker_agent

    def slow_docker(profile):
        import time as _time

        _time.sleep(2)
        return real_docker(profile)

    monkeypatch.setattr(planning, "run_docker_agent", slow_docker)
    monkeypatch.setattr(get_settings(), "timeout_specialists_s", 0.1)
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo,
                             intent=f"force verification failure {secret}"),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "failed"
    blob_parts = []
    for ln in _log_lines(client, final["deployment_id"]):
        blob_parts.append(ln["message"])
    blob_parts.append(str(final.get("result") or ""))
    blob_parts.append(str(final.get("error_summary") or ""))
    verification = client.get(
        f"/api/deploy/{final['deployment_id']}/verification").json()
    blob_parts.append(str(verification))
    blob = "\n".join(blob_parts)
    assert secret not in blob


def test_run_control_helpers():
    run_control.clear_run("dep_helper")
    try:
        assert run_control.cancel_requested("dep_helper") is False
        run_control.request_cancel("dep_helper")
        assert run_control.cancel_requested("dep_helper") is True
        run_control.request_cancel("dep_helper")  # idempotent
        assert run_control.cancel_requested("dep_helper") is True
    finally:
        run_control.clear_run("dep_helper")
    assert run_control.cancel_requested("dep_helper") is False
