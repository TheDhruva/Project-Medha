"""Versioned product scores API (Phase 6).

GET /api/deploy/{id}/scores — compute (deterministic), persist snapshots,
  return the four scores with version, timestamp, inputs hash, and evidence.
GET /api/scores/history — queryable score history (by run or project).
"""

from __future__ import annotations

import asyncio
import hashlib
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.api_token import require_mutation_token
from app.core.clerk_auth import LOCAL_SUBJECT, RequireSubject
from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import (
    DeploymentRepository,
    ProjectRepository,
    ScoreRepository,
)
from app.scores.compute import VERSION, compute_all

logger = get_logger(__name__)
router = APIRouter(prefix="/api")
repo = DeploymentRepository()
scores = ScoreRepository()


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": {}}},
    )


def _inputs_hash(record, verification, critic, change_intel) -> str:
    canonical = json.dumps({
        "target": record.target_revision,
        "v": verification, "c": critic, "ci": change_intel,
        "score_version": VERSION,
    }, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@router.get("/deploy/{deployment_id}/scores", response_model=None)
async def get_scores(deployment_id: str, subject: str = RequireSubject):
    record = await asyncio.to_thread(repo.get, deployment_id)
    owner = subject if subject != LOCAL_SUBJECT else None
    if record is None or (owner is not None and record.owner_sub != owner):
        if record is not None and record.project_id and owner is not None:
            project = await asyncio.to_thread(
                ProjectRepository().get, record.project_id)
            if project is None or project.owner_sub != owner:
                return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")
        elif record is None or owner is not None:
            return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")
    verification = record.verification if isinstance(record.verification, dict) else None
    critic = record.critic if isinstance(record.critic, dict) else None
    change_intel = record.change_intel if isinstance(record.change_intel, dict) else None
    analysis = change_intel.get("analysis", change_intel) if change_intel else None
    support_code = None
    profile_confidence = None
    health_hints: list = []
    result = record.result if isinstance(record.result, dict) else {}
    profile = result.get("profile") if isinstance(result, dict) else None
    if isinstance(profile, dict):
        stack = profile.get("inferred_stack", {})
        if isinstance(stack, dict):
            profile_confidence = stack.get("confidence")
            health_hints = stack.get("health_hints", []) or []
    computed = compute_all(
        verification=verification, critic=critic, change_intel=analysis,
        support_code=support_code, profile_confidence=profile_confidence,
        health_hints=health_hints,
        runtime_measured=result.get("runtime_measured") if result else None,
    )
    inputs_hash = _inputs_hash(record, verification, critic, change_intel)
    now = utc_now_iso()
    target_sha = ""
    if isinstance(result, dict) and result.get("target_sha"):
        target_sha = str(result["target_sha"])
    elif record.target_revision:
        target_sha = str(record.target_revision)
    out: dict = {}
    for name, entry in computed.items():
        await asyncio.to_thread(
            scores.save, run_id=deployment_id, score_name=name,
            value=entry["value"], version=VERSION, computed_at=now,
            inputs_hash=inputs_hash, target_sha=target_sha,
            project_id=record.project_id, evidence=entry["evidence"],
        )
        out[name] = {
            "value": entry["value"],
            "version": VERSION,
            "computed_at": now,
            "inputs_hash": inputs_hash,
            "target_sha": target_sha or None,
            "evidence": entry["evidence"],
        }
    return JSONResponse({
        "deployment_id": deployment_id,
        "is_demo": record.is_demo,
        "label": "DEMO/MOCK" if record.is_demo else None,
        "scores": out,
    })


@router.get("/scores/history", response_model=None)
async def scores_history(
    run_id: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    subject: str = RequireSubject,
):
    if project_id:
        project = await asyncio.to_thread(ProjectRepository().get, project_id)
        if project is None or (subject != LOCAL_SUBJECT and project.owner_sub != subject):
            return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    history = await asyncio.to_thread(
        scores.history, project_id=project_id, run_id=run_id, limit=limit)
    if subject != LOCAL_SUBJECT and not project_id and not run_id:
        history = [h for h in history if h.get("project_id") is None]
    return JSONResponse({"scores": history, "total": len(history)})
