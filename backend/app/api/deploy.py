from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.core.enums import (
    TERMINAL_EVENT_TYPES,
    DeployMode,
    DeploymentStatus,
    EventType,
)
from app.core.events import event_bus, make_event, utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import DeploymentRepository
from app.demo.runner import schedule_demo_runner
from app.demo.scenarios import list_scenarios
from app.models.deployment import DeploymentRecord, DeploymentRequest, DeploymentResponse
from app.workflow.planning import schedule_planning_pipeline

logger = get_logger(__name__)
router = APIRouter(prefix="/api")
repo = DeploymentRepository()

TERMINAL_TYPES = TERMINAL_EVENT_TYPES


def _error(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def _parse_ts(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _compute_duration_seconds(created_at: str, updated_at: str) -> float | None:
    created = _parse_ts(created_at)
    updated = _parse_ts(updated_at)
    if created is None or updated is None:
        return None
    return round(max(0.0, (updated - created).total_seconds()), 1)


def _run_summary(record: DeploymentRecord) -> dict:
    change_intel = record.change_intel or {}
    risk: str | None = None
    if isinstance(change_intel, dict) and isinstance(change_intel.get("risk"), dict):
        risk = change_intel["risk"].get("level")
    result = record.result or {}
    return {
        "deployment_id": record.deployment_id,
        "status": record.status.value,
        "mode": record.mode.value,
        "is_demo": record.is_demo,
        "label": "DEMO/MOCK" if record.is_demo else None,
        "scenario": record.scenario.value if record.scenario else None,
        "repository_url": record.repository_url,
        "intent": record.intent,
        "base_revision": record.base_revision,
        "target_revision": record.target_revision,
        "current_stage": record.current_stage,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "duration_seconds": _compute_duration_seconds(record.created_at, record.updated_at),
        "risk": risk,
        "result_kind": result.get("kind") if isinstance(result, dict) else None,
        "error_summary": record.error_summary,
    }


@router.get("/demo/scenarios")
async def demo_scenarios():
    return JSONResponse(
        {
            "is_demo": True,
            "label": "DEMO/MOCK",
            "scenarios": list_scenarios(),
            "note": (
                "Demo Mode simulates deployment behavior and is not evidence of real "
                "infrastructure execution."
            ),
        }
    )


@router.get("/deploys")
async def list_deployments(
    status: str | None = Query(default=None),
    mode: str | None = Query(default=None),
    repository: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    if mode is not None and mode not in {DeployMode.DEMO.value, DeployMode.REAL.value}:
        return _error(400, "INVALID_MODE", f"mode must be 'demo' or 'real', got '{mode}'")
    records, total = repo.list(
        status=status, mode=mode, repository=repository, limit=limit, offset=offset
    )
    return JSONResponse(
        {
            "runs": [_run_summary(r) for r in records],
            "total": total,
            "limit": limit,
            "offset": offset,
            "filters": {"status": status, "mode": mode, "repository": repository},
        }
    )


@router.post("/deploy", status_code=202, response_model=DeploymentResponse)
async def create_deployment(payload: DeploymentRequest):
    if payload.mode == DeployMode.DEMO and payload.scenario is None:
        return _error(
            400,
            "SCENARIO_REQUIRED",
            "scenario is required when mode=demo",
        )

    deployment_id = f"dep_{uuid4().hex[:16]}"
    now = utc_now_iso()
    is_demo = payload.mode == DeployMode.DEMO

    if not is_demo:
        from app.core.deploy_lock import DeployBusyError, try_acquire_real_deploy

        try:
            try_acquire_real_deploy(deployment_id)
        except DeployBusyError as exc:
            return _error(
                409,
                "DEPLOYMENT_BUSY",
                "Another real deployment is already running (V1 allows one at a time).",
                details={
                    "busy": True,
                    "deployment_id": exc.current_deployment_id,
                    "limit": "one_real_deployment_at_a_time",
                },
            )

    if is_demo:
        explain_simple = "Deployment accepted. DEMO pipeline is starting."
        explain_technical = (
            f"deployment_id={deployment_id} · workflow=demo · "
            f"scenario={payload.scenario.value if payload.scenario else None} · is_demo=true"
        )
        created_message = "DEMO deployment created."
    else:
        explain_simple = (
            "Deployment accepted. Real pipeline starting "
            "(analyze → CNP → verify → local execute)."
        )
        explain_technical = (
            f"deployment_id={deployment_id} · workflow=planning · phases=10-12 · is_demo=false"
        )
        created_message = "Real-mode deployment created."

    record = DeploymentRecord(
        deployment_id=deployment_id,
        repository_url=payload.repository_url,
        mode=payload.mode,
        scenario=payload.scenario,
        target_host=payload.target.host,
        target_port=payload.target.port,
        intent=payload.intent,
        base_revision=payload.base_revision,
        target_revision=payload.target_revision,
        status=DeploymentStatus.STARTED,
        current_stage=None,
        explain_simple=explain_simple,
        explain_technical=explain_technical,
        created_at=now,
        updated_at=now,
        is_demo=is_demo,
    )
    try:
        repo.create(record)

        created = make_event(
            deployment_id=deployment_id,
            event_type=EventType.DEPLOYMENT_CREATED,
            message=created_message,
            status=DeploymentStatus.STARTED.value,
            metadata={
                "scenario": payload.scenario.value if payload.scenario else None,
                "repository_url": payload.repository_url,
                "mode": payload.mode.value,
                "simple": explain_simple,
                "technical": explain_technical,
                "label": "DEMO/MOCK" if is_demo else None,
            },
            is_demo=is_demo,
        )
        repo.add_event(created)
        await event_bus.publish(created)

        if is_demo:
            assert payload.scenario is not None
            schedule_demo_runner(deployment_id, payload.scenario, repo=repo)
            logger.info("Created demo deployment_id=%s scenario=%s", deployment_id, payload.scenario)
        else:
            schedule_planning_pipeline(deployment_id, repo=repo)
            logger.info("Created real planning deployment_id=%s", deployment_id)
    except Exception:
        if not is_demo:
            from app.core.deploy_lock import release_real_deploy

            release_real_deploy(deployment_id)
        raise

    return DeploymentResponse(
        deployment_id=deployment_id,
        status=DeploymentStatus.STARTED,
        mode=payload.mode,
        is_demo=is_demo,
    )


@router.get("/deploy/{deployment_id}")
async def get_deployment(deployment_id: str):
    record = repo.get(deployment_id)
    if record is None:
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")
    return JSONResponse(record.to_api())


@router.get("/deploy/{deployment_id}/events")
async def stream_events(deployment_id: str, request: Request):
    record = repo.get(deployment_id)
    if record is None:
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")

    async def event_generator():
        for event in repo.list_events(deployment_id):
            payload = json.dumps(event.to_sse_payload())
            yield f"data: {payload}\n\n"
            if event.event_type in TERMINAL_TYPES:
                return

        queue = await event_bus.subscribe(deployment_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                    continue

                payload = json.dumps(event.to_sse_payload())
                yield f"data: {payload}\n\n"
                if event.event_type in TERMINAL_TYPES:
                    break
        finally:
            await event_bus.unsubscribe(deployment_id, queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/deploy/{deployment_id}/constraints", response_model=None)
async def get_constraints(deployment_id: str):
    record = repo.get(deployment_id)
    if record is None:
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")

    negotiation = record.negotiation or {
        "rounds_used": 0,
        "max_rounds": 3,
        "status": "pending",
        "conflicts_resolved": [],
        "resolution_methods": [],
    }
    return JSONResponse(
        {
            "deployment_id": deployment_id,
            "is_demo": record.is_demo,
            "label": "DEMO/MOCK" if record.is_demo else None,
            "constraints": record.constraints or [],
            "negotiation": negotiation,
        }
    )


@router.get("/deploy/{deployment_id}/graph", response_model=None)
async def get_graph(deployment_id: str):
    record = repo.get(deployment_id)
    if record is None:
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")
    return JSONResponse(
        {
            "deployment_id": deployment_id,
            "is_demo": record.is_demo,
            "label": "DEMO/MOCK" if record.is_demo else None,
            "graph": record.graph or {"nodes": [], "edges": []},
            "rollback": record.rollback,
        }
    )


@router.get("/deploy/{deployment_id}/verification", response_model=None)
async def get_verification(deployment_id: str):
    record = repo.get(deployment_id)
    if record is None:
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")
    return JSONResponse(
        {
            "deployment_id": deployment_id,
            "is_demo": record.is_demo,
            "label": "DEMO/MOCK" if record.is_demo else None,
            "verification": record.verification,
            "critic": record.critic,
        }
    )


@router.get("/deploy/{deployment_id}/rollback", response_model=None)
async def get_rollback(deployment_id: str):
    record = repo.get(deployment_id)
    if record is None:
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")
    return JSONResponse(
        {
            "deployment_id": deployment_id,
            "is_demo": record.is_demo,
            "rollback": record.rollback,
        }
    )


@router.get("/deploy/{deployment_id}/execution", response_model=None)
async def get_execution(deployment_id: str):
    record = repo.get(deployment_id)
    if record is None:
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")
    return JSONResponse(
        {
            "deployment_id": deployment_id,
            "is_demo": record.is_demo,
            "result": record.result,
            "graph": record.graph or {"nodes": [], "edges": []},
            "rollback": record.rollback,
        }
    )


@router.get("/deploy/{deployment_id}/logs")
async def get_logs(
    deployment_id: str,
    limit: int = Query(default=200, ge=1, le=2000),
):
    record = repo.get(deployment_id)
    if record is None:
        return _error(404, "NOT_FOUND", f"Deployment '{deployment_id}' was not found.")

    events = repo.list_events(deployment_id, limit=limit)
    lines = [
        {
            "ts": event.ts,
            "level": event.level,
            "source": event.stage or "system",
            "message": event.message,
            "type": event.event_type,
            "stage": event.stage,
            "status": event.status,
            "is_demo": event.is_demo,
        }
        for event in events
    ]
    return JSONResponse(
        {
            "deployment_id": deployment_id,
            "is_demo": record.is_demo,
            "label": "DEMO/MOCK" if record.is_demo else None,
            "lines": lines,
        }
    )
