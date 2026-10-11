"""Deterministic fixture payloads for Demo Mode (no external I/O)."""

from __future__ import annotations

from typing import Any

SERVICES = ["network", "database", "backend", "frontend", "analytics"]

MAX_CNP_ROUNDS = 3
MAX_REPLAN_ROUNDS = 1

# Port conflict resolution (deterministic)
PORT_PRIMARY = 8080
PORT_ALTERNATIVE = 8081

# ═══════════════════════════════════════════════════════════════
# ATLAS COMMERCE FICTITIOUS DEMO REPOSITORY — Three months of history
# Age: approximately three months (Sept 12 – Oct 12, 2026)
# Stack: TypeScript, Node.js, PostgreSQL, Redis, Docker
# Repository: atlas-labs/atlas-commerce
# Six fictional contributors
# ═══════════════════════════════════════════════════════════════

# — Contributors —
# Six contributors with roles and commit counts over the three-month window.
ATLAS_CONTRIBUTORS: list[dict[str, Any]] = [
    {
        "initials": "PS",
        "name": "Priya S.",
        "role": "API",
        "commits": 12,
        "github": "priya-s",
    },
    {
        "initials": "RK",
        "name": "Rahul K.",
        "role": "Infrastructure",
        "commits": 9,
        "github": "rahul-k",
    },
    {
        "initials": "MT",
        "name": "Maya T.",
        "role": "Frontend",
        "commits": 8,
        "github": "maya-t",
    },
    {
        "initials": "DL",
        "name": "Diego L.",
        "role": "DevOps",
        "commits": 7,
        "github": "diego-l",
    },
    {
        "initials": "ER",
        "name": "Elena R.",
        "role": "QA",
        "commits": 5,
        "github": "elena-r",
    },
    {
        "initials": "SY",
        "name": "Sam Y.",
        "role": "Documentation",
        "commits": 4,
        "github": "sam-y",
    },
]

# — Latest push (deterministic fixture) —
# The canonical latest push for Atlas Commerce. Connected to the deployment
# run, CEG, verification, and alerts below.
ATLAS_LATEST_PUSH: dict[str, Any] = {
    "commitHash": "a82f31c",
    "shortHash": "a82f31c",
    "author": "Priya S.",
    "authorInitials": "PS",
    "title": "Optimize checkout queries",
    "summary": "Adds query batching and an index for order lookups.",
    "changedFiles": 3,
    "additions": 124,
    "deletions": 38,
    "commitTimestamp": "2026-10-10T14:32:00Z",
    "relativeTimestamp": "18 min ago",
    "checks": {"passed": 2, "pending": 1, "total": 3},
    "relatedServices": ["backend", "database"],
}

# — Deployment history (3 months, Sept 12 – Oct 12, 2026) —
# All deployment runs share the same fixture data: same deployment IDs, same
# outcomes, same CEG, same constraints, same verification. This ensures every
# panel agrees about the same project, commit, run, alert, and service states.
ATLAS_DEPLOYMENTS: list[dict[str, Any]] = [
    {
        "deploymentId": "dep_atlas_001",
        "scenario": "SUCCESSFUL_DEPLOYMENT",
        "status": "completed",
        "mode": "demo",
        "started": "2026-09-13T09:15:00Z",
        "completed": "2026-09-13T09:32:00Z",
        "duration": "~17s",
        "title": "Initial successful deployment",
        "verificationScore": 94,
        "constraintsResolved": 0,
        "resultKind": "success",
        "cegNodes": 5,
        "cegEdges": 4,
        "summary": "All services healthy. No conflicts.",
    },
    {
        "deploymentId": "dep_atlas_002",
        "scenario": "PORT_CONFLICT",
        "status": "completed",
        "mode": "demo",
        "started": "2026-09-20T14:30:00Z",
        "completed": "2026-09-20T14:55:00Z",
        "duration": "~25s",
        "title": "Port conflict: Docker and Nginx claimed port 8080",
        "verificationScore": 91,
        "constraintsResolved": 1,
        "resultKind": "success",
        "cegNodes": 5,
        "cegEdges": 4,
        "summary": "Nginx remapped to 8081. Conflict resolved via alternative.",
    },
    {
        "deploymentId": "dep_atlas_003",
        "scenario": "SECURITY_CONFLICT",
        "status": "completed",
        "mode": "demo",
        "started": "2026-09-27T16:00:00Z",
        "completed": "2026-09-27T16:30:00Z",
        "duration": "~30s",
        "title": "Security policy enforced over preference",
        "verificationScore": 96,
        "constraintsResolved": 1,
        "resultKind": "success",
        "cegNodes": 5,
        "cegEdges": 4,
        "summary": "Security constraint won; unsafe preference rejected.",
    },
    {
        "deploymentId": "dep_atlas_004",
        "scenario": "VERIFICATION_FAILURE",
        "status": "partial_recovery",
        "mode": "demo",
        "started": "2026-10-04T10:00:00Z",
        "completed": "2026-10-04T10:22:00Z",
        "duration": "~22s",
        "title": "Verification failure — missing env var, bounded replan",
        "verificationScore": 90,
        "constraintsResolved": 0,
        "resultKind": "partial_recovery",
        "cegNodes": 5,
        "cegEdges": 4,
        "summary": "DATABASE_URL missing; replanned within retry limit. Backend failed; frontend rolled back; analytics preserved.",
    },
    {
        "deploymentId": "dep_atlas_005",
        "scenario": "PARTIAL_FAILURE",
        "status": "partial_recovery",
        "mode": "demo",
        "started": "2026-10-10T11:00:00Z",
        "completed": "2026-10-10T11:18:00Z",
        "duration": "~18s",
        "title": "Latest run — degraded worker, scoped rollback",
        "verificationScore": 87,
        "constraintsResolved": 1,
        "resultKind": "partial_recovery",
        "cegNodes": 5,
        "cegEdges": 6,
        "summary": "Background worker degraded. Scoped rollback rolled back frontend only. Network, database, analytics preserved.",
    },
]

