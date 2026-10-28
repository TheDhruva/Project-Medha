"""Continuous analysis workflow (acceptance 1, 2, 3, 4, 7, 8, 10 e2e).

First assessment + baseline persistence, push updates, finding lifecycle
across commits (introduced → confirmed → fix not auto-resolved), webhook
duplicate/PR handling, reuse of an already-assessed commit, out-of-order
finding observations, and the worker's merge-decision publication for PRs.

Pipeline tests run the real ``PlanningPipeline`` against a local git
repository; webhook tests drive the signed HTTP receiver.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.events import utc_now_iso
from app.database.connection import init_db
from app.database.repositories import (
    DeploymentRepository,
    FindingRepository,
    ProjectRepository,
    ProposalRepository,
    PullRequestRepository,
)
from app.main import create_app
from app.models.deployment import DeploymentRecord, ProjectRecord

SECRET = "whsec_continuous"


# -- git helpers ---------------------------------------------------------------

def _git(cwd: Path, *args: str) -> str:
    res = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )
    return res.stdout.strip()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(src: Path, message: str) -> str:
    _git(src, "add", "-A")
    _git(src, "commit", "-m", message, "--allow-empty")
    return _git(src, "rev-parse", "HEAD").lower()


def _init_repo(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    src = tmp_path / "repo"
    src.mkdir()
    _git(src, "init", "-b", "main")
    _git(src, "config", "user.email", "t@t.t")
    _git(src, "config", "user.name", "t")
    for rel, text in files.items():
        _write(src / rel, text)
    return src, _commit(src, "initial app")


# -- pipeline environment ------------------------------------------------------

@pytest.fixture()
def pipeline_env(tmp_path, monkeypatch):
    """Deterministic scanners: every external scanner is unavailable, so
    coverage is honestly 'none' on any machine."""
    from app.security import scanners as sc

    # Isolated-test declaration (never a production default): plan-only runs
    # never execute containers, so the host daemon must not gate them.
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "false")
    get_settings.cache_clear()
    monkeypatch.setattr(
        sc, "supported_scanners", lambda: ["gitleaks", "semgrep", "trivy"]
    )
    monkeypatch.setattr(
        sc, "run_scanner",
        lambda name, target, timeout_s=0.0: sc.ScannerResult(
            scanner=name, status=sc.UNAVAILABLE, message="not installed (test)"
        ),
    )
    db = tmp_path / "continuous.db"
    init_db(db)
    now = utc_now_iso()
    ProjectRepository(db_path=db).create(ProjectRecord(
        project_id="prj_ca", owner_sub="local-operator", name="app",
        provider="github", repo_owner="o", repo_name="app",
        repository="o/app", canonical_url="https://github.com/o/app.git",
        branch="main", visibility="unverified", connection_status="pending",
        created_at=now, updated_at=now,
    ))
    return db


def _assess(db: Path, src: Path, *, deployment_id: str, target: str,
            base: str | None = None) -> DeploymentRecord:
    from app.workflow.planning import PlanningPipeline

    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id=deployment_id, repository_url=str(src),
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=base, target_revision=target,
        status="started", current_stage=None, project_id="prj_ca",
        created_at=now, updated_at=now, is_demo=False,
    ))
    asyncio.run(PlanningPipeline(repo=repo).run(deployment_id, plan_only=True))
    record = repo.get(deployment_id)
    assert record is not None
    return record


def _analysis_of(record: DeploymentRecord) -> dict:
    result = record.result if isinstance(record.result, dict) else {}
    analysis = result.get("repository_analysis")
    assert isinstance(analysis, dict), f"no analysis on {record.deployment_id}"
    return analysis


# -- acceptance 1: first assessment + baseline --------------------------------

def test_first_assessment_persists_baseline_and_coverage(pipeline_env, tmp_path):
    db = pipeline_env
    src, head = _init_repo(tmp_path, {
        "package.json": '{"scripts": {"start": "node server.js"}}',
        "server.js": "console.log(1)",
    })

    record = _assess(db, src, deployment_id="dep_ca1", target=head)
    analysis = _analysis_of(record)

    assert analysis["analysis_status"] == "completed"
    assert analysis["commit_sha"] == head
    coverage = analysis["coverage"]
    assert coverage["security_scan"] == "none"
    assert any("no external security scanner executed" in g
               for g in coverage["gaps"])

    project = ProjectRepository(db_path=db).get("prj_ca")
    assert project is not None
    assert project.baseline_sha == head          # baseline recorded once
    assert project.baseline_at
    # No scanner actually completed → the rescan clock must NOT advance.
    assert project.last_full_scan_at is None


# -- acceptance 2: push modifies a file ---------------------------------------

def test_push_to_new_commit_adopts_new_assessment_keeps_baseline(
    pipeline_env, tmp_path
):
    db = pipeline_env
    src, head1 = _init_repo(tmp_path, {
        "package.json": '{"scripts": {"start": "node server.js"}}',
        "server.js": "console.log(1)",
    })
    _assess(db, src, deployment_id="dep_ca_a", target=head1)

    _write(src / "server.js", "console.log('changed')")
    head2 = _commit(src, "modify server")
    record2 = _assess(db, src, deployment_id="dep_ca_b", target=head2,
                      base=head1)
    analysis2 = _analysis_of(record2)

    assert record2.target_revision == head2
    assert record2.base_revision == head1
    assert analysis2["commit_sha"] == head2
    assert analysis2["analysis_status"] == "completed"

    project = ProjectRepository(db_path=db).get("prj_ca")
    assert project.baseline_sha == head1   # baseline never regresses


# -- acceptance 3 + 4: finding introduced, then fixed --------------------------

def test_new_finding_is_detected_and_fix_is_not_auto_resolved(
    pipeline_env, tmp_path
):
    db = pipeline_env
    src, head1 = _init_repo(tmp_path, {
        "app.py": "def handler():\n    return 1\n",
    })
    _assess(db, src, deployment_id="dep_ca_f1", target=head1)
    assert FindingRepository(db_path=db).list(project_id="prj_ca") == []

    # Commit 2 introduces a builtin-detectable condition (SEC-101).
    _write(src / "app.py", "import subprocess\n\ndef handler():\n"
                           "    subprocess.run('ls', shell=True)\n")
    head2 = _commit(src, "use shell")
    record2 = _assess(db, src, deployment_id="dep_ca_f2", target=head2,
                      base=head1)
    assert _analysis_of(record2)["finding_count"] >= 1

    findings = FindingRepository(db_path=db).list(project_id="prj_ca")
    assert len(findings) == 1
    finding = findings[0]
    assert finding["rule_id"] == "SEC-101"
    assert finding["status"] == "detected"
    assert finding["first_seen_sha"] == head2     # new at this commit

    # Confirm it (evidence required by the state machine).
    from app.mergepolicy import evaluate_merge_readiness

    confirmed = FindingRepository(db_path=db).transition(
        finding["finding_id"], "confirmed",
        reason="reproduced at head", at=utc_now_iso(),
        evidence=[{"commit": head2, "why": "shell=True present"}],
        deployment_id="dep_ca_f2",
    )
    assert confirmed["status"] == "confirmed"

    # Merge decision at head2: blocked by the mandatory rule (new finding),
    # with security coverage honestly reported as absent too.
    decision = evaluate_merge_readiness("prj_ca", head_sha=head2, db_path=db)
    assert decision["outcome"] == "blocked"
    assert any(r["code"] == "blocking_finding" for r in decision["reasons"])
    assert decision["blocking_findings"][0]["rule_id"] == "SEC-101"

    # Commit 3 fixes the condition: the re-scan must mark it fixed but NOT
    # resolved — disappearance without fix verification is not resolution.
    _write(src / "app.py", "def handler():\n    return 2\n")
    head3 = _commit(src, "fix shell")
    _assess(db, src, deployment_id="dep_ca_f3", target=head3, base=head2)

    after = FindingRepository(db_path=db).get(finding["finding_id"])
    assert after is not None
    assert after["status"] == "fixed_unverified"
    assert after["first_seen_sha"] == head2       # identity is preserved
    assert after["last_seen_sha"] == head2        # absence is not an observation

    decision3 = evaluate_merge_readiness("prj_ca", head_sha=head3, db_path=db)
    assert decision3["blocking_findings"] == []
    # The fix clears the blocker, but without security coverage MEDHA must
    # never report the merge as ready.
    assert decision3["outcome"] == "assessment_incomplete"


# -- acceptance 8 (ledger): out-of-order observations -------------------------

def test_out_of_order_scan_never_regresses_finding(tmp_path):
    db = tmp_path / "ooo.db"
    init_db(db)
    ledger = FindingRepository(db_path=db)
    item = {
        "source": "builtin", "rule_id": "SEC-101", "path": "app.py",
        "severity": "high", "message": "shell=True", "category": "security",
    }
    t_new = "2026-10-02T00:00:00+00:00"
    t_old = "2026-10-01T00:00:00+00:00"

    # Newer observation lands first (fast job for the newest commit).
    ledger.sync_scan(
        project_id="prj_ooo", repository="o/r", deployment_id="dep_new",
        commit_sha="a" * 40, findings=[item], active_sources={"builtin"},
        scanned_at=t_new,
    )
    finding_id = ledger.list(project_id="prj_ooo")[0]["finding_id"]

    # A delayed job for an older commit finishes afterwards: its silence
    # about this finding is not evidence of a fix, and its observation of
    # the finding is stale evidence that cannot regress last-seen state.
    stale = ledger.sync_scan(
        project_id="prj_ooo", repository="o/r", deployment_id="dep_old",
        commit_sha="b" * 40, findings=[], active_sources={"builtin"},
        scanned_at=t_old,
    )
    row = ledger.get(finding_id)
    assert row["status"] == "detected"           # NOT marked absent/fixed
    assert row["last_seen_sha"] == "a" * 40
    assert stale["marked_absent"] == 0

    # Stale re-observation cannot reopen a resolved finding either.
    ledger.transition(
        finding_id, "under_investigation", reason="triage",
        at=utc_now_iso(), evidence=[{"step": "1"}],
    )
    ledger.transition(
        finding_id, "confirmed", reason="still present at a*40",
        at=utc_now_iso(), evidence=[{"commit": "a" * 40}],
    )
    ledger.transition(
        finding_id, "resolved", reason="verified fixed at a*40",
        at=utc_now_iso(), evidence=[{"commit": "a" * 40, "recheck": True}],
    )
    ledger.sync_scan(
        project_id="prj_ooo", repository="o/r", deployment_id="dep_old2",
        commit_sha="c" * 40, findings=[item], active_sources={"builtin"},
        scanned_at=t_old,
    )
    row = ledger.get(finding_id)
    assert row["status"] == "resolved"           # stale scan must not reopen
    assert row["last_seen_sha"] == "a" * 40


# -- webhook fixture (mirrors test_webhook_project_routing) -------------------

@pytest.fixture()
def ca_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "ca_web.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("MEDHA_WEBHOOK_ALLOWED_REPOS", "octo/demo")
    monkeypatch.setenv("MEDHA_WEBHOOK_BRANCHES", "main")
    get_settings.cache_clear()
    init_db(tmp_path / "ca_web.db")
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def _signed(body: dict, *, delivery: str, event: str = "push") -> dict:
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return {
        "content": raw,
        "headers": {
            "x-hub-signature-256": sig,
            "x-github-delivery": delivery,
            "x-github-event": event,
            "content-type": "application/json",
        },
    }


def _push(sha="a" * 40, before="b" * 40, repo="octo/demo") -> dict:
    return {
        "repository": {"full_name": repo},
        "ref": "refs/heads/main",
        "after": sha,
        "before": before,
        "commits": [{
            "id": sha, "message": "change",
            "added": [], "removed": [], "modified": ["app.py"],
        }],
    }


def _pull_request(action="opened", number=42, base_sha="b" * 40,
                  head_sha="d" * 40, head_repo="octo/demo") -> dict:
    return {
        "action": action,
        "number": number,
        "repository": {"full_name": "octo/demo"},
        "pull_request": {
            "state": "open",
            "title": "Feature",
            "base": {"ref": "main", "sha": base_sha,
                     "repo": {"full_name": "octo/demo"}},
            "head": {"ref": "feature", "sha": head_sha,
                     "repo": {"full_name": head_repo}},
        },
    }


def _connect(client, repo="octo/demo", branch="main") -> str:
    created = client.post(
        "/api/projects", json={"name": "P", "repository": repo,
                               "branch": branch}
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["project_id"]
    ProjectRepository().update(
        project_id, connection_status="connected", visibility="public",
        updated_at=utc_now_iso(),
    )
    return project_id


# -- acceptance 7: duplicate delivery -----------------------------------------

def test_duplicate_delivery_schedules_one_analysis(ca_client):
    project_id = _connect(ca_client)
    first = ca_client.post(
        "/api/webhooks/github", **_signed(_push(), delivery="del_dup1")
    )
    assert first.status_code == 202, first.text
    first_body = first.json()
    assert first_body["status"] == "analyzing"

    second = ca_client.post(
        "/api/webhooks/github", **_signed(_push(), delivery="del_dup1")
    )
    assert second.status_code == 200
    assert second.json() == {"status": "duplicate", "delivery_id": "del_dup1"}

    records, _ = DeploymentRepository().list(project_id=project_id, limit=50)
    assert len(records) == 1                       # exactly one analysis


# -- acceptance 8: pull_request analysis --------------------------------------

def test_pull_request_opened_schedules_pr_analysis(ca_client):
    project_id = _connect(ca_client)
    response = ca_client.post(
        "/api/webhooks/github",
        **_signed(_pull_request(), delivery="del_pr1",
                  event="pull_request"),
    )
    assert response.status_code == 202, response.text

    records, _ = DeploymentRepository().list(project_id=project_id, limit=50)
    assert len(records) == 1
    record = records[0]
    assert record.pr_number == 42
    assert record.base_revision == "b" * 40
    assert record.target_revision == "d" * 40

    prs = PullRequestRepository().list_for_project(project_id)
    assert len(prs) == 1
    assert prs[0]["number"] == 42
    assert prs[0]["head_sha"] == "d" * 40
    assert prs[0]["base_ref"] == "main"
    assert prs[0]["repository"] == "octo/demo"    # stored lowercased

    proposal = ProposalRepository().get(response.json()["proposal_id"])
    assert proposal is not None and proposal.push is not None
    assert proposal.push["source"] == "pull_request"


def test_pull_request_unsupported_action_ignored(ca_client):
    _connect(ca_client)
    response = ca_client.post(
        "/api/webhooks/github",
        **_signed(_pull_request(action="labeled"), delivery="del_pr2",
                  event="pull_request"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert "does not change merge state" in response.json()["reason"]


def test_pull_request_from_fork_ignored(ca_client):
    _connect(ca_client)
    response = ca_client.post(
        "/api/webhooks/github",
        **_signed(_pull_request(head_repo="forker/elsewhere"),
                  delivery="del_pr3", event="pull_request"),
    )
    assert response.status_code == 200
    assert "fork" in response.json()["reason"]
    records, _ = DeploymentRepository().list(limit=50)
    assert records == []                            # never analyzed


# -- acceptance 8: reuse of an assessed commit --------------------------------

def test_same_commit_redelivery_reuses_completed_assessment(ca_client):
    project_id = _connect(ca_client)
    now = utc_now_iso()
    repo = DeploymentRepository()
    repo.create(DeploymentRecord(
        deployment_id="dep_seed", repository_url="https://github.com/octo/demo.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision="b" * 40, target_revision="a" * 40,
        status="awaiting_approval", current_stage=None,
        project_id=project_id, created_at=now, updated_at=now, is_demo=False,
    ))
    repo.save_artifacts(
        "dep_seed",
        result={"analysis_status": "completed",
                "repository_analysis": {"analysis_status": "completed"}},
        updated_at=now,
    )
    proposals = ProposalRepository()
    from app.models.deployment import ProposalRecord

    proposals.create(ProposalRecord(
        proposal_id="prp_seed", repository="octo/demo", branch="main",
        base_sha="b" * 40, target_sha="a" * 40,
        deployment_id="dep_seed", status="ready",
        created_by="webhook:github", created_at=now,
        project_id=project_id, idempotency_key="seed:1",
    ))

    response = ca_client.post(
        "/api/webhooks/github",
        **_signed(_push(sha="a" * 40, before="b" * 40),
                  delivery="del_reuse"),
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["status"] == "reused"
    assert body["reused"] is True
    assert body["deployment_id"] == "dep_seed"

    records, _ = DeploymentRepository().list(project_id=project_id, limit=50)
    assert len(records) == 1                        # no redundant second scan

    # A different commit is still assessed anew.
    fresh = ca_client.post(
        "/api/webhooks/github",
        **_signed(_push(sha="e" * 40, before="a" * 40),
                  delivery="del_reuse2"),
    )
    assert fresh.status_code == 202
    assert fresh.json().get("reused") is None
    records, _ = DeploymentRepository().list(project_id=project_id, limit=50)
    assert len(records) == 2


def test_failed_assessment_is_never_reused(ca_client):
    project_id = _connect(ca_client)
    now = utc_now_iso()
    repo = DeploymentRepository()
    repo.create(DeploymentRecord(
        deployment_id="dep_fail", repository_url="https://github.com/octo/demo.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision="b" * 40, target_revision="a" * 40,
        status="failed", current_stage=None,
        project_id=project_id, created_at=now, updated_at=now, is_demo=False,
    ))
    from app.models.deployment import ProposalRecord

    ProposalRepository().create(ProposalRecord(
        proposal_id="prp_fail", repository="octo/demo", branch="main",
        base_sha="b" * 40, target_sha="a" * 40, deployment_id="dep_fail",
        status="ready", created_by="webhook:github", created_at=now,
        project_id=project_id, idempotency_key="fail:1",
    ))

    response = ca_client.post(
        "/api/webhooks/github",
        **_signed(_push(sha="a" * 40, before="b" * 40),
                  delivery="del_fail"),
    )
    assert response.status_code == 202
    assert response.json().get("reused") is None   # failure is re-analyzed
    records, _ = DeploymentRepository().list(project_id=project_id, limit=50)
    assert len(records) == 2


# -- worker: merge decision publication for PR runs ---------------------------

def test_pr_run_publishes_decision_status_and_event(tmp_path, monkeypatch):
    from app.jobs.worker import _publish_merge_decision

    db = tmp_path / "worker_pr.db"
    init_db(db)
    now = utc_now_iso()
    projects = ProjectRepository(db_path=db)
    projects.create(ProjectRecord(
        project_id="prj_wp", owner_sub="local-operator", name="app",
        provider="github", repo_owner="o", repo_name="app",
        repository="o/app", canonical_url="https://github.com/o/app.git",
        branch="main", visibility="unverified", connection_status="pending",
        created_at=now, updated_at=now,
    ))
    projects.update_scan_state("prj_wp", baseline_sha="b" * 40,
                               baseline_at=now, full_scan=True, at=now)
    repo = DeploymentRepository(db_path=db)
    repo.create(DeploymentRecord(
        deployment_id="dep_wp", repository_url="https://github.com/o/app.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision="b" * 40, target_revision="d" * 40,
        status="awaiting_approval", current_stage=None, project_id="prj_wp",
        pr_number=7, created_at=now, updated_at=now, is_demo=False,
    ))
    repo.save_artifacts(
        "dep_wp",
        result={
            "analysis_status": "completed",
            "repository_analysis": {
                "analysis_status": "completed",
                "coverage": {"security_scan": "complete", "scan_mode": "full"},
                "scanners": [], "finding_count": 0,
            },
        },
        verification={"checks": [
            {"id": cid, "name": cid, "status": "pass"}
            for cid in ("schema", "yaml", "compose", "security",
                        "constraints", "ports", "order", "env", "target")
        ]},
        updated_at=now,
    )
    PullRequestRepository(db_path=db).upsert(
        project_id="prj_wp", repository="o/app", number=7,
        base_ref="main", base_sha="b" * 40,
        head_ref="feature", head_sha="d" * 40,
        state="open", at=now,
    )

    published: list[tuple] = []

    def _fake_publish(repo_full, sha, decision, **kw):
        published.append((repo_full, sha, decision.get("outcome")))
        return {"published": False, "reason": "setup_required",
                "state": "failure"}

    import app.services.github_status as gs
    monkeypatch.setattr(gs, "publish_decision", _fake_publish)

    record = repo.get("dep_wp")
    assert record is not None and record.pr_number == 7
    asyncio.run(_publish_merge_decision("dep_wp", record, db_path=db))

    # Status publishing attempted once with the parsed repo and head SHA.
    assert published == [("o/app", "d" * 40, "approved")]

    pr_row = PullRequestRepository(db_path=db).get(
        project_id="prj_wp", repository="o/app", number=7
    )
    assert pr_row is not None
    decision = pr_row["decision"]
    assert decision is not None
    assert decision["outcome"] == "approved"
    assert decision["advisory"] is True
    # Honest setup requirement persisted alongside the decision.
    assert decision["github_status"]["reason"] == "setup_required"

    events = repo.list_events("dep_wp")
    merge_events = [
        e for e in events
        if (e.data or {}).get("merge_decision") is not None
    ]
    assert len(merge_events) == 1
    assert "approved" in merge_events[0].message
