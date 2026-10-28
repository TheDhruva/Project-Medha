"""New-contract regression tests (Phases 4-8).

Covers: tier routing + budgets, inputs hashing, durable jobs, versioned
scores (+API/history), real git history service, webhook SHA strictness,
and v8 schema migration. All local; live GitHub/Docker never required.
"""

from __future__ import annotations

import shutil
import subprocess
import time

import pytest


# --- Tier routing ------------------------------------------------------------

def test_tier_doc_only_zero_llm():
    from app.changeintel.tiers import TIER_BUDGETS, route

    decision = route(["README.md", "docs/guide.md"])
    assert decision.tier == 1
    assert decision.llm_budget == 0
    assert TIER_BUDGETS[1] == 0


def test_tier_lockfile_triggers_dependency_rescan():
    from app.changeintel.tiers import route

    decision = route(["package-lock.json"])
    assert decision.tier == 2
    assert decision.reason == "dependency-manifest-change"


def test_tier_auth_expands():
    from app.changeintel.tiers import route

    decision = route(["backend/app/auth.py"])
    assert decision.tier == 3
    assert "auth" in decision.reason


def test_tier_uncertain_expands():
    from app.changeintel.tiers import route

    decision = route(["src/shared/util.py"], risk_level="high", blast_radius=8)
    assert decision.tier == 3


def test_tier_deploy_config_expands():
    from app.changeintel.tiers import route

    decision = route(["Dockerfile"])
    assert decision.tier == 3
    assert "deployment" in decision.reason


def test_inputs_hash_stable_and_sensitive():
    from app.changeintel.tiers import inputs_hash

    kwargs = dict(base_sha="a" * 40, target_sha="b" * 40,
                  file_hashes={"x.py": "00" * 32},
                  tool_version="changeintel-v1", config={})
    assert inputs_hash(**kwargs) == inputs_hash(**kwargs)
    changed = dict(kwargs, target_sha="c" * 40)
    assert inputs_hash(**changed) != inputs_hash(**kwargs)


# --- Durable jobs ------------------------------------------------------------

def test_jobs_idempotent_claim_finish(tmp_path):
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import JobRepository

    db = tmp_path / "jobs.db"
    init_db(db)
    repo = JobRepository(db_path=db)
    now = utc_now_iso()
    job = repo.create(job_id="job_1", repository="octo/app", branch="main",
                      target_sha="a" * 40, delivery_id="del_1", created_at=now)
    assert job is not None and job["status"] == "queued"
    dup = repo.create(job_id="job_2", repository="octo/app", branch="main",
                      target_sha="a" * 40, delivery_id="del_1", created_at=now)
    assert dup is None  # duplicate delivery → one job
    claimed = repo.claim_next()
    assert claimed is not None and claimed["status"] == "running"
    repo.finish(claimed["job_id"], ok=True, updated_at=utc_now_iso())
    assert repo.get(claimed["job_id"])["status"] == "succeeded"


def test_jobs_retry_then_dead_letter(tmp_path):
    import sqlite3

    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import JobRepository

    db = tmp_path / "jobs2.db"
    init_db(db)
    repo = JobRepository(db_path=db)
    repo.create(job_id="job_r", repository="octo/app", branch="main",
                target_sha="b" * 40, created_at=utc_now_iso())
    claimed = repo.claim_next()
    assert claimed is not None
    # Failed attempt requeues with exponential backoff (not_before set).
    repo.finish(claimed["job_id"], ok=False, error="boom",
                updated_at=utc_now_iso())
    row = repo.get("job_r")
    assert row["status"] == "queued"
    assert row["last_error"] == "boom"
    assert row["not_before"] is not None
    # Backoff expiry makes the job claimable again; exhausting max attempts
    # moves it to dead_letter instead of retrying forever.
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE jobs SET not_before=NULL, attempts=3 WHERE job_id='job_r'")
        conn.commit()
    claimed = repo.claim_next()
    assert claimed is not None
    repo.finish(claimed["job_id"], ok=False, error="boom",
                updated_at=utc_now_iso())
    assert repo.get("job_r")["status"] == "dead_letter"


def test_jobs_supersede_and_recovery(tmp_path):
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import JobRepository

    db = tmp_path / "jobs3.db"
    init_db(db)
    repo = JobRepository(db_path=db)
    now = utc_now_iso()
    repo.create(job_id="job_old", repository="octo/app", branch="main",
                target_sha="a" * 40, created_at=now)
    new = repo.create(job_id="job_new", repository="octo/app", branch="main",
                      target_sha="b" * 40, created_at=now)
    assert new is not None
    superseded = repo.cancel_queued_superseded(
        repository="octo/app", branch="main", keep_seq=int(new["seq"]))
    assert superseded >= 1
    assert repo.get("job_old")["status"] == "superseded"
    # Interrupted running jobs requeue on restart.
    repo.create(job_id="job_run", repository="octo/app", branch="dev",
                target_sha="c" * 40, created_at=now)
    running = repo.claim_next()
    assert running is not None
    recovered = repo.recover_interrupted(updated_at=utc_now_iso(), error="restart")
    assert recovered >= 1