# — CEG node definitions (shared across deployments, positioned consistently) —
# Node positions are deterministic so the graph layout is stable.
ATLAS_CEG_NODES: list[dict[str, Any]] = [
    {
        "nodeId": "n_network",
        "service": "NETWORK",
        "action": "create_network",
        "status": "preserved",
        "timestamp": "11:00:00",
        "dependencies": [],
        "dependents": ["n_backend"],
        "position": {"x": 280, "y": 0},
        "reason": "Independent infrastructure — not affected by any failure",
        "preserved": True,
        "rollbackRequired": False,
    },
    {
        "nodeId": "n_database",
        "service": "DATABASE",
        "action": "start_container",
        "status": "preserved",
        "timestamp": "11:02:00",
        "dependencies": ["n_network"],
        "dependents": ["n_backend"],
        "position": {"x": 80, "y": 120},
        "reason": "Upstream success retained through rollback",
        "preserved": True,
        "rollbackRequired": False,
    },
    {
        "nodeId": "n_backend",
        "service": "BACKEND",
        "action": "start_container",
        "status": "failed",
        "timestamp": "11:05:00",
        "dependencies": ["n_database"],
        "dependents": ["n_frontend"],
        "position": {"x": 80, "y": 250},
        "reason": "Health check failed after start; elevated retry rates",
        "dependents": ["n_frontend"],
        "rollbackRequired": True,
        "preserved": False,
    },
    {
        "nodeId": "n_frontend",
        "service": "FRONTEND",
        "action": "start_container",
        "status": "rolled_back",
        "timestamp": "11:08:00",
        "dependencies": ["n_backend"],
        "dependents": [],
        "position": {"x": 80, "y": 380},
        "reason": "Dependent on failed backend; reversed during rollback",
        "rollbackRequired": True,
        "preserved": False,
    },
    {
        "nodeId": "n_analytics",
        "service": "ANALYTICS",
        "action": "start_container",
        "status": "preserved",
        "timestamp": "11:01:00",
        "dependencies": ["n_network"],
        "dependents": [],
        "position": {"x": 480, "y": 120},
        "reason": "Causally independent branch kept running",
        "preserved": True,
        "rollbackRequired": False,
    },
]

ATLAS_CEG_EDGES: list[dict[str, Any]] = [
    {"id": "e1", "source": "n_network", "target": "n_database", "relation": "depends_on"},
    {"id": "e2", "source": "n_network", "target": "n_analytics", "relation": "depends_on"},
    {"id": "e3", "source": "n_database", "target": "n_backend", "relation": "depends_on"},
    {"id": "e4", "source": "n_backend", "target": "n_frontend", "relation": "depends_on"},
    {"id": "e5", "source": "n_backend", "target": "n_frontend", "relation": "depends_on"},
    {"id": "e6", "source": "n_network", "target": "n_analytics", "relation": "depends_on"},
]

# — Constraint negotiation fixture for Atlas Commerce —
# The port conflict between Docker (backend) and Nginx is the active/conflict
# constraint. It was resolved in deployment dep_atlas_002 (port 8080→8081)
# and is reflected in the latest run (dep_atlas_005) as a contributing factor
# to the worker degradation.
ATLAS_NEGOTIATION: dict[str, Any] = {
    "title": "CONSTRAINT NEGOTIATION",
    "conflictSummary": "Docker and Nginx claimed host port 8080",
    "round": 1,
    "maxRounds": 3,
    "status": "resolved",
    "resolution": "8081 selected for Nginx",
    "method": "ALTERNATIVE",
    "simpleExplanation": "Two deployment components requested the same port. MEDHA detected the conflict before execution and selected an available alternative.",
    "method": "ALTERNATIVE",
    "involvedConstraintIds": ["c_port_docker", "c_port_nginx"],
    "roundsUsed": 1,
    "conflictsResolved": ["c_port_nginx"],
    "resolutionMethod": "ALTERNATIVE",
    "oldValue": 8080,
    "newValue": 8081,
    "winnerConstraint": "c_port_docker",
    "loserConstraint": "c_port_nginx",
    "technicalNotes": [
        "conflict_id=cf_port_8080",
        "type=PORT_CLAIM",
        "key=host:8080",
        "priority=RESOURCE vs RESOURCE",
        "old_value=8080",
        "new_value=8081",
        "winner=c_port_docker",
        "loser=c_port_nginx",
        "rounds_used=1",
    ],
}

