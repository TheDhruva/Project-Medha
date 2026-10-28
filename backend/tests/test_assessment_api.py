"""Assessment / findings / merge-readiness API consistency (acceptance 13, 14).

Every dashboard number must come from persisted state and stay consistent
across refreshes: the summary agrees with the runs list and the ledger,
failed scans never read as success, and coverage is reported separately
from pass rate.
"""

from __future__ import annotations

from app.core.events import utc_now_iso
from app.database.repositories import (
    DeploymentRepository,
    FindingRepository,
    ProjectRepository,
    PullRequestRepository,
)
from app.models.deployment import DeploymentRecord, ProjectRecord

HEAD = "a" * 40
BASE = "b" * 40
BASELINE = "c" * 40
OLDER = "e" * 40

_REQUIRED_IDS = (
    "schema", "yaml", "compose", "security", "constraints",
    "ports", "order", "env", "target",
)


def _mk_project(project_id="prj_api", *, baseline=BASELINE, last_full=True):
    now = utc_now_iso()
    projects = ProjectRepository()
    projects.create(ProjectRecord(
        project_id=project_id, owner_sub="local-operator", name="app",
        provider="github", repo_owner="o", repo_name="app",
        repository="o/app", canonical_url="https://github.com/o/app.git",
        branch="main", visibility="unverified", connection_status="pending",
        created_at=now, updated_at=now,
    ))
    if baseline:
        projects.update_scan_state(
            project_id, baseline_sha=baseline, baseline_at=now,
            full_scan=last_full, at=now,
        )
    return project_id


def _mk_run(deployment_id, *, project_id, target=HEAD, base=BASE,
            status="awaiting_approval", analysis_status="completed",
            security_scan="complete", verification="full", pr_number=None,
            with_result=True):
    now = utc_now_iso()
    repo = DeploymentRepository()
    repo.create(DeploymentRecord(
        deployment_id=deployment_id,
        repository_url="https://github.com/o/app.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=base, target_revision=target,
        status=status, current_stage=None, project_id=project_id,
        pr_number=pr_number, created_at=now, updated_at=now, is_demo=False,
    ))
    if not with_result:
        return repo.get(deployment_id)
    result = {
        "analysis_status": analysis_status,
        "repository_analysis": {
            "analysis_status": analysis_status,
            "commit_sha": target,
            "coverage": {
                "security_scan": security_scan,
                "scan_mode": "full",
                "gaps": [] if security_scan == "complete"
                else ["no external security scanner executed"],
            },
            "scanners": [],
            "finding_count": 0,
        },
    }
    ver = None
    if verification == "full":
        ver = {"checks": [
            {"id": cid, "name": cid, "status": "pass"}
            for cid in _REQUIRED_IDS
        ]}
    elif verification == "partial":
        # 8 of 9 required checks recorded; ports never ran.
        ver = {"checks": [
            {"id": cid, "name": cid, "status": "pass"}
            for cid in _REQUIRED_IDS if cid != "ports"
        ]}
    repo.save_artifacts(deployment_id, result=result, verification=ver,
                        updated_at=now)
    return repo.get(deployment_id)


def _mk_finding(*, severity="critical", status="detected",
                rule="SEC-99", first_sha=HEAD):
    FindingRepository().sync_scan(
        project_id="prj_api", repository="https://github.com/o/app.git",
        deployment_id="dep_api", commit_sha=first_sha,
        findings=[{
            "source": "semgrep", "rule_id": rule, "path": "app/auth.py",
            "severity": severity, "message": f"issue {rule}",
            "category": "security", "confidence": "high",
        }],
        active_sources=set(),
        scanned_at=utc_now_iso(),
    )
    row = next(
        r for r in FindingRepository().list(project_id="prj_api", limit=50)
        if r["rule_id"] == rule
    )
    if status != "detected":
        FindingRepository().transition(
            row["finding_id"], status, reason="test state",
            at=utc_now_iso(), evidence=[{"step": "manual"}],
        )
    return row["finding_id"]


# -- criterion 13: summary agrees across refreshes ----------------------------

