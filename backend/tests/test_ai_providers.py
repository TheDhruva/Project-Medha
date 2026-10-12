"""AI provider tests — all HTTP is mocked; no keys or network required."""

from __future__ import annotations

import json

import httpx
import pytest

from app.ai import assist
from app.ai.cache import AICache, cache_key
from app.ai.redact import redact_mapping, redact_text
from app.ai.schemas import SCHEMA_BY_KIND
from app.ai.service import AIBudget, AIService, DEGRADED, RULE_BASED, UNAVAILABLE


def _settings(**overrides):
    from app.core.config import Settings

    base = {
        "MEDHA_AI_ENABLED": True,
        "MEDHA_AI_PRIMARY_PROVIDER": "groq",
        "MEDHA_AI_FALLBACK_PROVIDER": "gemini",
        "GROQ_API_KEY": "gsk_test_primary",
        "GROQ_MODEL": "openai/gpt-oss-20b",
        "GEMINI_API_KEY": "test-fallback-key",
        "GEMINI_MODEL": "gemini-3.8-flash",
        "MEDHA_AI_REQUEST_TIMEOUT_SECONDS": 5.0,
        "MEDHA_AI_MAX_RETRIES": 1,
        "MEDHA_AI_MAX_OUTPUT_TOKENS": 200,
        "MEDHA_AI_MAX_CALLS_PER_RUN": 5,
    }
    base.update(overrides)
    return Settings(**base)


def _groq_ok(payload: dict) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def _gemini_ok(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
    )


def _client(handler, calls: list) -> httpx.AsyncClient:
    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(wrapped))


VALID_SUMMARY = {"summary": "Three files changed.", "changed_areas": ["api"],
                 "risk_level": "low", "notable_risks": []}


async def _generate(service, kind="change_summary", payload=None):
    return await service.generate_structured(
        kind=kind, payload=payload or {"change": "x"}, system="sys", owner_ctx="local"
    )


async def test_ai_disabled_makes_no_requests():
    calls: list = []
    service = AIService(_settings(MEDHA_AI_ENABLED=False), client=_client(lambda r: _groq_ok(VALID_SUMMARY), calls))
    data, meta = await _generate(service)
    assert data is None and meta.outcome == RULE_BASED and calls == []


async def test_missing_credentials_no_requests():
    calls: list = []
    service = AIService(
        _settings(GROQ_API_KEY="", GEMINI_API_KEY=""),
        client=_client(lambda r: _groq_ok(VALID_SUMMARY), calls),
    )
    data, meta = await _generate(service)
    assert data is None and meta.outcome == RULE_BASED and calls == []


async def test_groq_success():
    calls: list = []
    service = AIService(_settings(), client=_client(lambda r: _groq_ok(VALID_SUMMARY), calls))
    data, meta = await _generate(service)
    assert data is not None and data["risk_level"] == "low"
    assert meta.outcome == "ai_assisted" and meta.provider == "groq"
    assert meta.model == "openai/gpt-oss-20b" and meta.schema_valid and not meta.fallback_used
    assert len(calls) == 1
    body = json.loads(calls[0].content.decode())
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 200


async def test_gemini_success_as_primary():
    calls: list = []
    service = AIService(
        _settings(MEDHA_AI_PRIMARY_PROVIDER="gemini", MEDHA_AI_FALLBACK_PROVIDER="none"),
        client=_client(lambda r: _gemini_ok(VALID_SUMMARY), calls),
    )
    data, meta = await _generate(service)
    assert data is not None and meta.provider == "gemini" and meta.outcome == "ai_assisted"


async def test_primary_timeout_falls_back_to_gemini():
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "groq" in str(request.url):
            raise httpx.ConnectTimeout("boom")
        return _gemini_ok(VALID_SUMMARY)

    service = AIService(
        _settings(MEDHA_AI_MAX_RETRIES=0), client=_client(handler, [])
    )
    # rebuild client to share call list: handler already appends; drop outer list
    data, meta = await _generate(service)
    assert data is not None and meta.outcome == DEGRADED and meta.fallback_used
    assert meta.provider == "gemini"
    assert sum("groq" in str(c.url) for c in calls) == 1


async def test_rate_limit_retries_then_falls_back():
    calls: list = []
    groq_calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if "groq" in str(request.url):
            groq_calls["n"] += 1
            return httpx.Response(429, headers={"retry-after": "0"})
        return _gemini_ok(VALID_SUMMARY)

    service = AIService(_settings(), client=_client(handler, []))
    data, meta = await _generate(service)
    assert data is not None and meta.provider == "gemini" and meta.outcome == DEGRADED
    # 1 initial + 1 bounded retry on Groq, then fallback
    assert groq_calls["n"] == 2


