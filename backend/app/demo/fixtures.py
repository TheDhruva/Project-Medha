"""Deterministic fixture payloads for Demo Mode (no external I/O)."""

from __future__ import annotations

from typing import Any

SERVICES = ["network", "database", "backend", "frontend", "analytics"]

MAX_CNP_ROUNDS = 3
MAX_REPLAN_ROUNDS = 1

# Port conflict resolution (deterministic)
PORT_PRIMARY = 8080
PORT_ALTERNATIVE = 8081


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
