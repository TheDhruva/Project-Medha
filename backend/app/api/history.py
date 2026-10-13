"""Commit history API (Phase 7). Real ancestry only; shallow honestly labelled."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from app.core.api_token import require_mutation_token
from app.core.clerk_auth import LOCAL_SUBJECT, RequireSubject
from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import CommitRepository, ProjectRepository
from app.services import history_service
from app.services.git_service import GitAcquireError, acquire_repository
from app.services.workspace import deployment_workspace

logger = get_logger(__name__)
router = APIRouter(prefix="/api")
commits = CommitRepository()


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": {}}},
    )


def _owned_project(project_id: str, subject: str):
    project = ProjectRepository().get(project_id)
    if project is None:
        return None
    if subject != LOCAL_SUBJECT and project.owner_sub != subject:
        return None
    return project


@router.get("/projects/{project_id}/history", response_model=None)
async def project_history(
    project_id: str, subject: str = RequireSubject,
    limit: int = Query(default=50, ge=1, le=200),
    since: str | None = Query(default=None),
):
    project = await asyncio.to_thread(_owned_project, project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    try:
        acquisition = await asyncio.to_thread(
            acquire_repository,
            deployment_id=f"history_{project_id}",
            repository_url=project.canonical_url,
            ref_sha=None,
        )
    except GitAcquireError as exc:
        return _error(400, exc.code, exc.message)
    except Exception:  # noqa: BLE001 - honest failure
        return _error(500, "HISTORY_UNAVAILABLE", "Commit history could not be retrieved.")
    try:
        entries, partial = await asyncio.to_thread(
            history_service.list_history, acquisition.path, limit=limit)
    except history_service.HistoryError as exc:
        return _error(500, exc.code, exc.message)
    now = utc_now_iso()
    out = []
    for entry in entries:
        try:
            await asyncio.to_thread(
                commits.upsert, project_id=project_id, sha=entry.sha,
                parents=entry.parents, author=entry.author,
                committed_at=entry.committed_at, message=entry.message,
                branch=project.branch, recorded_at=now)
        except Exception:  # noqa: BLE001 - persistence advisory
            pass
        out.append({
            "sha": entry.sha, "parents": entry.parents, "author": entry.author,
            "committed_at": entry.committed_at, "message": entry.message,
            "branch": project.branch,
            "github_url": history_service.github_commit_url(
                project.canonical_url, entry.sha),
        })
    return JSONResponse({
        "project_id": project_id, "commits": out,
        "partial": partial, "truncated": partial,
        "shallow": acquisition.method == "shallow_clone",
    })


@router.get("/projects/{project_id}/history/{sha}", response_model=None)
async def commit_detail(project_id: str, sha: str, subject: str = RequireSubject):
    project = await asyncio.to_thread(_owned_project, project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    candidate = (sha or "").strip().lower()
    if len(candidate) != 40 or any(c not in "0123456789abcdef" for c in candidate):
        return _error(400, "INVALID_SHA", "Commit SHA must be 40-char hex.")
    try:
        acquisition = await asyncio.to_thread(
            acquire_repository,
            deployment_id=f"history_{project_id}_{candidate[:12]}",
            repository_url=project.canonical_url,
            ref_sha=candidate,
        )
    except GitAcquireError as exc:
        return _error(400, exc.code, exc.message)
    except Exception:  # noqa: BLE001
        return _error(500, "HISTORY_UNAVAILABLE", "Commit detail could not be retrieved.")
    try:
        summary = await asyncio.to_thread(
            history_service.changed_files_summary, acquisition.path, candidate)
    except history_service.HistoryError as exc:
        return _error(500, exc.code, exc.message)
    summary["github_url"] = history_service.github_commit_url(
        project.canonical_url, candidate)
    return JSONResponse(summary)
