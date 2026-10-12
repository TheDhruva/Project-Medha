"""Gated live E2E: real build + readiness + logs (requires isolated Docker host).

Runs only when MEDHA_E2E_REAL=1 AND a Docker daemon is reachable. Never runs
malicious code: fixtures are MEDHA-owned static/python/node apps. Skipped
everywhere else (unit suite is the default gate).
"""
from __future__ import annotations

import os
import shutil

import pytest

from app.execution import docker_ops

LIVE = os.environ.get("MEDHA_E2E_REAL") == "1"
HAS_DOCKER = shutil.which("docker") is not None and docker_ops.docker_daemon_running()

pytestmark = pytest.mark.skipif(
    not (LIVE and HAS_DOCKER),
    reason="live E2E needs MEDHA_E2E_REAL=1 and a Docker daemon",
)


def test_live_static_deploy_ready_with_logs(tmp_path):
    import asyncio

    from app.execution.real_executor import RealExecutor

    checkout = tmp_path / "site"
    checkout.mkdir()
    (checkout / "index.html").write_text("<h1>medha e2e</h1>", encoding="utf-8")
    outcome = asyncio.run(
        RealExecutor().deploy(
            deployment_id="dep_e2e1", checkout=checkout, target_port=18081,
            readiness_timeout=60, build_timeout=300,
        )
    )
    try:
        assert outcome.ok, outcome.message
        assert outcome.readiness.get("status") == "ready"
        assert outcome.image_digest
        logs = asyncio.run(RealExecutor().logs(container=outcome.container or ""))
        assert isinstance(logs, dict)
    finally:
        asyncio.run(
            RealExecutor().cleanup(
                deployment_id="dep_e2e1", container=outcome.container,
                image=outcome.image,
            )
        )