# — Verification checks for the latest (partial recovery) run —
# Two checks passed, one pending. The pending check is connected to the
# degraded background worker / Redis state.
ATLAS_VERIFICATION_CHECKS: list[dict[str, Any]] = [
    {
        "id": "check_schema",
        "name": "Schema",
        "status": "pass",
        "message": "Configs match schema",
        "category": "configuration",
        "rule": "schema_compliance",
    },
    {
        "id": "check_yaml",
        "name": "YAML",
        "status": "pass",
        "message": "YAML parses cleanly",
        "category": "configuration",
        "rule": "yaml_parse",
    },
    {
        "id": "check_compose",
        "name": "Compose",
        "status": "pass",
        "message": "Compose graph valid",
        "category": "configuration",
        "rule": "compose_valid",
    },
    {
        "id": "check_security",
        "name": "Security",
        "status": "pass",
        "message": "Security floor intact",
        "category": "security",
        "rule": "security_floor",
    },
    {
        "id": "check_constraints",
        "name": "Constraints",
        "status": "pass",
        "message": "Agreed set consistent",
        "category": "constraints",
        "rule": "constraint_consistency",
    },
    {
        "id": "check_env",
        "name": "Environment",
        "status": "pending",
        "message": "DATABASE_URL present for worker config",
        "category": "configuration",
        "rule": "required_env_var",
    },
]

# — Active alerts for the latest run —
# Three coherent alerts that connect to the fixture data.
ATLAS_ALERTS: list[dict[str, Any]] = [
    {
        "id": "alert_redis",
        "severity": "high",
        "title": "Redis connection failures",
        "description": "Elevated retry rates detected on the background worker; 47 failed connection attempts in the last minute. May be related to the degraded worker state.",
        "affectedService": "background worker",
        "timestamp": "2026-10-10T11:14:00Z",
        "relatedRun": "dep_atlas_005",
        "investigationPath": "Check Redis connectivity, review connection pool settings, verify worker heartbeat",
        "severityColor": "red",
    },
    {
        "id": "alert_vulnerability",
        "severity": "medium",
        "title": "Dependency vulnerability requiring review",
        "description": "PostgreSQL driver version 2.3.5 has a known CVE. Schedule update in the next release cycle.",
        "affectedService": "API service",
        "timestamp": "2026-10-08T09:30:00Z",
        "relatedRun": "dep_atlas_003",
        "investigationPath": "Run dependency audit, update postgres driver, verify compatibility",
        "severityColor": "amber",
    },
    {
        "id": "alert_drift",
        "severity": "medium",
        "title": "Deployment configuration drift",
        "description": "Nginx configuration has drifted from the canonical spec; port 8080 reference persists despite port-conflict resolution. Update config to reference 8081.",
        "affectedService": "nginx",
        "timestamp": "2026-10-09T15:20:00Z",
        "relatedRun": "dep_atlas_002",
        "investigationPath": "Apply configuration drift remediation, redeploy nginx",
        "severityColor": "amber",
    },
]

# — Service health states —
# Five services with statuses connecting to the fixture. The degraded background
# worker connects logically to the Redis alert above.
ATLAS_SERVICE_HEALTH: list[dict[str, Any]] = [
    {
        "service": "web frontend",
        "status": "healthy",
        "endpoint": "http://localhost:3000",
        "latencyMs": 42,
    },
    {
        "service": "API service",
        "status": "healthy",
        "endpoint": "http://localhost:8080",
        "latencyMs": 28,
    },
    {
        "service": "background worker",
        "status": "degraded",
        "endpoint": "http://localhost:8081/worker/health",
        "latencyMs": 310,
        "connectsToAlert": "alert_redis",
    },
    {
        "service": "PostgreSQL",
        "status": "healthy",
        "endpoint": "postgresql://localhost:5432/atlas_commerce",
        "latencyMs": 15,
    },
    {
        "service": "Redis",
        "status": "elevated_retries",
        "endpoint": "redis://localhost:6379",
        "latencyMs": 85,
        "connectsToAlert": "alert_redis",
    },
]

# — Recent activity entries (compact) —
ATLAS_RECENT_ACTIVITY: list[dict[str, Any]] = [
    {
        "timestamp": "2026-10-10T11:00:00Z",
        "title": "Deployment dep_atlas_005 completed",
        "description": "Partial recovery: background worker degraded, frontend rolled back, analytics preserved.",
        "type": "deployment",
    },
    {
        "timestamp": "2026-10-10T10:55:00Z",
        "title": "Constraint conflict resolved",
        "description": "Nginx remapped from port 8080 to 8081. ALTERNATIVE method. Round 1 of 3.",
        "type": "negotiation",
    },
    {
        "timestamp": "2026-10-10T10:45:00Z",
        "title": "Verification started",
        "description": "6 checks — 4 passed, 1 pending (DATABASE_URL), 1 failed gate.",
        "type": "verification",
    },
    {
        "timestamp": "2026-10-10T10:30:00Z",
        "title": "CEG updated — 5 nodes, 6 edges",
        "description": "Execution graph reflects partial failure with scoped rollback.",
        "type": "graph",
    },
    {
        "timestamp": "2026-10-10T10:15:00Z",
        "title": "Latest push a82f31c — Optimize checkout queries",
        "description": "Priya S. added query batching and index for order lookups. +124/-38, 3 files.",
        "type": "push",
    },
]

