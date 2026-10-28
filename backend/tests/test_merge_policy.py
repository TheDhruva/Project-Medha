"""Deterministic merge-readiness policy (acceptance 10 + 11).

A successful scan is never a merge approval: every outcome here derives
from persisted evidence (run, analysis coverage, verification checks,
findings ledger, baseline). Decisions are advisory — nothing merges,
deploys, or mutates workflow state.
"""

from __future__ import annotations

import json

import pytest

from app.core.events import utc_now_iso
from app.database.connection import init_db
from app.database.repositories import (
    DeploymentRepository,
    FindingRepository,
    ProjectRepository,
)
from app.mergepolicy import evaluate_merge_readiness
from app.mergepolicy.engine import (
    DEFAULT_POLICY,
    evaluate,
    load_policy,
)
from app.models.deployment import DeploymentRecord, ProjectRecord

HEAD = "a" * 40
BASE = "b" * 40
BASELINE = "c" * 40
NEW = "d" * 40

_REQUIRED_IDS = (
    "schema", "yaml", "compose", "security", "constraints",
    "ports", "order", "env", "target",
)


# -- helpers -----------------------------------------------------------------

def _verification(*, fail: str | None = None, omit: str | None = None) -> dict:
    """Verification evidence with all required checks recorded as passing."""
    checks = []
    for cid in _REQUIRED_IDS:
        if omit and cid == omit:
            continue
        status = "fail" if fail and cid == fail else "pass"
        checks.append({"id": cid, "name": cid, "status": status})
    return {"checks": checks}


def _analysis(*, security_scan: str = "complete",
              analysis_status: str = "completed") -> dict:
    return {
        "analysis_status": analysis_status,
        "coverage": {"security_scan": security_scan, "scan_mode": "full"},
        "scanners": [],
        "finding_count": 0,
        "commit_sha": HEAD,
    }


def _run(**over) -> dict:
    row = {
        "deployment_id": "dep_x",
        "status": "awaiting_approval",
        "created_at": "2026-10-01T00:00:00+00:00",
        "updated_at": "2026-10-01T01:00:00+00:00",
        "error_summary": None,
        "is_demo": False,
        "target_revision": HEAD,
        "base_revision": BASE,
        "result": {"analysis_status": "completed"},
        "pr_number": 7,
    }
    row.update(over)
    return row


def _finding(**over) -> dict:
    row = {
        "finding_id": "fnd_1",
        "severity": "critical",
        "status": "confirmed",
        "source": "semgrep",
        "rule_id": "SEC-1",
        "category": "security",
        "path": "app/auth.py",
        "message": "hardcoded bypass",
        "first_seen_sha": NEW,
        "last_seen_sha": NEW,
        "verification_status": "verified",
    }
    row.update(over)
    return row


def _evaluate(**over) -> dict:
    args = dict(
        policy=dict(DEFAULT_POLICY),
        base_sha=BASE,
        head_sha=HEAD,
        baseline_sha=BASELINE,
        last_full_scan_at="2026-10-01T00:00:00+00:00",
        run=_run(),
        run_active=False,
        analysis=_analysis(),
        verification=_verification(),
        findings=[],
        generated_at="2026-10-02T00:00:00+00:00",
    )
    args.update(over)
    return evaluate(**args)


def _reason_codes(decision) -> list[str]:
    return [r["code"] for r in decision["reasons"]]


# -- unit: outcomes ----------------------------------------------------------

def test_all_green_is_approved_and_advisory():
    d = _evaluate()
    assert d["outcome"] == "approved"
    assert d["advisory"] is True
    assert d["policy_version"] == "merge-policy/v1"
    assert d["assessed"]["head_sha"] == HEAD
    assert d["assessed"]["run_id"] == "dep_x"
    assert "all_required_checks_passed" in _reason_codes(d)


