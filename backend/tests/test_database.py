"""Database initialization/migration tests: idempotency and safe upgrades."""

from __future__ import annotations

import sqlite3

from app.database.connection import (
    _ARTIFACT_COLUMNS,
    _SCHEMA_PATH,
    _SCHEMA_VERSION,
    get_connection,
    init_db,
)

LEGACY_SCHEMA = """
CREATE TABLE deployments (
    deployment_id TEXT PRIMARY KEY,
    repository_url TEXT NOT NULL,
    mode TEXT NOT NULL,
    scenario TEXT,
    target_host TEXT NOT NULL,
    target_port INTEGER NOT NULL,
    intent TEXT,
    status TEXT NOT NULL,
    current_stage TEXT,
    explain_simple TEXT,
    explain_technical TEXT,
    error_summary TEXT,
    is_demo INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _user_version(db_path) -> int:
    conn = get_connection(db_path)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    finally:
        conn.close()


def _install_legacy_schema(db_path) -> None:
    conn = get_connection(db_path)
    try:
        conn.executescript(LEGACY_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def test_init_db_creates_schema_and_sets_version(tmp_path):
    db_path = init_db(tmp_path / "fresh.db")
    assert db_path.exists()
    assert _user_version(db_path) == _SCHEMA_VERSION
    conn = get_connection(db_path)
    try:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"deployments", "events"}.issubset(tables)
    finally:
        conn.close()


def test_init_db_is_idempotent(tmp_path):
    db_path = init_db(tmp_path / "idempotent.db")
    init_db(db_path)
    assert _user_version(db_path) == _SCHEMA_VERSION
    conn = get_connection(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM deployments").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


def test_init_db_preserves_existing_rows(tmp_path):
    db_path = tmp_path / "preserve.db"
    _install_legacy_schema(db_path)
    conn = get_connection(db_path)
    try:
        conn.execute(
            "INSERT INTO deployments "
            "(deployment_id, repository_url, mode, target_host, target_port, status, "
            "is_demo, created_at, updated_at) "
            "VALUES ('dep_keep', 'https://example.com/app', 'real', 'localhost', 8080, "
            "'completed', 0, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')"
        )
        conn.commit()
    finally:
        conn.close()
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM deployments WHERE deployment_id='dep_keep'").fetchone()
        assert row["repository_url"] == "https://example.com/app"
        assert row["status"] == "completed"
        assert _user_version(db_path) == _SCHEMA_VERSION
    finally:
        conn.close()


def test_init_db_upgrades_legacy_schema_with_artifact_columns(tmp_path):
    db_path = tmp_path / "legacy.db"
    _install_legacy_schema(db_path)
    conn = get_connection(db_path)
    try:
        before = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
        assert "result_json" not in before
    finally:
        conn.close()
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        after = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
        for column in _ARTIFACT_COLUMNS:
            assert column in after
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_init_db_heals_revision_columns_on_stale_v2_database(tmp_path):
    db_path = tmp_path / "stale_v2.db"
    _install_legacy_schema(db_path)
    conn = get_connection(db_path)
    try:
        # Replica of the historical v2 no-op state: artifact columns present,
        # revision columns missing, user_version already stamped at v2.
        conn.executescript(
            "ALTER TABLE deployments ADD COLUMN result_json TEXT;"
            "ALTER TABLE deployments ADD COLUMN constraints_json TEXT;"
            "ALTER TABLE deployments ADD COLUMN negotiation_json TEXT;"
            "ALTER TABLE deployments ADD COLUMN verification_json TEXT;"
            "ALTER TABLE deployments ADD COLUMN critic_json TEXT;"
            "ALTER TABLE deployments ADD COLUMN graph_json TEXT;"
            "ALTER TABLE deployments ADD COLUMN rollback_json TEXT;"
            "ALTER TABLE deployments ADD COLUMN change_intel_json TEXT;"
            "PRAGMA user_version = 2"
        )
        conn.commit()
    finally:
        conn.close()
    init_db(db_path)
    conn = get_connection(db_path)
    try:
        after = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
        assert "base_revision" in after
        assert "target_revision" in after
    finally:
        conn.close()
    assert _user_version(db_path) == _SCHEMA_VERSION


def test_schema_sql_matches_expected_columns():
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS deployments" in sql
    assert "CREATE TABLE IF NOT EXISTS events" in sql
    for column in _ARTIFACT_COLUMNS:
        assert column in sql
    assert "CREATE INDEX IF NOT EXISTS idx_events_deployment_ts" in sql