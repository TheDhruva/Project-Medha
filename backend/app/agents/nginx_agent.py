"""Nginx Agent — reverse-proxy constraints (no execution)."""

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


def run_nginx_agent(profile: ApplicationProfile) -> AgentResult:
    started = _now()
    edge_port = profile.target_port
    # Intentionally claim the same host port as the primary app publish port so
    # CNP can demonstrate same-priority PORT_CLAIM resolution via alternatives.
    constraints = [
        Constraint(
            constraint_id=f"c_port_nginx_{uuid4().hex[:8]}",
            type=ConstraintType.PORT_CLAIM,
            priority=Priority.RESOURCE,
            source_agent="Nginx Agent",
            service="nginx",
            payload={
                "key": f"host:{edge_port}",
                "port": edge_port,
                "protocol": "tcp",
                "exclusive": True,
                "summary": f"Nginx Agent requested host port {edge_port}",
                "detail": "Edge listener for reverse proxy",
            },
            alternatives=[{"port": edge_port + 1}, {"port": edge_port + 2}],
            status=ConstraintStatus.PROPOSED,
        ),
        Constraint(
            constraint_id=f"c_net_nginx_{uuid4().hex[:8]}",
            type=ConstraintType.NETWORK_POLICY,
            priority=Priority.DEPENDENCY,
            source_agent="Nginx Agent",
            service="nginx",
            payload={
                "rule": "proxy_upstream",
                "network": "medha_net",
                "isolation": "bridge",
                "summary": "Nginx joins application bridge network",
                "detail": "Proxy upstream access via medha_net",
            },
            status=ConstraintStatus.PROPOSED,
        ),
    ]

    nginx_conf = {
        "listen": edge_port,
        "upstream": "backend",
        "locations": [{"path": "/", "proxy_pass": "http://backend"}],
    }

    return AgentResult(
        agent="nginx",
        ok=True,
        started_at=started,
        finished_at=_now(),
        summary=f"Published {len(constraints)} Nginx constraints",
        artifacts={"nginx_config": nginx_conf},
        constraints=constraints,
        is_demo=False,
    )
