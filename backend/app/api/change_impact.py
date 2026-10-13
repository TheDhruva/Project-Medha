"""Phase 2 Change Intelligence REST endpoints.

POST /api/change-impact/analyze          — deterministic live analysis over a local git repo
GET  /api/deploy/{id}/change-impact      — persisted analysis attached to a deployment
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from app.changeintel.engine import analyze_change_impact
from app.changeintel.git_extract import ChangeIntelError
from app.core.api_token import require_mutation_token
from app.core.clerk_auth import LOCAL_SUBJECT, RequireSubject
from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.core.repo_url import RepositoryUrlError, validate_repository_url
from app.database.repositories import DeploymentRepository

logger = get_logger(__name__)
router = APIRouter(prefix="/api")
repo = DeploymentRepository()


class ChangeImpactRequest(BaseModel):
    repository_url: str
    base_revision: str
    target_revision: str
    deployment_id: Optional[str] = None

    @field_validator("repository_url")
    @classmethod
    def repository_url_must_be_safe(cls, value: str) -> str:
        try:
            return validate_repository_url(value)
        except RepositoryUrlError as exc:
            raise ValueError(f"{exc.code}: {exc.message}") from exc

    @field_validator("base_revision", "target_revision")
    @classmethod
    def revision_must_be_nonempty(cls, value: str) -> str:
        candidate = (value or "").strip()
        if not candidate or len(candidate) > 256 or any(c in candidate for c in ["\x00", "\n", "\r"]):
            raise ValueError("revision must be a non-empty ref or SHA (max 256 chars)")
        if candidate.startswith("-"):
            raise ValueError("revision must not start with '-'")
        return candidate


def _error(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


_ERROR_MAP = {
    "NOT_A_GIT_REPOSITORY": (400, ""),
    "NOT_LOCAL_REPOSITORY": (400, ""),
    "REPO_NOT_FOUND": (400, ""),
    "REVISION_INVALID": (400, ""),
    "REVISION_NOT_FOUND": (400, ""),
    "IDENTICAL_REVISIONS": (400, ""),
    "GIT_COMMAND_FAILED": (500, ""),
    "GIT_TIMEOUT": (500, ""),
    "GIT_UNAVAILABLE": (500, ""),
}


@router.post(
    "/change-impact/analyze",
    response_model=None,
    dependencies=[Depends(require_mutation_token)],
)
async def change_impact_analyze(
    payload: ChangeImpactRequest, request: Request, subject: str = RequireSubject
):
    from app.core.config import get_settings
    from app.core.rate_limit import check_rate_limit, client_ip

    ip = client_ip(request, trusted_proxy=get_settings().trusted_proxy)
    if not check_rate_limit(
        f"change-impact:{ip}",
        limit_per_minute=get_settings().rate_limit_per_minute,
    ):
        return _error(429, "RATE_LIMITED", "Too many analysis requests; retry later.")
    try:
        import asyncio

        analysis = await asyncio.to_thread(
            analyze_change_impact,
            repository_url=payload.repository_url,
            base_revision=payload.base_revision,
            target_revision=payload.target_revision,
        )
    except ChangeIntelError as exc:
        status, _ = _ERROR_MAP.get(exc.code, (400, ""))
        return _error(status, exc.code, exc.message, exc.details)

    analysis_generated_at = analysis.generated_at
    if payload.deployment_id:
        import asyncio

        record = await asyncio.to_thread(repo.get, payload.deployment_id)
        owner = subject if subject != LOCAL_SUBJECT else None
        if record is None or (owner is not None and record.owner_sub != owner):
            return _error(
                404,
                "NOT_FOUND",
                f"Deployment '{payload.deployment_id}' was not found.",
            )
        stored = analysis.model_dump(mode="json")
        await asyncio.to_thread(
            repo.save_artifacts,
            payload.deployment_id,
            change_intel=stored,
            updated_at=utc_now_iso(),
        )
        analysis.deployment_id = payload.deployment_id

    return JSONResponse(
        {
            "deployment_id": analysis.deployment_id,
            "is_demo": False,
            "label": None,
            "generated_at": analysis_generated_at,
            "analysis": analysis.to_ui(),
        }
    )


@router.get("/deploy/{deployment_id}/change-impact", response_model=None)
async def get_change_impact(deployment_id: str, subject: str = RequireSubject):
    import asyncio

    record = await asyncio.to_thread(repo.get, deployment_id)
    owner = subject if subject != LOCAL_SUBJECT else None
    if record is None or (owner is not None and record.owner_sub != owner):
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")
    change_intel = record.change_intel
    if change_intel is None:
        return _error(
            404,
            "CHANGE_INTEL_NOT_FOUND",
            f"Deployment '{deployment_id}' has no recorded change-intelligence analysis.",
        )
    analysis = change_intel.get("analysis", change_intel)
    return JSONResponse(
        {
            "deployment_id": deployment_id,
            "is_demo": bool(change_intel.get("is_demo", False)),
            "label": "DEMO/MOCK" if change_intel.get("is_demo") else None,
            "analysis": analysis,
        }
    )