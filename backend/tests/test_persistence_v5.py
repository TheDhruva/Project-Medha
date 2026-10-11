"""Schema v5 persistence: users, deliveries, proposals, ai/owner columns."""

from __future__ import annotations

import sqlite3

from app.core.enums import DeployMode, DeploymentStatus
from app.database.connection import _SCHEMA_VERSION, get_connection, init_db
from app.database.repositories import (
    AccountRepository,
    DeploymentRepository,
    ProposalRepository,
)
from app.models.deployment import DeploymentRecord, ProposalRecord
from app.core.events import utc_now_iso


def _record(**overrides) -> DeploymentRecord:
    now = utc_now_iso()
    base = {
        "deployment_id": "dep_test_v5",
        "repository_url": "https://github.com/example/app",
        "mode": DeployMode.REAL,
        "scenario": None,
        "target_host": "localhost",
        "target_port": 8080,
        "intent": "test",
        "status": DeploymentStatus.STARTED,
        "current_stage": None,
        "created_at": now,
        "updated_at": now,
        "is_demo": False,
    }
    base.update(overrides)
    return DeploymentRecord(**base)


def test_schema_v5_tables_and_columns(tmp_path, monkeypatch):
    from app.core.config import get_settings

    db_path = tmp_path / "v5.db"
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    get_settings.cache_clear()
    init_db(db_path)
    with get_connection(db_path) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"deployments", "events", "users", "webhook_deliveries", "proposals"} <= tables
        cols = {row[1] for row in conn.execute("PRAGMA table_info(deployments)")}
        assert {"ai_json", "owner_sub"} <= cols
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == _SCHEMA_VERSION
    get_settings.cache_clear()


def test_migration_heals_v4_database(tmp_path, monkeypatch):
    from app.core.config import get_settings

    db_path = tmp_path / "v4.db"
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    get_settings.cache_clear()
    with sqlite3.connect(db_path) as conn:
        # Realistic pre-v5 database: full base columns, none of the newer ones.
        conn.execute(
            "CREATE TABLE deployments (deployment_id TEXT PRIMARY KEY, repository_url TEXT,"
            " mode TEXT, scenario TEXT, target_host TEXT, target_port INTEGER, intent TEXT,"
            " base_revision TEXT, target_revision TEXT, status TEXT, current_stage TEXT,"
            " explain_simple TEXT, explain_technical TEXT, error_summary TEXT,"
            " result_json TEXT, created_at TEXT, updated_at TEXT,"
            " is_demo INTEGER DEFAULT 1)"
        )
        conn.execute("PRAGMA user_version = 3")
        conn.commit()
    init_db(db_path)
    repo = DeploymentRepository(db_path)
    repo.create(_record())
    fetched = repo.get("dep_test_v5")
    assert fetched is not None and fetched.ai is None and fetched.owner_sub is None
    get_settings.cache_clear()


def test_ai_and_owner_roundtrip(client):
    repo = DeploymentRepository()
    repo.create(_record(ai={"outcome": "degraded", "provider": "gemini"}, owner_sub="user_alice"))
    fetched = repo.get("dep_test_v5")
    assert fetched is not None
    assert fetched.ai == {"outcome": "degraded", "provider": "gemini"}
    assert fetched.owner_sub == "user_alice"
    updated = repo.save_artifacts("dep_test_v5", ai={"outcome": "ai_assisted"}, updated_at=utc_now_iso())
    assert updated is not None and updated.ai == {"outcome": "ai_assisted"}
    owned, _ = repo.list(owner_sub="user_alice")
    assert [r.deployment_id for r in owned] == ["dep_test_v5"]
    others, _ = repo.list(owner_sub="user_bob")
    assert others == []


def test_repository_filter_escapes_wildcards(client):
    repo = DeploymentRepository()
    repo.create(_record(deployment_id="dep_wild", repository_url="https://github.com/example/app100x"))
    found, _ = repo.list(repository="app_00")
    assert found == []  # '_' must not act as a wildcard
    found, _ = repo.list(repository="app100x")
    assert [r.deployment_id for r in found] == ["dep_wild"]


def test_user_upsert_and_delivery_idempotency(client):
    accounts = AccountRepository()
    now = utc_now_iso()
    accounts.upsert_user("user_alice", seen_at=now)
    accounts.upsert_user("user_alice", seen_at=now)  # idempotent
    assert accounts.get_user("user_alice") is not None
    assert accounts.get_user("nobody") is None

    proposals = ProposalRepository()
    first = proposals.record_delivery(
        delivery_id="del_1", repository="o/r", ref="refs/heads/main",
        sha="abc1234567", event="push", status="received", received_at=now,
    )
    second = proposals.record_delivery(
        delivery_id="del_1", repository="o/r", ref="refs/heads/main",
        sha="abc1234567", event="push", status="received", received_at=now,
    )
    assert first is True and second is False


def test_proposal_lifecycle_and_supersede(client):
    proposals = ProposalRepository()
    now = utc_now_iso()

    def _proposal(pid: str, sha: str) -> ProposalRecord:
        return ProposalRecord(
            proposal_id=pid, repository="o/r", branch="main", base_sha=None,
            target_sha=sha, status="ready", created_by="webhook:github",
            created_at=now, idempotency_key=f"github:{pid}",
        )

    proposals.create(_proposal("prp_old", "aaa"))
    proposals.create(_proposal("prp_new", "bbb"))
    assert proposals.supersede_older(repository="o/r", branch="main", except_proposal_id="prp_new") == 1
    assert proposals.get("prp_old") is not None and proposals.get("prp_old").status == "superseded"
    updated = proposals.update("prp_new", status="approved", decided_by="user_alice", decided_at=now)
    assert updated is not None and updated.status == "approved" and updated.decided_by == "user_alice"
    items, total = proposals.list(repository="o/r")
    assert total == 2 and len(items) == 2
