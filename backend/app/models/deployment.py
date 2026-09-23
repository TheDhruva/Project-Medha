from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.enums import DeployMode, DeploymentStatus, ScenarioId


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
    intent: str | None = None
    base_revision: str | None = None
    target_revision: str | None = None

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
            "label": "DEMO/MOCK" if self.is_demo else None,
        }
