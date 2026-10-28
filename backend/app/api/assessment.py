"""Assessment summary, findings, and merge-readiness read models.

Every value comes from persisted state (runs, findings ledger, PR rows,
baseline columns). Nothing is re-derived from client input: missing evidence
is reported as missing, and unsupported configuration is reported as a setup
requirement instead of a passing state.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.core.clerk_auth import LOCAL_SUBJECT, RequireSubject
from app.core.config import get_settings
from app.database.repositories import (
    FINDING_STATUSES,
    DeploymentRepository,
    FindingRepository,
    ProjectRepository,
    PullRequestRepository,
)

router = APIRouter(prefix="/api")

_SEVERITIES = ("critical", "high", "medium", "low")
_OPEN_STATUSES = frozenset(
    {"detected", "under_investigation", "confirmed", "reopened"}
)
_FIXED_STATUSES = frozenset({"fixed_unverified", "resolved"})
_SEVERITY_RANK = {"critical": 4, "high": 3, "medium": 2, "low": 1}


def _error(status_code: int, code: str, message: str,
           details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message,
                           "details": details or {}}},
    )


async def _owned_project(project_id: str, subject: str):
    project = await asyncio.to_thread(ProjectRepository().get, project_id)
    if project is None or (
        subject != LOCAL_SUBJECT and project.owner_sub != subject
    ):
        return None
    return project


def _analysis_of(result: dict | None) -> dict | None:
    if not isinstance(result, dict):
        return None
    analysis = result.get("repository_analysis")
    if not isinstance(analysis, dict):
        analysis = result.get("analysis")
    return analysis if isinstance(analysis, dict) else None


def _finding_view(f: dict, baseline_sha: str | None) -> dict:
    from app.mergepolicy.engine import BLOCKING_STATUSES

    severity = str(f.get("severity") or "").lower()
    status = str(f.get("status") or "")
    first = f.get("first_seen_sha")
    return {
        "finding_id": f.get("finding_id"),
        "severity": severity,
        "status": status,
        "category": f.get("category"),
        "rule_id": f.get("rule_id"),
        "source": f.get("source"),
        "confidence": f.get("confidence"),
        "path": f.get("path"),
        "line": f.get("line"),
        "message": f.get("message"),
        "explanation": f.get("explanation"),
        "remediation": f.get("remediation"),
        "verification_status": f.get("verification_status"),
        "first_seen_sha": first,
        "last_seen_sha": f.get("last_seen_sha"),
        "first_seen_at": f.get("first_seen_at"),
        "last_seen_at": f.get("last_seen_at"),
        "is_new_since_baseline": bool(
            first and baseline_sha and first != baseline_sha
        ),
        "blocks_merge": severity in {"critical", "high"}
        and status in BLOCKING_STATUSES,
        "evidence": (f.get("evidence") or [])[-3:],
        "history": (f.get("history") or [])[-5:],
        "is_demo": f.get("is_demo"),
    }


@router.get("/projects/{project_id}/assessment-summary", response_model=None)
async def assessment_summary(project_id: str, subject: str = RequireSubject):
    """Dashboard truth: scan status, coverage, findings, merge decision."""
    project = await _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")

    records, _ = await asyncio.to_thread(
        DeploymentRepository().list, project_id=project_id, limit=100
    )
    latest_with_result = next(
        (r for r in records if isinstance(r.result, dict) and r.result), None
    )
    latest_completed = next(
        (
            r for r in records
            if isinstance(r.result, dict)
            and r.result.get("analysis_status") == "completed"
        ),
        None,
    )
    active_run = next(
        (
            r for r in records
            if r.status.value in {"queued", "started", "running"}
        ),
        None,
    )

    latest_assessment = None
    if latest_with_result is not None:
        analysis = _analysis_of(latest_with_result.result)
        coverage = (analysis or {}).get("coverage") or {}
        latest_assessment = {
            "deployment_id": latest_with_result.deployment_id,
            "commit_sha": latest_with_result.target_revision,
            "base_sha": latest_with_result.base_revision,
            "run_status": latest_with_result.status.value,
            "analysis_status": (latest_with_result.result or {}).get(
                "analysis_status"
            ),
            "assessed_at": latest_with_result.updated_at,
            "created_at": latest_with_result.created_at,
            "is_demo": latest_with_result.is_demo,
            "label": "DEMO/MOCK" if latest_with_result.is_demo else None,
            "pr_number": latest_with_result.pr_number,
            "coverage": {
                "security_scan": coverage.get("security_scan"),
                "scan_mode": coverage.get("scan_mode"),
                "scanner_scope": coverage.get("scanner_scope"),
                "gaps": coverage.get("gaps") or [],
            },
            "finding_count": (analysis or {}).get("finding_count", 0),
        }

    last_successful = None
    if latest_completed is not None:
        last_successful = {
            "deployment_id": latest_completed.deployment_id,
            "commit_sha": latest_completed.target_revision,
            "at": latest_completed.updated_at,
        }

    if latest_assessment is None:
        status = "running" if active_run is not None else "never_assessed"
    elif active_run is not None:
        status = "running"
    else:
        status = str(latest_assessment["analysis_status"] or "unknown")

    findings = await asyncio.to_thread(
        FindingRepository().list, project_id=project_id, limit=500
    )
    baseline_sha = project.baseline_sha
    by_severity = {s: 0 for s in _SEVERITIES}
    counts = {
        "total": len(findings),
        "new_since_baseline": 0,
        "unresolved": 0,
        "fixed": 0,
        "reopened": 0,
        "accepted_risk": 0,
    }
    views = []
    for f in findings:
        view = _finding_view(f, baseline_sha)
        views.append(view)
        status_f = view["status"]
        if status_f in _OPEN_STATUSES:
            counts["unresolved"] += 1
            if view["severity"] in by_severity:
                by_severity[view["severity"]] += 1
        if status_f in _FIXED_STATUSES:
            counts["fixed"] += 1
        if status_f == "reopened":
            counts["reopened"] += 1
        if status_f == "accepted_risk":
            counts["accepted_risk"] += 1
        if view["is_new_since_baseline"]:
            counts["new_since_baseline"] += 1
    counts["by_severity"] = by_severity
    blocking = sorted(
        [v for v in views if v["blocks_merge"]],
        key=lambda v: -_SEVERITY_RANK.get(v["severity"], 0),
    )

    # Verification + merge decision from the latest assessment's evidence.
    verification = None
    merge = None
    merge_source = None
    pr = None
    prs = await asyncio.to_thread(
        PullRequestRepository().list_for_project, project_id, limit=50
    )
    if prs:
        top = prs[0]
        pr = {
            "number": top.get("number"),
            "base_ref": top.get("base_ref"),
            "base_sha": top.get("base_sha"),
            "head_ref": top.get("head_ref"),
            "head_sha": top.get("head_sha"),
            "state": top.get("state"),
            "updated_at": top.get("updated_at"),
            "decision": top.get("decision"),
        }
        if isinstance(top.get("decision"), dict):
            merge = top["decision"]
            merge_source = "pull_request"

    if latest_completed is not None:
        full = await asyncio.to_thread(
            DeploymentRepository().get, latest_completed.deployment_id
        )
        if full is not None and full.verification:
            from app.mergepolicy.engine import _verification_summary
            from app.scores.compute import compute_verification_confidence

            value, evidence = compute_verification_confidence(
                verification=full.verification,
                assessed_at=full.updated_at,
                revision=full.target_revision,
            )
            verification = {
                "value": value,
                "coverage": evidence.get("coverage"),
                "reason": evidence.get("reason"),
                "required": _verification_summary(full.verification),
                "checks": evidence.get("checks") or [],
            }

    if merge is None:
        try:
            from app.mergepolicy import evaluate_merge_readiness

            merge = await asyncio.to_thread(
                evaluate_merge_readiness, project_id
            )
            merge_source = "computed"
        except Exception:  # noqa: BLE001 - summary must not fail
            merge = None

    settings = get_settings()
    try:
        from app.services.github_app import get_github_app_config

        app_configured = get_github_app_config().configured
    except Exception:  # noqa: BLE001
        app_configured = False

    return JSONResponse(
        {
            "project_id": project.project_id,
            "repository": project.repository,
            "branch": project.branch,
            "status": status,
            "baseline": (
                {"sha": project.baseline_sha, "at": project.baseline_at}
                if project.baseline_sha
                else None
            ),
            "last_full_scan_at": project.last_full_scan_at,
            "latest_assessment": latest_assessment,
            "last_successful_assessment": last_successful,
            "active_run_id": active_run.deployment_id if active_run else None,
            "findings": counts,
            "blocking_findings": blocking[:5],
            "verification": verification,
            "merge": merge,
            "merge_source": merge_source,
            "pull_request": pr,
            "setup": {
                "webhook_secret_configured": bool(
                    (settings.github_webhook_secret or "").strip()
                ),
                "github_app_configured": app_configured,
                "status_checks": (
                    "configured" if app_configured else "setup_required"
                ),
                "note": (
                    "MEDHA cannot verify the GitHub-side webhook "
                    "configuration until a signed delivery arrives; "
                    "continuous analysis is not claimed until then."
                ),
            },
        }
    )


@router.get("/projects/{project_id}/merge-readiness", response_model=None)
async def merge_readiness(
    project_id: str,
    base: str | None = Query(default=None),
    head: str | None = Query(default=None),
    subject: str = RequireSubject,
):
    """Fresh, deterministic merge decision for base/head (advisory)."""
    project = await _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    try:
        from app.mergepolicy import evaluate_merge_readiness

        decision = await asyncio.to_thread(
            evaluate_merge_readiness,
            project_id,
            base_sha=base,
            head_sha=head,
        )
    except KeyError:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    return JSONResponse(decision)


@router.get("/projects/{project_id}/findings", response_model=None)
async def project_findings(
    project_id: str,
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    sort: str = Query(default="severity"),
    limit: int = Query(default=200, ge=1, le=500),
    subject: str = RequireSubject,
):
    """Focused findings view with lifecycle/severity filters and sorting."""
    from app.mergepolicy.engine import BLOCKING_STATUSES

    project = await _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    if status is not None and status not in FINDING_STATUSES:
        return _error(
            400, "FINDING_STATUS_INVALID",
            f"Unknown finding status '{status}'.",
            {"allowed": list(FINDING_STATUSES)},
        )
    if severity is not None and severity not in _SEVERITIES:
        return _error(
            400, "SEVERITY_INVALID",
            f"Unknown severity '{severity}'.",
            {"allowed": list(_SEVERITIES)},
        )
    if sort not in {"severity", "last_seen", "first_seen"}:
        return _error(
            400, "SORT_INVALID",
            f"Unknown sort '{sort}'.",
            {"allowed": ["severity", "last_seen", "first_seen"]},
        )

    rows = await asyncio.to_thread(
        FindingRepository().list, project_id=project_id, limit=500
    )
    views = [_finding_view(f, project.baseline_sha) for f in rows]
    status_counts: dict[str, int] = {}
    severity_counts: dict[str, int] = {}
    for view in views:
        status_counts[view["status"]] = status_counts.get(view["status"], 0) + 1
        severity_counts[view["severity"]] = (
            severity_counts.get(view["severity"], 0) + 1
        )

    filtered = [
        v for v in views
        if (status is None or v["status"] == status)
        and (severity is None or v["severity"] == severity)
    ]
    if sort == "severity":
        filtered.sort(
            key=lambda v: (-_SEVERITY_RANK.get(v["severity"], 0),
                           v["status"] not in _OPEN_STATUSES,
                           v.get("last_seen_at") or "")
        )
    elif sort == "last_seen":
        filtered.sort(
            key=lambda v: (v.get("last_seen_at") or "",
                           v.get("last_seen_sha") or ""),
            reverse=True,
        )
    else:
        filtered.sort(
            key=lambda v: (v.get("first_seen_at") or "",
                           v.get("first_seen_sha") or ""),
            reverse=True,
        )

    return JSONResponse(
        {
            "project_id": project_id,
            "lifecycle_states": list(FINDING_STATUSES),
            "status_counts": status_counts,
            "severity_counts": severity_counts,
            "baseline_sha": project.baseline_sha,
            "filters": {"status": status, "severity": severity, "sort": sort},
            "findings": filtered[:limit],
            "total": len(filtered),
            "blocking_rule": {
                "severities": ["critical", "high"],
                "statuses": sorted(BLOCKING_STATUSES),
            },
        }
    )
