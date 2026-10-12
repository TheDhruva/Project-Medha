"""Project-scoped GitHub repository connections (multi-user).

A project binds one authenticated owner to one ``owner/name`` repository +
branch. Projects are the unit of isolation: runs, proposals, and webhook
events route through the project, and cross-owner access is rejected.

Security properties:
- No credentials are ever accepted or stored here. A repository URL in a
  form is *configuration*, not proof of access: readability is proven by
  `git ls-remote` (verify endpoint) and by exact-SHA checkout at analysis
  time. Private repositories stay `private_unsupported` until a GitHub App
  (or equivalent) exists — see DECISIONS.md.
- Only `github.com` refs are accepted in V1 (explicit code otherwise).
- Owner identity comes from the verified Clerk subject (or the legacy
  single-operator subject), never from request bodies.
"""

from __future__ import annotations

import re
from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.api_token import require_mutation_token
from app.core.clerk_auth import LOCAL_SUBJECT, RequireSubject
from app.core.enums import DeploymentStatus, DeployMode, EventType
from app.core.events import event_bus, make_event, utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import (
    DeploymentRepository,
    ProjectConflictError,
    ProjectRepository,
)
from app.models.deployment import DeploymentRecord, ProjectRecord

logger = get_logger(__name__)
router = APIRouter(prefix="/api")
repo = DeploymentRepository()
projects = ProjectRepository()

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]{1,120}$")


class ProjectRefError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_github_repo_ref(raw: str) -> tuple[str, str, str]:
    """Parse `owner/name` or a github.com URL into (owner, name, canonical_url).

    Returns the lowercased `owner/name`, original-case owner/name, and the
    canonical clone URL. Anything else raises ProjectRefError — a URL in a
    form is never trusted as proof of access.
    """
    value = (raw or "").strip()
    if not value or len(value) > 300:
        raise ProjectRefError("INVALID_REPOSITORY_REF", "Repository reference is empty or too long.")
    candidate = value
    if "://" in candidate:
        lowered = candidate.lower()
        if "github.com" not in lowered.split("://", 1)[1].split("/", 1)[0]:
            raise ProjectRefError(
                "NON_GITHUB_REPOSITORY",
                "V1 supports github.com repositories only.",
            )
        path = candidate.split("://", 1)[1].split("/", 1)
        if len(path) < 2:
            raise ProjectRefError("INVALID_REPOSITORY_REF", "GitHub URL has no owner/name path.")
        candidate = path[1]
    candidate = candidate.strip().strip("/")
    if candidate.lower().endswith(".git"):
        candidate = candidate[: -len(".git")]
    parts = [p for p in candidate.split("/") if p]
    if len(parts) != 2:
        raise ProjectRefError(
            "INVALID_REPOSITORY_REF",
            "Repository must look like 'owner/name' or a github.com URL.",
        )
    owner, name = parts[0].strip(), parts[1].strip()
    if not _OWNER_RE.match(owner) or not _NAME_RE.match(name):
        raise ProjectRefError(
            "INVALID_REPOSITORY_REF",
            "Owner/name contain unsupported characters.",
        )
    repository = f"{owner.lower()}/{name.lower()}"
    canonical = f"https://github.com/{owner}/{name}.git"
    return owner, name, repository, canonical


def validate_branch_name(branch: str) -> str:
    value = (branch or "").strip()
    if (
        not value
        or not _BRANCH_RE.match(value)
        or value.startswith(("-", ".", "/"))
        or ".." in value
        or "//" in value
        or value.endswith(("/", ".lock"))
    ):
        raise ProjectRefError("INVALID_BRANCH", "Branch name is not acceptable.")
    return value