def test_assessment_summary_consistent_across_refreshes(client):
    _mk_project()
    _mk_run("dep_api", project_id="prj_api")
    _mk_finding(severity="critical")

    first = client.get("/api/projects/prj_api/assessment-summary")
    assert first.status_code == 200, first.text
    body = first.json()
    second = client.get("/api/projects/prj_api/assessment-summary")
    assert second.json() == body            # identical across refreshes

    assert body["status"] == "completed"
    assert body["baseline"]["sha"] == BASELINE
    assert body["last_full_scan_at"]
    assert body["latest_assessment"]["commit_sha"] == HEAD
    assert body["latest_assessment"]["coverage"]["security_scan"] == "complete"
    assert body["last_successful_assessment"]["commit_sha"] == HEAD

    # Numbers match the persisted ledger exactly.
    ledger = FindingRepository().list(project_id="prj_api", limit=500)
    assert body["findings"]["total"] == len(ledger)
    assert body["findings"]["unresolved"] == 1
    assert body["findings"]["by_severity"]["critical"] == 1
    assert len(body["blocking_findings"]) == 1
    assert body["blocking_findings"][0]["blocks_merge"] is True

    # Merge decision is derived from the same evidence and deterministic.
    assert body["merge"]["outcome"] == "blocked"
    fresh = client.get("/api/projects/prj_api/merge-readiness").json()
    assert fresh["outcome"] == body["merge"]["outcome"]
    assert fresh["advisory"] is True

    # The runs list tells the same story as the summary.
    runs = client.get("/api/deploys").json()["runs"]
    mine = [r for r in runs if r["deployment_id"] == "dep_api"]
    assert mine
    assert mine[0]["target_revision"] == body["latest_assessment"]["commit_sha"]
    assert mine[0]["analysis_status"] == "completed"

    # Setup state is honest: no fabricated monitoring claims.
    setup = body["setup"]
    assert set(setup) == {
        "webhook_secret_configured", "github_app_configured",
        "status_checks", "note",
    }
    assert setup["status_checks"] in {"configured", "setup_required"}
    assert "not claimed" in setup["note"] or "verify" in setup["note"]


def test_failed_latest_scan_never_reads_as_success(client):
    _mk_project()
    _mk_run("dep_old_ok", project_id="prj_api", target=OLDER, base=None)
    _mk_run("dep_new_fail", project_id="prj_api", analysis_status="failed",
            status="failed", security_scan="none")

    body = client.get("/api/projects/prj_api/assessment-summary").json()
    assert body["status"] == "failed"                    # not "completed"
    assert body["latest_assessment"]["deployment_id"] == "dep_new_fail"
    # The last SUCCESSFUL assessment is reported separately and honestly.
    assert body["last_successful_assessment"]["deployment_id"] == "dep_old_ok"
    # And the merge decision cannot be approval on a failed latest scan.
    assert body["merge"]["outcome"] != "approved"


def test_running_assessment_shows_running_and_blocks_approval(client):
    _mk_project()
    _mk_run("dep_run", project_id="prj_api", status="running",
            with_result=False)

    body = client.get("/api/projects/prj_api/assessment-summary").json()
    assert body["status"] == "running"
    assert body["active_run_id"] == "dep_run"
    assert body["latest_assessment"] is None
    decision = client.get("/api/projects/prj_api/merge-readiness").json()
    assert decision["outcome"] == "pending"


def test_never_assessed_project_is_never_approval(client):
    _mk_project(baseline=None, last_full=False)
    body = client.get("/api/projects/prj_api/assessment-summary").json()
    assert body["status"] == "never_assessed"
    assert body["baseline"] is None
    assert body["last_full_scan_at"] is None
    assert body["findings"]["total"] == 0
    assert body["merge"]["outcome"] == "assessment_incomplete"


# -- criterion 14: focused findings view --------------------------------------

def test_findings_endpoint_filters_sorts_and_validates(client):
    _mk_project()
    _mk_run("dep_api", project_id="prj_api")
    _mk_finding(severity="critical", rule="SEC-99")
    _mk_finding(severity="medium", rule="SEC-50")
    _mk_finding(severity="high", rule="SEC-70", status="fixed_unverified",
                first_sha=BASE)

    all_rows = client.get("/api/projects/prj_api/findings").json()
    assert all_rows["total"] == 3
    assert all_rows["lifecycle_states"] == [
        "detected", "under_investigation", "confirmed", "rejected",
        "accepted_risk", "fixed_unverified", "resolved", "reopened",
    ]
    # Default sort: severity first (critical before medium).
    assert all_rows["findings"][0]["severity"] == "critical"
    # Open critical/high block; a fixed one never does.
    blocks = {f["rule_id"]: f["blocks_merge"] for f in all_rows["findings"]}
    assert blocks["SEC-99"] is True
    assert blocks["SEC-50"] is False
    assert blocks["SEC-70"] is False

    sev = client.get("/api/projects/prj_api/findings?severity=medium").json()
    assert sev["total"] == 1
    assert sev["findings"][0]["rule_id"] == "SEC-50"

    st = client.get(
        "/api/projects/prj_api/findings?status=fixed_unverified"
    ).json()
    assert st["total"] == 1
    assert st["findings"][0]["rule_id"] == "SEC-70"

    by_seen = client.get(
        "/api/projects/prj_api/findings?sort=first_seen"
    ).json()
    firsts = [f["first_seen_sha"] for f in by_seen["findings"]]
    assert firsts == sorted(firsts, reverse=True)

    # Invalid filters are rejected, not silently ignored.
    bad = client.get("/api/projects/prj_api/findings?status=banana")
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "FINDING_STATUS_INVALID"
    bad2 = client.get("/api/projects/prj_api/findings?severity=ultra")
    assert bad2.status_code == 400
    bad3 = client.get("/api/projects/prj_api/findings?sort=colour")
    assert bad3.status_code == 400

    missing = client.get("/api/projects/prj_missing/findings")
    assert missing.status_code == 404


