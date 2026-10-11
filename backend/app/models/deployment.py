from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import DeployMode, DeploymentStatus, ScenarioId
from app.core.repo_url import RepositoryUrlError, validate_repository_url


class TargetRef(BaseModel):
    host: str = Field(..., min_length=1)
    port: int = Field(..., ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def host_must_be_local(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("V1 target host must be localhost / 127.0.0.1")
        return value.strip()


class DeploymentRequest(BaseModel):
    repository_url: str = Field(..., min_length=1)
    mode: DeployMode
    scenario: ScenarioId | None = None
    target: TargetRef
    intent: str | None = Field(default=None, max_length=2000)
    base_revision: str | None = None
    target_revision: str | None = None

    @field_validator("repository_url")
    @classmethod
    def repository_url_must_be_safe(cls, value: str) -> str:
        try:
            return validate_repository_url(value)
        except RepositoryUrlError as exc:
            raise ValueError(f"{exc.code}: {exc.message}") from exc

    @field_validator("scenario", mode="before")
    @classmethod
    def normalize_scenario(cls, value: Any) -> Any:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            return value.strip().upper()
        return value

    @model_validator(mode="after")
    def require_scenario_for_demo(self) -> Self:
        if self.mode == DeployMode.DEMO and self.scenario is None:
            raise ValueError("scenario is required when mode=demo")
        return self

class DeploymentResponse(BaseModel):
    deployment_id: str
    status: DeploymentStatus
    mode: DeployMode
    is_demo: bool


class DeploymentRecord(BaseModel):
    deployment_id: str
    repository_url: str
    mode: DeployMode
    scenario: ScenarioId | None
    target_host: str
    target_port: int
    intent: str | None
    base_revision: str | None = None
    target_revision: str | None = None
    status: DeploymentStatus
    current_stage: str | None
    explain_simple: str | None = None
    explain_technical: str | None = None
    error_summary: str | None = None
    result: dict[str, Any] | None = None
    constraints: list[dict[str, Any]] | None = None
    negotiation: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    critic: dict[str, Any] | None = None
    graph: dict[str, Any] | None = None
    rollback: dict[str, Any] | None = None
    change_intel: dict[str, Any] | None = None
    ai: dict[str, Any] | None = None
    owner_sub: str | None = None
    project_id: str | None = None
    created_at: str
    updated_at: str
    is_demo: bool = True

    def to_api(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "status": self.status.value,
            "mode": self.mode.value,
            "is_demo": self.is_demo,
            "scenario": self.scenario.value if self.scenario else None,
            "repository_url": self.repository_url,
            "target": {"host": self.target_host, "port": self.target_port},
            "intent": self.intent,
            "base_revision": self.base_revision,
            "target_revision": self.target_revision,
            "current_stage": self.current_stage,
            "explain": {
                "simple": self.explain_simple,
                "technical": self.explain_technical,
            },
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error_summary": self.error_summary,
            "change_intel": self.change_intel,
            "ai": self.ai,
            "owner_sub": self.owner_sub,
            "project_id": self.project_id,
            "label": "DEMO/MOCK" if self.is_demo else None,
        }


class ProjectRecord(BaseModel):
    """One owner's connection to one GitHub repository + branch.

    No credentials are stored: readability is proven by `git ls-remote`
    (verify) and by exact-SHA checkout at analysis time. Visibility stays
    `unverified` until a check proves otherwise; `private_unsupported`
    labels repositories MEDHA cannot access without a GitHub App.
    """

    project_id: str
    owner_sub: str
    name: str
    provider: str = "github"
    repo_owner: str
    repo_name: str
    repository: str  # lowercased "owner/name"
    canonical_url: str
    branch: str = "main"
    visibility: str = "unverified"
    connection_status: str = "pending"
    created_at: str
    updated_at: str

    def to_api(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "provider": self.provider,
            "repo_owner": self.repo_owner,
            "repo_name": self.repo_name,
            "repository": self.repository,
            "canonical_url": self.canonical_url,
            "branch": self.branch,
            "visibility": self.visibility,
            "connection_status": self.connection_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class ProposalRecord(BaseModel):
    proposal_id: str
    repository: str
    branch: str
    base_sha: str | None = None
    target_sha: str
    deployment_id: str | None = None
    plan_hash: str | None = None
    plan: dict[str, Any] | None = None
    push: dict[str, Any] | None = None
    project_id: str | None = None
    status: str = "pending"
    created_by: str | None = None
    created_at: str
    decided_by: str | None = None
    decided_at: str | None = None
    execution_id: str | None = None
    idempotency_key: str

    def to_api(self) -> dict[str, Any]:
        return {
            "proposal_id": self.proposal_id,
            "repository": self.repository,
            "branch": self.branch,
            "base_sha": self.base_sha,
            "target_sha": self.target_sha,
            "deployment_id": self.deployment_id,
            "plan_hash": self.plan_hash,
            "plan": self.plan,
            "push": self.push,
            "project_id": self.project_id,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "decided_by": self.decided_by,
            "decided_at": self.decided_at,
            "execution_id": self.execution_id,
        }
