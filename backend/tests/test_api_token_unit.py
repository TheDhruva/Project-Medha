"""Mutation-token guard + production simulator pin (single-service hosting).

Covers backend/app/core/api_token.py (401 on bad token, 503 fail-closed in
production without a token, permissive local default) and the production
simulator pin in choose_executor.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.deploy_lock import release_real_deploy
from app.database.connection import init_db
from app.execution.executor import DockerExecutor, SimulatorExecutor, choose_executor
from app.main import create_app


@pytest.fixture()
def authed_client(tmp_path, monkeypatch):
    """Isolated app; caller sets MEDHA_API_TOKEN / MEDHA_ENV via monkeypatch."""

    def _make(**env: str) -> TestClient:
        db_path = tmp_path / "test_token.db"
        monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db_path))
        monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
        monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        get_settings.cache_clear()
        release_real_deploy()
        init_db(db_path)
        return TestClient(create_app())

    yield _make
    release_real_deploy()
    get_settings.cache_clear()


def _demo_payload(**overrides):
    payload = {
        "repository_url": "https://github.com/example/app",
        "mode": "demo",
        "scenario": "PORT_CONFLICT",
        "target": {"host": "localhost", "port": 8080},
    }
    payload.update(overrides)
    return payload


def test_local_default_allows_mutations_without_token(authed_client):
    with authed_client() as client:
        resp = client.post("/api/deploy", json=_demo_payload())
    assert resp.status_code == 202, resp.text


def test_configured_token_enforced(authed_client):
    with authed_client(MEDHA_API_TOKEN="s3cret") as client:
        assert client.post("/api/deploy", json=_demo_payload()).status_code == 401
        wrong = client.post(
            "/api/deploy", json=_demo_payload(), headers={"X-Medha-Token": "nope"}
        )
        assert wrong.status_code == 401
        ok = client.post(
            "/api/deploy", json=_demo_payload(), headers={"X-Medha-Token": "s3cret"}
        )
        assert ok.status_code == 202, ok.text


def test_evaluation_and_change_impact_posts_guarded(authed_client):
    with authed_client(MEDHA_API_TOKEN="s3cret") as client:
        assert client.post("/api/evaluation/run/cnp").status_code == 401
        assert (
            client.post(
                "/api/change-impact/analyze",
                json={
                    "repository_url": "https://github.com/example/app",
                    "base_revision": "base",
                    "target_revision": "target",
                },
            ).status_code
            == 401
        )
        headers = {"X-Medha-Token": "s3cret"}
        assert client.post("/api/evaluation/run/cnp", headers=headers).status_code == 200


def test_production_without_token_fails_closed(authed_client):
    with authed_client(MEDHA_ENV="production") as client:
        resp = client.post("/api/deploy", json=_demo_payload())
        assert resp.status_code == 503
        assert resp.json()["detail"]["code"] == "API_TOKEN_NOT_CONFIGURED"
        # Reads stay open: health + deployment reads are not mutating routes.
        assert client.get("/health").status_code == 200


def test_production_pins_simulator_executor(monkeypatch):
    monkeypatch.setenv("MEDHA_ENV", "production")
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "docker")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    try:
        assert isinstance(choose_executor(is_demo=False), SimulatorExecutor)
    finally:
        get_settings.cache_clear()


def test_non_production_docker_mode_still_selects_docker(monkeypatch):
    monkeypatch.setenv("MEDHA_ENV", "development")
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "docker")
    get_settings.cache_clear()
    try:
        assert isinstance(choose_executor(is_demo=False), DockerExecutor)
    finally:
        get_settings.cache_clear()


def test_oversized_intent_rejected_before_pipeline(authed_client):
    with authed_client() as client:
        resp = client.post("/api/deploy", json=_demo_payload(intent="x" * 2001))
    assert resp.status_code == 422, resp.text