async def test_auth_failure_no_retry_no_fallback_pointless():
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    service = AIService(_settings(), client=_client(handler, []))
    data, meta = await _generate(service)
    assert data is None and meta.outcome == UNAVAILABLE
    assert meta.failure_category == "auth"
    assert len(calls) == 1  # terminal: no retry, no fallback


async def test_both_providers_unavailable():
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"error": "down"})

    service = AIService(
        _settings(MEDHA_AI_MAX_RETRIES=0), client=_client(handler, [])
    )
    data, meta = await _generate(service)
    assert data is None and meta.outcome == UNAVAILABLE
    assert meta.failure_category == "server"
    assert meta.fallback_used  # fallback was attempted


async def test_invalid_json_and_schema_invalid():
    calls: list = []
    bad = [httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}),
           httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"summary": 123}'}]} }]})]
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        resp = bad[min(state["n"], 1)]
        state["n"] += 1
        return resp

    service = AIService(_settings(MEDHA_AI_MAX_RETRIES=0), client=_client(handler, []))
    data, meta = await _generate(service)
    assert data is None and meta.outcome == UNAVAILABLE
    assert meta.failure_category == "schema_invalid"


async def test_retry_bounds_respected():
    calls: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(503, json={"error": "x"})

    service = AIService(
        _settings(MEDHA_AI_FALLBACK_PROVIDER="none", MEDHA_AI_MAX_RETRIES=3),
        client=_client(handler, []),
    )
    data, meta = await _generate(service)
    assert data is None and len(calls) == 4  # 1 + 3 retries, then stop


async def test_concurrency_limit_configured():
    service = AIService(_settings())
    assert service._semaphore._value == 2


async def test_secret_redaction():
    dirty = "key=gsk_abc123SECRET and https://user:P@ssw0rd@host/db and Bearer abc.def.ghi"
    clean = redact_text(dirty)
    assert "gsk_abc123SECRET" not in clean and "P@ssw0rd" not in clean
    assert "abc.def.ghi" not in clean and "[redacted]" in clean
    mapped = redact_mapping({"GROQ_API_KEY": "gsk_real", "nested": {"note": "sk-live-12345678 here"}})
    assert mapped["GROQ_API_KEY"] == "[redacted]"
    assert "sk-live-12345678" not in mapped["nested"]["note"]


async def test_cache_hit_and_owner_isolation():
    calls: list = []
    cache = AICache()
    service = AIService(_settings(), cache=cache, client=_client(lambda r: _groq_ok(VALID_SUMMARY), calls))
    first, meta1 = await service.generate_structured(
        kind="change_summary", payload={"change": "x"}, system="sys", owner_ctx="alice")
    second, meta2 = await service.generate_structured(
        kind="change_summary", payload={"change": "x"}, system="sys", owner_ctx="alice")
    assert first == second and meta2.cached and len(calls) == 1
    third, meta3 = await service.generate_structured(
        kind="change_summary", payload={"change": "x"}, system="sys", owner_ctx="bob")
    assert not meta3.cached and len(calls) == 2  # no cross-user leak


async def test_budget_exhaustion_stays_deterministic():
    calls: list = []
    service = AIService(_settings(), client=_client(lambda r: _groq_ok(VALID_SUMMARY), calls))
    budget = AIBudget(max_calls=1)
    first, _ = await service.generate_structured(kind="change_summary", payload={}, system="s", budget=budget)
    assert first is not None and len(calls) == 1
    # Same prompt is cache-served without consuming the exhausted budget:
    # deterministic, no extra provider call. A *different* prompt with an
    # exhausted budget still falls back to rule_based.
    data, meta = await service.generate_structured(kind="change_summary", payload={}, system="s", budget=budget)
    assert data == first and meta.cached is True and len(calls) == 1
    other, other_meta = await service.generate_structured(
        kind="change_summary", payload={"different": True}, system="s", budget=budget)
    assert other is None and other_meta.failure_category == "budget_exhausted" and len(calls) == 1


async def test_assist_helpers_use_budget_and_stay_deterministic_when_disabled():
    service = AIService(_settings(MEDHA_AI_ENABLED=False))
    budget = AIBudget(max_calls=3)
    for helper, args in [
        (assist.assist_change_summary, ({"changed_files": ["a.py"]},)),
        (assist.assist_repo_interpretation, ({"inferred_stack": {}},)),
        (assist.assist_plan_suggestion, ([], {})),
        (assist.assist_agent_explanation, ({"finding": "x"},)),
        (assist.assist_critic, ({}, {})),
        (assist.assist_review_brief, ({"x": 1},)),
    ]:
        data, meta = await helper(service, *args, budget=budget)
        assert data is None and meta.outcome == RULE_BASED
    assert budget.calls_made == 0  # disabled path consumes no budget
    assert set(assist.available_kinds()) == set(SCHEMA_BY_KIND.keys())


