"""Postgres/Supabase backend selection, DSN handling, and SQL translation.

Offline-safe: everything here runs without a database except
test_live_postgres_roundtrip, which is skip-guarded on MEDHA_DATABASE_URL
and skips again when the server is unreachable.

Live run (requires the secret in your shell, never committed):
    MEDHA_DATABASE_URL=postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres \
        .venv/Scripts/python.exe -m pytest tests/test_database_postgres.py -q
"""

from __future__ import annotations

import os

import pytest

from app.core.config import get_settings, is_postgres_dsn
from app.database.connection import (
    describe_db,
    normalize_dsn,
    redacted_label,
    resolve_backend,
    translate_sql,
)

SUPABASE_HOST = "db.myukgjmhzmlzkxjszsdh.supabase.co"


def test_is_postgres_dsn() -> None:
    assert is_postgres_dsn("postgresql://postgres:pw@host:5432/postgres")
    assert is_postgres_dsn("postgres://postgres:pw@host:5432/postgres")
    assert is_postgres_dsn("  postgresql://x@h/db  ")
    assert not is_postgres_dsn("")
    assert not is_postgres_dsn(None)
    assert not is_postgres_dsn("./data/medha.db")
    assert not is_postgres_dsn("sqlite:///data/medha.db")


def test_normalize_dsn_adds_sslmode_for_supabase() -> None:
    dsn = f"postgresql://postgres:p%40ss%3Aw0rd@{SUPABASE_HOST}:5432/postgres"
    out = normalize_dsn(dsn)
    assert "sslmode=require" in out
    # Percent-encoded password passes through byte-identical.
    assert "p%40ss%3Aw0rd" in out


def test_normalize_dsn_keeps_explicit_sslmode() -> None:
    dsn = (
        f"postgresql://postgres:pw@{SUPABASE_HOST}:5432/postgres?sslmode=disable"
    )
    assert normalize_dsn(dsn) == dsn


def test_redacted_label_never_contains_password() -> None:
    dsn = f"postgresql://postgres:Sup3rS3cret!@{SUPABASE_HOST}:5432/postgres"
    label = redacted_label(dsn)
    assert "Sup3rS3cret" not in label
    assert SUPABASE_HOST in label
    assert label.startswith("postgresql://postgres@")


def test_translate_sql_placeholders_and_rowid() -> None:
    assert (
        translate_sql("SELECT * FROM deployments WHERE deployment_id = ?")
        == "SELECT * FROM deployments WHERE deployment_id = %s"
    )
    assert (
        translate_sql("SELECT * FROM deployments ORDER BY rowid DESC LIMIT ? OFFSET ?")
        == "SELECT * FROM deployments ORDER BY seq DESC LIMIT %s OFFSET %s"
    )
    # LIKE wildcards live in params, never in SQL — nothing else changes.
    assert (
        translate_sql("SELECT * FROM deployments WHERE repository_url LIKE ?")
        == "SELECT * FROM deployments WHERE repository_url LIKE %s"
    )


def test_resolve_backend_explicit_path_always_sqlite(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(
        "MEDHA_DATABASE_URL",
        f"postgresql://postgres:pw@{SUPABASE_HOST}:5432/postgres",
    )
    get_settings.cache_clear()
    try:
        assert resolve_backend(tmp_path / "x.db") == "sqlite"
        assert resolve_backend(None) == "postgres"
    finally:
        get_settings.cache_clear()


def test_resolve_backend_defaults_to_sqlite(monkeypatch) -> None:
    # Empty URL overrides shell env *and* any local backend/.env secret.
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    get_settings.cache_clear()
    try:
        assert resolve_backend(None) == "sqlite"
        assert "medha.db" in describe_db()
    finally:
        get_settings.cache_clear()


def test_describe_db_redacts_postgres_password(monkeypatch) -> None:
    monkeypatch.setenv(
        "MEDHA_DATABASE_URL",
        f"postgresql://postgres:Sup3rS3cret!@{SUPABASE_HOST}:5432/postgres",
    )
    get_settings.cache_clear()
    try:
        label = describe_db()
        assert "Sup3rS3cret" not in label
        assert SUPABASE_HOST in label
    finally:
        get_settings.cache_clear()


def _configured_live_url() -> str | None:
    """Live URL from shell env or local backend/.env (whatever configured it)."""
    shell = os.environ.get("MEDHA_DATABASE_URL", "").strip()
    if shell:
        return shell
    file_url = get_settings().database_url.strip()
    return file_url or None


def test_live_postgres_roundtrip() -> None:
    """Full repository CRUD against the configured Postgres (Supabase)."""
    if not _configured_live_url():
        pytest.skip("MEDHA_DATABASE_URL not set — live Postgres test skipped")
    import uuid

    from app.core.enums import DeployMode, DeploymentStatus
    from app.database.connection import _pg_connect, init_db, ping_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord
    from app.models.events import SystemEvent

    get_settings.cache_clear()
    try:
        assert get_settings().use_postgres
        try:
            init_db()
        except Exception as exc:
            pytest.skip(f"Postgres unreachable: {exc}")
        assert ping_db()

        repo = DeploymentRepository()
        stamp = uuid.uuid4().hex[:8]
        dep_id = f"dep_pgtest_{stamp}"
        now = "2026-10-11T00:00:00Z"
        record = DeploymentRecord(
            deployment_id=dep_id,
            repository_url="https://github.com/example/pg-test",
            mode=DeployMode.REAL,
            scenario=None,
            target_host="localhost",
            target_port=8080,
            intent="pg roundtrip",
            status=DeploymentStatus.STARTED,
            current_stage="PREFLIGHT",
            created_at=now,
            updated_at=now,
            is_demo=True,
        )
        repo.create(record)
        try:
            got = repo.get(dep_id)
            assert got is not None and got.deployment_id == dep_id

            event = SystemEvent(
                event_id=f"evt_pgtest_{stamp}",
                deployment_id=dep_id,
                event_type="deployment.created",
                ts=now,
                stage="PREFLIGHT",
                message="pg roundtrip",
                status=None,
                level="info",
                is_demo=True,
                data={"seq": 1},
            )
            repo.add_event(event)
            assert len(repo.list_events(dep_id)) == 1

            updated = repo.update_status(
                dep_id, status=DeploymentStatus.COMPLETED, updated_at=now
            )
            assert updated is not None
            assert updated.status == DeploymentStatus.COMPLETED

            saved = repo.save_artifacts(
                dep_id,
                verification={"passed": True},
                updated_at=now,
            )
            assert saved is not None
            assert saved.verification == {"passed": True}

            runs, total = repo.list(limit=10, offset=0)
            assert total >= 1
            assert any(r.deployment_id == dep_id for r in runs)
        finally:
            # Leave no test rows behind.
            with _pg_connect() as conn:
                conn.execute(
                    "DELETE FROM events WHERE deployment_id = %s", (dep_id,)
                )
                conn.execute(
                    "DELETE FROM deployments WHERE deployment_id = %s", (dep_id,)
                )
                conn.commit()
    finally:
        get_settings.cache_clear()
