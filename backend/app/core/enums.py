from __future__ import annotations

from enum import Enum


class DeployMode(str, Enum):
    DEMO = "demo"
    REAL = "real"


class ScenarioId(str, Enum):
    SUCCESSFUL_DEPLOYMENT = "SUCCESSFUL_DEPLOYMENT"
    PORT_CONFLICT = "PORT_CONFLICT"
    SECURITY_CONFLICT = "SECURITY_CONFLICT"
    VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
    PARTIAL_FAILURE = "PARTIAL_FAILURE"


class DeploymentStatus(str, Enum):
    """High-level deployment lifecycle (Phases 0–12 pipeline)."""

    QUEUED = "queued"
    STARTED = "started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL_RECOVERY = "partial_recovery"
    CANCELLED = "cancelled"


class StageId(str, Enum):
    PREFLIGHT = "PREFLIGHT"
    ANALYZE = "ANALYZE"
    PLAN = "PLAN"
    AGENTS = "AGENTS"
    NEGOTIATE = "NEGOTIATE"
    VERIFY = "VERIFY"
    EXECUTE = "EXECUTE"
    RECOVER = "RECOVER"
    COMPLETE = "COMPLETE"


class EventType(str, Enum):
    DEPLOYMENT_CREATED = "deployment.created"
    DEPLOYMENT_STARTED = "deployment.started"
    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    AGENT_STARTED = "agent.started"
    AGENT_COMPLETED = "agent.completed"
    CONSTRAINT_PUBLISHED = "constraint.published"
    CONSTRAINT_CONFLICT = "constraint.conflict"
    NEGOTIATION_STARTED = "negotiation.started"
    NEGOTIATION_RESOLVED = "negotiation.resolved"
    VERIFICATION_STARTED = "verification.started"
    VERIFICATION_FAILED = "verification.failed"
    VERIFICATION_PASSED = "verification.passed"
    VERIFICATION_CHECK = "verification.check"
    CRITIC_STARTED = "critic.started"
    CRITIC_COMPLETED = "critic.completed"
    REPLAN_STARTED = "replan.started"
    REPLAN_COMPLETED = "replan.completed"
    EXECUTION_STARTED = "execution.started"
    EXECUTION_NODE_STARTED = "execution.node.started"
    EXECUTION_NODE_COMPLETED = "execution.node.completed"
    EXECUTION_NODE_FAILED = "execution.node.failed"
    EXECUTION_SERVICE_STATUS = "execution.service_status"
    EXECUTION_FAILED = "execution.failed"
    CEG_CREATED = "ceg.created"
    ROLLBACK_STARTED = "rollback.started"
    ROLLBACK_SCOPE = "rollback.scope_determined"
    ROLLBACK_NODE = "rollback.node"
    ROLLBACK_COMPLETED = "rollback.completed"
    SYSTEM_MESSAGE = "system.message"
    DEPLOYMENT_COMPLETED = "deployment.completed"
    DEPLOYMENT_FAILED = "deployment.failed"


# Event types that terminate an SSE stream (persisted and replayed first).
TERMINAL_EVENT_TYPES = frozenset(
    {
        EventType.DEPLOYMENT_COMPLETED.value,
        EventType.DEPLOYMENT_FAILED.value,
    }
)

# Statuses after which a deployment's lifecycle is complete.
TERMINAL_STATUSES = frozenset(
    {
        DeploymentStatus.COMPLETED.value,
        DeploymentStatus.FAILED.value,
        DeploymentStatus.PARTIAL_RECOVERY.value,
        DeploymentStatus.CANCELLED.value,
    }
)
