"""Deterministic merge-readiness policy over persisted assessment evidence.

Semantics (identical in API, UI and GitHub status checks):

- ``approved``               — a completed assessment exists for the head
  commit, mandatory rules all hold. Advisory only.
- ``blocked``                — a mandatory rule is violated (blocking
  finding, failed required check, failed run).
- ``pending``                — assessment finished but required checks have
  not run yet (or an assessment is still in progress).
- ``assessment_incomplete``  — no completed, sufficiently covered assessment
  exists for the head commit. Missing evidence is never approval.

A scan that ran successfully is not a merge approval, and an agent's
verdict never overrides these rules: this module only reads persisted
findings, verification checks and analysis coverage. Nothing here merges,
deploys, or mutates workflow state.
"""

from __future__ import annotations

import json
from typing import Any

from app.core.events import utc_now_iso
from app.core.logging import get_logger

logger = get_logger(__name__)

POLICY_VERSION = "merge-policy/v1"

DEFAULT_POLICY: dict[str, Any] = {
    # Severities whose unresolved findings block a merge.
    "block_severities": ["critical", "high"],
    # When true only findings explicitly confirmed block (detected/reopened
    # findings then inform but do not block).
    "block_confirmed_only": False,
    # When false, findings inherited from the baseline commit are reported
    # but do not block (baseline debt is tracked, not re-litigated).
    "block_inherited": False,
    # Accepted risks never block unless this is true.
    "accepted_risk_blocks": False,
    # Require security coverage for the head assessment.
    "require_security_coverage": True,
    # Require recorded verification checks before approval.
    "require_verification": True,
    # A failed required verification check blocks.
    "verification_fail_blocks": True,
}

OUTCOMES = ("approved", "blocked", "pending", "assessment_incomplete")

# Ledger statuses that mean "the condition still stands". Resolved, rejected
# and fixed (awaiting verification) findings never block.
BLOCKING_STATUSES = frozenset(
    {"detected", "under_investigation", "confirmed", "reopened"}
)

_ACTIVE_RUN_STATUSES = frozenset({"queued", "started", "running"})


def load_policy(raw: str | None = None) -> dict[str, Any]:
    """Policy from a JSON string over the defaults.

    Invalid JSON or unknown keys fall back to defaults — a decision is
    always produced deterministically, never a crash.
    """
    policy = dict(DEFAULT_POLICY)
    if raw and raw.strip():
        try:
            override = json.loads(raw)
        except ValueError:
            logger.warning("MEDHA_MERGE_POLICY is not valid JSON; using defaults")
            override = {}
        if isinstance(override, dict):
            for key in DEFAULT_POLICY:
                if key in override:
                    policy[key] = override[key]
        else:
            logger.warning("MEDHA_MERGE_POLICY must be a JSON object; using defaults")
    policy["block_severities"] = [
        str(s).strip().lower()
        for s in (policy.get("block_severities") or [])
        if str(s).strip()
    ]
    return policy


# -- pure evaluation ---------------------------------------------------------

def _reason(code: str, message: str, kind: str) -> dict[str, str]:
    return {"code": code, "message": message, "kind": kind}


def _finding_view(f: dict[str, Any], *, blocks: bool) -> dict[str, Any]:
    return {
        "finding_id": f.get("finding_id"),
        "severity": f.get("severity"),
        "status": f.get("status"),
        "rule_id": f.get("rule_id"),
        "source": f.get("source"),
        "category": f.get("category"),
        "path": f.get("path"),
        "message": f.get("message"),
        "first_seen_sha": f.get("first_seen_sha"),
        "last_seen_sha": f.get("last_seen_sha"),
        "verification_status": f.get("verification_status"),
        "blocks_merge": blocks,
    }


