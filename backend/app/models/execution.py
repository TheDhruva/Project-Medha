"""Phase 7–9 domain models: verification, critic, execution, CEG, rollback."""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.domain import _utc_now


class CheckSeverity(str, Enum):
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warning"
    FAIL = "fail"
    PENDING = "pending"


class VerificationCheck(BaseModel):
    id: str
    name: str
    category: str
    severity: CheckSeverity = CheckSeverity.MEDIUM
    rule: str
    status: CheckStatus
    message: str
    affected_service: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_ui(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "category": self.category,
            "severity": self.severity.value,
            "rule": self.rule,
            "affected_service": self.affected_service,
            "metadata": self.metadata,
        }


class VerificationResult(BaseModel):
    deployment_id: str
    passed: bool
    checks: list[VerificationCheck] = Field(default_factory=list)
    blocking_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    score: int = 100
    finished_at: str = Field(default_factory=_utc_now)
    replan_count: int = 0
    is_demo: bool = False

    def to_ui(self) -> dict[str, Any]:
        return {
            "checks": [c.to_ui() for c in self.checks],
            "passed": self.passed,
            "summary": (
                "Verification passed. Execution is allowed."
                if self.passed
                else "Verification failed. Execution is blocked."
            ),
            "blocking_failures": self.blocking_failures,
            "warnings": self.warnings,
            "score": self.score,
            "replan_count": self.replan_count,
            "is_demo": self.is_demo,
        }


class CriticRecommendation(str, Enum):
    PASS = "PASS"
    REPLAN = "REPLAN"
    ESCALATE = "ESCALATE"
    WARN = "WARN"
    BLOCK = "BLOCK"  # alias for escalate/block gate


class CriticResult(BaseModel):
    deployment_id: str
    score: int
    security_score: int
    completeness_score: int
    constraint_score: int
    intent_alignment_score: int
    recommendation: CriticRecommendation
    findings: list[str] = Field(default_factory=list)
    summary: str
    finished_at: str = Field(default_factory=_utc_now)
    is_demo: bool = False

    def to_ui(self) -> dict[str, Any]:
        # Map REPLAN/ESCALATE to UI recommendation vocabulary used by frontend
        rec = self.recommendation
        ui_rec = rec.value
        if rec == CriticRecommendation.ESCALATE:
            ui_rec = "BLOCK"
        elif rec == CriticRecommendation.REPLAN:
            ui_rec = "WARN"
        return {
            "score": self.score,
            "breakdown": {
                "security": self.security_score,
                "completeness": self.completeness_score,
                "constraints": self.constraint_score,
                "intentAlignment": self.intent_alignment_score,
            },
            "recommendation": ui_rec,
            "findings": self.findings,
            "summary": self.summary,
            "gate_recommendation": self.recommendation.value,
            "is_demo": self.is_demo,
        }


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    SUCCEEDED = "success"  # alias
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    SKIPPED = "skipped"
    PRESERVED = "preserved"


class ExecutionAction(BaseModel):
    action_id: str
    action_type: str
    service: str
    parent_actions: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    reversible: bool = True
    rollback_action: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, Any] = Field(default_factory=dict)


class ExecutionPlan(BaseModel):
    deployment_id: str
    services: list[str] = Field(default_factory=list)
    networks: list[str] = Field(default_factory=list)
    volumes: list[str] = Field(default_factory=list)
    actions: list[ExecutionAction] = Field(default_factory=list)
    dependencies: dict[str, list[str]] = Field(default_factory=dict)
    compose: dict[str, Any] = Field(default_factory=dict)
    fail_service: str | None = None  # simulator injection
    is_demo: bool = False


class ExecutionNode(BaseModel):
    node_id: str
    action: str
    service: str
    status: str = NodeStatus.PENDING.value
    timestamp: str = Field(default_factory=_utc_now)
    parent_nodes: list[str] = Field(default_factory=list)
    child_nodes: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    reversible: bool = True
    rollback_action: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None
    position: dict[str, float] = Field(default_factory=dict)
    is_demo: bool = False

    def to_ui(self) -> dict[str, Any]:
        return {
            "id": self.node_id,
            "node_id": self.node_id,
            "service": self.service.upper(),
            "action": self.action,
            "status": self.status,
            "timestamp": self.timestamp,
            "dependencies": self.dependencies or self.parent_nodes,
            "parent_nodes": self.parent_nodes,
            "dependents": self.child_nodes,
            "position": self.position,
            "reason": self.reason,
            "rollbackRequired": self.status in {NodeStatus.FAILED.value, NodeStatus.ROLLED_BACK.value},
            "preserved": self.status == NodeStatus.PRESERVED.value,
            "reversible": self.reversible,
            "is_demo": self.is_demo,
        }


class ExecutionEdge(BaseModel):
    id: str
    source: str
    target: str
    relation: str = "depends_on"

    def to_ui(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "from_node_id": self.source,
            "to_node_id": self.target,
            "relation": self.relation,
        }


