"""Phase 2 Change Intelligence REST endpoints.

POST /api/change-impact/analyze          — deterministic live analysis over a local git repo
GET  /api/deploy/{id}/change-impact      — persisted analysis attached to a deployment
GET  /api/change-impact/demo/fixture     — canned demo fixture, clearly labelled DEMO/MOCK
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.changeintel.engine import analyze_change_impact
from app.changeintel.git_extract import ChangeIntelError
from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import DeploymentRepository
from app.demo.fixtures import change_intel_demo

logger = get_logger(__name__)
router = APIRouter(prefix="/api")
repo = DeploymentRepository()


class ChangeImpactRequest(BaseModel):
    repository_url: str
    base_revision: str
    target_revision: str
    deployment_id: Optional[str] = None


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


@router.post("/change-impact/analyze", response_model=None)
async def change_impact_analyze(payload: ChangeImpactRequest):
    try:
        analysis = analyze_change_impact(
            repository_url=payload.repository_url,
            base_revision=payload.base_revision,
            target_revision=payload.target_revision,
        )
    except ChangeIntelError as exc:
        status, _ = _ERROR_MAP.get(exc.code, (400, ""))
        return _error(status, exc.code, exc.message, exc.details)

    analysis_generated_at = analysis.generated_at
    if payload.deployment_id:
        record = repo.get(payload.deployment_id)
        if record is None:
            return _error(
                404,
                "NOT_FOUND",
                f"Deployment '{payload.deployment_id}' was not found.",
            )
        stored = analysis.model_dump(mode="json")
        repo.save_artifacts(
            deployment_id=payload.deployment_id,
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
async def get_change_impact(deployment_id: str):
    record = repo.get(deployment_id)
    if record is None:
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


@router.get("/change-impact/demo/fixture", response_model=None)
async def change_impact_demo_fixture():
    analysis = change_intel_demo()
    return JSONResponse(
        {
            "deployment_id": None,
            "is_demo": True,
            "label": "DEMO/MOCK",
            "generated_at": utc_now_iso(),
            "note": (
                "Demo fixture: canned change-impact results to illustrate the Phase 2 "
                "Change Intelligence UI. Not derived from a real repository."
            ),
            "analysis": analysis.to_ui(),
        }
    )