def _is_inherited(f: dict[str, Any], baseline_sha: str | None) -> bool:
    """Inherited = present at the baseline commit (or unclassifiable).

    An unknown first-seen commit is treated as inherited so unversioned
    local runs cannot produce phantom "new" blockers.
    """
    first = f.get("first_seen_sha")
    if not first:
        return True
    if not baseline_sha:
        return True
    return first == baseline_sha


def _verification_summary(verification: dict[str, Any] | None) -> dict[str, Any]:
    """Required-check outcomes from persisted verification evidence."""
    from app.scores.compute import (
        _REQUIRED_VERIFICATION_IDS,
        compute_verification_confidence,
    )

    _, evidence = compute_verification_confidence(verification=verification)
    checks = evidence.get("checks") or []
    if not checks:
        # No verification was ever recorded for this run: every required
        # check counts as "did not run" — zero evidence is never approval.
        not_run = sorted(_REQUIRED_VERIFICATION_IDS)
        return {
            "failed": [],
            "not_run": not_run,
            "passed": 0,
            "total_required": len(not_run),
            "reason": evidence.get("reason"),
            "coverage": evidence.get("coverage"),
        }
    failed: list[str] = []
    not_run: list[str] = []
    passed = 0
    total_required = 0
    for check in checks:
        if not check.get("required"):
            continue
        total_required += 1
        status = check.get("status")
        if status == "failed":
            failed.append(check["id"])
        elif status == "passed":
            passed += 1
        elif status in {"not_assessed", "skipped"}:
            # skipped (incl. not_applicable) is reported but only a check
            # that never produced evidence can keep the decision pending.
            if status == "not_assessed":
                not_run.append(check["id"])
    return {
        "failed": failed,
        "not_run": not_run,
        "passed": passed,
        "total_required": total_required,
        "reason": evidence.get("reason"),
        "coverage": evidence.get("coverage"),
    }


