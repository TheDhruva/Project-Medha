"""Executor abstraction + simulator / docker implementations."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from typing import Any, Awaitable, Callable

from app.ceg.rollback import apply_scope_to_graph, compute_rollback_scope
from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.execution import docker_ops
from app.models.execution import (
    ExecutionGraph,
    ExecutionPlan,
    ExecutionResult,
    NodeStatus,
    RollbackScope,
)

logger = get_logger(__name__)

EventCallback = Callable[[str, str, dict[str, Any]], Awaitable[None]]

# Controlled local images only (never pull arbitrary repo builds in V1 mutate path).
SAFE_DEFAULT_IMAGE = "busybox:1.36"
SAFE_DEFAULT_COMMAND = ["sleep", "3600"]


class Executor(ABC):
    @abstractmethod
    async def execute(
        self,
        plan: ExecutionPlan,
        graph: ExecutionGraph,
        *,
        on_event: EventCallback | None = None,
    ) -> tuple[ExecutionGraph, ExecutionResult, RollbackScope | None]:
        raise NotImplementedError


class SimulatorExecutor(Executor):
    """Deterministic in-process executor (no Docker)."""

    def __init__(self, *, step_delay: float = 0.0, name: str = "simulator") -> None:
        self.step_delay = step_delay
        self.name = name

    async def execute(
        self,
        plan: ExecutionPlan,
        graph: ExecutionGraph,
        *,
        on_event: EventCallback | None = None,
    ) -> tuple[ExecutionGraph, ExecutionResult, RollbackScope | None]:
        started = time.time()
        nodes = {n.node_id: n.model_copy(deep=True) for n in graph.nodes}
        children: dict[str, list[str]] = defaultdict(list)
        parents = {n.node_id: list(n.parent_nodes) for n in graph.nodes}
        for n in graph.nodes:
            for p in n.parent_nodes:
                children[p].append(n.node_id)

        order = _topo_order([n.node_id for n in graph.nodes], parents)
        failed_id: str | None = None
        successful: list[str] = []
        skipped: set[str] = set()

        async def emit(etype: str, message: str, **meta: Any) -> None:
            if on_event:
                await on_event(etype, message, meta)

        for nid in order:
            node = nodes[nid]
            if nid in skipped or any(
                nodes[p].status == NodeStatus.FAILED.value for p in node.parent_nodes
            ):
                node.status = NodeStatus.SKIPPED.value
                node.timestamp = utc_now_iso()
                continue

            node.status = NodeStatus.RUNNING.value
            node.timestamp = utc_now_iso()
            await emit(
                "execution.node.started",
                f"{node.service} started",
                node_id=nid,
                service=node.service,
                graph=_graph_ui(nodes, graph),
            )
            if self.step_delay:
                await asyncio.sleep(self.step_delay)

            if plan.fail_service and node.service == plan.fail_service:
                node.status = NodeStatus.FAILED.value
                node.reason = "Simulated health check failed"
                node.timestamp = utc_now_iso()
                failed_id = nid
                await emit(
                    "execution.node.failed",
                    f"{node.service} failed",
                    node_id=nid,
                    service=node.service,
                    graph=_graph_ui(nodes, graph),
                )
                q = deque(children.get(nid, []))
                while q:
                    c = q.popleft()
                    skipped.add(c)
                    q.extend(children.get(c, []))
                continue

            node.status = NodeStatus.SUCCESS.value
            node.timestamp = utc_now_iso()
            successful.append(node.service)
            await emit(
                "execution.node.completed",
                f"{node.service} succeeded",
                node_id=nid,
                service=node.service,
                graph=_graph_ui(nodes, graph),
            )

        out_graph = ExecutionGraph(
            deployment_id=graph.deployment_id,
            nodes=list(nodes.values()),
            edges=list(graph.edges),
            is_demo=plan.is_demo,
        )
        if failed_id:
            return await _finalize_failure(
                plan=plan,
                graph=out_graph,
                nodes=nodes,
                failed_id=failed_id,
                started=started,
                executor_name=self.name,
                on_event=on_event,
                step_delay=self.step_delay,
                docker_rollback=False,
            )

        result = ExecutionResult(
            deployment_id=plan.deployment_id,
            status="SUCCESS",
            successful_services=successful,
            failed_services=[],
            rolled_back_services=[],
            preserved_services=successful,
            duration_seconds=time.time() - started,
            executor=self.name,
            is_demo=plan.is_demo,
        )
        return out_graph, result, None


class DockerExecutor(Executor):
    """
    Local Docker executor for verified MEDHA plans.

    Mutates Docker only when MEDHA_DOCKER_EXECUTE=true and the daemon is available.
    Uses allowlisted CLI + MEDHA labels. Never deletes unlabeled resources.
    """

    def __init__(self, *, step_delay: float = 0.05) -> None:
        self.step_delay = step_delay
        self._fallback = SimulatorExecutor(step_delay=step_delay, name="simulator_fallback")

    def available(self) -> bool:
        return docker_ops.docker_cli_available() and docker_ops.docker_daemon_running()

    async def execute(
        self,
        plan: ExecutionPlan,
        graph: ExecutionGraph,
        *,
        on_event: EventCallback | None = None,
    ) -> tuple[ExecutionGraph, ExecutionResult, RollbackScope | None]:
        from app.core.config import get_settings

        settings = get_settings()
        mode = (getattr(settings, "executor_mode", "auto") or "auto").lower()
        prefer_mutate = bool(getattr(settings, "docker_execute", False)) and mode != "simulator"

        # Controlled failure injection stays on simulator (deterministic tests).
        if plan.fail_service or mode == "simulator" or not prefer_mutate:
            logger.info(
                "DockerExecutor using simulator (available=%s execute=%s fail=%s mode=%s)",
                self.available(),
                prefer_mutate,
                plan.fail_service,
                mode,
            )
            return await self._fallback.execute(plan, graph, on_event=on_event)

        if prefer_mutate and not self.available():
            # Do not silently present simulator success as a Docker mutate run.
            err = (
                "MEDHA_DOCKER_EXECUTE is enabled but Docker CLI/daemon is unavailable. "
                "Refusing silent simulator fallback for real Docker mutate."
            )
            logger.error(err)
            failed = graph.nodes[0].node_id if graph.nodes else "n_unknown"
            result = ExecutionResult(
                deployment_id=plan.deployment_id,
                status="FAILED",
                successful_services=[],
                failed_services=[n.service for n in graph.nodes[:1]],
                rolled_back_services=[],
                preserved_services=[],
                duration_seconds=0.0,
                executor="docker_unavailable",
                is_demo=plan.is_demo,
                errors=[err],
            )
            out = ExecutionGraph(
                deployment_id=graph.deployment_id,
                nodes=[
                    n.model_copy(
                        update={
                            "status": "failed" if n.node_id == failed else "skipped",
                            "reason": err if n.node_id == failed else "Skipped — Docker unavailable",
                        }
                    )
                    for n in graph.nodes
                ],
                edges=list(graph.edges),
                is_demo=plan.is_demo,
            )
            return out, result, None

        return await self._execute_docker(plan, graph, on_event=on_event)

    async def _execute_docker(
        self,
        plan: ExecutionPlan,
        graph: ExecutionGraph,
        *,
        on_event: EventCallback | None,
    ) -> tuple[ExecutionGraph, ExecutionResult, RollbackScope | None]:
        started = time.time()
        deployment_id = plan.deployment_id
        nodes = {n.node_id: n.model_copy(deep=True) for n in graph.nodes}
        children: dict[str, list[str]] = defaultdict(list)
        parents = {n.node_id: list(n.parent_nodes) for n in graph.nodes}
        for n in graph.nodes:
            for p in n.parent_nodes:
                children[p].append(n.node_id)
        order = _topo_order([n.node_id for n in graph.nodes], parents)

        started_containers: dict[str, str] = {}  # service -> container name
        network: str | None = None
        failed_id: str | None = None
        successful: list[str] = []
        skipped: set[str] = set()
        errors: list[str] = []

        async def emit(etype: str, message: str, **meta: Any) -> None:
            if on_event:
                await on_event(etype, message, meta)

        try:
            network = await asyncio.to_thread(docker_ops.create_network, deployment_id)
            for nid in order:
                node = nodes[nid]
                if nid in skipped or any(
                    nodes[p].status == NodeStatus.FAILED.value for p in node.parent_nodes
                ):
                    node.status = NodeStatus.SKIPPED.value
                    node.timestamp = utc_now_iso()
                    continue

                node.status = NodeStatus.RUNNING.value
                node.timestamp = utc_now_iso()
                await emit(
                    "execution.node.started",
                    f"{node.service} started",
                    node_id=nid,
                    service=node.service,
                    graph=_graph_ui(nodes, graph),
                )
                if self.step_delay:
                    await asyncio.sleep(self.step_delay)

                try:
                    if node.service == "network" or node.action == "create_network":
                        # Network already created
                        ok = True
                    else:
                        image, command, ports, env = _resolve_runtime_spec(plan, node.service)
                        cname = await asyncio.to_thread(
                            docker_ops.start_container,
                            deployment_id=deployment_id,
                            service=node.service,
                            image=image,
                            network=network,
                            command=command,
                            ports=ports,
                            env=env,
                        )
                        started_containers[node.service] = cname
                        ok = await asyncio.to_thread(docker_ops.container_running, cname)
                        if not ok:
                            raise docker_ops.DockerOpsError(
                                f"Health check failed for {node.service}",
                                code="HEALTH_FAILED",
                            )
                except docker_ops.DockerOpsError as exc:
                    node.status = NodeStatus.FAILED.value
                    node.reason = str(exc)
                    node.timestamp = utc_now_iso()
                    failed_id = nid
                    errors.append(str(exc))
                    await emit(
                        "execution.node.failed",
                        f"{node.service} failed",
                        node_id=nid,
                        service=node.service,
                        graph=_graph_ui(nodes, graph),
                    )
                    q = deque(children.get(nid, []))
                    while q:
                        c = q.popleft()
                        skipped.add(c)
                        q.extend(children.get(c, []))
                    continue

                node.status = NodeStatus.SUCCESS.value
                node.timestamp = utc_now_iso()
                successful.append(node.service)
                await emit(
                    "execution.node.completed",
                    f"{node.service} succeeded",
                    node_id=nid,
                    service=node.service,
                    graph=_graph_ui(nodes, graph),
                )
        except Exception as exc:  # noqa: BLE001
            logger.exception("Docker execution aborted")
            errors.append(str(exc))
            if failed_id is None and order:
                # Mark first pending/running as failed
                for nid in order:
                    if nodes[nid].status in {
                        NodeStatus.PENDING.value,
                        NodeStatus.RUNNING.value,
                    }:
                        nodes[nid].status = NodeStatus.FAILED.value
                        nodes[nid].reason = str(exc)
                        failed_id = nid
                        break

        out_graph = ExecutionGraph(
            deployment_id=graph.deployment_id,
            nodes=list(nodes.values()),
            edges=list(graph.edges),
            is_demo=plan.is_demo,
        )

        if failed_id:
            return await _finalize_failure(
                plan=plan,
                graph=out_graph,
                nodes=nodes,
                failed_id=failed_id,
                started=started,
                executor_name="docker",
                on_event=on_event,
                step_delay=self.step_delay,
                docker_rollback=True,
                started_containers=started_containers,
                errors=errors,
            )

        result = ExecutionResult(
            deployment_id=plan.deployment_id,
            status="SUCCESS",
            successful_services=successful,
            failed_services=[],
            rolled_back_services=[],
            preserved_services=successful,
            duration_seconds=time.time() - started,
            executor="docker",
            is_demo=plan.is_demo,
            errors=errors,
        )
        return out_graph, result, None


def choose_executor(*, is_demo: bool, prefer_docker: bool = True) -> Executor:
    if is_demo:
        return SimulatorExecutor(name="demo")
    from app.core.config import get_settings

    settings = get_settings()
    mode = (settings.executor_mode or "auto").lower()
    if mode == "simulator" or not prefer_docker:
        return SimulatorExecutor(name="simulator")
    if mode == "docker" or settings.docker_execute or prefer_docker:
        return DockerExecutor()
    return SimulatorExecutor(name="simulator")


async def _finalize_failure(
    *,
    plan: ExecutionPlan,
    graph: ExecutionGraph,
    nodes: dict[str, Any],
    failed_id: str,
    started: float,
    executor_name: str,
    on_event: EventCallback | None,
    step_delay: float,
    docker_rollback: bool,
    started_containers: dict[str, str] | None = None,
    errors: list[str] | None = None,
) -> tuple[ExecutionGraph, ExecutionResult, RollbackScope]:
    scope = compute_rollback_scope(graph, failed_id, is_demo=plan.is_demo)
    started_containers = started_containers or {}
    rollback_failed = False

    for rid in scope.nodes_to_rollback:
        n = nodes[rid]
        if on_event:
            await on_event(
                "rollback.node",
                f"{n.service} rolled back",
                {"node_id": rid, "service": n.service},
            )
        if docker_rollback and n.service in started_containers:
            cname = started_containers[n.service]
            ok = await asyncio.to_thread(
                docker_ops.stop_and_remove_container,
                cname,
                deployment_id=plan.deployment_id,
            )
            if not ok:
                rollback_failed = True
                scope.not_rollbackable.append(rid)
        if step_delay:
            await asyncio.sleep(step_delay)

    # Also stop the failed service container if present (failed node itself)
    if docker_rollback and failed_id in nodes:
        failed_svc = nodes[failed_id].service
        if failed_svc in started_containers:
            await asyncio.to_thread(
                docker_ops.stop_and_remove_container,
                started_containers[failed_svc],
                deployment_id=plan.deployment_id,
            )

    out_graph = apply_scope_to_graph(
        ExecutionGraph(
            deployment_id=graph.deployment_id,
            nodes=list(nodes.values()),
            edges=list(graph.edges),
            is_demo=plan.is_demo,
        ),
        scope,
    )

    # Verify preserved containers still running (docker path)
    if docker_rollback:
        for nid in scope.nodes_preserved:
            svc = nodes[nid].service if nid in nodes else None
            if not svc or svc == "network" or svc not in started_containers:
                continue
            running = await asyncio.to_thread(
                docker_ops.container_running, started_containers[svc]
            )
            if not running:
                rollback_failed = True
                errors = list(errors or [])
                errors.append(f"Preserved service {svc} is not running after rollback")

    details = []
    for n in out_graph.nodes:
        if n.status in {
            NodeStatus.PRESERVED.value,
            NodeStatus.FAILED.value,
            NodeStatus.ROLLED_BACK.value,
        }:
            details.append(
                {
                    "service": n.service.upper(),
                    "status": n.status,
                    "note": n.reason or n.status,
                }
            )
    object.__setattr__(scope, "_details", details)

    status = "ROLLBACK_FAILED" if rollback_failed else "PARTIAL_FAILURE"
    result = ExecutionResult(
        deployment_id=plan.deployment_id,
        status=status,
        successful_services=[
            n.service
            for n in out_graph.nodes
            if n.status in {NodeStatus.SUCCESS.value, NodeStatus.PRESERVED.value}
        ],
        failed_services=[nodes[failed_id].service],
        rolled_back_services=[nodes[i].service for i in scope.nodes_to_rollback if i in nodes],
        preserved_services=[nodes[i].service for i in scope.nodes_preserved if i in nodes],
        duration_seconds=time.time() - started,
        executor=executor_name,
        is_demo=plan.is_demo,
        errors=list(errors or []),
    )
    return out_graph, result, scope


def _resolve_runtime_spec(
    plan: ExecutionPlan, service: str
) -> tuple[str, list[str], list[str] | None, dict[str, str] | None]:
    """Map verified plan service to safe local runtime (busybox by default)."""
    compose = plan.compose or {}
    services = compose.get("services") or {}
    spec = services.get(service) or {}
    image = str(spec.get("image") or SAFE_DEFAULT_IMAGE)
    # Force known-safe images for mutate path — avoid building untrusted Dockerfiles.
    if image.startswith("medha/") or not docker_ops._safe_image(image):
        image = SAFE_DEFAULT_IMAGE
    command = spec.get("command")
    if isinstance(command, str):
        command = command.split()
    if not isinstance(command, list) or not command:
        command = list(SAFE_DEFAULT_COMMAND)
    ports = None
    raw_ports = spec.get("ports")
    if isinstance(raw_ports, list):
        ports = [str(p) for p in raw_ports if isinstance(p, (str, int))]
    env = None
    raw_env = spec.get("environment")
    if isinstance(raw_env, dict):
        env = {str(k): str(v) for k, v in raw_env.items()}
    return image, [str(c) for c in command], ports, env


def _topo_order(node_ids: list[str], parents: dict[str, list[str]]) -> list[str]:
    indeg = {n: 0 for n in node_ids}
    children: dict[str, list[str]] = defaultdict(list)
    for n, ps in parents.items():
        for p in ps:
            children[p].append(n)
            if n in indeg:
                indeg[n] += 1
    q = deque([n for n, d in indeg.items() if d == 0])
    out: list[str] = []
    while q:
        n = q.popleft()
        out.append(n)
        for c in children.get(n, []):
            indeg[c] -= 1
            if indeg[c] == 0:
                q.append(c)
    for n in node_ids:
        if n not in out:
            out.append(n)
    return out


def _graph_ui(nodes: dict[str, Any], graph: ExecutionGraph) -> dict[str, Any]:
    tmp = ExecutionGraph(
        deployment_id=graph.deployment_id,
        nodes=list(nodes.values()),
        edges=list(graph.edges),
        is_demo=graph.is_demo,
    )
    return tmp.to_ui()