def test_webhook_short_sha_ignored(client, monkeypatch):
    import hashlib
    import hmac
    import json as _json

    from app.core.config import get_settings

    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "s3cret")
    monkeypatch.setenv("MEDHA_WEBHOOK_ALLOWED_REPOS", "octo/app")
    get_settings.cache_clear()
    try:
        payload = {"ref": "refs/heads/main", "after": "abc1234",
                   "before": "b" * 40, "repository": {"full_name": "octo/app"},
                   "deleted": False}
        body = _json.dumps(payload).encode()
        sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
        r = client.post("/api/webhooks/github", content=body,
                        headers={"X-Hub-Signature-256": sig,
                                 "X-GitHub-Event": "push",
                                 "X-GitHub-Delivery": "del-short-sha",
                                 "Content-Type": "application/json"})
        assert r.json()["status"] == "ignored"
    finally:
        get_settings.cache_clear()


# --- Scores ------------------------------------------------------------------

def test_scores_deterministic_and_missing_is_none():
    from app.scores.compute import VERSION, compute_all

    assert VERSION == "scores-v4"
    kwargs = dict(verification={"checks": []}, critic=None, change_intel=None)
    first = compute_all(**kwargs)
    second = compute_all(**kwargs)
    assert first == second
    assert first["code_quality"]["value"] is None
    assert first["deployment_readiness"]["value"] is None
    assert first["security"]["value"] is None
    assert first["verification_confidence"]["value"] is None


def test_scores_security_cap_on_secret_finding():
    from app.scores.compute import compute_all

    out = compute_all(
        verification={"checks": []}, critic=None, change_intel=None,
        repository_analysis={
            "analysis_status": "completed",
            "applications": [{"path": "."}],
            "findings": [{"scanner": "gitleaks", "severity": "high",
                          "rule_id": "secret", "path": "a", "line": 1,
                          "message": "secret detected"}],
            "scanners": [{"name": "gitleaks", "status": "completed_with_findings"}],
        },
    )
    assert out["security"]["value"] is not None
    assert out["security"]["value"] <= 30


def test_scores_api_and_history(client):
    from tests.conftest import _deploy_payload

    created = client.post("/api/deploy", json=_deploy_payload()).json()
    dep_id = created["deployment_id"]
    deadline = time.time() + 60.0
    while time.time() < deadline:
        status = client.get(f"/api/deploy/{dep_id}").json()["status"]
        if status in {"completed", "failed", "partial_recovery"}:
            break
        time.sleep(0.05)
    r = client.get(f"/api/deploy/{dep_id}/scores")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body["scores"]) == {
        "code_quality", "security", "verification_confidence",
        "deployment_readiness", "performance", "optimization",
    }
    for entry in body["scores"].values():
        assert entry["version"] == "scores-v4"
        assert entry["computed_at"]
        assert entry["inputs_hash"]
    for name in ("code_quality", "security", "verification_confidence",
                 "deployment_readiness"):
        evidence = body["scores"][name]["evidence"]
        assert "checks" in evidence and "coverage" in evidence
    r2 = client.get("/api/scores/history", params={"run_id": dep_id})
    assert r2.status_code == 200 and r2.json()["total"] == 6
    # Reproducible: the stored snapshot is reused while inputs are unchanged.
    r3 = client.get(f"/api/deploy/{dep_id}/scores")
    assert r3.json()["scores"] == body["scores"]


# --- Real git history --------------------------------------------------------

def _git_available() -> bool:
    return shutil.which("git") is not None


@pytest.mark.skipif(not _git_available(), reason="git executable not available")
def test_history_service_matches_git(tmp_path):
    from app.services import history_service

    repo = tmp_path / "hist"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.txt").write_text("one", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "first"], cwd=repo, check=True,
                   capture_output=True)
    (repo / "b.txt").write_text("two", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "second"], cwd=repo, check=True,
                   capture_output=True)
    entries, partial = history_service.list_history(repo, limit=10)
    assert partial is False
    assert len(entries) == 2
    assert entries[0].parents == [entries[1].sha]
    assert entries[1].parents == []
    assert entries[0].message == "second"
    summary = history_service.changed_files_summary(repo, entries[0].sha)
    assert summary["files"] and summary["files"][0]["path"] == "b.txt"
    with pytest.raises(history_service.HistoryError):
        history_service.changed_files_summary(repo, "short")


# --- Schema migration --------------------------------------------------------

def test_v8_tables_exist_on_fresh_db(tmp_path):
    import sqlite3

    from app.database.connection import _SCHEMA_VERSION, init_db

    assert _SCHEMA_VERSION >= 8
    db = tmp_path / "v8.db"
    init_db(db)
    with sqlite3.connect(db) as conn:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "commits", "scores", "analysis_cache"} <= tables
