"""Docker Agent — container/config constraints (no execution)."""

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


def run_docker_agent(profile: ApplicationProfile) -> AgentResult:
    started = _now()
    constraints: list[Constraint] = []
    stack = profile.inferred_stack
    primary_port = profile.target_port
    if stack.suggested_ports:
        primary_port = stack.suggested_ports[0]

    app_services = [
        s for s in stack.services if s.role in {"api", "backend", "web", "app", "service"}
    ]
    if not app_services:
        app_services = [s for s in stack.services if s.name not in {"network"}]

    # Primary publish port for main backend/app
    main = next(
        (s for s in app_services if s.role in {"api", "backend", "app"}),
        app_services[0] if app_services else None,
    )
    if main:
        port = main.suggested_port or primary_port
        constraints.append(
            Constraint(
                constraint_id=f"c_port_docker_{uuid4().hex[:8]}",
                type=ConstraintType.PORT_CLAIM,
                priority=Priority.RESOURCE,
                source_agent="Docker Agent",
                service=main.name,
                payload={
                    "key": f"host:{port}",
                    "port": port,
                    "protocol": "tcp",
                    "exclusive": True,
                    "summary": f"Docker Agent requested host port {port}",
                    "detail": f"Exclusive publish for service '{main.name}'",
                },
                alternatives=[{"port": port + 1}, {"port": port + 2}],
                status=ConstraintStatus.PROPOSED,
            )
        )

    db = next((s for s in stack.services if s.role == "database"), None)
    if db and main:
        constraints.append(
            Constraint(
                constraint_id=f"c_order_{uuid4().hex[:8]}",
                type=ConstraintType.EXEC_ORDER,
                priority=Priority.DEPENDENCY,
                source_agent="Docker Agent",
                service=main.name,
                payload={
                    "before": db.name,
                    "after": main.name,
                    "summary": f"{db.name} before {main.name}",
                    "detail": f"{main.name} starts only after {db.name} is healthy",
                },
                status=ConstraintStatus.PROPOSED,
            )
        )
        constraints.append(
            Constraint(
                constraint_id=f"c_env_{uuid4().hex[:8]}",
                type=ConstraintType.ENV_VAR,
                priority=Priority.DEPENDENCY,
                source_agent="Docker Agent",
                service=main.name,
                payload={
                    "key": "DATABASE_URL",
                    "required": True,
                    "value_policy": "secret_ref",
                    "summary": "DATABASE_URL required",
                    "detail": "Backend requires DATABASE_URL when a database service is present",
                },
                status=ConstraintStatus.PROPOSED,
            )
        )

    # Preference that may conflict with security (intentional research path)
    intent = (profile.intent or "").lower()
    if "privileged" in intent or "unrestricted" in intent:
        constraints.append(
            Constraint(
                constraint_id=f"c_pref_access_{uuid4().hex[:8]}",
                type=ConstraintType.NETWORK_POLICY,
                priority=Priority.PREFERENCE,
                source_agent="Docker Agent",
                service=main.name if main else None,
                payload={
                    "rule": "external_access",
                    "mode": "unrestricted",
                    "enforcement": "prefer",
                    "summary": "Prefer unrestricted external access",
                    "detail": "Convenience preference from operator intent",
                },
                status=ConstraintStatus.PROPOSED,
            )
        )

    compose_fragment = {
        "version": "3.9",
        "services": {
            s.name: {
                "image": f"medha/{s.name}:local",
                "ports": [f"{s.suggested_port or primary_port}:{s.suggested_port or primary_port}"]
                if s.role in {"api", "backend", "web", "app", "service"}
                else [],
            }
            for s in stack.services
            if s.name != "network"
        },
    }

    return AgentResult(
        agent="docker",
        ok=True,
        started_at=started,
        finished_at=_now(),
        summary=f"Published {len(constraints)} Docker constraints",
        artifacts={"compose_fragment": compose_fragment, "has_dockerfile": stack.has_dockerfile},
        constraints=constraints,
        is_demo=False,
    )
