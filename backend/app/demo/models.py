from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.enums import DeploymentStatus, ScenarioId, StageId


class DemoStep(BaseModel):
    """One observable pipeline tick emitted as an SSE event."""

    event_type: str
    message: str
    stage: StageId | None = None
    status: str | None = None
    level: str = "info"
    delay_after: float = 0.35
    explain_simple: str | None = None
    explain_technical: str | None = None
    deployment_status: DeploymentStatus | None = None
    # Structured UI patches (merged by frontend / persisted as artifacts)
    data: dict[str, Any] = Field(default_factory=dict)


class DemoScenarioDef(BaseModel):
    id: ScenarioId
    name: str
    description: str
    expected_final_status: DeploymentStatus
    steps: list[DemoStep]


class DemoArtifacts(BaseModel):
    """Persisted demo snapshot for REST endpoints after/during a run."""

    constraints: list[dict[str, Any]] = Field(default_factory=list)
    negotiation: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    critic: dict[str, Any] | None = None
    graph: dict[str, Any] = Field(default_factory=lambda: {"nodes": [], "edges": []})
    rollback: dict[str, Any] | None = None
    result: dict[str, Any] | None = None
    agents: list[dict[str, Any]] = Field(default_factory=list)
    selected_node_id: str | None = None