# -- verification coverage separate from pass rate ----------------------------

def test_verification_endpoint_reports_coverage_separately(client):
    _mk_project()
    _mk_run("dep_api", project_id="prj_api", verification="partial")

    body = client.get("/api/deploy/dep_api/verification").json()
    cov = body["coverage"]
    assert cov is not None
    counts = cov["counts"]
    # Coverage (8/9 assessed) is distinct from the pass rate over checks
    # that actually ran (8/8): the two are never conflated.
    assert counts["assessed"] == 8
    assert counts["applicable"] == 9
    assert counts["not_assessed"] == 1
    assert counts["passed"] == 8
    assert counts["failed"] == 0
    assert counts["ratio"] < 1.0                      # coverage below full
    assert counts["passed"] / (counts["passed"] + counts["failed"]) == 1.0
    normalized = {c["id"]: c for c in cov["normalized"]}
    assert normalized["ports"]["status"] == "not_assessed"
    assert normalized["ports"]["required"] is True
    assert normalized["schema"]["status"] == "passed"
    # Raw checks remain available for detail expansion.
    assert len(body["verification"]["checks"]) == 8

    # A run without verification reports coverage unavailable, never 0-pass.
    _mk_run("dep_noverify", project_id="prj_api", target=BASE, base=None,
            verification=None)
    none_body = client.get("/api/deploy/dep_noverify/verification").json()
    assert none_body["coverage"] is None
    assert none_body["verification"] is None


# -- runs list fields ----------------------------------------------------------

def test_runs_list_exposes_assessment_and_pr_fields(client):
    _mk_project()
    _mk_run("dep_api", project_id="prj_api", pr_number=12)
    _mk_run("dep_legacy", project_id="prj_api", target=OLDER, base=None,
            with_result=False)

    runs = client.get("/api/deploys").json()["runs"]
    by_id = {r["deployment_id"]: r for r in runs}

    modern = by_id["dep_api"]
    assert modern["pr_number"] == 12
    assert modern["target_revision"] == HEAD
    assert modern["analysis_status"] == "completed"
    assert modern["analysis_coverage"]["security_scan"] == "complete"
    assert modern["analysis_coverage"]["gaps"] == 0
    assert modern["analysis_coverage"]["commit_sha"] == HEAD

    # Historical runs without stored analysis stay honestly null.
    legacy = by_id["dep_legacy"]
    assert legacy["analysis_status"] is None
    assert legacy["analysis_coverage"] is None
    assert legacy["pr_number"] is None


# -- pull request decision visibility -----------------------------------------

def test_summary_surfaces_pr_decision(client):
    _mk_project()
    _mk_run("dep_api", project_id="prj_api", pr_number=7)
    PullRequestRepository().upsert(
        project_id="prj_api", repository="o/app", number=7,
        base_ref="main", base_sha=BASE, head_ref="feature",
        head_sha=HEAD, state="open", at=utc_now_iso(),
    )
    PullRequestRepository().save_decision(
        project_id="prj_api", repository="o/app", number=7,
        head_sha=HEAD,
        decision={"outcome": "blocked", "policy_version": "merge-policy/v1",
                  "reasons": [], "advisory": True},
        at=utc_now_iso(),
    )

    body = client.get("/api/projects/prj_api/assessment-summary").json()
    assert body["pull_request"]["number"] == 7
    assert body["pull_request"]["head_sha"] == HEAD
    assert body["merge"]["outcome"] == "blocked"
    assert body["merge_source"] == "pull_request"
