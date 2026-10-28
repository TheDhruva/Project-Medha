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

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.api_token import require_mutation_token
from app.core.clerk_auth import LOCAL_SUBJECT, RequireSubject
from app.core.enums import DeploymentStatus, DeployMode, EventType
from app.core.events import event_bus, make_event, utc_now_iso
from app.core.logging import get_logger
from app.core.repo_identity import (
    RepoIdentityError,
    canonical_repo_identity,
    validate_deploy_target,
)
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

_BRANCH_RE = re.compile(r"^[A-Za-z0-9_./-]{1,120}$")


class ProjectRefError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def parse_github_repo_ref(raw: str) -> tuple[str, str, str, str]:
    """Parse `owner/name` or a github.com URL into (owner, name, repository, canonical_url).

    Single authoritative identity lives in app.core.repo_identity; this
    wrapper preserves the established API-contract error codes. A URL in a
    form is never trusted as proof of access.
    """
    try:
        return canonical_repo_identity(raw)
    except RepoIdentityError as exc:
        raise ProjectRefError(exc.code, exc.message) from exc


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
    # Name defaults to the repository name when omitted; branch is
    # auto-detected from the remote default (via ls-remote --symref) when
    # omitted, falling back to "main" when detection is impossible.
    name: str | None = Field(default=None, max_length=80)
    repository: str = Field(..., min_length=1, max_length=300)
    branch: str | None = Field(default=None, max_length=120)


async def _resolve_branch(canonical_url: str, requested: str | None) -> str:
    """Explicit branch when given (validated); otherwise the remote default."""
    if requested is not None and requested.strip():
        return validate_branch_name(requested)
    from app.services import git_service

    import asyncio

    detected = await asyncio.to_thread(git_service.ls_remote_default_branch, canonical_url)
    if detected:
        try:
            return validate_branch_name(detected)
        except ProjectRefError:
            pass
    return "main"


class ProjectPatchBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    branch: str | None = Field(default=None, max_length=120)
    deploy_target: str | None = Field(default=None, max_length=120)


class ProjectRunBody(BaseModel):
    intent: str | None = Field(default=None, max_length=2000)
    base_revision: str | None = Field(default=None, max_length=100)
    target_revision: str | None = Field(default=None, max_length=100)
    target_host: str = Field(default="localhost", max_length=64)
    target_port: int = Field(default=8080, ge=1, le=65535)
    deployment_target: str | None = Field(default=None, max_length=120)
    # Optional link to the deployment this run retries: makes a retry a
    # traceable attempt without touching the prior run's diagnostics.
    retry_of: str | None = Field(default=None, max_length=64)


