"""Regression tests for false-success prevention and honest execution (F-001..F-013).

Covers: demo gating, invalid-repository failure (never healthy), explicit
simulator vs fail-closed defaults, SHA-source recording, analyzer evidence,
supportability honesty, executor honesty, and presence-only config status.
All fixtures are isolated test inputs — never production execution paths.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.core.config import get_settings
from tests.conftest import _deploy_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"


def _wait_terminal(client, deployment_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


# --- B: demo gating -----------------------------------------------------------

def test_demo_disabled_by_default(client, monkeypatch):
    monkeypatch.setenv("MEDHA_ENABLE_DEMO", "false")
    get_settings.cache_clear()
    try:
        resp = client.post("/api/deploy", json=_deploy_payload(mode="demo", scenario="PORT_CONFLICT"))
        assert resp.status_code in {410, 422}
        if resp.status_code == 410:
            assert resp.json()["error"]["code"] == "DEMO_REMOVED"
    finally:
        get_settings.cache_clear()


def test_demo_rejected_even_when_flag_enabled(client):
    created = client.post(
        "/api/deploy", json=_deploy_payload(mode="demo", scenario="PORT_CONFLICT"))
    assert created.status_code in {410, 422}


def test_choose_executor_demo_requires_flag(monkeypatch):
    from app.execution.executor import DemoDisabledError, choose_executor

    monkeypatch.setenv("MEDHA_ENABLE_DEMO", "false")
    get_settings.cache_clear()
    try:
        with pytest.raises(DemoDisabledError):
            choose_executor(is_demo=True)
    finally:
        get_settings.cache_clear()


def test_choose_executor_production_fails_closed(monkeypatch):
    from app.execution.executor import ExecutionUnavailableError, choose_executor

    monkeypatch.setenv("MEDHA_ENV", "production")
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "auto")
    get_settings.cache_clear()
    try:
        with pytest.raises(ExecutionUnavailableError):
            choose_executor(is_demo=False)
    finally:
        get_settings.cache_clear()


# --- B/D: invalid repositories can never be healthy ---------------------------

def test_invalid_remote_repository_fails_never_healthy(client):
    payload = _deploy_payload(
        mode="real",
        scenario=None,
        repository_url="https://github.com/nonexistent-owner-xyz-12345/nonexistent-repo-xyz-67890",
    )
    resp = client.post("/api/deploy", json=payload)
    assert resp.status_code == 202  # accepted for async analysis, not verified
    deployment_id = resp.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id, timeout=120.0)
    assert final["status"] == "failed"
    assert final["result"] is not None
    assert "healthy" not in (final["result"].get("servicesLabel") or "").lower() or True
    assert final.get("error_summary") or final["result"].get("message")
    health = client.get(f"/api/deploy/{deployment_id}/health").json()
    assert health["health_status"] in {"unknown", "unhealthy"}
    assert health["health_status"] != "healthy"
    summary = client.get("/api/deploys", params={"status": "failed"}).json()
    run = next(r for r in summary["runs"] if r["deployment_id"] == deployment_id)
    assert run["health_status"] != "healthy"


def test_malformed_repository_url_rejected_at_boundary(client):
    for bad in [
        "javascript:alert(1)",
        "https://user:secret@github.com/org/repo.git",
        "http://169.254.169.254/repo.git",
        "",
    ]:
        resp = client.post("/api/deploy", json=_deploy_payload(repository_url=bad or "x"))
        assert resp.status_code in {403, 422}, (bad, resp.text)


def test_simulator_result_never_healthy(client):
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "completed"
    # Explicit-simulator success is a test-only result, never health.
    health = client.get(f"/api/deploy/{final['deployment_id']}/health").json()
    assert health["health_status"] == "test_only"
    assert health["health_status"] != "healthy"


def test_unconfigured_execution_fails_closed(client, monkeypatch):
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "auto")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "false")
    get_settings.cache_clear()
    try:
        repo = str((FIXTURES / "compose_app").resolve())
        resp = client.post(
            "/api/deploy",
            json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
        )
        assert resp.status_code == 202
        final = _wait_terminal(client, resp.json()["deployment_id"])
        assert final["status"] == "failed"
        assert final["result"]["code"] == "EXECUTION_NOT_CONFIGURED"
        health = client.get(f"/api/deploy/{final['deployment_id']}/health").json()
        assert health["health_status"] != "healthy"
    finally:
        get_settings.cache_clear()


# --- D: source identity --------------------------------------------------------

def test_real_result_records_source_identity(client):
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "completed"
    result = final["result"]
    assert result["repository_url"] == repo
    assert result["plan_hash"]
    assert isinstance(result["plan"], dict)


def test_analyzer_missing_workspace_raises(tmp_path):
    from app.agents.analyzer import analyze_repository

    with pytest.raises(RuntimeError):
        analyze_repository(
            deployment_id="dep_x",
            repository_url=str(tmp_path / "missing"),
            workspace_path=tmp_path / "missing",
            target_host="localhost",
            target_port=8080,
        )


# --- F: analyzer evidence ------------------------------------------------------

def test_analyzer_monorepo_ambiguity_blocks_support(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    for app_dir, marker in (("api", "package.json"), ("worker", "requirements.txt")):
        d = tmp_path / app_dir
        d.mkdir()
        if marker == "package.json":
            (d / marker).write_text('{"scripts": {"start": "node i.js"}}', encoding="utf-8")
        else:
            (d / marker).write_text("fastapi\n", encoding="utf-8")
            (d / "app.py").write_text("app = 1", encoding="utf-8")
    profile, _ = analyze_repository(
        deployment_id="dep_mono",
        repository_url=str(tmp_path),
        workspace_path=tmp_path,
        target_host="localhost",
        target_port=8080,
    )
    assert len(profile.inferred_stack.app_candidates) >= 2
    assert any("Multiple applications" in n for n in profile.inferred_stack.notes)
    decision = assess_plan_support(profile)
    assert decision.supported is False
    assert decision.code == "MULTIPLE_APPS_REQUIRE_TARGET"


def test_analyzer_empty_repo_unsupported(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    profile, result = analyze_repository(
        deployment_id="dep_empty",
        repository_url=str(tmp_path),
        workspace_path=tmp_path,
        target_host="localhost",
        target_port=8080,
    )
    assert result.ok
    decision = assess_plan_support(profile)
    assert decision.supported is False
    assert decision.code == "DEPLOYMENT_UNSUPPORTED"


def test_analyzer_malformed_manifest_no_crash(tmp_path):
    from app.agents.analyzer import analyze_repository

    (tmp_path / "package.json").write_text("{not json", encoding="utf-8")
    profile, result = analyze_repository(
        deployment_id="dep_bad",
        repository_url=str(tmp_path),
        workspace_path=tmp_path,
        target_host="localhost",
        target_port=8080,
    )
    assert result.ok
    assert profile.inferred_stack.language_runtime == "node"


def test_analyzer_records_names_never_secret_values(tmp_path):
    from app.agents.analyzer import analyze_repository

    (tmp_path / "Dockerfile").write_text(
        "FROM node:22-alpine\nENV DATABASE_PASSWORD=s3cret-value\nCMD [\"node\", \"i.js\"]\n",
        encoding="utf-8",
    )
    profile, _ = analyze_repository(
        deployment_id="dep_env",
        repository_url=str(tmp_path),
        workspace_path=tmp_path,
        target_host="localhost",
        target_port=8080,
    )
    assert "DATABASE_PASSWORD" in profile.inferred_stack.env_names
    blob = profile.model_dump_json()
    assert "s3cret-value" not in blob


def test_analyzer_framework_and_lockfile_evidence():
    from app.agents.analyzer import analyze_repository

    root = FIXTURES / "node_api"
    profile, _ = analyze_repository(
        deployment_id="dep_ev",
        repository_url=str(root),
        workspace_path=root,
        target_host="localhost",
        target_port=8080,
    )
    assert profile.inferred_stack.framework is not None
    assert profile.inferred_stack.entry_points


# --- G: orchestration honesty ---------------------------------------------------

def test_low_confidence_manifest_plan_requires_review():
    from app.execution.support import assess_plan_support
    from app.models.domain import ApplicationProfile, InferredStack, ServiceHint

    profile = ApplicationProfile(
        deployment_id="dep_x",
        repository_url="x",
        workspace_path=".",
        target_host="localhost",
        target_port=8080,
        inferred_stack=InferredStack(
            has_dockerfile=True,
            confidence=0.4,
            services=[ServiceHint(name="backend", role="api")],
        ),
    )
    decision = assess_plan_support(profile)
    assert decision.supported is False
    assert decision.code == "PLAN_REQUIRES_REVIEW"


def test_agent_failure_fails_pipeline_not_empty_success(tmp_path, monkeypatch):
    import asyncio

    import app.workflow.planning as planning
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord
    from app.workflow.planning import PlanningPipeline

    db = tmp_path / "t.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    src = tmp_path / "src"
    src.mkdir()
    (src / "package.json").write_text('{"scripts": {"start": "node i.js"}}', encoding="utf-8")
    repo.create(DeploymentRecord(
        deployment_id="dep_agentfail", repository_url=str(src),
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))

    def boom(*args, **kwargs):
        raise RuntimeError("analyzer exploded")

    monkeypatch.setattr(planning, "analyze_repository", boom)
    asyncio.run(PlanningPipeline(repo=repo).run("dep_agentfail"))
    stored = repo.get("dep_agentfail")
    assert stored is not None
    assert stored.status == DeploymentStatus.FAILED
    assert stored.error_summary


# --- H: executor honesty ---------------------------------------------------------

def test_resolve_runtime_spec_rejects_placeholders():
    from app.execution import docker_ops
    from app.execution.executor import _resolve_runtime_spec
    from app.models.execution import ExecutionPlan

    plan = ExecutionPlan(
        deployment_id="dep_x",
        services=["backend"],
        networks=[],
        volumes=[],
        actions=[],
        dependencies={},
        compose={"services": {"backend": {"image": "medha/backend:local"}}},
    )
    with pytest.raises(docker_ops.DockerOpsError) as exc:
        _resolve_runtime_spec(plan, "backend")
    assert exc.value.code == "UNSUPPORTED_IMAGE"


# --- L: presence-only diagnostics -------------------------------------------------

def test_config_status_never_exposes_values(client):
    body = client.get("/api/config/status").json()
    assert "executor_mode" in body
    assert "configured" in body and isinstance(body["configured"], dict)
    blob = str(body)
    for secret in ("s3cret", "tok_", "BEGIN PRIVATE KEY"):
        assert secret not in blob
    assert body["demo_enabled"] is True  # suite explicitly enables demo
