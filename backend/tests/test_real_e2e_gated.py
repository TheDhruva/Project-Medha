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


def test_live_pipeline_static_deploy_persists_real_provenance(tmp_path, monkeypatch):
    """Full pipeline in real mode against a MEDHA-owned static fixture.

    No Docker mocking anywhere: build, run, readiness and provenance are all
    genuine. Proves live mode drives the real executor (never the simulator)
    and persists execution + analysis provenance on success.
    """
    import asyncio
    import os
    import subprocess

    from app.core.config import get_settings
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.execution.real_executor import RealExecutor
    from app.models.deployment import DeploymentRecord
    from app.workflow.planning import PlanningPipeline

    monkeypatch.setenv("MEDHA_ENV", "development")
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()

    checkout = tmp_path / "site"
    checkout.mkdir()
    (checkout / "index.html").write_text("<h1>medha e2e</h1>", encoding="utf-8")
    git_env = {
        **os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.test",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.test",
    }
    subprocess.run(["git", "init"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=checkout, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=checkout, check=True,
        capture_output=True, env=git_env,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=checkout, check=True,
        capture_output=True, text=True,
    ).stdout.strip()

    db = tmp_path / "e2e.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    dep = "dep_e2e_pipeline"
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id=dep, repository_url=str(checkout), mode="real",
        scenario=None, target_host="localhost", target_port=18082,
        intent="e2e", base_revision=None, target_revision=None,
        status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))

    container = None
    image = None
    try:
        asyncio.run(PlanningPipeline(repo=repo).run(dep))
        stored = repo.get(dep)
        assert stored is not None
        result = stored.result or {}
        container = result.get("container")
        image = result.get("image")
        assert stored.status == DeploymentStatus.COMPLETED, result
        assert result["execution_mode"] == "real"
        assert result["readiness"]["status"] == "ready"
        assert result.get("image_digest")
        assert result["target_sha"] == sha
        assert result["repository_analysis"]["commit_sha"] == sha
    finally:
        if container or image:
            asyncio.run(
                RealExecutor().cleanup(
                    deployment_id=dep, container=container, image=image
                )
            )


def test_live_node_deploy_ready_and_reports_real_mode(tmp_path, monkeypatch):
    """Node profile end-to-end live: install, run, readiness, provenance.

    Dependency-free MEDHA-owned Node app (built-in http only) so the install
    layer is exercised without third-party supply chain risk. Proves the Node
    profile builds and serves for real and reports execution_mode=real with no
    fabricated readiness.
    """
    import asyncio
    import json

    from app.core.config import get_settings
    from app.execution.real_executor import RealExecutor

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()

    checkout = tmp_path / "nodeapp"
    checkout.mkdir()
    (checkout / "package.json").write_text(
        json.dumps({"name": "medha-node", "scripts": {"start": "node server.js"}}),
        encoding="utf-8",
    )
    # The node profile bakes PORT=<negotiated target port> (see profiles.py),
    # so the app must bind process.env.PORT.
    (checkout / "server.js").write_text(
        "require('http').createServer((_, res) => {"
        " res.writeHead(200); res.end('ok'); })"
        ".listen(process.env.PORT || 18083);",
        encoding="utf-8",
    )
    outcome = asyncio.run(
        RealExecutor().deploy(
            deployment_id="dep_e2e_node", checkout=checkout, target_port=18083,
            readiness_timeout=60, build_timeout=300,
        )
    )
    try:
        assert outcome.ok, outcome.message
        assert outcome.execution_mode == "real"
        assert outcome.readiness.get("status") == "ready"
        assert outcome.readiness.get("http_status") == 200
        assert outcome.image_digest
    finally:
        asyncio.run(
            RealExecutor().cleanup(
                deployment_id="dep_e2e_node", container=outcome.container,
                image=outcome.image,
            )
        )


def test_live_static_deploy_ready_with_logs(tmp_path, monkeypatch):
    import asyncio

    from app.core.config import get_settings
    from app.execution.real_executor import RealExecutor

    # Pin real execution explicitly: the suite-wide autouse fixture selects
    # the simulator, so declare the operator configuration here (same values
    # as the documented .env: MEDHA_EXECUTOR_MODE=real + MEDHA_DOCKER_EXECUTE).
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()

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
