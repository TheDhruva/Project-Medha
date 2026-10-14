"""Environment safety: SQLite-by-default locally, Postgres in production.

All credentials here are fake (testuser/testpass, example.invalid,
127.0.0.1). No test opens a network connection: selection is pure string
logic on the DSN scheme plus MEDHA_ENV / MEDHA_DATABASE_BACKEND.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings, get_settings, is_postgres_dsn
from app.database.connection import resolve_backend

FAKE_PG_URL = "postgresql://testuser:testpass@127.0.0.1:5432/testdb"
FAKE_PASSWORD = "testpass"


def _write_env_file(path, lines: str):
    path.write_text(lines, encoding="utf-8")
    return str(path)


def test_local_default_is_sqlite_without_url(monkeypatch) -> None:
    monkeypatch.setenv("MEDHA_ENV", "development")
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.delenv("MEDHA_DATABASE_BACKEND", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert settings.hosted_security_error() is None
        assert not settings.use_postgres
        assert resolve_backend(None) == "sqlite"
    finally:
        get_settings.cache_clear()


def test_local_shell_url_without_optin_stays_sqlite(monkeypatch) -> None:
    """A stray production URL in local env must not hijack local runs."""
    monkeypatch.setenv("MEDHA_ENV", "development")
    monkeypatch.setenv("MEDHA_DATABASE_URL", FAKE_PG_URL)
    monkeypatch.delenv("MEDHA_DATABASE_BACKEND", raising=False)
    get_settings.cache_clear()
    try:
        settings = get_settings()
        assert not settings.use_postgres
        assert settings.ignored_db_url
        assert settings.database_url_source() == "shell"
        assert resolve_backend(None) == "sqlite"
    finally:
        get_settings.cache_clear()


def test_local_file_url_without_optin_stays_sqlite(monkeypatch, tmp_path) -> None:
    """Dotenv-inherited URLs (the implicit fallback) never select Postgres."""
    monkeypatch.delenv("MEDHA_DATABASE_URL", raising=False)
    monkeypatch.delenv("MEDHA_DATABASE_BACKEND", raising=False)
    env_file = _write_env_file(
        tmp_path / "dotenv-url", f'MEDHA_DATABASE_URL="{FAKE_PG_URL}"\n'
    )
    settings = Settings(_env_file=env_file, MEDHA_ENV="development")
    assert not settings.use_postgres
    assert settings.ignored_db_url
    assert settings.database_url_source() == "file"


def test_local_optin_selects_postgres_without_connecting(monkeypatch) -> None:
    """Explicit MEDHA_DATABASE_BACKEND=postgres + valid DSN selects Postgres.

    Pure selection logic — no socket is opened, so no live deployment is
    needed to verify Render-equivalent configuration.
    """
    monkeypatch.setenv("MEDHA_ENV", "development")
    monkeypatch.setenv("MEDHA_DATABASE_URL", FAKE_PG_URL)
    monkeypatch.setenv("MEDHA_DATABASE_BACKEND", "postgres")
    get_settings.cache_clear()
    try:
        assert get_settings().use_postgres
        assert resolve_backend(None) == "postgres"
    finally:
        get_settings.cache_clear()


def test_production_valid_url_selects_postgres() -> None:
    settings = Settings(
        MEDHA_ENV="production",
        MEDHA_AUTH_MODE="clerk",
        CLERK_DOMAIN="test.clerk.accounts.dev",
        MEDHA_API_TOKEN="test-token",
        MEDHA_DATABASE_URL=FAKE_PG_URL,
        MEDHA_EXECUTOR_MODE="disabled",
    )
    assert settings.use_postgres
    assert settings.hosted_security_error() is None


def test_production_missing_url_fails_closed() -> None:
    settings = Settings(
        MEDHA_ENV="production",
        MEDHA_AUTH_MODE="clerk",
        CLERK_DOMAIN="test.clerk.accounts.dev",
        MEDHA_API_TOKEN="test-token",
        MEDHA_DATABASE_URL="",
        MEDHA_EXECUTOR_MODE="disabled",
    )
    assert not settings.use_postgres
    err = settings.hosted_security_error()
    assert err is not None and "MEDHA_DATABASE_URL" in err


@pytest.mark.parametrize(
    "bad_url", ["not-a-dsn", "sqlite:///./data/medha.db", "mysql://u:p@h/db"]
)
def test_production_invalid_url_fails_closed(bad_url: str) -> None:
    """Present-but-invalid URLs must refuse boot, never silent SQLite."""
    settings = Settings(
        MEDHA_ENV="production",
        MEDHA_AUTH_MODE="clerk",
        CLERK_DOMAIN="test.clerk.accounts.dev",
        MEDHA_API_TOKEN="test-token",
        MEDHA_DATABASE_URL=bad_url,
        MEDHA_EXECUTOR_MODE="disabled",
    )
    assert not settings.use_postgres
    err = settings.hosted_security_error()
    assert err is not None and "MEDHA_DATABASE_URL" in err
    assert FAKE_PASSWORD not in err


def test_production_sqlite_flag_contradiction_fails_closed() -> None:
    settings = Settings(
        MEDHA_ENV="production",
        MEDHA_AUTH_MODE="clerk",
        CLERK_DOMAIN="test.clerk.accounts.dev",
        MEDHA_API_TOKEN="test-token",
        MEDHA_DATABASE_URL=FAKE_PG_URL,
        MEDHA_DATABASE_BACKEND="sqlite",
        MEDHA_EXECUTOR_MODE="disabled",
    )
    err = settings.hosted_security_error()
    assert err is not None and "MEDHA_DATABASE_BACKEND" in err


def test_invalid_backend_value_rejected() -> None:
    with pytest.raises(ValueError, match="MEDHA_DATABASE_BACKEND"):
        Settings(MEDHA_DATABASE_BACKEND="oracle")


def test_explicit_path_always_sqlite_even_for_production_pg(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("MEDHA_ENV", "production")
    monkeypatch.setenv("MEDHA_DATABASE_URL", FAKE_PG_URL)
    get_settings.cache_clear()
    try:
        assert get_settings().use_postgres
        assert resolve_backend(tmp_path / "offline.db") == "sqlite"
    finally:
        get_settings.cache_clear()


def test_no_secrets_in_db_labels() -> None:
    from app.database.connection import describe_db, redacted_label

    assert FAKE_PASSWORD not in redacted_label(FAKE_PG_URL)
    assert is_postgres_dsn(FAKE_PG_URL)
    assert not is_postgres_dsn("")
    assert not is_postgres_dsn("not-a-dsn")
    # describe_db with an explicit sqlite path never touches the URL.
    assert "testpass" not in str(describe_db())


def test_local_boot_with_stray_url_uses_sqlite(tmp_path, monkeypatch) -> None:
    """End-to-end: stray URL in local env boots SQLite, no remote needed."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    monkeypatch.setenv("MEDHA_ENV", "development")
    monkeypatch.setenv("MEDHA_AUTH_MODE", "off")
    monkeypatch.setenv("MEDHA_API_TOKEN", "")
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "local.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", FAKE_PG_URL)
    monkeypatch.delenv("MEDHA_DATABASE_BACKEND", raising=False)
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            health = client.get("/health")
            assert health.status_code == 200
            body = health.json()
            assert body["database"] == "ok"
            assert body["database_mode"] == "sqlite"
        assert (tmp_path / "local.db").exists()
    finally:
        get_settings.cache_clear()
