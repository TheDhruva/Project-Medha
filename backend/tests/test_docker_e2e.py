"""Docker E2E — skipped when Docker daemon unavailable."""

from __future__ import annotations

import pytest

from app.execution import docker_ops
from app.execution.executor import DockerExecutor
from app.execution.plan_builder import build_ceg_from_plan, build_execution_plan
from app.models.domain import ApplicationProfile, Constraint, InferredStack, ServiceHint
from app.models.execution import NodeStatus

pytestmark = pytest.mark.docker


def _docker_ready() -> bool:
    return docker_ops.docker_cli_available() and docker_ops.docker_daemon_running()


@pytest.mark.skipif(not _docker_ready(), reason="Docker daemon unavailable")
def test_docker_labeled_cleanup_only_medha(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type(
            "S",
            (),
            {"docker_execute": True, "executor_mode": "docker", "docker_cleanup": True},
        )(),
    )

    dep = "dep_dockertest01"
    docker_ops.cleanup_deployment(dep)
    try:
        net = docker_ops.create_network(dep)
        assert net
        cname = docker_ops.start_container(
            deployment_id=dep,
            service="analytics",
            image="busybox:1.36",
            network=net,
            command=["sleep", "60"],
        )
        assert docker_ops.container_running(cname)
        # Unrelated name must not be deleted
        foreign = "not_medha_foreign_probe"
        removed = docker_ops.stop_and_remove_container(foreign, deployment_id=dep)
        assert removed is False
        cleaned = docker_ops.cleanup_deployment(dep)
        assert cname in cleaned["removed"] or not docker_ops.container_running(cname)
    finally:
        docker_ops.cleanup_deployment(dep)
        get_settings.cache_clear()


@pytest.mark.skipif(not _docker_ready(), reason="Docker daemon unavailable")
@pytest.mark.asyncio
async def test_docker_executor_topo_order(monkeypatch):
    monkeypatch.setattr(
        "app.core.config.get_settings",
        lambda: type(
            "S",
            (),
            {"docker_execute": True, "executor_mode": "docker", "docker_cleanup": True},
        )(),
    )
    dep = "dep_dockerexec02"
    docker_ops.cleanup_deployment(dep)
    profile = ApplicationProfile(
        deployment_id=dep,
        repository_url="fixture",
        workspace_path=".",
        target_host="localhost",
        target_port=18080,
        inferred_stack=InferredStack(
            services=[
                ServiceHint(name="network", role="network"),
                ServiceHint(name="database", role="database"),
                ServiceHint(name="backend", role="api"),
                ServiceHint(name="frontend", role="web"),
                ServiceHint(name="analytics", role="service"),
            ],
            has_compose=True,
            confidence=0.9,
        ),
    )
    plan = build_execution_plan(
        deployment_id=dep,
        profile=profile,
        constraints=[],
        config_fragments={
            "docker": {
                "compose_fragment": {
                    "services": {
                        "database": {"image": "busybox:1.36", "command": ["sleep", "30"]},
                        "backend": {"image": "busybox:1.36", "command": ["sleep", "30"]},
                        "frontend": {"image": "busybox:1.36", "command": ["sleep", "30"]},
                        "analytics": {"image": "busybox:1.36", "command": ["sleep", "30"]},
                    }
                }
            }
        },
    )
    ceg = build_ceg_from_plan(plan)
    try:
        graph, result, scope = await DockerExecutor(step_delay=0).execute(plan, ceg)
        assert scope is None
        assert result.status == "SUCCESS"
        assert result.executor == "docker"
        assert all(
            n.status == NodeStatus.SUCCESS.value for n in graph.nodes
        )
    finally:
        docker_ops.cleanup_deployment(dep)
