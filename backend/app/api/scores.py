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

_SCORE_NAMES = (
    "code_quality",
    "security",
    "verification_confidence",
    "deployment_readiness",
    "performance",
    "optimization",
)


def _readiness_health(record, result: dict) -> str:
    """Health evidence relevant to deployment readiness.

    A pre-execution failure (verification, target, build) has no application
    health evidence; it must not be reported as a confirmed unhealthy app.
    """
    if record.is_demo:
        return "demo"
    mode = result.get("execution_mode")
    if mode in {"simulator", "simulator_fallback", "demo", "controlled_test"}:
        return "test_only"
    if mode != "real":
        return "unknown"
    readiness = result.get("readiness") if isinstance(result.get("readiness"), dict) else {}
    kind = result.get("kind")
    code = str(result.get("code") or "")
    if kind == "success" and readiness.get("status") == "ready":
        return "healthy"
    if kind == "failed" and (
        result.get("container") or code in {"READINESS_FAILED", "START_FAILED", "REAL_EXECUTION_FAILED"}
    ):
        return "unhealthy"
    return "unknown"


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": {}}},
    )


def _inputs_hash(record, verification, change_intel, repository_analysis,
                 result, health_status, support_code, execution_mode) -> str:
    canonical = json.dumps({
        "target": record.target_revision,
        "v": verification,
        "ci": change_intel,
        "ra": repository_analysis,
        "result": result,
        "health": health_status,
        "support": support_code,
        "mode": execution_mode,
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
    change_intel = record.change_intel if isinstance(record.change_intel, dict) else None
    analysis = change_intel.get("analysis", change_intel) if change_intel else None
    result = record.result if isinstance(record.result, dict) else {}
    repository_analysis = (
        result.get("repository_analysis")
        if isinstance(result.get("repository_analysis"), dict) else None
    )
    profile_confidence = None
    health_hints: list = []
    profile = result.get("profile") if isinstance(result, dict) else None
    if isinstance(profile, dict):
        stack = profile.get("inferred_stack", {})
        if isinstance(stack, dict):
            profile_confidence = stack.get("confidence")
            health_hints = stack.get("health_hints", []) or []
    execution_mode = result.get("execution_mode")
    deployment = result.get("deployment") if isinstance(result.get("deployment"), dict) else {}
    support_code = None
    if result.get("blocked_stage") == "analyze" and deployment.get("code"):
        support_code = str(deployment["code"])
    elif result.get("kind") == "success":
        # A successful run necessarily passed the support gate.
        support_code = "SUPPORTED"
    elif repository_analysis is not None and execution_mode in {
        "real", "simulator", "simulator_fallback", "demo", "controlled_test",
    }:
        # The support gate runs right after repository analysis. A run that
        # died earlier (e.g. clone failure) has no repository_analysis, so
        # target support was never established — it must read as
        # not_assessed, never as a pass for an operation that never ran.
        support_code = "SUPPORTED"
    health_status = _readiness_health(record, result)
    target_sha = ""
    if result.get("target_sha"):
        target_sha = str(result["target_sha"])
    elif record.target_revision:
        target_sha = str(record.target_revision)

    inputs_hash = _inputs_hash(
        record, verification, change_intel, repository_analysis, result,
        health_status, support_code, execution_mode,
    )
    previous = await asyncio.to_thread(scores.history, run_id=deployment_id)
    stored = {row["score_name"]: row for row in previous}
    if stored and all(
        name in stored
        and stored[name].get("version") == VERSION
        and stored[name].get("inputs_hash") == inputs_hash
        for name in _SCORE_NAMES
    ):
        out = {
            name: {
                "value": stored[name].get("value"),
                "version": stored[name].get("version"),
                "computed_at": stored[name].get("computed_at"),
                "inputs_hash": stored[name].get("inputs_hash"),
                "target_sha": stored[name].get("target_sha") or None,
                "evidence": stored[name].get("evidence") or {},
            }
            for name in _SCORE_NAMES
        }
        return JSONResponse({
            "deployment_id": deployment_id,
            "is_demo": record.is_demo,
            "label": "DEMO/MOCK" if record.is_demo else None,
            "scores": out,
        })

    now = utc_now_iso()
    computed = compute_all(
        verification=verification, critic=None, change_intel=analysis,
        support_code=support_code, profile_confidence=profile_confidence,
        health_hints=health_hints,
        runtime_measured=result.get("runtime_measured") if result else None,
        repository_analysis=repository_analysis, result=result,
        health_status=health_status, execution_mode=execution_mode,
        assessed_at=now, revision=target_sha or None,
    )
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