async def test_health_check_no_keys_reports_not_configured():
    service = AIService(_settings(GROQ_API_KEY="", GEMINI_API_KEY=""))
    status = await service.health_check()
    assert status["enabled"] is True
    assert status["providers"]["groq"]["failure_category"] == "not_configured"


async def test_output_limit_floor():
    calls: list = []
    service = AIService(
        _settings(MEDHA_AI_MAX_OUTPUT_TOKENS=10),
        client=_client(lambda r: _groq_ok(VALID_SUMMARY), calls),
    )
    await _generate(service)
    body = json.loads(calls[0].content.decode())
    assert body["max_completion_tokens"] >= 128


def test_real_run_without_keys_stays_rule_based(client, monkeypatch):
    import time as _time

    from tests.conftest import _deploy_payload
    from tests.test_planning_api import FIXTURE_REPO

    monkeypatch.setenv("MEDHA_AI_ENABLED", "true")
    monkeypatch.setenv("GROQ_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.core.config import get_settings as _gs

    _gs.cache_clear()
    try:
        response = client.post(
            "/api/deploy",
            json=_deploy_payload(
                mode="real", scenario=None, repository_url=FIXTURE_REPO,
                intent="Deploy the application securely",
            ),
        )
        assert response.status_code == 202
        deployment_id = response.json()["deployment_id"]
        deadline = _time.time() + 45.0
        body: dict = {}
        while _time.time() < deadline:
            body = client.get(f"/api/deploy/{deployment_id}").json()
            if body["status"] in {"completed", "failed", "partial_recovery"}:
                break
            _time.sleep(0.05)
        assert body["status"] == "completed"
        ai = body.get("ai") or {}
        # Notes recorded for every assist stage, all deterministic.
        assert ai.get("outcome") == "rule_based"
        assert ai.get("provider") is None
    finally:
        _gs.cache_clear()


def test_real_run_with_stubbed_provider_records_ai_assisted(client, monkeypatch):
    import time as _time

    from app.ai.providers import GroqProvider, ProviderResult
    from tests.conftest import _deploy_payload
    from tests.test_planning_api import FIXTURE_REPO

    async def fake_review(self, *, system, user, max_tokens, timeout_s):
        payloads = {
            "change_summary": {
                "summary": "Stubbed summary.", "changed_areas": [],
                "risk_level": "low", "notable_risks": [],
            },
            "repo_interpretation": {
                "runtime": "node", "deploy_shape": "compose",
                "implications": [], "missing_evidence": [],
            },
            "plan_suggestion": {"actions": [], "open_questions": []},
            "agent_explanation": {"finding": "stub", "why": "stub", "tradeoffs": []},
            "critic_assist": {"omissions": [], "contradictions": [], "confidence": "high"},
            "review_brief": {"risk_explanation": "stub", "assumptions": [], "next_steps": []},
        }
        if '"support"' in user or '"decisions"' in user:
            kind = "plan_suggestion"
        elif '"agent"' in user:
            kind = "agent_explanation"
        elif '"negotiation"' in user:
            kind = "review_brief"
        elif '"critic"' in user:
            kind = "critic_assist"
        elif '"profile"' in user:
            kind = "repo_interpretation"
        else:
            kind = "change_summary"
        return ProviderResult(ok=True, text=json.dumps(payloads[kind]),
                              model=self.model, duration_s=0.01)

    monkeypatch.setattr(GroqProvider, "complete_json", fake_review)
    monkeypatch.setenv("MEDHA_AI_ENABLED", "true")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    from app.core.config import get_settings as _gs

    _gs.cache_clear()
    try:
        response = client.post(
            "/api/deploy",
            json=_deploy_payload(
                mode="real", scenario=None, repository_url=FIXTURE_REPO,
                intent="Deploy the application securely",
            ),
        )
        assert response.status_code == 202
        deployment_id = response.json()["deployment_id"]
        deadline = _time.time() + 45.0
        body: dict = {}
        while _time.time() < deadline:
            body = client.get(f"/api/deploy/{deployment_id}").json()
            if body["status"] in {"completed", "failed", "partial_recovery"}:
                break
            _time.sleep(0.05)
        assert body["status"] == "completed"
        ai = body.get("ai") or {}
        assert ai.get("outcome") == "ai_assisted"
        assert ai.get("provider") == "groq"
        assert set(ai.get("notes", {}).keys()) >= {"change_summary", "repo_interpretation", "review_brief"}
        for note in ai["notes"].values():
            assert note["meta"]["schema_valid"] is True
    finally:
        _gs.cache_clear()
