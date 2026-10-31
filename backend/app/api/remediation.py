"""API routes for automated issue remediation, patch review, and delivery."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.clerk_auth import LOCAL_SUBJECT, RequireSubject
from app.core.config import get_settings
from app.core.rate_limit import check_rate_limit, client_ip
from app.database.repositories import ProjectRepository
from app.models.deployment import ProjectRecord
from app.remediation.service import RemediationService
from app.remediation.worktree import validate_safe_branch_name

router = APIRouter(prefix="/api")


class DeliverBody(BaseModel):
    branch_name: str | None = Field(default=None, max_length=120)
    delivery_method: Literal["github_pr", "local_branch", "auto"] = Field(default="auto")


def _verify_owned_project(project_repo: ProjectRepository, project_id: str, subject: str) -> ProjectRecord:
    project = project_repo.get(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' was not found.")
    if subject != LOCAL_SUBJECT and project.owner_sub != subject:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' was not found.")
    return project


def _enforce_rate_limit(request: Request, subject: str) -> None:
    settings = get_settings()
    ip = client_ip(request, trusted_proxy=settings.trusted_proxy or "")
    key = f"remediation:{subject}:{ip}"
    limit = max(10, settings.rate_limit_per_minute // 2)
    if not check_rate_limit(key, limit_per_minute=limit):
        raise HTTPException(
            status_code=429,
            detail="Too many remediation requests. Please slow down and try again shortly.",
        )


@router.post("/projects/{project_id}/findings/{finding_id}/repair-plan")
async def create_repair_plan(
    project_id: str,
    finding_id: str,
    request: Request,
    subject: str = RequireSubject,
):
    _enforce_rate_limit(request, subject)
    service = RemediationService()
    _verify_owned_project(service.project_repo, project_id, subject)
    try:
        plan = await service.create_plan(project_id, finding_id)
        return JSONResponse(plan.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=400 if "path" in str(exc).lower() or "belong" in str(exc).lower() else 404, detail=str(exc))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to generate repair plan: {exc}")


@router.post("/projects/{project_id}/findings/{finding_id}/apply-and-verify")
async def apply_and_verify_repair(
    project_id: str,
    finding_id: str,
    request: Request,
    subject: str = RequireSubject,
):
    _enforce_rate_limit(request, subject)
    service = RemediationService()
    _verify_owned_project(service.project_repo, project_id, subject)
    try:
        verification, branch_name, commit_sha = await service.apply_and_verify(
            project_id, finding_id
        )
        return JSONResponse({
            "verification": verification.model_dump(mode="json"),
            "branch_name": branch_name,
            "commit_sha": commit_sha,
        })
    except ValueError as exc:
        raise HTTPException(status_code=404 if "not found" in str(exc).lower() else 400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to verify repair: {exc}")


@router.post("/projects/{project_id}/findings/{finding_id}/approve")
async def approve_repair(
    project_id: str,
    finding_id: str,
    request: Request,
    subject: str = RequireSubject,
):
    _enforce_rate_limit(request, subject)
    service = RemediationService()
    _verify_owned_project(service.project_repo, project_id, subject)
    try:
        session = await service.approve(project_id, finding_id, subject=subject)
        return JSONResponse(session.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Approval failed: {exc}")


@router.post("/projects/{project_id}/findings/{finding_id}/deliver")
async def deliver_repair(
    project_id: str,
    finding_id: str,
    request: Request,
    body: DeliverBody | None = None,
    subject: str = RequireSubject,
):
    _enforce_rate_limit(request, subject)
    service = RemediationService()
    _verify_owned_project(service.project_repo, project_id, subject)

    branch = body.branch_name if body else None
    delivery_method = body.delivery_method if body else "auto"
    if branch:
        try:
            branch = validate_safe_branch_name(branch)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid branch name: {exc}")

    try:
        delivery = await service.deliver(
            project_id,
            finding_id,
            branch_name=branch,
            delivery_method=delivery_method,
            subject=subject,
        )
        return JSONResponse(delivery.model_dump(mode="json"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Delivery failed: {exc}")


@router.get("/projects/{project_id}/findings/{finding_id}/repair")
async def get_repair_status(
    project_id: str,
    finding_id: str,
    subject: str = RequireSubject,
):
    service = RemediationService()
    _verify_owned_project(service.project_repo, project_id, subject)
    session = service.get_repair_session(finding_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active repair session for this finding.")
    return JSONResponse(session.model_dump(mode="json"))


@router.get("/projects/{project_id}/findings/{finding_id}/audit-trail")
async def get_repair_audit_trail(
    project_id: str,
    finding_id: str,
    subject: str = RequireSubject,
):
    service = RemediationService()
    _verify_owned_project(service.project_repo, project_id, subject)
    session = service.get_repair_session(finding_id)
    if not session:
        raise HTTPException(status_code=404, detail="No active repair session for this finding.")
    return JSONResponse({
        "finding_id": finding_id,
        "repair_id": session.repair_id,
        "status": session.status,
        "diff_hash": session.diff_hash,
        "approved": session.approved,
        "approved_by": session.approved_by,
        "approved_at": session.approved_at,
        "approved_diff_hash": session.approved_diff_hash,
        "audit_events": session.audit_events,
    })