def test_no_assessment_is_never_approval():
    d = _evaluate(run=None, run_active=False, verification=None)
    assert d["outcome"] == "assessment_incomplete"
    assert "no_assessment" in _reason_codes(d)
    assert any("run an assessment" in a for a in d["next_actions"])


def test_running_assessment_is_pending_not_approved():
    d = _evaluate(run=None, run_active=True)
    assert d["outcome"] == "pending"
    assert "assessment_in_progress" in _reason_codes(d)


def test_partial_analysis_is_incomplete():
    d = _evaluate(analysis=_analysis(analysis_status="partial"))
    assert d["outcome"] == "assessment_incomplete"
    assert "assessment_not_completed" in _reason_codes(d)


def test_new_confirmed_critical_finding_blocks_merge():
    d = _evaluate(findings=[_finding()])
    assert d["outcome"] == "blocked"
    assert "blocking_finding" in _reason_codes(d)
    assert d["blocking_findings"][0]["blocks_merge"] is True
    assert any("fix the blocking findings" in a for a in d["next_actions"])


def test_inherited_baseline_finding_is_reported_but_does_not_block():
    d = _evaluate(findings=[_finding(first_seen_sha=BASELINE)])
    assert d["outcome"] == "approved"
    assert len(d["inherited_findings"]) == 1
    assert d["blocking_findings"] == []


def test_inherited_finding_blocks_when_policy_says_so():
    policy = dict(DEFAULT_POLICY, block_inherited=True)
    d = _evaluate(policy=policy, findings=[_finding(first_seen_sha=BASELINE)])
    assert d["outcome"] == "blocked"


def test_accepted_risk_does_not_block_by_default():
    d = _evaluate(findings=[_finding(status="accepted_risk")])
    assert d["outcome"] == "approved"
    assert len(d["accepted_risks"]) == 1


def test_accepted_risk_blocks_when_policy_requires_it():
    policy = dict(DEFAULT_POLICY, accepted_risk_blocks=True)
    d = _evaluate(policy=policy, findings=[_finding(status="accepted_risk")])
    assert d["outcome"] == "blocked"


def test_fixed_and_resolved_findings_never_block():
    for status in ("fixed_unverified", "resolved", "rejected"):
        d = _evaluate(findings=[_finding(status=status, first_seen_sha=NEW)])
        assert d["outcome"] == "approved", status


def test_low_severity_finding_does_not_block_by_default():
    d = _evaluate(findings=[_finding(severity="medium", first_seen_sha=NEW)])
    assert d["outcome"] == "approved"


def test_failed_run_is_blocked_even_without_findings():
    d = _evaluate(run=_run(status="failed", error_summary="scanner crashed"))
    assert d["outcome"] == "blocked"
    assert "run_failed" in _reason_codes(d)


def test_failed_required_check_blocks():
    d = _evaluate(verification=_verification(fail="security"))
    assert d["outcome"] == "blocked"
    assert "required_check_failed" in _reason_codes(d)


def test_unrun_required_check_is_pending_not_approved():
    d = _evaluate(verification=_verification(omit="ports"))
    assert d["outcome"] == "pending"
    assert "required_check_not_run" in _reason_codes(d)
    assert "ports" in d["required_checks"]["not_run"]


def test_no_security_coverage_is_incomplete():
    d = _evaluate(analysis=_analysis(security_scan="none"))
    assert d["outcome"] == "assessment_incomplete"
    assert "no_security_coverage" in _reason_codes(d)
    assert any("scanner" in a for a in d["next_actions"])


def test_partial_security_coverage_is_pending_not_approved():
    d = _evaluate(analysis=_analysis(security_scan="partial"))
    assert d["outcome"] == "pending"
    assert "partial_security_scan" in _reason_codes(d)
    assert any("scanners" in a for a in d["next_actions"])


