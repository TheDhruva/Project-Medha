from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.config import get_settings, is_postgres_dsn
from app.core.logging import get_logger

logger = get_logger(__name__)

_SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_SCHEMA_PG_PATH = Path(__file__).with_name("schema_pg.sql")

# Bump when schema.sql or migration steps change. Tracked via PRAGMA user_version.
_SCHEMA_VERSION = 8

_ARTIFACT_COLUMNS = (
    "result_json",
    "constraints_json",
    "negotiation_json",
    "verification_json",
    "critic_json",
    "graph_json",
    "rollback_json",
    "change_intel_json",
    "ai_json",
)

_NEW_TABLES_SQL = (
    """CREATE TABLE IF NOT EXISTS users (
        clerk_sub TEXT PRIMARY KEY,
        created_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS webhook_deliveries (
        delivery_id TEXT PRIMARY KEY,
        source TEXT NOT NULL DEFAULT 'github',
        repository TEXT NOT NULL,
        ref TEXT,
        sha TEXT,
        event TEXT,
        status TEXT NOT NULL DEFAULT 'received',
        proposal_id TEXT,
        received_at TEXT NOT NULL,
        note TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS proposals (
        proposal_id TEXT PRIMARY KEY,
        repository TEXT NOT NULL,
        branch TEXT NOT NULL,
        base_sha TEXT,
        target_sha TEXT NOT NULL,
        deployment_id TEXT,
        plan_hash TEXT,
        plan_json TEXT,
        push_json TEXT,
        project_id TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_by TEXT,
        created_at TEXT NOT NULL,
        decided_by TEXT,
        decided_at TEXT,
        execution_id TEXT,
        idempotency_key TEXT UNIQUE NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_proposals_repo_branch
        ON proposals (repository, branch)""",
    """CREATE TABLE IF NOT EXISTS projects (
        project_id TEXT PRIMARY KEY,
        owner_sub TEXT NOT NULL,
        name TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT 'github',
        repo_owner TEXT NOT NULL,
        repo_name TEXT NOT NULL,
        repository TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        branch TEXT NOT NULL DEFAULT 'main',
        visibility TEXT NOT NULL DEFAULT 'unverified',
        connection_status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """Create UNIQUE INDEX IF NOT EXISTS idx_projects_owner_repo
        ON projects (owner_sub, repository)""",
    """CREATE INDEX IF NOT EXISTS idx_projects_repository
        ON projects (repository)""",
    """CREATE INDEX IF NOT EXISTS idx_deployments_owner_status
        ON deployments (owner_sub, status)""",
    """CREATE INDEX IF NOT EXISTS idx_deployments_status
        ON deployments (status)""",
    """CREATE INDEX IF NOT EXISTS idx_proposals_deployment
        ON proposals (deployment_id)""",
)


def resolve_backend(db_path: Path | None = None) -> str:
    """Return "postgres" or "sqlite" without opening any connection.

    An explicit file path always means SQLite (offline tests, Demo Mode).
    Otherwise MEDHA_DATABASE_URL selects Postgres when set.
    """
    if db_path is not None:
        return "sqlite"
    return "postgres" if get_settings().use_postgres else "sqlite"


def normalize_dsn(dsn: str) -> str:
    """Append sslmode=require when the DSN sets none (Supabase requires TLS).

    Only the query string is touched; userinfo (percent-encoded password)
    passes through byte-identical via urlsplit/urlunsplit.
    """
    parts = urlsplit(dsn.strip())
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    if "sslmode" not in query:
        query["sslmode"] = "require"
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment)
        )
    return dsn.strip()


def redacted_label(dsn: str) -> str:
    """Log-safe database label: scheme + user + host, never the password."""
    try:
        parts = urlsplit(dsn.strip())
        user = parts.username or "?"
        host = parts.hostname or "?"
        port = f":{parts.port}" if parts.port else ""
        db = parts.path.lstrip("/") or "?"
        return f"postgresql://{user}@{host}{port}/{db}"
    except ValueError:
        return "postgresql://?"


def describe_db() -> str:
    """Short log-safe label for the configured backend."""
    if get_settings().use_postgres:
        return redacted_label(get_settings().database_url)
    return str(get_settings().database_path)


def translate_sql(sql: str) -> str:
    """Map repository SQL (sqlite dialect) to Postgres.

    - `?` placeholders become `%s`. Repository SQL never uses `?` inside
      string literals or JSON operators, so a plain replace is exact.
    - `rowid` ordering becomes the BIGSERIAL `seq` column (schema_pg.sql).
    """
    return sql.replace("rowid", "seq").replace("?", "%s")


class PostgresConnection:
    """Minimal shim so repositories keep `?` placeholders and `row.keys()`.

    Each repository call opens one short-lived connection (same lifecycle as
    the SQLite path): `with get_connection() as conn:` commits explicitly via
    conn.commit() and closes on block exit. Uncommitted work on error is
    rolled back before close.
    """

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    def execute(self, sql: str, params: Any = ()) -> Any:
        from psycopg.rows import dict_row

        cursor = self._conn.cursor(row_factory=dict_row)
        cursor.execute(translate_sql(sql), params or None)
        return cursor

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> PostgresConnection:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if exc_type is not None:
                self.rollback()
        finally:
            self.close()


def _pg_connect() -> PostgresConnection:
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError(
            "MEDHA_DATABASE_URL selects Postgres but the 'psycopg' package is "
            "not installed (pip install psycopg[binary])."
        ) from exc
    dsn = normalize_dsn(get_settings().database_url)
    conn = psycopg.connect(dsn, connect_timeout=10)
    return PostgresConnection(conn)


def get_connection(
    db_path: Path | None = None,
) -> sqlite3.Connection | PostgresConnection:
    if resolve_backend(db_path) == "postgres":
        return _pg_connect()
    path = db_path or get_settings().database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    # timeout=10s bounds lock waits; WAL + busy_timeout keep concurrent
    # readers/writers (API + pipeline tasks) from failing fast with
    # SQLITE_BUSY. SQLite-only pragmas — never applied to Postgres.
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA synchronous = NORMAL")
    except Exception:  # noqa: BLE001 - pragmas are advisory (e.g. read-only fs)
        pass
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


def _ensure_owner_column(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
    if "owner_sub" not in existing:
        conn.execute("ALTER TABLE deployments ADD COLUMN owner_sub TEXT")


def _ensure_v5_tables(conn: sqlite3.Connection) -> None:
    for statement in _NEW_TABLES_SQL:
        conn.execute(statement)


_V8_TABLES_SQL = (
    """CREATE TABLE IF NOT EXISTS jobs (
        job_id TEXT PRIMARY KEY,
        delivery_id TEXT UNIQUE,
        project_id TEXT,
        repository TEXT NOT NULL,
        branch TEXT NOT NULL DEFAULT 'main',
        base_sha TEXT,
        target_sha TEXT NOT NULL,
        seq INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'queued',
        attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3,
        deployment_id TEXT,
        last_error TEXT,
        not_before TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE INDEX IF NOT EXISTS idx_jobs_repo_branch_seq
        ON jobs (repository, branch, seq)""",
    """CREATE INDEX IF NOT EXISTS idx_jobs_status
        ON jobs (status)""",
    """CREATE TABLE IF NOT EXISTS commits (
        project_id TEXT NOT NULL,
        sha TEXT NOT NULL,
        parents_json TEXT NOT NULL DEFAULT '[]',
        author TEXT,
        committed_at TEXT,
        message TEXT,
        branch TEXT,
        recorded_at TEXT NOT NULL,
        PRIMARY KEY (project_id, sha)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_commits_project_time
        ON commits (project_id, committed_at)""",
    """CREATE TABLE IF NOT EXISTS scores (
        run_id TEXT NOT NULL,
        score_name TEXT NOT NULL,
        value REAL,
        value_null INTEGER NOT NULL DEFAULT 0,
        version TEXT NOT NULL DEFAULT 'v1',
        computed_at TEXT NOT NULL,
        inputs_hash TEXT NOT NULL,
        target_sha TEXT NOT NULL,
        project_id TEXT,
        evidence_json TEXT NOT NULL DEFAULT '{}',
        PRIMARY KEY (run_id, score_name)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_scores_project_sha
        ON scores (project_id, target_sha)""",
    """CREATE TABLE IF NOT EXISTS analysis_cache (
        cache_key TEXT PRIMARY KEY,
        project_id TEXT,
        kind TEXT NOT NULL,
        inputs_hash TEXT NOT NULL,
        target_sha TEXT NOT NULL,
        created_at TEXT NOT NULL,
        payload_json TEXT NOT NULL DEFAULT '{}'
    )""",
)


def _ensure_v8_tables(conn: sqlite3.Connection) -> None:
    for statement in _V8_TABLES_SQL:
        conn.execute(statement)


def _ensure_v6_columns(conn: sqlite3.Connection) -> None:
    """Project-scoped connections (v6): projects table + link columns."""
    for statement in _NEW_TABLES_SQL:
        conn.execute(statement)
    deployments_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(deployments)")
    }
    if "project_id" not in deployments_cols:
        conn.execute("ALTER TABLE deployments ADD COLUMN project_id TEXT")
    proposals_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(proposals)")
    }
    if "project_id" not in proposals_cols:
        conn.execute("ALTER TABLE proposals ADD COLUMN project_id TEXT")
    if "push_json" not in proposals_cols:
        conn.execute("ALTER TABLE proposals ADD COLUMN push_json TEXT")


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
    _ensure_owner_column(conn)
    _ensure_v5_tables(conn)
    _ensure_v6_columns(conn)
    _ensure_v8_tables(conn)
    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


def _split_statements(schema: str) -> list[str]:
    return [part.strip() for part in schema.split(";") if part.strip()]


def _schema_code(schema: str) -> str:
    """Schema text with full-line `--` comments removed.

    schema.sql documents tables with comment blocks directly above the
    CREATE TABLE they describe, and some comments contain semicolons.
    Splitting the raw text on ";" would slice comment fragments into the
    following statement, so a table chunk would no longer be recognized
    as one: the table is silently skipped and its indexes later fail
    with "no such table". All `--` markers in schema.sql are full-line
    comments (no `--` inside string literals), so line filtering is safe.
    """
    return "\n".join(
        line for line in schema.splitlines()
        if not line.strip().startswith("--")
    )


def _code_without_comments(statement: str) -> str:
    """Statement with leading/trailing `--` comment lines removed.

    Kept as a safety net for classification when statements arrive from
    other sources (e.g. inline migration SQL with header comments).
    """
    lines = [
        line for line in statement.splitlines()
        if not line.strip().startswith("--")
    ]
    return "\n".join(lines).strip()


def _init_postgres() -> str:
    """Create Postgres tables idempotently. Returns a redacted label."""
    schema = _SCHEMA_PG_PATH.read_text(encoding="utf-8")
    with _pg_connect() as conn:
        for statement in _split_statements(schema):
            conn.execute(statement)
        # Heal drift for databases created before seq existed.
        for table in ("deployments", "events"):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS seq BIGSERIAL"
            )
        for table, column, ddl in (
            ("deployments", "ai_json", "TEXT"),
            ("deployments", "owner_sub", "TEXT"),
            ("deployments", "project_id", "TEXT"),
            ("proposals", "project_id", "TEXT"),
            ("proposals", "push_json", "TEXT"),
        ):
            conn.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}"
            )
        # New tables are created idempotently by schema_pg.sql above.
        conn.commit()
    label = redacted_label(get_settings().database_url)
    logger.info("Postgres ready at %s", label)
    return label


def init_db(db_path: Path | None = None) -> Path | str:
    """Create or upgrade the configured database deterministically.

    Repeat calls are safe. An explicit path always initializes SQLite;
    otherwise the backend follows MEDHA_DATABASE_URL (Postgres) or falls
    back to the SQLite file.
    """
    if resolve_backend(db_path) == "postgres":
        return _init_postgres()
    path = db_path or get_settings().database_path
    schema = _schema_code(_SCHEMA_PATH.read_text(encoding="utf-8"))
    with get_connection(path) as conn:
        # Legacy databases may lack newer columns that fresh-schema indexes
        # reference (e.g. owner_sub). Create tables first, heal columns via
        # _migrate, then create indexes — so upgrades never fail on index
        # creation against a stale column set.
        statements = _split_statements(schema)
        tables = [s for s in statements if _code_without_comments(s).upper().startswith("CREATE TABLE")]
        indexes = [s for s in statements if s.upper().startswith("CREATE")]
        indexes = [s for s in indexes if s not in tables]
        for statement in tables:
            conn.execute(statement)
        _migrate(conn)
        for statement in indexes:
            conn.execute(statement)
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        conn.commit()
    logger.info("SQLite ready at %s (schema v%d)", path, _SCHEMA_VERSION)
    return path


def ping_db(db_path: Path | None = None) -> bool:
    try:
        with get_connection(db_path) as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except Exception as exc:  # noqa: BLE001 - ping must never raise
        if resolve_backend(db_path) == "postgres":
            logger.error(
                "Postgres ping failed at %s: %s",
                redacted_label(get_settings().database_url),
                exc,
            )
        else:
            logger.error("SQLite ping failed: %s", exc)
        return False
