"""GitHub push webhooks → analysis proposals → human approval → execution.

Authentication here is the GitHub webhook secret (HMAC-SHA256), independent
of Clerk user sessions. Flow:

1. GitHub POSTs a push event → signature verified → delivery recorded
   (idempotent by delivery ID) → proposal created → plan-only analysis runs.
2. Pipeline persists the verified plan + plan_hash, marks the proposal READY.
3. A human approves (Clerk subject in clerk mode) → the pipeline re-runs and
   revalidates the exact plan hash before executing anything.
4. Stale proposals (newer push, hash mismatch, wrong state) can never execute.

Hosted execution stays disabled unless the operator explicitly configures
an isolated builder (MEDHA_EXECUTOR_MODE=real + MEDHA_DOCKER_EXECUTE on a
non-production host) — webhooks never enable it.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.api_token import require_mutation_token
from app.core.clerk_auth import LOCAL_SUBJECT, RequireSubject
from app.core.config import get_settings
from app.core.enums import DeploymentStatus, DeployMode, EventType, ProposalStatus
from app.core.events import event_bus, make_event, utc_now_iso
from app.core.logging import get_logger
from app.changeintel.push_intel import ZERO_SHA, summarize_push
from app.database.repositories import (
    DeploymentRepository,
    ProjectRepository,
    ProposalRepository,
)
from app.models.deployment import DeploymentRecord, ProjectRecord, ProposalRecord
from app.workflow.planning import _plan_hash, schedule_planning_pipeline

logger = get_logger(__name__)
router = APIRouter(prefix="/api")
repo = DeploymentRepository()
proposals = ProposalRepository()

TERMINAL_PROPOSAL = frozenset(
    {
        ProposalStatus.APPROVED.value,
        ProposalStatus.REJECTED.value,
        ProposalStatus.SUPERSEDED.value,
        ProposalStatus.STALE.value,
        ProposalStatus.EXECUTED.value,
        ProposalStatus.FAILED.value,
    }
)


def _error(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def _webhook_secret() -> str:
    return (get_settings().github_webhook_secret or "").strip()


def _allowed_repos() -> list[str]:
    raw = get_settings().webhook_allowed_repos or ""
    return [part.strip().lower() for part in raw.split(",") if part.strip()]


def _allowed_branches() -> list[str]:
    raw = get_settings().webhook_branches or "main"
    return [part.strip() for part in raw.split(",") if part.strip()]


def verify_github_signature(body: bytes, signature: str, secret: str) -> bool:
    """HMAC-SHA256 with constant-time comparison. No secret in errors."""
    if not secret or not signature.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    try:
        return hmac.compare_digest(expected, signature)
    except TypeError:
        return False


def _settle_proposal(proposal_id: str, deployment_id: str, task) -> None:
    """Done-callback: mark the proposal executed/failed from terminal state."""
    try:
        if task.cancelled():
            proposals.update(proposal_id, status=ProposalStatus.FAILED.value)
            return
        exc = task.exception()
        if exc is not None:
            logger.warning("Proposal pipeline raised: %s", type(exc).__name__)
            current = proposals.get(proposal_id)
            if current is not None and current.status not in TERMINAL_PROPOSAL:
                proposals.update(proposal_id, status=ProposalStatus.FAILED.value)
            return
        record = repo.get(deployment_id)
        current = proposals.get(proposal_id)
        if current is None or current.status in TERMINAL_PROPOSAL:
            return
        if record is None:
            proposals.update(proposal_id, status=ProposalStatus.FAILED.value)
            return
        if record.status == DeploymentStatus.AWAITING_APPROVAL:
            # Plan-only run finished analysis and is waiting for a human.
            return
        if record.status in (
            DeploymentStatus.COMPLETED,
            DeploymentStatus.PARTIAL_RECOVERY,
        ):
            proposals.update(proposal_id, status=ProposalStatus.EXECUTED.value,
                             execution_id=deployment_id)
        elif record.status == DeploymentStatus.FAILED:
            proposals.update(proposal_id, status=ProposalStatus.FAILED.value)
    except Exception:  # noqa: BLE001 - bookkeeping must never raise
        logger.exception("Proposal settle failed")


@router.post("/webhooks/github")
async def github_webhook(request: Request):
    settings = get_settings()
    secret = _webhook_secret()
    if not secret:
        return _error(
            503, "WEBHOOK_NOT_CONFIGURED",
            "GitHub webhook receiver is not configured (GITHUB_WEBHOOK_SECRET).",
        )
    body = await request.body()
    signature = request.headers.get("x-hub-signature-256", "")
    from app.core.rate_limit import check_rate_limit, client_ip

    ip = client_ip(request, trusted_proxy=get_settings().trusted_proxy)
    if not check_rate_limit(
        f"webhook:{ip}", limit_per_minute=get_settings().rate_limit_per_minute
    ):
        return _error(429, "RATE_LIMITED", "Too many webhook deliveries; retry later.")
    if not verify_github_signature(body, signature, secret):
        return _error(401, "INVALID_SIGNATURE", "Webhook signature verification failed.")
    delivery_id = request.headers.get("x-github-delivery", "").strip()
    if not delivery_id:
        return _error(400, "DELIVERY_ID_REQUIRED", "Missing X-GitHub-Delivery header.")
    event = request.headers.get("x-github-event", "").strip().lower()
    try:
        payload = json.loads(body.decode("utf-8") if body else "{}")
    except ValueError:
        return _error(400, "INVALID_PAYLOAD", "Webhook body is not valid JSON.")
    if not isinstance(payload, dict):
        return _error(400, "INVALID_PAYLOAD", "Webhook body must be a JSON object.")

    repository = ""
    repo_obj = payload.get("repository")
    if isinstance(repo_obj, dict):
        repository = str(repo_obj.get("full_name") or "").strip()
    ref = str(payload.get("ref") or "")
    push = summarize_push(payload)
    sha = push.get("target_sha") or ""
    base_sha = push.get("base_sha")
    deleted = bool(push.get("deleted"))
    now = utc_now_iso()

    if event != "push":
        proposals.record_delivery(
            delivery_id=delivery_id, repository=repository, ref=ref or None,
            sha=sha or None, event=event or "unknown",
            status="ignored", received_at=now, note="non-push event",
        )
        return JSONResponse({"status": "ignored", "reason": "non-push event"})

    branch = ref.split("/")[-1] if ref.startswith("refs/heads/") else ""
    if deleted:
        proposals.record_delivery(
            delivery_id=delivery_id, repository=repository, ref=ref or None,
            sha=None, event=event, status="ignored",
            received_at=now, note="branch deleted (null SHA)",
        )
        return JSONResponse({"status": "ignored", "reason": "branch deleted"})
    if branch not in _allowed_branches():
        proposals.record_delivery(
            delivery_id=delivery_id, repository=repository, ref=ref or None,
            sha=sha or None, event=event, status="ignored",
            received_at=now, note=f"branch not watched: {ref}",
        )
        return JSONResponse({"status": "ignored", "reason": "branch not watched"})

    import re as _re

    if not repository or not _re.fullmatch(r"[0-9a-fA-F]{40}", sha or ""):
        proposals.record_delivery(
            delivery_id=delivery_id, repository=repository, ref=ref or None,
            sha=sha or None, event=event, status="ignored",
            received_at=now, note="missing repository or full 40-hex commit SHA",
        )
        return JSONResponse({"status": "ignored", "reason": "missing repository or commit"})

    allowlist = _allowed_repos()
    if allowlist and repository.lower() not in allowlist:
        proposals.record_delivery(
            delivery_id=delivery_id, repository=repository, ref=ref or None,
            sha=sha or None, event=event, status="ignored",
            received_at=now, note="repository not configured",
        )
        return JSONResponse({"status": "ignored", "reason": "repository not configured"})
    if not allowlist and (settings.medha_env or "").strip().lower() == "production":
        return _error(
            503, "WEBHOOK_ALLOWLIST_NOT_CONFIGURED",
            "No webhook repositories configured for this production service.",
        )

    inserted = proposals.record_delivery(
        delivery_id=delivery_id, repository=repository, ref=ref,
        sha=sha, event=event, status="received", received_at=now,
    )
    if not inserted:
        return JSONResponse({"status": "duplicate", "delivery_id": delivery_id})

    # Project-scoped routing: a signed event must resolve to at least one
    # connected project watching this branch. Once any project exists, an
    # unmapped repository is rejected instead of analyzed (no unauthenticated
    # oracle for arbitrary repos). With zero projects configured, the legacy
    # server-allowlist path applies (fresh installs, offline tests).
    project_store = ProjectRepository()
    matched = [
        p for p in project_store.find_connected_by_repo(repository)
        if p.branch == branch
    ]
    if not matched and project_store.has_any():
        proposals.set_delivery_status(delivery_id, "ignored")
        return JSONResponse({"status": "ignored", "reason": "no connected project"})
    targets: list[ProjectRecord | None] = matched if matched else [None]

    repository_url = f"https://github.com/{repository}.git"
    started: list[dict[str, str]] = []
    for target in targets:
        outcome = await _start_proposal_analysis(
            delivery_id=delivery_id,
            repository=repository,
            repository_url=(
                target.canonical_url if target is not None else repository_url
            ),
            branch=branch,
            base_sha=base_sha,
            sha=sha,
            push=push,
            project=target,
            now=now,
        )
        if outcome is None:
            for done in started:
                proposals.update(done["proposal_id"], status=ProposalStatus.FAILED.value)
            return _error(500, "ANALYSIS_SCHEDULE_FAILED", "Could not start analysis.")
        started.append(outcome)
        proposals.bind_delivery(delivery_id, outcome["proposal_id"], "analyzing")

    if len(started) == 1:
        single = started[0]
        return JSONResponse(
            {"status": "analyzing", "proposal_id": single["proposal_id"],
             "deployment_id": single["deployment_id"]},
            status_code=202,
        )
    return JSONResponse({"status": "analyzing", "proposals": started}, status_code=202)


async def _start_proposal_analysis(
    *,
    delivery_id: str,
    repository: str,
    repository_url: str,
    branch: str,
    base_sha: str | None,
    sha: str,
    push: dict,
    project: ProjectRecord | None,
    now: str,
) -> dict[str, str] | None:
    """Persist one proposal + plan-only run for a (repo, project) target."""
    proposal_id = f"prp_{uuid4().hex[:16]}"
    deployment_id = f"dep_{uuid4().hex[:16]}"
    proposal = ProposalRecord(
        proposal_id=proposal_id,
        repository=repository,
        branch=branch,
        base_sha=base_sha,
        target_sha=sha,
        deployment_id=deployment_id,
        push=push,
        project_id=project.project_id if project is not None else None,
        status=ProposalStatus.ANALYZING.value,
        created_by="webhook:github",
        created_at=now,
        idempotency_key=f"github:{delivery_id}:{proposal_id}",
    )
    try:
        proposals.create(proposal)
        proposals.supersede_older(
            repository=repository, branch=branch, except_proposal_id=proposal_id,
            project_id=project.project_id if project is not None else None,
        )
    except Exception as exc:
        logger.warning("Proposal create failed: %s", type(exc).__name__)
        return None

    record = DeploymentRecord(
        deployment_id=deployment_id,
        repository_url=repository_url,
        mode=DeployMode.REAL,
        scenario=None,
        target_host="localhost",
        target_port=8080,
        intent=f"GitHub push to {branch} ({sha[:8]})",
        base_revision=base_sha,
        target_revision=sha,
        status=DeploymentStatus.STARTED,
        current_stage=None,
        explain_simple="Push received. Analysis started; execution waits for approval.",
        explain_technical=f"proposal={proposal_id} · sha={sha[:12]} · plan_only=true",
        owner_sub=project.owner_sub if project is not None else None,
        project_id=project.project_id if project is not None else None,
        created_at=now,
        updated_at=now,
        is_demo=False,
    )
    try:
        repo.create(record)
        created = make_event(
            deployment_id=deployment_id,
            event_type=EventType.DEPLOYMENT_CREATED,
            message="Push-triggered analysis created (approval required before execution).",
            status=DeploymentStatus.STARTED.value,
            metadata={
                "proposal_id": proposal_id, "sha": sha, "plan_only": True,
                "project_id": project.project_id if project is not None else None,
            },
            is_demo=False,
        )
        repo.add_event(created)
        await event_bus.publish(created)
    except Exception as exc:
        logger.warning("Proposal record creation failed: %s", type(exc).__name__)
        proposals.update(proposal_id, status=ProposalStatus.FAILED.value)
        return None

    # The durable worker owns the analysis: it claims this job, runs the real
    # plan-only pipeline, and marks the job succeeded only after persistence.
    try:
        from app.jobs.worker import enqueue_job

        enqueue_job(
            repository=repository, branch=branch, target_sha=sha,
            base_sha=base_sha,
            project_id=project.project_id if project is not None else None,
            delivery_id=f"github:{delivery_id}:{proposal_id}",
            deployment_id=deployment_id,
        )
    except Exception as exc:  # noqa: BLE001 - no job means no analysis: fail closed
        logger.warning("Job enqueue failed for proposal=%s", proposal_id)
        proposals.update(proposal_id, status=ProposalStatus.FAILED.value)
        repo.update_status(
            deployment_id, status=DeploymentStatus.FAILED,
            error_summary="Analysis job could not be queued.", updated_at=utc_now_iso(),
        )
        return None

    logger.info(
        "Webhook proposal=%s repo=%s sha=%.12s project=%s",
        proposal_id, repository, sha,
        project.project_id if project is not None else "-",
    )
    return {"proposal_id": proposal_id, "deployment_id": deployment_id}


@router.get("/proposals")
async def list_proposals(
    repository: str | None = Query(default=None),
    status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    subject: str = RequireSubject,
):
    if project_id:
        project = ProjectRepository().get(project_id)
        if (
            project is None
            or (subject != LOCAL_SUBJECT and project.owner_sub != subject)
        ):
            return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
        items, total = proposals.list(
            repository=repository, status=status, project_id=project_id,
            limit=limit, offset=offset,
        )
        return JSONResponse(
            {"proposals": [p.to_api() for p in items], "total": total,
             "limit": limit, "offset": offset}
        )
    owner = subject if subject != LOCAL_SUBJECT else None
    items, total = proposals.list(
        repository=repository, status=status, created_by=owner,
        limit=limit, offset=offset,
    )
    # Webhook-created proposals are visible per project ownership: include
    # team rows only when they are unbound (legacy) or bound to a project
    # owned by the subject. No cross-project leakage.
    if owner is not None:
        team_items, _ = proposals.list(
            repository=repository, status=status, created_by="webhook:github",
            limit=limit, offset=offset,
        )
        seen = {p.proposal_id for p in items}
        owned_projects = {
            p.project_id
            for p in ProjectRepository().list_for_owner(subject)
        }
        items = items + [
            p for p in team_items
            if p.proposal_id not in seen
            and (p.project_id is None or p.project_id in owned_projects)
        ]
    return JSONResponse(
        {"proposals": [p.to_api() for p in items], "total": total,
         "limit": limit, "offset": offset}
    )


@router.get("/proposals/{proposal_id}")
async def get_proposal(proposal_id: str, subject: str = RequireSubject):
    proposal = proposals.get(proposal_id)
    if proposal is None or not _may_view(proposal, subject):
        return _error(404, "NOT_FOUND", f"Proposal '{proposal_id}' was not found.")
    return JSONResponse(proposal.to_api())


def _may_view(proposal: ProposalRecord, subject: str) -> bool:
    if subject == LOCAL_SUBJECT:
        return True
    if proposal.project_id:
        project = ProjectRepository().get(proposal.project_id)
        if project is None:
            return False
        return project.owner_sub == subject
    return proposal.created_by in (None, subject)


def _may_decide(proposal: ProposalRecord, subject: str) -> bool:
    """Project-bound proposals are decided by the project owner only."""
    if subject == LOCAL_SUBJECT:
        # Legacy single-operator mode: the local operator owns everything.
        return True
    if proposal.project_id:
        project = ProjectRepository().get(proposal.project_id)
        if project is None or project.connection_status == "disconnected":
            return False
        return project.owner_sub == subject
    return proposal.created_by in (None, subject)


class DecisionBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


@router.post(
    "/proposals/{proposal_id}/approve",
    dependencies=[Depends(require_mutation_token)],
)
async def approve_proposal(proposal_id: str, body: DecisionBody, subject: str = RequireSubject):
    proposal = proposals.get(proposal_id)
    if proposal is None:
        return _error(404, "NOT_FOUND", f"Proposal '{proposal_id}' was not found.")
    if not _may_decide(proposal, subject):
        return _error(404, "NOT_FOUND", f"Proposal '{proposal_id}' was not found.")
    if proposal.status in (
        ProposalStatus.APPROVED.value,
        ProposalStatus.EXECUTING.value,
        ProposalStatus.EXECUTED.value,
    ):
        # Idempotent replay: report current state, never execute twice.
        return JSONResponse({**proposal.to_api(), "duplicate": True})
    if proposal.status != ProposalStatus.READY.value:
        return _error(
            409, "PROPOSAL_NOT_READY",
            f"Proposal is {proposal.status}; only ready proposals can be approved.",
        )
    if not proposal.deployment_id or not proposal.plan_hash:
        return _error(409, "PROPOSAL_INCOMPLETE", "Proposal has no analyzed plan.")
    record = repo.get(proposal.deployment_id)
    if record is None or record.status != DeploymentStatus.AWAITING_APPROVAL:
        proposals.update(proposal_id, status=ProposalStatus.STALE.value)
        return _error(409, "STALE_PROPOSAL", "The analyzed run is no longer awaiting approval.")
    if record.target_revision != proposal.target_sha:
        proposals.update(proposal_id, status=ProposalStatus.STALE.value)
        return _error(409, "STALE_PROPOSAL", "Record commit does not match the proposal.")
    stored_plan = (record.result or {}).get("plan") if isinstance(record.result, dict) else None
    if not isinstance(stored_plan, dict) or _plan_hash(stored_plan) != proposal.plan_hash:
        proposals.update(proposal_id, status=ProposalStatus.STALE.value)
        return _error(409, "STALE_PROPOSAL", "Stored plan does not match the proposal hash.")
    if proposal.project_id:
        project = ProjectRepository().get(proposal.project_id)
        if (
            project is None
            or project.connection_status != "connected"
            or project.repository != proposal.repository
            or project.branch != proposal.branch
            or project.canonical_url != record.repository_url
        ):
            proposals.update(proposal_id, status=ProposalStatus.STALE.value)
            return _error(
                409, "STALE_PROPOSAL",
                "The linked project is disconnected or no longer watches this commit.",
            )

    now = utc_now_iso()
    proposals.update(
        proposal_id,
        status=ProposalStatus.APPROVED.value,
        decided_by=subject,
        decided_at=now,
        execution_id=record.deployment_id,
    )
    try:
        task = schedule_planning_pipeline(
            record.deployment_id,
            repo=repo,
            expected_plan_hash=proposal.plan_hash,
        )
        try:
            task.add_done_callback(
                lambda t, pid=proposal_id, did=record.deployment_id: _settle_proposal(pid, did, t)
            )
        except AttributeError:
            pass
        proposals.update(proposal_id, status=ProposalStatus.EXECUTING.value)
    except Exception as exc:
        logger.warning("Approved execution schedule failed: %s", type(exc).__name__)
        proposals.update(proposal_id, status=ProposalStatus.FAILED.value)
        return _error(500, "EXECUTION_SCHEDULE_FAILED", "Could not start execution.")
    updated = proposals.get(proposal_id)
    return JSONResponse({**(updated.to_api() if updated else proposal.to_api())})


@router.post(
    "/proposals/{proposal_id}/reject",
    dependencies=[Depends(require_mutation_token)],
)
async def reject_proposal(proposal_id: str, body: DecisionBody, subject: str = RequireSubject):
    proposal = proposals.get(proposal_id)
    if proposal is None:
        return _error(404, "NOT_FOUND", f"Proposal '{proposal_id}' was not found.")
    if not _may_decide(proposal, subject):
        return _error(404, "NOT_FOUND", f"Proposal '{proposal_id}' was not found.")
    if proposal.status != ProposalStatus.READY.value:
        return _error(
            409, "PROPOSAL_NOT_READY",
            f"Proposal is {proposal.status}; only ready proposals can be rejected.",
        )
    now = utc_now_iso()
    updated = proposals.update(
        proposal_id,
        status=ProposalStatus.REJECTED.value,
        decided_by=subject,
        decided_at=now,
    )
    return JSONResponse(updated.to_api() if updated else proposal.to_api())