def test_never_scanned_repository_with_not_requested_coverage():
    d = _evaluate(
        analysis=_analysis(security_scan="not_requested"),
        last_full_scan_at=None,
    )
    assert d["outcome"] == "assessment_incomplete"
    assert "no_security_coverage" in _reason_codes(d)


def test_incremental_not_requested_coverage_is_info_over_last_full_scan():
    d = _evaluate(analysis=_analysis(security_scan="not_requested"))
    assert d["outcome"] == "approved"
    assert "incremental_scan_coverage" in _reason_codes(d)


def test_precedence_blocked_beats_incomplete_and_pending():
    # blocking finding AND partial analysis → blocked stays blocked.
    d = _evaluate(
        analysis=_analysis(analysis_status="partial"),
        findings=[_finding()],
    )
    assert d["outcome"] == "blocked"


def test_cancelled_run_is_incomplete():
    d = _evaluate(run=_run(status="cancelled"))
    assert d["outcome"] == "assessment_incomplete"
    assert "assessment_cancelled" in _reason_codes(d)


def test_successful_scan_alone_is_not_approval_without_verification():
    policy = dict(DEFAULT_POLICY)
    d = _evaluate(policy=policy, verification={"checks": []})
    # required checks never ran → pending, despite a completed clean scan
    assert d["outcome"] == "pending"
    assert d["required_checks"]["not_run"]


# -- unit: policy loading ----------------------------------------------------

def test_invalid_policy_json_falls_back_to_defaults():
    policy = load_policy("{not json")
    assert policy == load_policy(None)
    assert policy["block_severities"] == ["critical", "high"]


def test_policy_override_keys_apply():
    policy = load_policy(json.dumps({"block_severities": ["Critical"]}))
    assert policy["block_severities"] == ["critical"]
    assert policy["require_verification"] is True  # untouched default


# -- unit: GitHub status mapping ---------------------------------------------

def test_status_body_maps_outcomes_to_states():
    from app.services.github_status import OUTCOME_TO_STATE, decision_status_body

    assert OUTCOME_TO_STATE == {
        "approved": "success", "blocked": "failure",
        "pending": "pending", "assessment_incomplete": "error",
    }
    body = decision_status_body(_evaluate(findings=[_finding()]))
    assert body["state"] == "failure"
    assert body["context"] == "medha/merge-readiness"
    ok = decision_status_body(_evaluate())
    assert ok["state"] == "success"


def test_unconfigured_github_app_reports_setup_required(monkeypatch):
    from app.services.github_status import publish_decision

    for var in ("GITHUB_APP_ID", "GITHUB_APP_PRIVATE_KEY",
                "GITHUB_APP_INSTALLATION_ID"):
        monkeypatch.delenv(var, raising=False)
    result = publish_decision("o/r", HEAD, _evaluate())
    assert result["published"] is False
    assert result["reason"] == "setup_required"
    assert "GITHUB_APP_ID" in result["detail"]
    assert result["decision_outcome"] == "approved"


# -- integration: persisted evidence (acceptance 10 + 11) --------------------

def _seed_db(tmp_path, *, security_scan: str = "complete",
             analysis_status: str = "completed",
             verification: dict | None = None,
             baseline: str = BASELINE) -> tuple:
    db = tmp_path / "policy.db"
    init_db(db)
    now = utc_now_iso()
    projects = ProjectRepository(db_path=db)
    projects.create(ProjectRecord(
        project_id="prj_pol", owner_sub="local-operator", name="app",
        provider="github", repo_owner="o", repo_name="app", repository="o/app",
        canonical_url="https://github.com/o/app.git", branch="main",
        visibility="unverified", connection_status="pending",
        created_at=now, updated_at=now,
    ))
    # Baseline + full-scan state are written the way production writes them:
    # by the first completed assessment (create() never sets them).
    projects.update_scan_state(
        "prj_pol", baseline_sha=baseline, baseline_at=now,
        full_scan=True, at=now,
    )
    repo = DeploymentRepository(db_path=db)
    repo.create(DeploymentRecord(
        deployment_id="dep_pol", repository_url="https://github.com/o/app.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=BASE, target_revision=HEAD,
        status="awaiting_approval", current_stage=None,
        project_id="prj_pol", created_at=now, updated_at=now, is_demo=False,
    ))
    repo.save_artifacts(
        "dep_pol",
        result={
            "repository_analysis": _analysis(
                security_scan=security_scan, analysis_status=analysis_status
            ),
            "analysis_status": analysis_status,
        },
        verification=verification if verification is not None
        else _verification(),
        updated_at=now,
    )
    return db, repo


