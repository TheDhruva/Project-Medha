"""Durable job lifecycle: the worker owns webhook-triggered analysis.

Regression coverage for the reported defect where a job was marked succeeded
without owning the analysis. Here the worker runs the (faked) planning
pipeline and settles the job from the real deployment outcome. No network,
no Docker: the pipeline is replaced with a deterministic stand-in that mutates
the same deployment record the real pipeline would.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.enums import DeploymentStatus, DeployMode
from app.core.events import utc_now_iso
from app.database.connection import init_db
from app.database.repositories import (
    DeploymentRepository,
    JobRepository,
    ProjectRepository,
    ProposalRepository,
)
from app.main import create_app
from app.models.deployment import DeploymentRecord, ProposalRecord

SHA = "a" * 40
SECRET = "whsec_job_lifecycle"


def _seed(tmp_path, *, terminal: DeploymentStatus | None = None):
    db = tmp_path / "jobs.db"
    init_db(db)
    now = utc_now_iso()
    dep = DeploymentRepository(db_path=db)
    dep.create(DeploymentRecord(
        deployment_id="dep_1", repository_url="https://github.com/octo/demo.git",
        mode=DeployMode.REAL, scenario=None, target_host="localhost",
        target_port=8080, intent="push", base_revision="b" * 40,
        target_revision=SHA, status=terminal or DeploymentStatus.STARTED,
        current_stage=None, created_at=now, updated_at=now, is_demo=False,
        error_summary="analysis blew up" if terminal == DeploymentStatus.FAILED else None,
    ))
    ProposalRepository(db_path=db).create(ProposalRecord(
        proposal_id="prp_1", repository="octo/demo", branch="main",
        base_sha="b" * 40, target_sha=SHA, deployment_id="dep_1",
        status="analyzing", created_by="webhook:github", created_at=now,
        idempotency_key="github:del_1:prp_1",
    ))
    JobRepository(db_path=db).create(
        job_id="job_1", repository="octo/demo", branch="main",
        target_sha=SHA, base_sha="b" * 40, delivery_id="del_1",
        deployment_id="dep_1", created_at=now,
    )
    return db


def _fake_pipeline(repo_status: DeploymentStatus):
    class _Fake:
        calls: list[tuple[str, bool]] = []

        def __init__(self, repo=None):
            self.repo = repo

        async def run(self, deployment_id, *, plan_only=False, proposal_id=None,
                      expected_plan_hash=None):
            _Fake.calls.append((deployment_id, plan_only))
            self.repo.update_status(
                deployment_id, status=repo_status, updated_at=utc_now_iso(),
                error_summary="boom" if repo_status == DeploymentStatus.FAILED else None,
            )

    return _Fake


def _run_worker(job: dict, db):
    from app.jobs.worker import _process_one

    asyncio.run(_process_one(job, db_path=db))


def test_job_succeeds_only_after_analysis(tmp_path, monkeypatch):
    import app.workflow.planning as planning

    db = _seed(tmp_path)
    fake = _fake_pipeline(DeploymentStatus.AWAITING_APPROVAL)
    fake.calls.clear()
    monkeypatch.setattr(planning, "PlanningPipeline", fake)

    jobs = JobRepository(db_path=db)
    claimed = jobs.claim_next()
    assert claimed is not None
    _run_worker(claimed, db)

    assert jobs.get("job_1")["status"] == "succeeded"
    assert fake.calls == [("dep_1", True)]  # exactly one plan-only analysis
    proposal = ProposalRepository(db_path=db).get("prp_1")
    assert proposal is not None and proposal.status == "ready"


def test_job_failure_is_not_reported_success(tmp_path, monkeypatch):
    import app.workflow.planning as planning

    db = _seed(tmp_path)
    monkeypatch.setattr(
        planning, "PlanningPipeline", _fake_pipeline(DeploymentStatus.FAILED)
    )
    jobs = JobRepository(db_path=db)
    _run_worker(jobs.claim_next(), db)

    row = jobs.get("job_1")
    assert row["status"] != "succeeded"
    assert row["last_error"]
    assert ProposalRepository(db_path=db).get("prp_1").status == "failed"


def test_job_exception_leaves_job_unfinished(tmp_path, monkeypatch):
    import app.workflow.planning as planning

    db = _seed(tmp_path)

    class _Boom:
        def __init__(self, repo=None):
            pass

        async def run(self, *args, **kwargs):
            raise RuntimeError("pipeline exploded")

    monkeypatch.setattr(planning, "PlanningPipeline", _Boom)
    jobs = JobRepository(db_path=db)
    _run_worker(jobs.claim_next(), db)

    row = jobs.get("job_1")
    assert row["status"] != "succeeded"
    assert row["last_error"] == "RuntimeError"


def test_interrupted_job_is_recovered(tmp_path):
    db = _seed(tmp_path)
    jobs = JobRepository(db_path=db)
    claimed = jobs.claim_next()
    assert claimed["status"] == "running"

    recovered = jobs.recover_interrupted(updated_at=utc_now_iso(), error="worker-restart")
    assert recovered == 1
    assert jobs.get("job_1")["status"] == "queued"


def test_concurrent_claim_single_winner(tmp_path):
    db = _seed(tmp_path)
    jobs = JobRepository(db_path=db)
    first = jobs.claim_next()
    second = jobs.claim_next()
    assert first is not None and first["status"] == "running"
    assert second is None


def test_duplicate_delivery_enqueues_one_job(tmp_path):
    db = _seed(tmp_path)
    from app.jobs.worker import enqueue_job

    jobs = JobRepository(db_path=db)
    jobs.finish("job_1", ok=True, updated_at=utc_now_iso())
    extra = enqueue_job(
        repository="octo/demo", branch="main", target_sha="c" * 40,
        delivery_id="del_1", deployment_id="dep_2", db_path=db,
    )
    assert extra is None  # same delivery id → no second job


def test_analysis_already_done_is_not_rerun(tmp_path, monkeypatch):
    import app.workflow.planning as planning

    db = _seed(tmp_path, terminal=DeploymentStatus.AWAITING_APPROVAL)
    fake = _fake_pipeline(DeploymentStatus.AWAITING_APPROVAL)
    fake.calls.clear()
    monkeypatch.setattr(planning, "PlanningPipeline", fake)
    jobs = JobRepository(db_path=db)
    _run_worker(jobs.claim_next(), db)

    assert jobs.get("job_1")["status"] == "succeeded"
    assert fake.calls == []  # idempotent: no second analysis


# --- webhook → durable job integration ---------------------------------------


def _signed(body: dict, *, delivery: str) -> dict:
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return {
        "content": raw,
        "headers": {
            "x-hub-signature-256": sig,
            "x-github-delivery": delivery,
            "x-github-event": "push",
            "content-type": "application/json",
        },
    }


def test_webhook_enqueues_durable_job(tmp_path, monkeypatch):
    import app.workflow.planning as planning

    db = tmp_path / "wh.db"
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("MEDHA_WEBHOOK_ALLOWED_REPOS", "octo/demo")
    monkeypatch.setenv("MEDHA_WEBHOOK_BRANCHES", "main")
    get_settings.cache_clear()
    init_db(db)

    fake = _fake_pipeline(DeploymentStatus.AWAITING_APPROVAL)
    fake.calls.clear()
    monkeypatch.setattr(planning, "PlanningPipeline", fake)
    try:
        with TestClient(create_app()) as client:
            created = client.post(
                "/api/projects", json={"name": "P", "repository": "octo/demo", "branch": "main"}
            )
            project_id = created.json()["project_id"]
            ProjectRepository().update(
                project_id, connection_status="connected", visibility="public",
                updated_at=utc_now_iso(),
            )
            body = {
                "repository": {"full_name": "octo/demo"},
                "ref": "refs/heads/main", "after": SHA, "before": "b" * 40,
                "commits": [{"id": SHA, "message": "x", "added": ["app.py"],
                             "removed": [], "modified": []}],
            }
            resp = client.post("/api/webhooks/github", **_signed(body, delivery="del-job"))
            assert resp.status_code == 202, resp.text
            proposal_id = resp.json()["proposal_id"]

            latest = JobRepository(db_path=db).latest_for_branch("octo/demo", "main")
            assert latest is not None
            assert latest["target_sha"] == SHA

            deadline = time.time() + 10.0
            while time.time() < deadline:
                if ProposalRepository(db_path=db).get(proposal_id).status == "ready":
                    break
                time.sleep(0.1)
            assert ProposalRepository(db_path=db).get(proposal_id).status == "ready"
            assert len(fake.calls) == 1
    finally:
        get_settings.cache_clear()