class ExecutionGraph(BaseModel):
    deployment_id: str
    nodes: list[ExecutionNode] = Field(default_factory=list)
    edges: list[ExecutionEdge] = Field(default_factory=list)
    updated_at: str = Field(default_factory=_utc_now)
    is_demo: bool = False

    def to_ui(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_ui() for n in self.nodes],
            "edges": [e.to_ui() for e in self.edges],
        }

    def node_map(self) -> dict[str, ExecutionNode]:
        return {n.node_id: n for n in self.nodes}


class RollbackScope(BaseModel):
    deployment_id: str
    failed_node_id: str
    failed_nodes: list[str] = Field(default_factory=list)
    affected_nodes: list[str] = Field(default_factory=list)
    nodes_to_rollback: list[str] = Field(default_factory=list)
    nodes_preserved: list[str] = Field(default_factory=list)
    skipped_nodes: list[str] = Field(default_factory=list)
    not_rollbackable: list[str] = Field(default_factory=list)
    rationale: str
    order: list[str] = Field(default_factory=list)
    is_demo: bool = False

    def to_ui(self) -> dict[str, Any]:
        failed = self.failed_nodes or ([self.failed_node_id] if self.failed_node_id else [])

        def _svc(nid: str) -> str:
            return nid.removeprefix("n_").upper()

        details: list[dict[str, Any]] = []
        for nid in failed:
            details.append(
                {
                    "service": _svc(nid),
                    "status": "failed",
                    "note": "Failure detected",
                }
            )
        for nid in self.nodes_to_rollback:
            details.append(
                {
                    "service": _svc(nid),
                    "status": "rolled_back",
                    "note": "Dependent on failed branch",
                }
            )
        for nid in self.nodes_preserved:
            details.append(
                {
                    "service": _svc(nid),
                    "status": "preserved",
                    "note": "Independent / upstream success retained",
                }
            )
        return {
            "headline": "SCOPED ROLLBACK COMPLETE",
            "deployment_id": self.deployment_id,
            "failed_node_id": self.failed_node_id,
            "failed_nodes": failed,
            "affected_nodes": self.affected_nodes,
            "nodes_to_rollback": self.nodes_to_rollback,
            "nodes_preserved": self.nodes_preserved,
            "skipped_nodes": self.skipped_nodes,
            "not_rollbackable": self.not_rollbackable,
            "preserved": len(self.nodes_preserved),
            "failed": len(failed),
            "rolledBack": len(self.nodes_to_rollback),
            "scopeNodeIds": self.nodes_to_rollback,
            "order": self.order or self.nodes_to_rollback,
            "details": details,
            "simpleExplanation": self.rationale,
            "rationale": self.rationale,
            "is_demo": self.is_demo,
        }


class ExecutionResult(BaseModel):
    deployment_id: str
    status: str  # SUCCESS | PARTIAL_FAILURE | FAILED | ROLLED_BACK | ESCALATED
    successful_services: list[str] = Field(default_factory=list)
    failed_services: list[str] = Field(default_factory=list)
    rolled_back_services: list[str] = Field(default_factory=list)
    preserved_services: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    duration_seconds: float = 0.0
    executor: str = "simulator"
    is_demo: bool = False

    def to_deployment_result(
        self,
        *,
        verification_score: int | None,
        constraints_resolved: int,
        rollback_scope: str | None,
        message: str,
    ) -> dict[str, Any]:
        if self.status == "SUCCESS":
            kind, title = "success", "SUCCESS"
        elif self.status == "PARTIAL_FAILURE":
            kind, title = "partial_recovery", "PARTIAL_FAILURE"
        else:
            kind, title = "failed", self.status
        return {
            "kind": kind,
            "title": title,
            "final_status": (
                "succeeded"
                if self.status == "SUCCESS"
                else "partial_recovery"
                if self.status == "PARTIAL_FAILURE"
                else "failed"
            ),
            "message": message,
            "durationLabel": f"~{self.duration_seconds:.0f}s",
            "servicesLabel": (
                f"{len(self.preserved_services or self.successful_services)} preserved · "
                f"{len(self.failed_services)} failed · "
                f"{len(self.rolled_back_services)} rolled back"
                if self.status == "PARTIAL_FAILURE"
                else f"{len(self.successful_services)} / {len(self.successful_services) + len(self.failed_services)} healthy"
            ),
            "verificationScore": verification_score,
            "constraintsResolved": constraints_resolved,
            "rollbackScope": rollback_scope,
            "failed_services": self.failed_services,
            "rolled_back_services": self.rolled_back_services,
            "preserved_services": self.preserved_services,
            "successful_services": self.successful_services,
            "phase": "7-9",
            "executor": self.executor,
            "is_demo": self.is_demo,
            "label": "DEMO/MOCK" if self.is_demo else None,
        }


def new_action_id(prefix: str = "act") -> str:
    return f"{prefix}_{uuid4().hex[:10]}"
