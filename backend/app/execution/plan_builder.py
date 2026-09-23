"""Build ExecutionPlan + CEG from negotiated profile/constraints."""

from __future__ import annotations

from typing import Any

from app.models.domain import ApplicationProfile, Constraint, ConstraintType
from app.models.execution import (
    ExecutionAction,
    ExecutionEdge,
    ExecutionGraph,
    ExecutionNode,
    ExecutionPlan,
    NodeStatus,
    new_action_id,
)


def build_execution_plan(
    *,
    deployment_id: str,
    profile: ApplicationProfile,
    constraints: list[Constraint],
    config_fragments: dict[str, Any],
    fail_service: str | None = None,
    is_demo: bool = False,
) -> ExecutionPlan:
    stack_services = [s for s in profile.inferred_stack.services if s.name != "network"]
    names = [s.name for s in stack_services]

    # Canonical research graph when enough roles exist; else use inferred order.
    roles = {s.name: s.role for s in stack_services}
    ordered = _order_services(names, roles, constraints)

    # Ensure analytics independence when present
    if "analytics" not in ordered and any(n == "analytics" for n in names):
        ordered.append("analytics")

    # Minimal controlled fixture shape for demos/tests when services are sparse
    if len(ordered) < 2:
        ordered = ["network", "database", "backend", "frontend", "analytics"]

    # Always include network as first action
    if "network" not in ordered:
        ordered = ["network", *ordered]

    actions: list[ExecutionAction] = []
    deps_map: dict[str, list[str]] = {}
    prev_chain: str | None = None

    for name in ordered:
        parent: list[str] = []
        if name == "network":
            parent = []
        elif name == "analytics":
            # Independent branch off network only
            parent = ["network"] if "network" in ordered else []
        elif name == "database":
            parent = ["network"] if "network" in ordered else []
        elif name == "backend":
            parent = ["database"] if "database" in ordered else (["network"] if "network" in ordered else [])
        elif name == "frontend":
            parent = ["backend"] if "backend" in ordered else (prev_chain and [prev_chain] or [])
        else:
            parent = [prev_chain] if prev_chain else (["network"] if "network" in ordered else [])

        # Honor EXEC_ORDER constraints
        for c in constraints:
            if c.type != ConstraintType.EXEC_ORDER:
                continue
            if c.payload.get("after") == name and c.payload.get("before") in ordered:
                before = c.payload["before"]
                if before not in parent:
                    parent.append(before)

        action_id = f"n_{name}"
        actions.append(
            ExecutionAction(
                action_id=action_id,
                action_type="create_network" if name == "network" else "start_container",
                service=name,
                parent_actions=[f"n_{p}" if not p.startswith("n_") else p for p in parent],
                dependencies=[f"n_{p}" if not p.startswith("n_") else p for p in parent],
                reversible=True,
                rollback_action={"type": "remove", "service": name},
                metadata={"role": roles.get(name, "service")},
                config={"image": f"medha/{name}:local"},
            )
        )
        deps_map[action_id] = [f"n_{p}" if not str(p).startswith("n_") else p for p in parent]
        if name not in {"analytics"}:
            prev_chain = name

    compose = config_fragments.get("docker", {}).get("compose_fragment") or {
        "services": {a.service: {"image": a.config.get("image")} for a in actions if a.service != "network"}
    }

    return ExecutionPlan(
        deployment_id=deployment_id,
        services=[a.service for a in actions],
        networks=["medha_net"],
        volumes=[],
        actions=actions,
        dependencies=deps_map,
        compose=compose,
        fail_service=fail_service,
        is_demo=is_demo,
    )


def build_ceg_from_plan(plan: ExecutionPlan) -> ExecutionGraph:
    nodes: list[ExecutionNode] = []
    edges: list[ExecutionEdge] = []
    # Layout positions
    y_by_service = {
        "network": 0,
        "database": 120,
        "analytics": 120,
        "backend": 250,
        "frontend": 380,
    }
    x_by_service = {
        "network": 280,
        "database": 80,
        "analytics": 480,
        "backend": 80,
        "frontend": 80,
    }

    children: dict[str, list[str]] = {a.action_id: [] for a in plan.actions}
    for a in plan.actions:
        for p in a.parent_actions:
            children.setdefault(p, []).append(a.action_id)

    for idx, a in enumerate(plan.actions):
        nodes.append(
            ExecutionNode(
                node_id=a.action_id,
                action=a.action_type,
                service=a.service,
                status=NodeStatus.PENDING.value,
                parent_nodes=list(a.parent_actions),
                child_nodes=children.get(a.action_id, []),
                dependencies=list(a.dependencies),
                reversible=a.reversible,
                rollback_action=a.rollback_action,
                metadata=a.metadata,
                position={
                    "x": float(x_by_service.get(a.service, 100 + (idx % 3) * 160)),
                    "y": float(y_by_service.get(a.service, idx * 100)),
                },
                is_demo=plan.is_demo,
            )
        )
        for parent in a.parent_actions:
            edges.append(
                ExecutionEdge(
                    id=f"e_{parent}_{a.action_id}",
                    source=parent,
                    target=a.action_id,
                    relation="depends_on",
                )
            )

    return ExecutionGraph(
        deployment_id=plan.deployment_id,
        nodes=nodes,
        edges=edges,
        is_demo=plan.is_demo,
    )


def _order_services(
    names: list[str],
    roles: dict[str, str],
    constraints: list[Constraint],
) -> list[str]:
    preferred = ["database", "backend", "frontend", "analytics"]
    # Map roles to canonical names when possible
    mapped: list[str] = []
    used = set()
    by_role = {}
    for n, r in roles.items():
        by_role.setdefault(r, []).append(n)

    def take(candidates: list[str]) -> None:
        for c in candidates:
            if c in names and c not in used:
                mapped.append(c)
                used.add(c)

    take(["database", *by_role.get("database", [])])
    take(["backend", *by_role.get("api", []), *by_role.get("backend", []), *by_role.get("app", [])])
    take(["frontend", *by_role.get("web", [])])
    take(["analytics"])
    for n in names:
        if n not in used and n != "network":
            mapped.append(n)
            used.add(n)
    return mapped or preferred
