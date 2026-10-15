"""Startup recovery: orphaned work fails closed, READY work is preserved."""

from __future__ import annotations

from app.core.config import get_settings
from app.core.enums import DeploymentStatus, DeployMode
from app.core.events import utc_now_iso
from app.database.connection import init_db
from app.database.repositories import DeploymentRepository, ProposalRepository
from app.models.deployment import DeploymentRecord, ProposalRecord
from app.services.recovery import reconcile_interrupted


def _record(deployment_id, status, **overrides):
    now = utc_now_iso()
    base = {
        "deployment_id": deployment_id,
        "repository_url": "https://github.com/example/app",
        "mode": DeployMode.REAL,
        "scenario": None,
        "target_host": "localhost",
        "target_port": 8080,
        "intent": "test",
        "status": status,
        "current_stage": "VERIFY",
        "created_at": now,
        "updated_at": now,
        "is_demo": False,
    }
    base.update(overrides)
    return DeploymentRecord(**base)


def _proposal(proposal_id, status, deployment_id=None):
    now = utc_now_iso()
    return ProposalRecord(
        proposal_id=proposal_id,
        repository="octo/demo",
        branch="main",
        base_sha=None,
        target_sha="a" * 40,
        deployment_id=deployment_id,
        status=status,
        created_by="webhook:github",
        created_at=now,
        idempotency_key=f"test:{proposal_id}",
    )


def _seeded_db(tmp_path, monkeypatch):
    db_path = tmp_path / "recovery.db"
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    get_settings.cache_clear()
    init_db(db_path)
    return db_path


def test_reconcile_fails_orphans_and_preserves_ready(tmp_path, monkeypatch):
    db_path = _seeded_db(tmp_path, monkeypatch)
    repo = DeploymentRepository(db_path)
    proposals = ProposalRepository(db_path)
    repo.create(_record("dep_running", DeploymentStatus.RUNNING))
    repo.create(_record("dep_started", DeploymentStatus.STARTED))
    repo.create(_record("dep_waiting", DeploymentStatus.AWAITING_APPROVAL))
    repo.create(_record("dep_done", DeploymentStatus.COMPLETED))
    proposals.create(_proposal("prp_analyzing", "analyzing", "dep_running"))
    proposals.create(_proposal("prp_ready", "ready", "dep_waiting"))
    proposals.create(_proposal("prp_executing", "executing", "dep_running"))

    result = reconcile_interrupted(db_path)
    assert result["deployments"] == 2
    assert result["proposals"] == 2
    assert result["events"] == 2

    assert repo.get("dep_running").status == DeploymentStatus.FAILED
    assert "restart" in (repo.get("dep_running").error_summary or "")
    assert repo.get("dep_started").status == DeploymentStatus.FAILED
    # Stable wait state preserved with its plan intact.
    assert repo.get("dep_waiting").status == DeploymentStatus.AWAITING_APPROVAL
    assert repo.get("dep_done").status == DeploymentStatus.COMPLETED
    assert proposals.get("prp_analyzing").status == "failed"
    assert proposals.get("prp_executing").status == "failed"
    assert proposals.get("prp_ready").status == "ready"
    # Terminal recovery event recorded for each orphaned run.
    assert any(e.event_type == "deployment.failed" for e in repo.list_events("dep_running"))
    get_settings.cache_clear()


def test_reconcile_is_idempotent(tmp_path, monkeypatch):
    db_path = _seeded_db(tmp_path, monkeypatch)
    repo = DeploymentRepository(db_path)
    repo.create(_record("dep_running", DeploymentStatus.RUNNING))
    first = reconcile_interrupted(db_path)
    assert first["deployments"] == 1
    second = reconcile_interrupted(db_path)
    # Core reconciliation is a no-op the second time. Housekeeping keys
    # (stale-workspace prune, container observation) may vary with host
    # state and are asserted separately.
    assert second["deployments"] == 0
    assert second["proposals"] == 0
    assert second["events"] == 0
    get_settings.cache_clear()


def test_duplicate_delivery_still_idempotent_after_restart(tmp_path, monkeypatch):
    db_path = _seeded_db(tmp_path, monkeypatch)
    proposals = ProposalRepository(db_path)
    now = utc_now_iso()
    assert proposals.record_delivery(
        delivery_id="del_1", repository="octo/demo", ref="refs/heads/main",
        sha="a" * 40, event="push", status="received", received_at=now,
    ) is True
    reconcile_interrupted(db_path)
    # Same delivery ID can never create a second run, even after recovery.
    assert proposals.record_delivery(
        delivery_id="del_1", repository="octo/demo", ref="refs/heads/main",
        sha="a" * 40, event="push", status="received", received_at=now,
    ) is False
    get_settings.cache_clear()