@router.post("/projects", status_code=201, dependencies=[Depends(require_mutation_token)])
async def create_project(body: ProjectCreateBody, subject: str = RequireSubject):
    try:
        owner, name, repository, canonical = parse_github_repo_ref(body.repository)
        branch = await _resolve_branch(canonical, body.branch)
    except ProjectRefError as exc:
        return _error(400, exc.code, exc.message)
    display_name = (body.name or "").strip() or name
    if len(display_name) > 80:
        return _error(400, "INVALID_NAME", "Connection name is too long (max 80).")
    # Idempotent reconnect: the same authorized user resolving the same
    # canonical identity gets their existing project (200) instead of a
    # duplicate row. The DB unique index remains the concurrency guard —
    # this pre-check is a fast path, never the sole enforcement.
    existing = projects.find_by_owner_repo(subject, repository)
    if existing is not None:
        return JSONResponse(existing.to_api(), status_code=200)
    now = utc_now_iso()
    project = ProjectRecord(
        project_id=f"prj_{uuid4().hex[:16]}",
        owner_sub=subject,
        name=display_name,
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
    except ProjectConflictError:
        # Lost a race: re-read the winner owned by this subject. A row owned
        # by someone else never leaks — return the contract 409 instead.
        winner = projects.find_by_owner_repo(subject, repository)
        if winner is not None:
            return JSONResponse(winner.to_api(), status_code=200)
        return _error(
            409, "PROJECT_EXISTS",
            f"Repository '{repository}' is already connected for this owner.",
            details={"repository": repository},
        )
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
        # Empty string clears the stored target (back to auto-resolution);
        # None leaves it unchanged; any other value is validated + stored.
        if body.deploy_target is None:
            deploy_target = None
            clear_target = False
        elif not body.deploy_target.strip():
            deploy_target = None
            clear_target = True
        else:
            deploy_target = validate_deploy_target(body.deploy_target)
            clear_target = False
    except ProjectRefError as exc:
        return _error(400, exc.code, exc.message)
    except RepoIdentityError as exc:
        return _error(400, exc.code, exc.message)
    updated = projects.update(
        project_id,
        name=body.name.strip() if body.name is not None else None,
        branch=branch,
        deploy_target=deploy_target,
        clear_deploy_target=clear_target,
        updated_at=utc_now_iso(),
    )
    if updated is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    return JSONResponse(updated.to_api())


@router.get("/projects/{project_id}/targets")
async def project_targets(project_id: str, subject: str = RequireSubject):
    """Current deployment target plus last observed candidates.

    Candidates come from the latest run's persisted result (no extra clone):
    empty with an honest note when no run has reported them yet. Setting the
    target is PATCH /projects/{id} {deploy_target}; it takes effect on the
    next run and never leaks across projects.
    """
    project = _owned_project(project_id, subject)
    if project is None:
        return _error(404, "NOT_FOUND", f"Project '{project_id}' was not found.")
    candidates: list[dict] = []
    relationship: str | None = None
    source_run: str | None = None
    try:
        runs, _ = repo.list(project_id=project_id, limit=20, offset=0)
        for run in runs:
            result = run.result if isinstance(run.result, dict) else None
            detail = (result or {}).get("target_selection") if result else None
            if isinstance(detail, dict) and detail.get("candidates"):
                candidates = detail["candidates"]
                relationship = detail.get("relationship")
                source_run = run.deployment_id
                break
    except Exception:
        candidates = []
    return JSONResponse({
        "project_id": project_id,
        "deploy_target": project.deploy_target,
        "candidates": candidates,
        "relationship": relationship,
        "source_run": source_run,
        "note": (
            "No candidate information recorded yet; run an analysis first."
            if not candidates else
            "V1 executes exactly one selected service; coordinated multi-service deployment is unsupported."
        ),
    })


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
                   "require a configured GitHub App (GITHUB_APP_ID + "
                   "GITHUB_APP_PRIVATE_KEY + GITHUB_APP_INSTALLATION_ID); see "
                   "docs/REAL_EXECUTION_RUNBOOK.md."}
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
    # Active runs keep their history rows; refusing deletion while a run is
    # in flight avoids orphaning an executing pipeline. Disconnect instead,
    # or retry once the run settles.
    if repo.has_active_runs(project_id):
        return _error(
            409, "ACTIVE_RUNS",
            "This project has a run still in flight; deletion is blocked "
            "until it finishes. Disconnect the repository instead, or retry "
            "after the run settles.",
        )
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
    """Start a project-bound run using the stored repository configuration.

    Omitting both revisions runs a full analysis (backend resolves HEAD);
    providing base/target revisions (40-hex SHAs) runs a change analysis.
    """
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
    try:
        raw_target = body.deployment_target
        # Blank/whitespace means "no explicit target for this run": fall
        # back to the saved project target instead of persisting ".".
        deployment_target = (
            validate_deploy_target(raw_target)
            if raw_target is not None and raw_target.strip()
            else None
        )
    except RepoIdentityError as exc:
        return _error(400, exc.code, exc.message)
    if deployment_target is not None:
        # Persisted on the project: scoped to this project only, takes
        # effect on this run and every later one until changed again.
        project = projects.update(
            project_id, deploy_target=deployment_target, updated_at=utc_now_iso()
        ) or project
    target_revision: str | None = None
    if body.target_revision:
        from app.services import git_service

        try:
            target_revision = git_service.normalize_commit_sha(body.target_revision)
        except Exception:
            return _error(400, "INVALID_SHA", "target_revision must be a 40-hex commit SHA.")
    base_revision: str | None = None
    if body.base_revision:
        from app.services import git_service

        try:
            base_revision = git_service.normalize_commit_sha(body.base_revision)
        except Exception:
            return _error(400, "INVALID_SHA", "base_revision must be a 40-hex commit SHA.")

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
        base_revision=base_revision,
        target_revision=target_revision,
        status=DeploymentStatus.STARTED,
        current_stage=None,
        explain_simple="Project analysis accepted. Real pipeline starting.",
        explain_technical=f"deployment_id={deployment_id} · project={project_id} · is_demo=false"
        + (f" · retry_of={body.retry_of}" if body.retry_of else ""),
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
            metadata={
                "project_id": project_id,
                "repository": project.repository,
                **({"retry_of": body.retry_of} if body.retry_of else {}),
            },
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
         "project_id": project_id, "mode": DeployMode.REAL.value, "is_demo": False,
         "deploy_target": project.deploy_target, "retry_of": body.retry_of},
        status_code=202,
    )
