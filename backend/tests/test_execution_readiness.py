"""Execution configuration + readiness preflight (centralized, deterministic).

Covers: explicit mode parsing (invalid values rejected at Settings), the
structured readiness contract for every supported configuration, its
exposure via /api/config/status, and the guarantee that a blocked execution
stage preserves upstream analysis/verification results.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.execution.readiness import (
    EXECUTION_DISABLED,
    EXECUTION_DISABLED_HOSTED,
    EXECUTION_NOT_CONFIGURED,
    EXECUTOR_SIMULATOR_EXPLICIT,
    REAL_BUILDER_UNAVAILABLE,
    REAL_EXECUTION_NOT_ENABLED,
    REAL_EXECUTOR_READY,
    assess_execution_readiness,
)
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


# --- configuration parsing ----------------------------------------------------

def test_invalid_executor_mode_rejected_at_settings():
    with pytest.raises(ValidationError, match="MEDHA_EXECUTOR_MODE"):
        Settings(MEDHA_EXECUTOR_MODE="turbo")


def test_executor_mode_normalized_deterministically():
    settings = Settings(MEDHA_EXECUTOR_MODE="  Simulator ")
    assert settings.executor_mode == "simulator"
    empty = Settings(MEDHA_EXECUTOR_MODE="")
    assert empty.executor_mode == "auto"


# --- readiness contract -------------------------------------------------------

def _settings(**overrides) -> Settings:
    base = {"MEDHA_EXECUTOR_MODE": "auto", "MEDHA_DOCKER_EXECUTE": "false",
            "MEDHA_ENV": "development", "MEDHA_DATABASE_URL": ""}
    base.update(overrides)
    return Settings(_env_file=None, **base)


def test_readiness_auto_fails_closed_with_stable_code():
    result = assess_execution_readiness(_settings(MEDHA_EXECUTOR_MODE="auto"))
    assert result["status"] == "blocked"
    assert result["reason_code"] == EXECUTION_NOT_CONFIGURED
    assert result["requires_operator"] is True
    assert result["restart_required"] is True
    assert "MEDHA_EXECUTOR_MODE=simulator" in result["message"]
    assert result["next_actions"]


def test_readiness_simulator_is_explicit_and_labelled():
    result = assess_execution_readiness(_settings(MEDHA_EXECUTOR_MODE="simulator"))
    assert result["status"] == "ready"
    assert result["reason_code"] == EXECUTOR_SIMULATOR_EXPLICIT
    assert result["simulated"] is True
    assert "test-only" in result["message"]


def test_readiness_disabled_is_not_ready():
    result = assess_execution_readiness(_settings(MEDHA_EXECUTOR_MODE="disabled"))
    assert result["status"] == "disabled"
    assert result["reason_code"] == EXECUTION_DISABLED
    assert result["simulated"] is False


def test_readiness_real_requires_docker_execute_flag():
    result = assess_execution_readiness(
        _settings(MEDHA_EXECUTOR_MODE="real", MEDHA_DOCKER_EXECUTE="false")
    )
    assert result["status"] == "blocked"
    assert result["reason_code"] == REAL_EXECUTION_NOT_ENABLED
    assert result["restart_required"] is True


def test_readiness_real_builder_unavailable_without_docker():
    result = assess_execution_readiness(
        _settings(MEDHA_EXECUTOR_MODE="real", MEDHA_DOCKER_EXECUTE="true"),
        docker_cli=False,
        docker_daemon=False,
    )
    assert result["status"] == "blocked"
    assert result["reason_code"] == REAL_BUILDER_UNAVAILABLE
    # Starting Docker does not require an app restart.
    assert result["restart_required"] is False


def test_readiness_real_ready_with_isolated_builder():
    result = assess_execution_readiness(
        _settings(MEDHA_EXECUTOR_MODE="real", MEDHA_DOCKER_EXECUTE="true"),
        docker_cli=True,
        docker_daemon=True,
    )
    assert result["status"] == "ready"
    assert result["reason_code"] == REAL_EXECUTOR_READY
    assert result["simulated"] is False


def test_readiness_production_never_executes():
    result = assess_execution_readiness(
        _settings(MEDHA_ENV="production", MEDHA_EXECUTOR_MODE="simulator")
    )
    assert result["status"] == "disabled"
    assert result["reason_code"] == EXECUTION_DISABLED_HOSTED


def test_readiness_message_never_leaks_env_values():
    result = assess_execution_readiness(_settings(MEDHA_EXECUTOR_MODE="auto"))
    blob = str(result)
    for secret in ("postgresql://", "gsk_", "AQ.", "BEGIN PRIVATE KEY"):
        assert secret not in blob


# --- API exposure -------------------------------------------------------------

def test_config_status_exposes_structured_readiness(client):
    body = client.get("/api/config/status").json()
    readiness = body.get("execution_readiness")
    assert isinstance(readiness, dict)
    assert readiness["status"] in {"ready", "blocked", "disabled"}
    assert readiness["reason_code"]
    assert readiness["message"]
    assert isinstance(readiness["next_actions"], list)
    # Legacy fields stay intact for existing consumers.
    assert body["execution"] in {"unconfigured", "simulator-explicit", "real-ready"}


# --- blocked execution preserves upstream results -----------------------------

def test_blocked_execution_preserves_verification_results(client, monkeypatch):
    """Executor unconfigured: run fails closed at execute, verification stays."""
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
        result = final["result"]
        assert result["code"] == EXECUTION_NOT_CONFIGURED
        assert result["blocked"] is True
        assert result["blocked_stage"] == "execute"
        assert result["readiness"]["reason_code"] == EXECUTION_NOT_CONFIGURED
        assert result["verification_preserved"] is True
        # Verification artifact remains readable and successful.
        verification = client.get(
            f"/api/deploy/{final['deployment_id']}/verification"
        ).json()
        assert verification["verification"]["passed"] is True
        assert len(verification["verification"]["checks"]) > 0
        # The run summary carries a structured error code for the UI.
        summary = client.get("/api/deploys", params={"status": "failed"}).json()
        run = next(r for r in summary["runs"] if r["deployment_id"] == final["deployment_id"])
        assert run["error_code"] == EXECUTION_NOT_CONFIGURED
    finally:
        get_settings.cache_clear()
