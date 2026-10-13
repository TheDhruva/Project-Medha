from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.deploy_lock import release_real_deploy
from app.database.connection import init_db
from app.main import create_app


@pytest.fixture(autouse=True)
def _clear_deploy_lock():
    release_real_deploy()
    yield
    release_real_deploy()


@pytest.fixture(autouse=True)
def _explicit_test_execution(monkeypatch):
    """Suite-wide isolated-test declarations (never production defaults).

    The demo engine is explicitly enabled and the simulator explicitly
    selected for every test. Production defaults are MEDHA_ENABLE_DEMO=false
    and fail-closed execution (no silent simulator). Tests that pin other
    modes override these via their own monkeypatch (applied after autouse).
    """
    monkeypatch.setenv("MEDHA_ENABLE_DEMO", "true")
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "simulator")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_medha.db"
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db_path))
    # Keep the suite offline-deterministic: an empty URL overrides both the
    # shell env and any local backend/.env secret (env beats dotenv file).
    # Live PG coverage is isolated in test_database_postgres.py.
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    # Isolated-test declarations (never production defaults): the demo engine
    # is explicitly enabled here, and the simulator is explicitly selected.
    # Production defaults are MEDHA_ENABLE_DEMO=false and fail-closed
    # execution (no silent simulator). See ADR-037.
    monkeypatch.setenv("MEDHA_ENABLE_DEMO", "true")
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "simulator")
    get_settings.cache_clear()
    init_db(db_path)
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _deploy_payload(**overrides):
    from pathlib import Path as _Path

    _fixture_repo = str(
        (_Path(__file__).resolve().parent / "fixtures" / "repos" / "node_api").resolve()
    )
    payload = {
        "repository_url": _fixture_repo,
        "mode": "real",
        "scenario": None,
        "target": {"host": "localhost", "port": 8080},
        "intent": "Deploy securely",
    }
    payload.update(overrides)
    return payload
