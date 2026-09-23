"""Shared domain models for Phases 4–6 (analysis, specialists, CNP)."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ConstraintType(str, Enum):
    PORT_CLAIM = "PORT_CLAIM"
    ENV_VAR = "ENV_VAR"
    VOLUME_MOUNT = "VOLUME_MOUNT"
    NETWORK_POLICY = "NETWORK_POLICY"
    SECURITY_POLICY = "SECURITY_POLICY"
    EXEC_ORDER = "EXEC_ORDER"


class Priority(str, Enum):
    SECURITY = "SECURITY"
    RESOURCE = "RESOURCE"
    DEPENDENCY = "DEPENDENCY"
    PREFERENCE = "PREFERENCE"


PRIORITY_RANK = {
    Priority.SECURITY: 4,
    Priority.RESOURCE: 3,
    Priority.DEPENDENCY: 2,
    Priority.PREFERENCE: 1,
}


class ConstraintStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    CONFLICT = "conflict"


class ServiceHint(BaseModel):
    name: str
    role: str
    evidence_paths: list[str] = Field(default_factory=list)
    suggested_port: int | None = None


class InferredStack(BaseModel):
    services: list[ServiceHint] = Field(default_factory=list)
    language_runtime: str | None = None
    has_dockerfile: bool = False
    has_compose: bool = False
    package_managers: list[str] = Field(default_factory=list)
    suggested_ports: list[int] = Field(default_factory=list)
    confidence: float = 0.5
    manifests_examined: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class ApplicationProfile(BaseModel):
    """Structured result of repository analysis (Phase 4)."""

    profile_id: str = Field(default_factory=lambda: f"prof_{uuid4().hex[:12]}")
    deployment_id: str
    repository_url: str
    workspace_path: str
    intent: str | None = None
    target_host: str
    target_port: int
    inferred_stack: InferredStack
    created_at: str = Field(default_factory=_utc_now)
    is_demo: bool = False

    def to_public(self) -> dict[str, Any]:
        return self.model_dump()


class Constraint(BaseModel):
    constraint_id: str
    type: ConstraintType
    priority: Priority
    source_agent: str
    service: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    status: ConstraintStatus = ConstraintStatus.PROPOSED
    is_demo: bool = False

    def resource_key(self) -> str:
        """Grouping key for conflict detection."""
        p = self.payload
        if self.type == ConstraintType.PORT_CLAIM:
            return f"port:{p.get('key') or p.get('port')}"
        if self.type == ConstraintType.ENV_VAR:
            return f"env:{p.get('key')}"
        if self.type == ConstraintType.VOLUME_MOUNT:
            return f"vol:{p.get('host_path') or p.get('host') or p.get('container_path')}"
        if self.type == ConstraintType.NETWORK_POLICY:
            return f"policy:{p.get('rule') or p.get('network') or 'default'}"
        if self.type == ConstraintType.SECURITY_POLICY:
            return f"policy:{p.get('rule')}"
        if self.type == ConstraintType.EXEC_ORDER:
            return f"order:{p.get('before')}->{p.get('after')}"
        return f"{self.type.value}:{self.constraint_id}"

    def to_ui(self) -> dict[str, Any]:
        summary = self.payload.get("summary") or f"{self.type.value} from {self.source_agent}"
        detail = self.payload.get("detail") or str(self.payload)
        return {
            "id": self.constraint_id,
            "constraint_id": self.constraint_id,
            "type": self.type.value,
            "priority": self.priority.value,
            "sourceAgent": self.source_agent,
            "source_agent": self.source_agent,
            "service": self.service,
            "summary": summary,
            "detail": detail,
            "status": self.status.value,
            "payload": self.payload,
            "alternatives": self.alternatives,
            "technical": {"payload": self.payload},
            "is_demo": self.is_demo,
        }


class AgentResult(BaseModel):
    agent: str
    ok: bool
    started_at: str
    finished_at: str
    summary: str
    artifacts: dict[str, Any] = Field(default_factory=dict)
    constraints: list[Constraint] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    is_demo: bool = False


class ConflictRecord(BaseModel):
    conflict_id: str
    constraint_ids: list[str]
    reason: str
    priority_span: list[str] = Field(default_factory=list)
    resource_key: str | None = None


class DecisionRecord(BaseModel):
    conflict_id: str
    method: str  # priority | alternative | llm_mediation | deterministic_tiebreak
    winner_ids: list[str] = Field(default_factory=list)
    loser_ids: list[str] = Field(default_factory=list)
    rationale: str
    updates: list[dict[str, Any]] = Field(default_factory=list)


class NegotiationResult(BaseModel):
    deployment_id: str
    status: str  # pending | resolved | failed | exhausted
    rounds_used: int = 0
    max_rounds: int = 3
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    decisions: list[DecisionRecord] = Field(default_factory=list)
    final_constraints: list[Constraint] = Field(default_factory=list)
    is_demo: bool = False

    def to_ui(self) -> dict[str, Any]:
        methods = [d.method for d in self.decisions]
        resolved = [d.conflict_id for d in self.decisions]
        last = self.decisions[-1] if self.decisions else None
        return {
            "title": "CONSTRAINT NEGOTIATION",
            "conflictSummary": (
                self.conflicts[0].reason if self.conflicts else "No conflicting claims detected"
            ),
            "round": max(1, self.rounds_used),
            "maxRounds": self.max_rounds,
            "rounds_used": self.rounds_used,
            "max_rounds": self.max_rounds,
            "status": self.status if self.status != "pending" else "resolved",
            "resolution": last.rationale if last else "Constraint set accepted as proposed",
            "method": last.method.upper() if last else "VALIDATE",
            "involvedConstraintIds": [
                cid for c in self.conflicts for cid in c.constraint_ids
            ]
            or [c.constraint_id for c in self.final_constraints],
            "simpleExplanation": (
                last.rationale
                if last
                else "All specialist constraints were compatible."
            ),
            "technicalNotes": [
                f"rounds_used={self.rounds_used}",
                f"status={self.status}",
                f"conflicts={len(self.conflicts)}",
                f"methods={methods}",
            ],
            "conflicts_resolved": resolved,
            "resolution_methods": methods,
            "is_demo": self.is_demo,
        }


class NegotiatedPlan(BaseModel):
    """Output of Phases 4–6; execution deferred to Phase 7+."""

    deployment_id: str
    profile: ApplicationProfile
    agent_results: list[AgentResult] = Field(default_factory=list)
    negotiation: NegotiationResult
    config_fragments: dict[str, Any] = Field(default_factory=dict)
    message: str
    is_demo: bool = False

    def to_result(self) -> dict[str, Any]:
        return {
            "kind": "success" if self.negotiation.status == "resolved" else "failed",
            "title": "PLAN_READY" if self.negotiation.status == "resolved" else "PLAN_FAILED",
            "final_status": (
                "succeeded" if self.negotiation.status == "resolved" else "failed"
            ),
            "message": self.message,
            "durationLabel": "planning",
            "servicesLabel": f"{len(self.profile.inferred_stack.services)} services inferred",
            "verificationScore": None,
            "constraintsResolved": len(self.negotiation.decisions),
            "rollbackScope": None,
            "phase": "7-9",
            "execution": "completed_or_partial",
            "note": "Verification, critic, execution, and scoped rollback are active (Phases 7–9).",
            "is_demo": self.is_demo,
            "label": None,
            "profile": {
                "language_runtime": self.profile.inferred_stack.language_runtime,
                "has_dockerfile": self.profile.inferred_stack.has_dockerfile,
                "has_compose": self.profile.inferred_stack.has_compose,
                "services": [s.model_dump() for s in self.profile.inferred_stack.services],
                "suggested_ports": self.profile.inferred_stack.suggested_ports,
                "confidence": self.profile.inferred_stack.confidence,
            },
            "negotiation_status": self.negotiation.status,
        }
