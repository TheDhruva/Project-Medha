from __future__ import annotations

import sqlite3
from pathlib import Path

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Bump when schema.sql or migration steps change. Tracked via PRAGMA user_version.
_SCHEMA_VERSION = 4

_ARTIFACT_COLUMNS = (
    "result_json",
    "constraints_json",
    "negotiation_json",
    "verification_json",
    "critic_json",
    "graph_json",
    "rollback_json",
    "change_intel_json",
)


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_settings().database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_artifact_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
    for column in _ARTIFACT_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE deployments ADD COLUMN {column} TEXT")


def _ensure_revision_columns(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
    if "base_revision" not in existing:
        conn.execute("ALTER TABLE deployments ADD COLUMN base_revision TEXT")
    if "target_revision" not in existing:
        conn.execute("ALTER TABLE deployments ADD COLUMN target_revision TEXT")


def _migrate(conn: sqlite3.Connection) -> None:
    """Apply pending schema migrations. Idempotent and version-gated.

    schema.sql describes the canonical (newest) schema. Existing databases
    created before a column was added are upgraded in place, keeping any rows.
    """
    version = int(conn.execute("PRAGMA user_version").fetchone()[0] or 0)
    if version >= _SCHEMA_VERSION:
        return
    # Heal drift in place for any older database. Both helpers are idempotent
    # (they check PRAGMA table_info before ALTER), so they are safe to run for
    # every pre-v3 database regardless of which historical version it reports.
    _ensure_artifact_columns(conn)
    _ensure_revision_columns(conn)
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


def init_db(db_path: Path | None = None) -> Path:
    """Create or upgrade the SQLite database deterministically.

    Repeat calls are safe (schema uses IF NOT EXISTS; migrations are guarded by
    PRAGMA user_version), so init_db can run on every app start.
    """
    path = db_path or get_settings().database_path
    schema = _SCHEMA_PATH.read_text(encoding="utf-8")
    with get_connection(path) as conn:
        conn.executescript(schema)
        _migrate(conn)
        conn.commit()
    logger.info("SQLite ready at %s (schema v%d)", path, _SCHEMA_VERSION)
    return path


def ping_db(db_path: Path | None = None) -> bool:
    try:
        with get_connection(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error as exc:
        logger.error("SQLite ping failed: %s", exc)
        return False