# — 30-day deployment success rate data (Sept 12 – Oct 12, 2026) —
# One data point per day, success = green, failure = red. Every point comes from
# the fixture deployment history above.
ATLAS_DEPLOYMENT_TREND: list[dict[str, Any]] = [
    {"date": "2026-09-12", "success": True, "deploymentId": "dep_atlas_001"},
    {"date": "2026-09-13", "success": True, "deploymentId": "dep_atlas_001"},
    {"date": "2026-09-14", "success": False, "deploymentId": "dep_atlas_002"},  # port conflict day
    {"date": "2026-09-15", "success": True, "deploymentId": "dep_atlas_002"},
    {"date": "2026-09-16", "success": True, "deploymentId": "dep_atlas_002"},
    {"date": "2026-09-17", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-18", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-19", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-20", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-21", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-22", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-23", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-24", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-25", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-26", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-27", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-28", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-29", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-09-30", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-10-01", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-10-02", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-10-03", "success": True, "deploymentId": "dep_atlas_003"},
    {"date": "2026-10-04", "success": False, "deploymentId": "dep_atlas_004"},  # verification failure
    {"date": "2026-10-05", "success": True, "deploymentId": "dep_atlas_004"},
    {"date": "2026-10-06", "success": True, "deploymentId": "dep_atlas_004"},
    {"date": "2026-10-07", "success": True, "deploymentId": "dep_atlas_004"},
    {"date": "2026-10-08", "success": True, "deploymentId": "dep_atlas_004"},
    {"date": "2026-10-09", "success": True, "deploymentId": "dep_atlas_004"},
    {"date": "2026-10-10", "success": False, "deploymentId": "dep_atlas_005"},  # partial recovery
    {"date": "2026-10-11", "success": True, "deploymentId": "dep_atlas_005"},
    {"date": "2026-10-12", "success": True, "deploymentId": "dep_atlas_005"},
]

# — Bounded replanning attempt for verification failure —
ATLAS_REPLAN_ATTEMPT: dict[str, Any] = {
    "attempt": 1,
    "maxReplan": 1,
    "fix": "inject_DATABASE_URL",
    "description": "MEDHA found a configuration problem and is replanning within the allowed retry limit.",
    "originalPlan": "deploy atlantis services",
    "revisedPlan": "deploy with DATABASE_URL injected into worker config",
}


# — Alias for backward compatibility —
def ATLAS_FIXTURE_KEY(*_) -> str:
    return "atlas_demo"


def agent_row(
    agent_id: str,
    name: str,
    status: str,
    activity: str,
    last_event: str,
    duration_ms: int | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": agent_id,
        "name": name,
        "status": status,
        "activity": activity,
        "lastEvent": last_event,
    }
    if duration_ms is not None:
        row["durationMs"] = duration_ms
    return row


INITIAL_AGENTS: list[dict[str, Any]] = [
    agent_row("preflight", "Preflight", "idle", "Waiting for deployment start", "—"),
    agent_row("analyzer", "Code Analyzer", "idle", "Waiting for repository analysis", "—"),
    agent_row("docker", "Docker", "idle", "Waiting to publish constraints", "—"),
    agent_row("nginx", "Nginx", "idle", "Waiting to publish constraints", "—"),
    agent_row("security", "Security", "idle", "Waiting to publish policies", "—"),
    agent_row("mediator", "Mediator", "idle", "Waiting for constraint set", "—"),
    agent_row("verifier", "Verifier", "idle", "Waiting for agreed plan", "—"),
    agent_row("critic", "Critic", "idle", "Waiting for verification context", "—"),
    agent_row("executor", "Executor", "idle", "Waiting for gate pass", "—"),
    agent_row("rollback", "Rollback", "idle", "Standing by for failure scope", "—"),
]


