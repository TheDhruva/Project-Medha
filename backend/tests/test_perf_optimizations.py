"""Performance-optimization regression tests (offline, deterministic)."""
from __future__ import annotations

import asyncio

from app.ai.cache import cache_key
from app.ai.service import AIBudget, AIService, PROMPT_VERSION
from app.ai.redact import redact_mapping
from app.core.config import get_settings
from app.core.enums import TERMINAL_EVENT_TYPES, DeploymentStatus, EventType
from app.core.events import make_event
from app.database.repositories import DeploymentRepository
from app.models.deployment import DeploymentRecord


def _record(deployment_id: str = "dep_perf1") -> DeploymentRecord:
    from app.core.enums import DeployMode

    return DeploymentRecord(
        deployment_id=deployment_id,
        repository_url="https://github.com/example/app",
        mode=DeployMode.DEMO,
        scenario=None,
        target_host="localhost",
        target_port=8080,
        intent=None,
        status=DeploymentStatus.STARTED,
        current_stage=None,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        is_demo=True,
    )


def test_cancelled_is_terminal_event():
    assert EventType.DEPLOYMENT_CANCELLED.value == "deployment.cancelled"
    assert EventType.DEPLOYMENT_CANCELLED.value in TERMINAL_EVENT_TYPES


def test_save_artifacts_updates_only_provided_columns(client):
    repo = DeploymentRepository()
    repo.create(_record("dep_partial"))
    out = repo.save_artifacts(
        "dep_partial", constraints=[{"id": "c1"}], updated_at="2026-01-01T00:00:01Z"
    )
    assert out is not None
    assert out.constraints == [{"id": "c1"}]
    assert out.result is None
    assert out.verification is None
    # Second targeted write preserves the first.
    out2 = repo.save_artifacts(
        "dep_partial", result={"kind": "ok"}, updated_at="2026-01-01T00:00:02Z"
    )
    assert out2 is not None
    assert out2.constraints == [{"id": "c1"}]
    assert out2.result == {"kind": "ok"}
    # Missing deployment stays None (no silent create).
    assert (
        repo.save_artifacts("dep_missing", result={}, updated_at="2026-01-01T00:00:03Z")
        is None
    )


def test_list_events_after_cursor_returns_only_newer(client):
    repo = DeploymentRepository()
    repo.create(_record("dep_cursor"))
    ids: list[str] = []
    for i in range(5):
        event = make_event(
            deployment_id="dep_cursor",
            event_type=EventType.STAGE_STARTED,
            message=f"step {i}",
        )
        repo.add_event(event)
        ids.append(event.event_id)
    all_events = repo.list_events("dep_cursor", limit=100)
    assert len(all_events) == 5
    newer = repo.list_events("dep_cursor", limit=100, after_event_id=ids[1])
    assert [e.event_id for e in newer] == ids[2:]
    bounded = repo.list_events("dep_cursor", limit=2)
    assert len(bounded) == 2
    # Unknown cursor degrades to full window, never empty-on-valid-data.
    unknown = repo.list_events("dep_cursor", limit=100, after_event_id="evt_missing")
    assert len(unknown) == 5


def test_cancel_emits_terminal_event_and_stream_would_close(client):
    # Seed a still-running deployment directly: the demo runner finishes in
    # milliseconds with STEP_DELAY=0, so POST /api/deploy would already be
    # terminal (cancel returns duplicate without emitting).
    repo = DeploymentRepository()
    repo.create(_record("dep_cancel_me"))
    cancelled = client.post("/api/deploy/dep_cancel_me/cancel")
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    events = repo.list_events("dep_cancel_me", limit=100)
    types = [e.event_type for e in events]
    assert EventType.DEPLOYMENT_CANCELLED.value in types
    assert EventType.DEPLOYMENT_CANCELLED.value in TERMINAL_EVENT_TYPES


def test_health_cached_and_responsive(client):
    first = client.get("/health")
    assert first.status_code == 200
    assert first.json()["database"] == "ok"
    assert "X-Request-ID" in first.headers
    second = client.get("/health")
    assert second.status_code == 200
    assert second.json()["database"] == "ok"


def test_request_id_header_on_api(client):
    response = client.get("/api/demo/scenarios")
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID", "").startswith("req_")


def test_sse_replay_limit_param(client):
    repo = DeploymentRepository()
    repo.create(_record("dep_replay"))
    for i in range(4):
        repo.add_event(
            make_event(
                deployment_id="dep_replay",
                event_type=EventType.STAGE_STARTED,
                message=f"step {i}",
            )
        )
    # Terminal event last so the replay generator returns instead of
    # holding the stream open (non-terminal replays subscribe for live).
    terminal = make_event(
        deployment_id="dep_replay",
        event_type=EventType.DEPLOYMENT_FAILED,
        message="done",
        status=DeploymentStatus.FAILED.value,
        level="error",
    )
    repo.add_event(terminal)
    # Repository-level bound (what the endpoint replays through).
    assert len(repo.list_events("dep_replay", limit=2)) == 2
    full = client.get("/api/deploy/dep_replay/events?limit=100")
    assert full.status_code == 200
    assert full.text.count("data: ") == 5
    # Cursor resumes after the 4th event: only the terminal replays.
    resumed = client.get(
        f"/api/deploy/dep_replay/events?limit=100&after={repo.list_events('dep_replay', limit=100)[3].event_id}"
    )
    assert resumed.status_code == 200
    assert resumed.text.count("data: ") == 1
    assert terminal.event_id in resumed.text


def test_ai_cache_hit_does_not_consume_budget():
    settings = get_settings()
    settings.ai_enabled = True
    settings.groq_api_key = "test-key"
    settings.groq_model = "test-model"
    settings.ai_primary_provider = "groq"
    settings.ai_fallback_provider = "none"
    service = AIService(settings)
    payload = {"change": {"files": []}}
    safe = redact_mapping(payload)
    key = cache_key(
        prompt_version=PROMPT_VERSION,
        kind="change_summary",
        provider="groq",
        model="test-model",
        owner_ctx="local",
        payload=safe,
    )
    from app.ai.schemas import SCHEMA_BY_KIND

    cls = SCHEMA_BY_KIND["change_summary"]
    valid = None
    # Build a minimal valid instance from the schema (defaults where possible).
    try:
        valid = cls.model_validate({"summary": "cached summary"}).model_dump()
    except Exception:
        valid = {"summary": "cached summary"}
    service.cache.set(key, {"__kind": "change_summary", "data": valid,
                             "meta": {"enabled": True, "outcome": "ai_assisted",
                                      "provider": "groq", "model": "test-model",
                                      "fallback_used": False, "duration_s": 0.01,
                                      "failure_category": None, "schema_valid": True,
                                      "cached": False}})
    budget = AIBudget(max_calls=0)  # exhausted: cache hit must still succeed
    data, meta = asyncio.run(
        service.generate_structured(
            kind="change_summary", payload=payload, system="sys",
            owner_ctx="local", budget=budget,
        )
    )
    assert data is not None
    assert meta.cached is True
    assert budget.calls_made == 0
