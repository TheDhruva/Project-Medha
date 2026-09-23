"""Security Agent — mandatory security policy constraints."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.models.domain import (
    AgentResult,
    ApplicationProfile,
    Constraint,
    ConstraintStatus,
    ConstraintType,
    Priority,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_security_agent(profile: ApplicationProfile) -> AgentResult:
    started = _now()
    constraints = [
        Constraint(
            constraint_id=f"c_sec_nopriv_{uuid4().hex[:8]}",
            type=ConstraintType.SECURITY_POLICY,
            priority=Priority.SECURITY,
            source_agent="Security Agent",
            payload={
                "rule": "no_privileged",
                "enforcement": "block",
                "severity": "high",
                "summary": "Disallow privileged containers",
                "detail": "privileged=false required for all services",
            },
            status=ConstraintStatus.PROPOSED,
        ),
        Constraint(
            constraint_id=f"c_sec_access_{uuid4().hex[:8]}",
            type=ConstraintType.SECURITY_POLICY,
            priority=Priority.SECURITY,
            source_agent="Security Agent",
            service="backend",
            payload={
                "rule": "external_access",
                "mode": "restricted",
                "enforcement": "block",
                "severity": "high",
                "summary": "Require restricted network access",
                "detail": "Unrestricted external access is forbidden",
            },
            status=ConstraintStatus.PROPOSED,
        ),
    ]

    # If intent asks for secure deploy, reinforce secret handling preference as SECURITY
    intent = (profile.intent or "").lower()
    if "secure" in intent or "security" in intent:
        constraints.append(
            Constraint(
                constraint_id=f"c_sec_secrets_{uuid4().hex[:8]}",
                type=ConstraintType.SECURITY_POLICY,
                priority=Priority.SECURITY,
                source_agent="Security Agent",
                payload={
                    "rule": "no_plaintext_secrets",
                    "enforcement": "block",
                    "severity": "high",
                    "summary": "No plaintext secrets in compose",
                    "detail": "Secrets must use env refs / files, never inline values in plans",
                },
                status=ConstraintStatus.PROPOSED,
            )
        )

    return AgentResult(
        agent="security",
        ok=True,
        started_at=started,
        finished_at=_now(),
        summary=f"Published {len(constraints)} security policies",
        artifacts={"policies": [c.payload.get("rule") for c in constraints]},
        constraints=constraints,
        is_demo=False,
    )