def test_completed_assessment_with_clean_coverage_approves(tmp_path):
    db, _ = _seed_db(tmp_path)
    decision = evaluate_merge_readiness("prj_pol", db_path=db)
    assert decision["outcome"] == "approved"
    assert decision["assessed"]["run_id"] == "dep_pol"
    assert decision["pull_request"] is None
    assert decision["advisory"] is True


def test_confirmed_critical_finding_from_new_commit_blocks(tmp_path):
    db, repo = _seed_db(tmp_path)
    FindingRepository(db_path=db).sync_scan(
        project_id="prj_pol", repository="o/app", deployment_id="dep_pol",
        commit_sha=HEAD,
        findings=[{
            "source": "semgrep", "rule_id": "SEC-99", "path": "app/auth.py",
            "severity": "critical", "message": "auth bypass",
            "category": "security", "confidence": "high",
        }],
        active_sources={"semgrep"},
        scanned_at=utc_now_iso(),
    )
    # first_seen_sha == HEAD == the merge head (not the baseline) → new.
    decision = evaluate_merge_readiness("prj_pol", db_path=db)
    assert decision["outcome"] == "blocked"
    assert any(r["code"] == "blocking_finding" for r in decision["reasons"])
    assert decision["blocking_findings"][0]["severity"] == "critical"
    assert decision["required_checks"]["failed"] == []


def test_no_security_coverage_never_approves(tmp_path):
    db, _ = _seed_db(tmp_path, security_scan="none")
    decision = evaluate_merge_readiness("prj_pol", db_path=db)
    assert decision["outcome"] == "assessment_incomplete"
    assert any(r["code"] == "no_security_coverage" for r in decision["reasons"])


def test_failed_analysis_never_approves(tmp_path):
    db, _ = _seed_db(tmp_path, analysis_status="failed")
    decision = evaluate_merge_readiness("prj_pol", db_path=db)
    assert decision["outcome"] == "assessment_incomplete"


def test_old_run_cannot_overwrite_newer_commit_results(tmp_path):
    db, repo = _seed_db(tmp_path)
    now = utc_now_iso()
    # A late, failed run for an OLDER commit must not be chosen as the
    # assessment of the head commit.
    repo.create(DeploymentRecord(
        deployment_id="dep_old", repository_url="https://github.com/o/app.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=None, target_revision="e" * 40,
        status="failed", current_stage=None,
        project_id="prj_pol", created_at=now, updated_at=now, is_demo=False,
    ))
    decision = evaluate_merge_readiness(
        "prj_pol", head_sha=HEAD, db_path=db
    )
    assert decision["assessed"]["run_id"] == "dep_pol"
    assert decision["assessed"]["head_sha"] == HEAD


def test_unknown_head_sha_has_no_assessment(tmp_path):
    db, _ = _seed_db(tmp_path)
    decision = evaluate_merge_readiness(
        "prj_pol", head_sha="f" * 40, db_path=db
    )
    assert decision["outcome"] == "assessment_incomplete"
    assert "no_assessment" in [r["code"] for r in decision["reasons"]]


def test_missing_project_raises_key_error(tmp_path):
    db, _ = _seed_db(tmp_path)
    with pytest.raises(KeyError):
        evaluate_merge_readiness("prj_missing", db_path=db)