def _error(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def _owned_project(project_id: str, subject: str) -> ProjectRecord | None:
    project = projects.get(project_id)
    if project is None:
        return None
    owner = subject  # in off mode every project belongs to local-operator
    if project.owner_sub != owner:
        return None
    return project


class ProjectCreateBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    repository: str = Field(..., min_length=1, max_length=300)
    branch: str = Field(default="main", max_length=120)


class ProjectPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    branch: str | None = Field(default=None, max_length=120)


class ProjectRunBody(BaseModel):
    intent: str | None = Field(default=None, max_length=2000)
    target_revision: str | None = Field(default=None, max_length=100)
    target_host: str = Field(default="localhost", max_length=64)
    target_port: int = Field(default=8080, ge=1, le=65535)


@router.post("/projects", status_code=201, dependencies=[Depends(require_mutation_token)])
async def create_project(body: ProjectCreateBody, subject: str = RequireSubject):
    try:
        owner, name, repository, canonical = parse_github_repo_ref(body.repository)
        branch = validate_branch_name(body.branch or "main")
    except ProjectRefError as exc:
        return _error(400, exc.code, exc.message)
    now = utc_now_iso()
    project = ProjectRecord(
        project_id=f"prj_{uuid4().hex[:16]}",
        owner_sub=subject,
        name=body.name.strip(),
        provider="github",
        repo_owner=owner,
        repo_name=name,
        repository=repository,
        canonical_url=canonical,
        branch=branch,
        visibility="unverified",
        connection_status="pending",
        created_at=now,
        updated_at=now,
    )
    try:
        projects.create(project)
    except ProjectConflictError as exc:
        return _error(409, "PROJECT_EXISTS", str(exc))
    logger.info("Project created id=%s repo=%s owner=%s", project.project_id, repository, subject)
    return JSONResponse(project.to_api(), status_code=201)


@router.get("/projects")
async def list_projects(subject: str = RequireSubject):
    owner = subject if subject != LOCAL_SUBJECT else LOCAL_SUBJECT
    # In off mode all projects belong to local-operator; in clerk mode the
    # subject only ever sees its own rows (enforced by owner_sub match).
    items = projects.list_for_owner(subject if subject != LOCAL_SUBJECT else LOCAL_SUBJECT)
    _ = owner
    return JSONResponse({"projects": [p.to_api() for p in items], "total": len(items)})


@router.get("/projects/{project_id}")
async def get_project(project_id: str, subject: str = RequireSubject):
    project = _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    return JSONResponse(project.to_api())


@router.patch("/projects/{project_id}", dependencies=[Depends(require_mutation_token)])
async def update_project(project_id: str, body: ProjectPatchBody, subject: str = RequireSubject):
    project = _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    try:
        branch = validate_branch_name(body.branch) if body.branch is not None else None
    except ProjectRefError as exc:
        return _error(400, exc.code, exc.message)
    updated = projects.update(
        project_id,
        name=body.name.strip() if body.name is not None else None,
        branch=branch,
        updated_at=utc_now_iso(),
    )
    if updated is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    return JSONResponse(updated.to_api())


@router.post(
    "/projects/{project_id}/verify", dependencies=[Depends(require_mutation_token)]
)
async def verify_project(project_id: str, subject: str = RequireSubject):
    """Prove readability with `git ls-remote` — no credentials stored.

    Reachable → `connected`/`public`. Anything else stays honestly
    labelled (`failed`/`unverified`, or `private_unsupported` when the
    host answers but refuses), and the response says so.
    """
    project = _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    from app.services import git_service

    import asyncio

    sha = await asyncio.to_thread(git_service.ls_remote_sha, project.canonical_url, "HEAD")
    now = utc_now_iso()
    if sha:
        updated = projects.update(
            project_id,
            visibility="public",
            connection_status="connected",
            updated_at=now,
        )
        return JSONResponse(
            {"project": updated.to_api() if updated else project.to_api(),
             "reachable": True, "head_sha": sha}
        )
    updated = projects.update(
        project_id, visibility="unverified", connection_status="failed",
        updated_at=now,
    )
    return JSONResponse(
        {"project": updated.to_api() if updated else project.to_api(),
         "reachable": False,
         "reason": "Repository is unreachable or private. Private repositories "
                   "require a GitHub App (not yet implemented)."}
    )


@router.post(
    "/projects/{project_id}/disconnect", dependencies=[Depends(require_mutation_token)]
)
async def disconnect_project(project_id: str, subject: str = RequireSubject):
    project = _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    updated = projects.update(
        project_id, connection_status="disconnected", updated_at=utc_now_iso()
    )
    return JSONResponse(updated.to_api() if updated else project.to_api())


@router.delete(
    "/projects/{project_id}", dependencies=[Depends(require_mutation_token)]
)
async def delete_project(project_id: str, subject: str = RequireSubject):
    project = _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    projects.delete(project_id)
    # Run/proposal history is preserved; without the mapping, future webhook
    # events for this repository no longer route anywhere.
    return JSONResponse({"deleted": project_id})


@router.post(
    "/projects/{project_id}/runs",
    status_code=202,
    dependencies=[Depends(require_mutation_token)],
)
async def create_project_run(project_id: str, body: ProjectRunBody, subject: str = RequireSubject):
    """Start a real-mode analysis bound to this project (manual path)."""
    project = _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    if project.connection_status != "connected":
        return _error(
            409, "PROJECT_NOT_CONNECTED",
            f"Project is '{project.connection_status}'; verify the repository first.",
        )
    if body.target_host.strip().lower() not in {"localhost", "127.0.0.1", "::1"}:
        return _error(400, "INVALID_TARGET", "V1 target host must be localhost / 127.0.0.1")
    target_revision: str | None = None
    if body.target_revision:
        from app.services import git_service

        try:
            target_revision = git_service.normalize_commit_sha(body.target_revision)
        except Exception:
            return _error(400, "INVALID_SHA", "target_revision must be a 40-hex commit SHA.")

    from app.core.deploy_lock import DeployBusyError, try_acquire_real_deploy
    from app.workflow.planning import schedule_planning_pipeline

    deployment_id = f"dep_{uuid4().hex[:16]}"
    try:
        try_acquire_real_deploy(deployment_id)
    except DeployBusyError as exc:
        return _error(
            409, "DEPLOYMENT_BUSY",
            "Another real deployment is already running (V1 allows one at a time).",
            details={"deployment_id": exc.current_deployment_id},
        )
    now = utc_now_iso()
    record = DeploymentRecord(
        deployment_id=deployment_id,
        repository_url=project.canonical_url,
        mode=DeployMode.REAL,
        scenario=None,
        target_host=body.target_host.strip(),
        target_port=body.target_port,
        intent=body.intent or f"Project analysis ({project.repository}@{target_revision[:8] if target_revision else project.branch})",
        base_revision=None,
        target_revision=target_revision,
        status=DeploymentStatus.STARTED,
        current_stage=None,
        explain_simple="Project analysis accepted. Real pipeline starting.",
        explain_technical=f"deployment_id={deployment_id} · project={project_id} · is_demo=false",
        owner_sub=subject,
        project_id=project_id,
        created_at=now,
        updated_at=now,
        is_demo=False,
    )
    try:
        repo.create(record)
        created = make_event(
            deployment_id=deployment_id,
            event_type=EventType.DEPLOYMENT_CREATED,
            message="Project analysis created.",
            status=DeploymentStatus.STARTED.value,
            metadata={"project_id": project_id, "repository": project.repository},
            is_demo=False,
        )
        repo.add_event(created)
        await event_bus.publish(created)
        schedule_planning_pipeline(deployment_id, repo=repo)
        logger.info("Created project run project=%s deployment=%s", project_id, deployment_id)
    except Exception:
        from app.core.deploy_lock import release_real_deploy

        release_real_deploy(deployment_id)
        raise
    return JSONResponse(
        {"deployment_id": deployment_id, "status": DeploymentStatus.STARTED.value,
         "project_id": project_id, "mode": DeployMode.REAL.value, "is_demo": False},
        status_code=202,
    )
