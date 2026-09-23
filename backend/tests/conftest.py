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


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test_medha.db"
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    get_settings.cache_clear()
    init_db(db_path)
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _deploy_payload(**overrides):
    payload = {
        "repository_url": "https://github.com/example/app",
        "mode": "demo",
        "scenario": "PORT_CONFLICT",
        "target": {"host": "localhost", "port": 8080},
        "intent": "Deploy securely",
    }
    payload.update(overrides)
    return payload
