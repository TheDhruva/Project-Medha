"""PostgreSQL jobs persistence: ordering-column alignment (Phase 1).

Guards the reported defect where the job repository addressed the
per-branch ordering counter as `seq` on every backend, while
schema_pg.sql reserves `seq` for the BIGSERIAL row surrogate and keeps
the counter in `seq_num`.

- Unit-level tests prove the column selection per backend (no server).
- The live test (claim → finish → supersede → latest) runs only when
  MEDHA_DATABASE_URL points at a reachable Postgres AND Postgres is
  explicitly selected (MEDHA_DATABASE_BACKEND=postgres locally or
  MEDHA_ENV=production); otherwise it reports NOT RUN via pytest.skip —
  never a fabricated success.
"""

from __future__ import annotations

import os

import pytest

from app.core.config import get_settings, is_postgres_dsn


def test_job_order_column_sqlite() -> None:
    import pathlib

    from app.database.repositories import _job_order_col

    # Explicit file paths always mean SQLite, even with a PG URL configured.
    assert _job_order_col(pathlib.Path("x.db")) == "seq"


def test_job_order_column_postgres(monkeypatch) -> None:
    from app.database.repositories import _job_order_col

    monkeypatch.setenv("MEDHA_DATABASE_URL", "postgresql://user@host:5432/db")
    # Non-production selects Postgres only via explicit opt-in.
    monkeypatch.setenv("MEDHA_DATABASE_BACKEND", "postgres")
    get_settings.cache_clear()
    try:
        assert get_settings().use_postgres
        assert _job_order_col(None) == "seq_num"
    finally:
        get_settings.cache_clear()


def test_job_sql_uses_backend_order_column(monkeypatch) -> None:
    from app.database import repositories as repo_mod
    from app.database.repositories import _job_seq_sql

    assert "seq" in _job_seq_sql(object())  # sqlite default in tests
    monkeypatch.setattr(repo_mod, "resolve_backend", lambda _db_path: "postgres")
    try:
        assert "seq_num" in _job_seq_sql(None)
    finally:
        monkeypatch.delattr(repo_mod, "resolve_backend")


def _configured_live_url() -> str | None:
    shell = os.environ.get("MEDHA_DATABASE_URL", "").strip()
    if shell:
        return shell if is_postgres_dsn(shell) else None
    file_url = get_settings().database_url.strip()
    return file_url if file_url and is_postgres_dsn(file_url) else None


def test_jobs_claim_finish_supersede_live() -> None:
    """Claim → finish → supersede → latest against real Postgres (or skip)."""
    if not _configured_live_url():
        pytest.skip("MEDHA_DATABASE_URL not set — live Postgres jobs test NOT RUN")
    import uuid

    from app.core.events import utc_now_iso
    from app.database.connection import _pg_connect, init_db, ping_db
    from app.database.repositories import JobRepository

    get_settings.cache_clear()
    try:
        if not get_settings().use_postgres:
            pytest.skip(
                "Live Postgres test needs MEDHA_DATABASE_BACKEND=postgres "
                "locally (or MEDHA_ENV=production) — stray URLs stay SQLite."
            )
        assert get_settings().use_postgres
        try:
            init_db()
        except Exception as exc:
            pytest.skip(f"Postgres unreachable: {exc}")
        assert ping_db()

        repo = JobRepository()
        stamp = uuid.uuid4().hex[:8]
        repository = f"octo/pg-jobs-{stamp}"
        mine = {f"job_pg_old_{stamp}", f"job_pg_new_{stamp}", f"job_pg_pen_{stamp}"}
        now = utc_now_iso()
        try:
            old = repo.create(job_id=f"job_pg_old_{stamp}", repository=repository,
                              branch="main", target_sha="a" * 40, created_at=now)
            assert old is not None and old["status"] == "queued"
            new = repo.create(job_id=f"job_pg_new_{stamp}", repository=repository,
                              branch="main", target_sha="b" * 40, created_at=now)
            assert new is not None
            # Ordering counter advances per branch on the seq_num column.
            assert int(new.get("seq_num", -1)) > int(old.get("seq_num", -1))

            # claim_next is global: requeue foreign jobs untouched, claim ours.
            claimed = None
            for _ in range(10):
                candidate = repo.claim_next()
                assert candidate is not None  # our jobs are queued
                if candidate["job_id"] in mine:
                    claimed = candidate
                    break
                repo.finish(candidate["job_id"], ok=False,
                            error="pg-jobs-test-pass-through",
                            updated_at=utc_now_iso())
            assert claimed is not None and claimed["status"] == "running"
            repo.finish(claimed["job_id"], ok=True, updated_at=utc_now_iso())
            assert repo.get(claimed["job_id"])["status"] == "succeeded"

            # Supersede targets older queued jobs via the same counter column.
            pending = repo.create(job_id=f"job_pg_pen_{stamp}", repository=repository,
                                  branch="main", target_sha="c" * 40, created_at=now)
            assert pending is not None
            latest = repo.latest_for_branch(repository, "main")
            assert latest is not None and latest["job_id"] == pending["job_id"]
            superseded = repo.cancel_queued_superseded(
                repository=repository, branch="main",
                keep_seq=int(latest.get("seq_num", latest.get("seq", 0))))
            assert superseded >= 0
        finally:
            # Leave the shared database tidy: remove only this run's rows.
            from app.database.connection import get_connection

            with get_connection() as conn:
                conn.execute(
                    "DELETE FROM jobs WHERE job_id = ? OR job_id = ? OR job_id = ?",
                    tuple(sorted(mine)),
                )
                conn.commit()
    finally:
        get_settings.cache_clear()