def evaluate(
    *,
    policy: dict[str, Any],
    base_sha: str | None,
    head_sha: str | None,
    baseline_sha: str | None,
    last_full_scan_at: str | None,
    run: dict[str, Any] | None,
    run_active: bool,
    analysis: dict[str, Any] | None,
    verification: dict[str, Any] | None,
    findings: list[dict[str, Any]],
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Pure decision from persisted evidence. No I/O, no randomness."""
    reasons: list[dict[str, str]] = []
    next_actions: list[str] = []
    blocking: list[dict[str, Any]] = []
    inherited: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []

    required = _verification_summary(verification)
    outcome = "assessment_incomplete"

    severities = set(policy.get("block_severities") or [])
    accepted_blocks = bool(policy.get("accepted_risk_blocks"))

    for f in findings:
        status = str(f.get("status") or "")
        severity = str(f.get("severity") or "").lower()
        inherited_now = _is_inherited(f, baseline_sha)
        view = _finding_view(f, blocks=False)
        if status == "accepted_risk":
            accepted.append(view)
            if accepted_blocks and severity in severities:
                view["blocks_merge"] = True
                blocking.append(view)
        if inherited_now:
            inherited.append(view)
        if status not in BLOCKING_STATUSES or severity not in severities:
            continue
        if policy.get("block_confirmed_only") and status != "confirmed":
            continue
        if inherited_now and not policy.get("block_inherited"):
            # baseline debt: reported as inherited, never silently dropped
            continue
        blocking.append(view)

    head_run_id = run.get("deployment_id") if run else None
    run_status = run.get("status") if run else None
    analysis_status = None
    if isinstance(analysis, dict):
        analysis_status = analysis.get("analysis_status")

    def _decision() -> dict[str, Any]:
        return {
            "policy_version": POLICY_VERSION,
            "outcome": outcome,
            "advisory": True,
            "assessed": {
                "base_sha": base_sha,
                "head_sha": head_sha,
                "baseline_sha": baseline_sha,
                "run_id": head_run_id,
                "run_status": run_status,
                "analysis_status": analysis_status,
                "assessed_at": (run or {}).get("updated_at"),
            },
            "reasons": reasons,
            "blocking_findings": blocking,
            "required_checks": required,
            "inherited_findings": inherited,
            "accepted_risks": accepted,
            "next_actions": list(dict.fromkeys(next_actions)),
            # Reproducible: anchored to the assessed run's persisted
            # timestamp (same as assessed.assessed_at) so repeated reads of
            # the same evidence yield an identical decision. Wall-clock is
            # only a last resort when there is no run to anchor to.
            "generated_at": (
                generated_at
                or (run or {}).get("updated_at")
                or (run or {}).get("created_at")
                or utc_now_iso()
            ),
        }

    def _incomplete(code: str, message: str) -> dict[str, Any]:
        # Precedence: a violated mandatory rule stays `blocked` even when the
        # assessment is also incomplete — but incomplete evidence can never
        # improve the outcome beyond itself.
        nonlocal outcome
        reasons.append(_reason(code, message, "blocking"))
        if outcome != "blocked":
            outcome = "assessment_incomplete"
        return _decision()

    # --- evidence availability -------------------------------------------
    if run is None:
        if run_active:
            outcome = "pending"
            reasons.append(_reason(
                "assessment_in_progress",
                f"Assessment of {str(head_sha or '')[:12]} is still running.",
                "pending",
            ))
            next_actions.append("wait for the running assessment to finish")
            return _decision()
        outcome = "assessment_incomplete"
        reasons.append(_reason(
            "no_assessment",
            f"No assessment has been recorded for commit {str(head_sha or '')[:12]}.",
            "blocking",
        ))
        next_actions.append("run an assessment for the head commit")
        if blocking:
            reasons.append(_reason(
                "unresolved_findings",
                f"{len(blocking)} blocking finding(s) exist in the ledger "
                "(not assessed at the head commit).",
                "blocking",
            ))
            next_actions.append("review the findings ledger")
        return _decision()

    if run_status in _ACTIVE_RUN_STATUSES:
        outcome = "pending"
        reasons.append(_reason(
            "assessment_in_progress",
            f"Assessment run {head_run_id} is {run_status}.",
            "pending",
        ))
        next_actions.append("wait for the running assessment to finish")
        return _decision()

    if run_status == "cancelled":
        return _incomplete(
            "assessment_cancelled",
            f"Assessment run {head_run_id} was cancelled before completion.",
        )

    # --- rule 1: blocking findings (persisted ledger facts) ---------------
    if blocking:
        outcome = "blocked"
        for view in blocking:
            view["blocks_merge"] = True
            reasons.append(_reason(
                "blocking_finding",
                f"{str(view.get('severity')).upper()} {view.get('source')}"
                f":{view.get('rule_id') or 'finding'} at "
                f"{view.get('path') or 'repository'} — {view.get('status')}.",
                "blocking",
            ))
        next_actions.append(
            "fix the blocking findings or record an accepted-risk decision "
            "with evidence"
        )

    # --- rule 2: assessment completeness / security coverage --------------
    if analysis_status != "completed" or not isinstance(analysis, dict):
        next_actions.append("re-run the assessment until it completes")
        return _incomplete(
            "assessment_not_completed",
            f"Analysis for {str(head_sha or '')[:12]} is "
            f"'{analysis_status or 'missing'}'; a partial or failed "
            "assessment is not merge evidence.",
        )

    coverage = analysis.get("coverage") or {}
    security_scan = coverage.get("security_scan")
    if policy.get("require_security_coverage"):
        if security_scan == "none":
            next_actions.append(
                "install/enable a security scanner (semgrep/trivy/gitleaks) "
                "and re-run"
            )
            return _incomplete(
                "no_security_coverage",
                "No external security scanner completed for this assessment; "
                "security status is unknown, not clean.",
            )
        if security_scan == "not_requested" and not last_full_scan_at:
            next_actions.append("run a full security assessment")
            return _incomplete(
                "no_security_coverage",
                "No security scan has ever completed for this repository; "
                "there is no security coverage to approve against.",
            )
        if security_scan == "not_requested":
            reasons.append(_reason(
                "incremental_scan_coverage",
                "External scanners were skipped for this incremental "
                f"changeset; coverage comes from the full scan at "
                f"{last_full_scan_at}.",
                "info",
            ))
        if security_scan == "partial":
            failed = [
                str(s.get("name")) for s in (analysis.get("scanners") or [])
                if s.get("status") in {"failed", "timed_out", "unavailable"}
            ]
            reasons.append(_reason(
                "partial_security_scan",
                "Security scan is partial"
                + (f" (scanner issues: {', '.join(failed)})" if failed else "")
                + "; coverage is incomplete.",
                "pending",
            ))
            next_actions.append("re-run the assessment with all scanners working")
            if outcome != "blocked":
                # Inconclusive coverage is never merge-ready.
                outcome = "pending"

    # --- rule 3: run failure (tests/build/execution) ----------------------
    if run_status == "failed":
        outcome = "blocked"
        reasons.append(_reason(
            "run_failed",
            f"Assessment run {head_run_id} failed"
            + (f": {run.get('error_summary')}" if run.get("error_summary") else "."),
            "blocking",
        ))
        next_actions.append("inspect the run failure and re-run")
        return _decision()

    # --- rules 4/5: required verification checks --------------------------
    if policy.get("require_verification"):
        if required["failed"] and policy.get("verification_fail_blocks"):
            outcome = "blocked"
            for check_id in required["failed"]:
                reasons.append(_reason(
                    "required_check_failed",
                    f"Required verification check '{check_id}' failed.",
                    "blocking",
                ))
            next_actions.append("fix the failed required checks and re-verify")
        elif required["not_run"]:
            if outcome != "blocked":
                outcome = "pending"
            for check_id in required["not_run"]:
                reasons.append(_reason(
                    "required_check_not_run",
                    f"Required verification check '{check_id}' did not run.",
                    "pending",
                ))
            next_actions.append("run the missing required verification checks")
        elif outcome not in {"blocked", "pending"}:
            # Approval never improves a pending/blocked outcome (e.g. a
            # partial security coverage already made this pending).
            outcome = "approved"
            reasons.append(_reason(
                "all_required_checks_passed",
                f"All {required['passed']}/{required['total_required']} "
                "required verification checks passed at the head commit.",
                "info",
            ))
    elif outcome not in {"blocked", "pending"}:
        outcome = "approved"
        reasons.append(_reason(
            "verification_not_required",
            "Policy does not require verification checks; mandatory "
            "security rules passed.",
            "info",
        ))
    return _decision()


# -- context assembly (reads persisted state) --------------------------------

def _project_row(project_id: str, db_path=None):
    from app.database.repositories import ProjectRepository

    return ProjectRepository(db_path=db_path).get(project_id)


def _latest_completed_or_newest(
    project_id: str, head_sha: str, db_path=None
) -> tuple[dict[str, Any] | None, bool]:
    """Find the best assessment record for ``head_sha``.

    Returns ``(run_summary, active)``. A completed assessment for the same
    commit wins over a newer incomplete one (an older run for the SAME
    commit cannot overwrite newer-commit results — it is the same commit).
    """
    from app.database.repositories import DeploymentRepository

    records, _ = DeploymentRepository(db_path=db_path).list(
        project_id=project_id, limit=200
    )
    matches = [r for r in records if r.target_revision == head_sha]
    if not matches:
        return None, False
    completed = [
        r for r in matches
        if r.result
        and isinstance(r.result, dict)
        and r.result.get("analysis_status") == "completed"
    ]
    chosen = completed[0] if completed else matches[0]
    active = chosen.status.value in _ACTIVE_RUN_STATUSES
    summary = {
        "deployment_id": chosen.deployment_id,
        "status": chosen.status.value,
        "created_at": chosen.created_at,
        "updated_at": chosen.updated_at,
        "error_summary": chosen.error_summary,
        "is_demo": chosen.is_demo,
        "target_revision": chosen.target_revision,
        "base_revision": chosen.base_revision,
        "result": chosen.result,
        "pr_number": chosen.pr_number,
    }
    return summary, active


def build_context(
    project_id: str,
    *,
    base_sha: str | None = None,
    head_sha: str | None = None,
    db_path=None,
) -> dict[str, Any]:
    """Assemble persisted evidence for a merge decision. Read-only."""
    from app.database.repositories import (
        DeploymentRepository,
        FindingRepository,
        PullRequestRepository,
    )

    project = _project_row(project_id, db_path)
    if project is None:
        raise KeyError(f"project '{project_id}' not found")

    baseline_sha = project.baseline_sha
    pr_row: dict[str, Any] | None = None

    if head_sha is None:
        # Default head: the newest run with persisted evidence — a failed
        # or in-progress LATEST scan must surface as such, never be skipped
        # in favour of an older success.
        records, _ = DeploymentRepository(db_path=db_path).list(
            project_id=project_id, limit=200
        )
        with_revision = [r for r in records if r.target_revision]
        head_record = next(
            (r for r in with_revision
             if isinstance(r.result, dict) and r.result),
            with_revision[0] if with_revision else None,
        )
        head_sha = head_record.target_revision if head_record else None

    if head_sha:
        prs = PullRequestRepository(db_path=db_path).list_for_project(project_id)
        pr_row = next(
            (p for p in prs if p.get("head_sha") == head_sha), None
        )
        if pr_row is None:
            pr_row = next((p for p in prs if p.get("state") == "open"), None)

    if base_sha is None:
        base_sha = (pr_row or {}).get("base_sha") or baseline_sha

    run, active = (None, False)
    analysis = None
    verification = None
    if head_sha:
        run, active = _latest_completed_or_newest(project_id, head_sha, db_path)
        if run is not None:
            full = DeploymentRepository(db_path=db_path).get(run["deployment_id"])
            if full is not None:
                verification = full.verification
                analysis = (
                    full.result.get("repository_analysis")
                    if isinstance(full.result, dict)
                    else None
                )
                if analysis is None and isinstance(full.result, dict):
                    # blocked-support runs keep analysis under result["analysis"]
                    analysis = (full.result.get("analysis") or None)
                run["updated_at"] = full.updated_at
                run["error_summary"] = full.error_summary

    findings = FindingRepository(db_path=db_path).list(
        project_id=project_id, limit=500
    )
    return {
        "project": project,
        "policy": load_policy(),
        "base_sha": base_sha,
        "head_sha": head_sha,
        "baseline_sha": baseline_sha,
        "last_full_scan_at": project.last_full_scan_at,
        "run": run,
        "run_active": active,
        "analysis": analysis,
        "verification": verification,
        "findings": findings,
        "pr": pr_row,
    }


def evaluate_merge_readiness(
    project_id: str,
    *,
    base_sha: str | None = None,
    head_sha: str | None = None,
    db_path=None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Read persisted state and return a merge-readiness decision."""
    context = build_context(
        project_id, base_sha=base_sha, head_sha=head_sha, db_path=db_path
    )
    decision = evaluate(
        policy=policy or context["policy"],
        base_sha=context["base_sha"],
        head_sha=context["head_sha"],
        baseline_sha=context["baseline_sha"],
        last_full_scan_at=context["last_full_scan_at"],
        run=context["run"],
        run_active=context["run_active"],
        analysis=context["analysis"],
        verification=context["verification"],
        findings=context["findings"],
    )
    decision["pull_request"] = (
        {
            "number": context["pr"].get("number"),
            "base_ref": context["pr"].get("base_ref"),
            "head_ref": context["pr"].get("head_ref"),
        }
        if context.get("pr")
        else None
    )
    return decision