def merge_agents(updates: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for agent in INITIAL_AGENTS:
        patch = updates.get(agent["id"], {})
        result.append({**agent, **patch})
    return result


def constraint(
    *,
    constraint_id: str,
    ctype: str,
    priority: str,
    source_agent: str,
    summary: str,
    detail: str,
    status: str,
    service: str | None = None,
    payload: dict[str, Any] | None = None,
    alternatives: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": constraint_id,
        "constraint_id": constraint_id,
        "type": ctype,
        "priority": priority,
        "sourceAgent": source_agent,
        "source_agent": source_agent,
        "summary": summary,
        "detail": detail,
        "status": status,
        "is_demo": True,
        "payload": payload or {},
        "technical": {"payload": payload or {}},
    }
    if service:
        item["service"] = service
    if alternatives:
        item["alternatives"] = alternatives
    return item


CLEAN_CONSTRAINTS: list[dict[str, Any]] = [
    constraint(
        constraint_id="c_port_backend",
        ctype="PORT_CLAIM",
        priority="RESOURCE",
        source_agent="Docker Agent",
        service="backend",
        summary="Backend claims host port 8080",
        detail="Exclusive publish of container port 8080 → host 8080",
        status="accepted",
        payload={"key": "host:8080", "port": PORT_PRIMARY, "protocol": "tcp", "exclusive": True},
    ),
    constraint(
        constraint_id="c_port_proxy",
        ctype="PORT_CLAIM",
        priority="RESOURCE",
        source_agent="Nginx Agent",
        service="nginx",
        summary="Nginx publishes edge port 80",
        detail="Reverse proxy listens on host port 80",
        status="accepted",
        payload={"key": "host:80", "port": 80, "protocol": "tcp", "exclusive": True},
    ),
    constraint(
        constraint_id="c_sec_no_priv",
        ctype="SECURITY_POLICY",
        priority="SECURITY",
        source_agent="Security Agent",
        summary="Disallow privileged containers",
        detail="privileged=false required for all services",
        status="accepted",
        payload={"rule": "no_privileged", "enforcement": "block", "severity": "high"},
    ),
    constraint(
        constraint_id="c_order_db_be",
        ctype="EXEC_ORDER",
        priority="DEPENDENCY",
        source_agent="Docker Agent",
        summary="Database before backend",
        detail="backend starts only after database is healthy",
        status="accepted",
        payload={"before": "database", "after": "backend"},
    ),
]


PORT_CONFLICT_PROPOSED: list[dict[str, Any]] = [
    constraint(
        constraint_id="c_port_docker",
        ctype="PORT_CLAIM",
        priority="RESOURCE",
        source_agent="Docker Agent",
        service="backend",
        summary="Docker Agent requested 8080",
        detail="Exclusive host port 8080 for backend",
        status="proposed",
        payload={"key": "host:8080", "port": PORT_PRIMARY, "protocol": "tcp", "exclusive": True},
        alternatives=[{"port": PORT_ALTERNATIVE}],
    ),
    constraint(
        constraint_id="c_port_nginx",
        ctype="PORT_CLAIM",
        priority="RESOURCE",
        source_agent="Nginx Agent",
        service="nginx",
        summary="Nginx Agent requested 8080",
        detail="Edge listener also claimed 8080",
        status="proposed",
        payload={"key": "host:8080", "port": PORT_PRIMARY, "protocol": "tcp", "exclusive": True},
        alternatives=[{"port": PORT_ALTERNATIVE}],
    ),
    constraint(
        constraint_id="c_sec_no_priv",
        ctype="SECURITY_POLICY",
        priority="SECURITY",
        source_agent="Security Agent",
        summary="Disallow privileged containers",
        detail="privileged=false",
        status="accepted",
        payload={"rule": "no_privileged", "enforcement": "block", "severity": "high"},
    ),
]


def port_conflict_constraints() -> list[dict[str, Any]]:
    return [
        {**PORT_CONFLICT_PROPOSED[0], "status": "conflict"},
        {**PORT_CONFLICT_PROPOSED[1], "status": "conflict"},
        PORT_CONFLICT_PROPOSED[2],
    ]


def port_resolved_constraints() -> list[dict[str, Any]]:
    return [
        {**PORT_CONFLICT_PROPOSED[0], "status": "accepted"},
        {
            **PORT_CONFLICT_PROPOSED[1],
            "status": "superseded",
            "summary": "Nginx remapped to 8081",
            "detail": "Alternative port selected after conflict",
            "payload": {
                "key": "host:8081",
                "port": PORT_ALTERNATIVE,
                "protocol": "tcp",
                "exclusive": True,
                "previous_port": PORT_PRIMARY,
            },
            "technical": {
                "payload": {
                    "key": "host:8081",
                    "port": PORT_ALTERNATIVE,
                    "protocol": "tcp",
                    "exclusive": True,
                    "previous_port": PORT_PRIMARY,
                }
            },
        },
        PORT_CONFLICT_PROPOSED[2],
    ]


SECURITY_CONFLICT_PROPOSED: list[dict[str, Any]] = [
    constraint(
        constraint_id="c_net_open",
        ctype="NETWORK_POLICY",
        priority="PREFERENCE",
        source_agent="Docker Agent",
        service="backend",
        summary="Prefer unrestricted external access",
        detail="allow unrestricted external access",
        status="proposed",
        payload={
            "rule": "external_access",
            "mode": "unrestricted",
            "enforcement": "prefer",
        },
    ),
    constraint(
        constraint_id="c_sec_restricted",
        ctype="SECURITY_POLICY",
        priority="SECURITY",
        source_agent="Security Agent",
        service="backend",
        summary="Require restricted network access",
        detail="restricted access only",
        status="proposed",
        payload={
            "rule": "external_access",
            "mode": "restricted",
            "enforcement": "block",
            "severity": "high",
        },
    ),
]


def security_conflict_constraints() -> list[dict[str, Any]]:
    return [
        {**SECURITY_CONFLICT_PROPOSED[0], "status": "conflict"},
        {**SECURITY_CONFLICT_PROPOSED[1], "status": "conflict"},
    ]


def security_resolved_constraints() -> list[dict[str, Any]]:
    return [
        {**SECURITY_CONFLICT_PROPOSED[0], "status": "rejected"},
        {**SECURITY_CONFLICT_PROPOSED[1], "status": "accepted"},
        *[c for c in CLEAN_CONSTRAINTS if c["type"] in {"PORT_CLAIM", "EXEC_ORDER"}],
    ]


VERIFICATION_CHECKS_PASS: list[dict[str, Any]] = [
    {"id": "schema", "name": "Schema", "status": "pass", "message": "Configs match schema"},
    {"id": "yaml", "name": "YAML", "status": "pass", "message": "YAML parses cleanly"},
    {"id": "compose", "name": "Compose", "status": "pass", "message": "Compose graph valid"},
    {"id": "security", "name": "Security", "status": "pass", "message": "Security floor intact"},
    {
        "id": "constraints",
        "name": "Constraints",
        "status": "pass",
        "message": "Agreed set consistent",
    },
    {
        "id": "env",
        "name": "Environment",
        "status": "pass",
        "message": "Required environment variables present",
    },
]


VERIFICATION_CHECKS_FAIL_ENV: list[dict[str, Any]] = [
    {"id": "schema", "name": "Schema", "status": "pass", "message": "OK"},
    {"id": "yaml", "name": "YAML", "status": "pass", "message": "OK"},
    {"id": "compose", "name": "Compose", "status": "pass", "message": "OK"},
    {"id": "security", "name": "Security", "status": "pass", "message": "OK"},
    {"id": "constraints", "name": "Constraints", "status": "pass", "message": "OK"},
    {
        "id": "env",
        "name": "Environment",
        "status": "fail",
        "message": "Required environment variable DATABASE_URL missing",
        "rule": "required_env_var",
        "missing": ["DATABASE_URL"],
    },
]


def ceg_node(
    node_id: str,
    service: str,
    action: str,
    status: str,
    dependencies: list[str],
    *,
    x: float,
    y: float,
    reason: str | None = None,
    dependents: list[str] | None = None,
    rollback_required: bool | None = None,
    preserved: bool | None = None,
    timestamp: str = "08:41:00",
) -> dict[str, Any]:
    node: dict[str, Any] = {
        "id": node_id,
        "node_id": node_id,
        "service": service,
        "action": action,
        "status": status,
        "timestamp": timestamp,
        "dependencies": dependencies,
        "parent_nodes": dependencies,
        "position": {"x": x, "y": y},
        "is_demo": True,
    }
    if reason:
        node["reason"] = reason
    if dependents is not None:
        node["dependents"] = dependents
    if rollback_required is not None:
        node["rollbackRequired"] = rollback_required
    if preserved is not None:
        node["preserved"] = preserved
    return node


CEG_EDGES = [
    {"id": "e1", "source": "n_network", "target": "n_database", "from_node_id": "n_network", "to_node_id": "n_database", "relation": "depends_on"},
    {"id": "e2", "source": "n_network", "target": "n_analytics", "from_node_id": "n_network", "to_node_id": "n_analytics", "relation": "depends_on"},
    {"id": "e3", "source": "n_database", "target": "n_backend", "from_node_id": "n_database", "to_node_id": "n_backend", "relation": "depends_on"},
    {"id": "e4", "source": "n_backend", "target": "n_frontend", "from_node_id": "n_backend", "to_node_id": "n_frontend", "relation": "depends_on"},
]


def graph_all_success() -> dict[str, Any]:
    return {
        "nodes": [
            ceg_node("n_network", "NETWORK", "create_network", "success", [], x=280, y=0, timestamp="08:41:12"),
            ceg_node("n_database", "DATABASE", "start_container", "success", ["n_network"], x=80, y=120, timestamp="08:41:14"),
            ceg_node("n_analytics", "ANALYTICS", "start_container", "success", ["n_network"], x=480, y=120, timestamp="08:41:14"),
            ceg_node("n_backend", "BACKEND", "start_container", "success", ["n_database"], x=80, y=250, timestamp="08:41:16"),
            ceg_node("n_frontend", "FRONTEND", "start_container", "success", ["n_backend"], x=80, y=380, timestamp="08:41:18"),
        ],
        "edges": CEG_EDGES,
    }


def graph_partial_final() -> dict[str, Any]:
    return {
        "nodes": [
            ceg_node(
                "n_network", "NETWORK", "create_network", "preserved", [],
                x=280, y=0, preserved=True, timestamp="08:41:12",
            ),
            ceg_node(
                "n_database", "DATABASE", "start_container", "preserved", ["n_network"],
                x=80, y=120, preserved=True, timestamp="08:41:14",
            ),
            ceg_node(
                "n_analytics", "ANALYTICS", "start_container", "preserved", ["n_network"],
                x=480, y=120, preserved=True,
                reason="Causally independent of backend failure",
                timestamp="08:41:14",
            ),
            ceg_node(
                "n_backend", "BACKEND", "start_container", "failed", ["n_database"],
                x=80, y=250,
                reason="Health check failed after start",
                dependents=["n_frontend"],
                rollback_required=True,
                timestamp="08:41:16",
            ),
            ceg_node(
                "n_frontend", "FRONTEND", "start_container", "rolled_back", ["n_backend"],
                x=80, y=380,
                reason="Dependent on failed backend",
                rollback_required=True,
                timestamp="08:41:19",
            ),
        ],
        "edges": CEG_EDGES,
    }


def graph_execution_progress(
    *,
    network: str = "pending",
    database: str = "pending",
    analytics: str = "pending",
    backend: str = "pending",
    frontend: str = "pending",
) -> dict[str, Any]:
    return {
        "nodes": [
            ceg_node("n_network", "NETWORK", "create_network", network, [], x=280, y=0),
            ceg_node("n_database", "DATABASE", "start_container", database, ["n_network"], x=80, y=120),
            ceg_node("n_analytics", "ANALYTICS", "start_container", analytics, ["n_network"], x=480, y=120),
            ceg_node("n_backend", "BACKEND", "start_container", backend, ["n_database"], x=80, y=250),
            ceg_node("n_frontend", "FRONTEND", "start_container", frontend, ["n_backend"], x=80, y=380),
        ],
        "edges": CEG_EDGES,
    }


def service_outcomes_success() -> list[dict[str, Any]]:
    return [
        {"name": "network", "status": "success", "endpoint": None},
        {"name": "database", "status": "success", "endpoint": None},
        {"name": "backend", "status": "success", "endpoint": "http://localhost:8080"},
        {"name": "frontend", "status": "success", "endpoint": "http://localhost:8081"},
        {"name": "analytics", "status": "success", "endpoint": None},
    ]


def service_outcomes_partial() -> list[dict[str, Any]]:
    return [
        {"name": "network", "status": "preserved"},
        {"name": "database", "status": "preserved"},
        {"name": "backend", "status": "failed"},
        {"name": "frontend", "status": "rolled_back"},
        {"name": "analytics", "status": "preserved"},
    ]


def success_result(
    *,
    message: str,
    verification_score: int,
    constraints_resolved: int,
    duration_label: str = "~12s",
) -> dict[str, Any]:
    return {
        "kind": "success",
        "title": "SUCCESS",
        "final_status": "succeeded",
        "message": message,
        "durationLabel": duration_label,
        "servicesLabel": "5 / 5 healthy",
        "verificationScore": verification_score,
        "constraintsResolved": constraints_resolved,
        "rollbackScope": None,
        "services": service_outcomes_success(),
        "failed_services": [],
        "rolled_back_services": [],
        "preserved_services": SERVICES.copy(),
        "is_demo": True,
        "label": "DEMO/MOCK",
    }


def partial_result() -> dict[str, Any]:
    return {
        "kind": "partial_recovery",
        "title": "PARTIAL_FAILURE",
        "final_status": "partial_recovery",
        "message": (
            "Backend failed. MEDHA traced the dependency graph and rolled back only the "
            "affected Frontend branch. Independent services were preserved."
        ),
        "durationLabel": "~16s",
        "servicesLabel": "3 preserved · 1 failed · 1 rolled back",
        "verificationScore": 93,
        "constraintsResolved": 0,
        "rollbackScope": "frontend ← backend",
        "services": service_outcomes_partial(),
        "failed_services": ["backend"],
        "rolled_back_services": ["frontend"],
        "preserved_services": ["network", "database", "analytics"],
        "is_demo": True,
        "label": "DEMO/MOCK",
    }


def rollback_scope_partial() -> dict[str, Any]:
    return {
        "headline": "SCOPED ROLLBACK COMPLETE",
        "deployment_id": None,
        "failed_node_id": "n_backend",
        "nodes_to_rollback": ["n_frontend"],
        "nodes_preserved": ["n_network", "n_database", "n_analytics"],
        "preserved": 3,
        "failed": 1,
        "rolledBack": 1,
        "scopeNodeIds": ["n_frontend"],
        "details": [
            {"service": "NETWORK", "status": "preserved", "note": "Independent of failure branch"},
            {"service": "DATABASE", "status": "preserved", "note": "Upstream success retained"},
            {"service": "BACKEND", "status": "failed", "note": "Health check failed after start"},
            {"service": "FRONTEND", "status": "rolled_back", "note": "Dependent on backend — reversed"},
            {
                "service": "ANALYTICS",
                "status": "preserved",
                "note": "Causally independent branch kept running",
            },
        ],
        "simpleExplanation": (
            "Only the failed service and its dependents were rolled back. "
            "Independent successes stayed up."
        ),
        "rationale": (
            "Backend failed. Frontend depends on backend; analytics is independent. "
            "Rollback scope = frontend only."
        ),
        "is_demo": True,
    }


def change_intel_demo() -> "ChangeImpactAnalysis":
    """Canned Phase 2 change-impact fixture for the demo UI.

    Clearly labelled DEMO/MOCK; not derived from a real repository.
    """
    from app.changeintel.models import (
        ChangeImpactAnalysis,
        ChangeSet,
        ChangedSymbol,
        ChangeType,
        CigGraph,
        Confidence,
        Hunk,
        ImpactEdge,
        ImpactNode,
        ImpactRisk,
        ImpactTraversal,
        Language,
        NodeType,
        RelationshipType,
        RiskLevel,
        Symbol,
        SymbolKind,
        UnresolvedDependency,
        VerificationRequirement,
    )

    def symbol(symbol_id: str, name: str, fqn: str, kind: SymbolKind, path: str, line: int) -> Symbol:
        return Symbol(
            symbol_id=symbol_id,
            name=name,
            fqn=fqn,
            kind=kind,
            path=path,
            line=line,
            end_line=line + 3,
            language=Language.PYTHON,
        )

    svc_sym = symbol("services/checkout.py::class:services.checkout.CheckoutService",
                     "CheckoutService", "services.checkout.CheckoutService", SymbolKind.CLASS,
                     "services/checkout.py", 5)
    cart_sym = symbol("services/cart.py::function:services.cart.build_cart",
                      "build_cart", "services.cart.build_cart", SymbolKind.FUNCTION,
                      "services/cart.py", 8)
    pricing_sym = symbol("services/pricing.py::function:services.pricing.compute_total",
                         "compute_total", "services.pricing.compute_total", SymbolKind.FUNCTION,
                         "services/pricing.py", 12)

    analysis = ChangeImpactAnalysis(
        deployment_id=None,
        repository_url="github.com/acme/checkout-service (demo)",
        is_demo=True,
        changeset=ChangeSet(
            base_revision="e2f31a4",
            target_revision="9c61d02",
            base_sha="e2f31a4c9b2d07f1a88c9aa2d477fe0a",
            target_sha="9c61d02e27b4f83a1dc90b3e44d12f5c",
            source_method="demo",
            files=[
                {
                    "path": "services/checkout.py",
                    "change_type": ChangeType.MODIFIED.value,
                    "added_lines": 18,
                    "deleted_lines": 6,
                    "hunks": [{"new_start": 5, "new_end": 26, "old_start": 5, "old_end": 14}],
                },
                {
                    "path": "services/pricing.py",
                    "change_type": ChangeType.MODIFIED.value,
                    "added_lines": 4,
                    "deleted_lines": 0,
                    "hunks": [{"new_start": 12, "new_end": 16, "old_start": 11, "old_end": 12}],
                },
                {
                    "path": "config.yaml",
                    "change_type": ChangeType.MODIFIED.value,
                    "added_lines": 2,
                    "deleted_lines": 1,
                    "hunks": [{"new_start": 3, "new_end": 5, "old_start": 3, "old_end": 4}],
                },
            ],
        ),
        changed_symbols=[
            ChangedSymbol(symbol=svc_sym, change_type=ChangeType.MODIFIED, lines_changed=8),
            ChangedSymbol(
                symbol=Symbol(
                    symbol_id="services/checkout.py::function:services.checkout.CheckoutService.apply_discount",
                    name="apply_discount",
                    fqn="services.checkout.CheckoutService.apply_discount",
                    kind=SymbolKind.METHOD,
                    path="services/checkout.py",
                    line=21,
                    end_line=29,
                    language=Language.PYTHON,
                ),
                change_type=ChangeType.ADDED,
                lines_changed=8,
            ),
            ChangedSymbol(symbol=pricing_sym, change_type=ChangeType.MODIFIED, lines_changed=4),
        ],
        graph=CigGraph(
            nodes=[
                ImpactNode(id="services/checkout.py", path="services/checkout.py",
                           node_type=NodeType.CHANGED, language=Language.PYTHON, direct=True),
                ImpactNode(id="services/pricing.py", path="services/pricing.py",
                           node_type=NodeType.CHANGED, language=Language.PYTHON, direct=True),
                ImpactNode(id="config.yaml", path="config.yaml",
                           node_type=NodeType.CHANGED, language=Language.YAML, direct=True),
                ImpactNode(id="services/cart.py", path="services/cart.py",
                           node_type=NodeType.AFFECTED, language=Language.PYTHON, direct=True),
                ImpactNode(id="api/routes.py", path="api/routes.py",
                           node_type=NodeType.CONTEXT, language=Language.PYTHON),
                ImpactNode(id="services/checkout.py::class:services.checkout.CheckoutService",
                           path="services/checkout.py", node_type=NodeType.CHANGED,
                           symbol="CheckoutService",
                           symbol_id="services/checkout.py::class:services.checkout.CheckoutService",
                           kind=SymbolKind.CLASS, language=Language.PYTHON, direct=True),
                ImpactNode(id="services/cart.py::function:services.cart.build_cart",
                           path="services/cart.py", node_type=NodeType.AFFECTED,
                           symbol="build_cart",
                           symbol_id="services/cart.py::function:services.cart.build_cart",
                           kind=SymbolKind.FUNCTION, language=Language.PYTHON, direct=True),
                ImpactNode(id="services/pricing.py::function:services.pricing.compute_total",
                           path="services/pricing.py", node_type=NodeType.CHANGED,
                           symbol="compute_total",
                           symbol_id="services/pricing.py::function:services.pricing.compute_total",
                           kind=SymbolKind.FUNCTION, language=Language.PYTHON, direct=True),
            ],
            edges=[
                ImpactEdge(id="e_demo_1", source="services/cart.py", target="services/checkout.py",
                           relationship=RelationshipType.IMPORT, confidence=Confidence.HIGH,
                           evidence="services/cart.py:1 import checkout", direct=True),
                ImpactEdge(id="e_demo_2", source="services/checkout.py", target="services/pricing.py",
                           relationship=RelationshipType.IMPORT, confidence=Confidence.HIGH,
                           evidence="services/checkout.py:2 from pricing import compute_total", direct=True),
                ImpactEdge(id="e_demo_3", source="config.yaml", target="services/checkout.py",
                           relationship=RelationshipType.CONFIGURATION_DEPENDENCY,
                           confidence=Confidence.MEDIUM,
                           evidence="config.yaml references checkout", direct=True),
                ImpactEdge(id="e_demo_4", source="api/routes.py", target="services/checkout.py",
                           relationship=RelationshipType.API_CONSUMER, confidence=Confidence.HIGH,
                           evidence="api/routes.py:4 import checkout", direct=True),
            ],
        ),
        traversal=ImpactTraversal(
            max_depth=3,
            direct_targets=["services/cart.py", "api/routes.py"],
            transitive_targets=[],
            cycles_detected=[],
            depth_used=1,
        ),
        unresolved=[
            UnresolvedDependency(
                path="services/pricing.py", line=3, target="payment_gateway",
                kind="import",
                reason="bare import could not be mapped to a repository file",
            )
        ],
        risk=ImpactRisk(
            level=RiskLevel.MEDIUM,
            factors=[
                {"code": "api_contract_exposure", "level": "medium",
                 "reason": "1 API consumer edge(s) in the impact graph"},
                {"code": "configuration_dependencies", "level": "medium",
                 "reason": "configuration references changed source artifacts"},
                {"code": "unresolved_dependencies", "level": "medium",
                 "reason": "1 import(s) could not be resolved inside the repository"},
            ],
        ),
        requirements=[
            VerificationRequirement(
                id="req_demo_1",
                target_path="config.yaml",
                requirement=(
                    "Re-validate the modified configuration against its referenced "
                    "services before deployment."
                ),
                reason="config file 'config.yaml' changed (modified)",
                check_category="config",
                executable=True,
                status="executable",
            ),
            VerificationRequirement(
                id="req_demo_2",
                target_path="api/routes.py",
                requirement="Verify the API contract between consumer 'api/routes.py' and "
                            "changed endpoint 'services/checkout.py'.",
                reason="api/routes.py:4 import checkout",
                check_category="constraints",
                executable=False,
                status="not_executable",
            ),
            VerificationRequirement(
                id="req_demo_3",
                target_path="services/cart.py",
                requirement="Re-verify 'services/cart.py' against its changed dependencies (regression).",
                reason="services/cart.py is directly affected",
                check_category="preflight",
                executable=False,
                status="not_executable",
            ),
        ],
    )
    return analysis
