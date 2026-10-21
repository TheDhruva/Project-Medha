"""Live-execution enforcement + Issue B regression (repository_analysis kwarg).

Drives the full pipeline in explicit real mode with the isolated RealExecutor
mocked at the Docker boundary (no real containers are ever started). Proves:
real mode invokes the real executor, never silently simulates; the executor's
result and repository-analysis provenance reach the persisted result; and the
`_run_real_execute()` signature accepts `repository_analysis`.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess

import pytest

from app.core.config import get_settings
from app.core.enums import DeploymentStatus
from app.core.events import utc_now_iso
from app.database.connection import init_db
from app.database.repositories import DeploymentRepository
from app.execution.real_executor import RealDeployResult, RealExecutor
from app.models.deployment import DeploymentRecord
from app.workflow.planning import PlanningPipeline


def _node_repo(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "package.json").write_text(
        json.dumps({"name": "app", "scripts": {"start": "node index.js"}}),
        encoding="utf-8",
    )
    (src / "index.js").write_text("console.log('up')", encoding="utf-8")
    return src


def _git_commit(repo) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@e.test",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@e.test",
    }
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"], cwd=repo, check=True,
        capture_output=True, env=env,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _record(deployment_id: str, repo: str) -> DeploymentRecord:
    now = utc_now_iso()
    return DeploymentRecord(
        deployment_id=deployment_id,
        repository_url=repo,
        mode="real",
        scenario=None,
        target_host="localhost",
        target_port=18080,
        intent="enforcement",
        base_revision=None,
        target_revision=None,
        status=DeploymentStatus.STARTED,
        current_stage=None,
        created_at=now,
        updated_at=now,
        is_demo=False,
    )


@pytest.fixture()
def real_mode(monkeypatch):
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    monkeypatch.setenv("MEDHA_AUTH_MODE", "off")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _run_pipeline(repo, deployment_id):
    asyncio.run(PlanningPipeline(repo=repo).run(deployment_id))


def test_real_mode_invokes_real_executor_and_persists_provenance(tmp_path, real_mode, monkeypatch):
    db = tmp_path / "t.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    src = _node_repo(tmp_path)
    dep = "dep_real_ok"
    repo.create(_record(dep, str(src)))

    calls: list[dict] = []

    async def fake_deploy(self, **kwargs):
        calls.append(kwargs)
        return RealDeployResult(
            ok=True,
            profile="node",
            image="medha-app:local",
            image_digest="sha256:deadbeef",
            container="medha_c1_app",
            port=kwargs.get("host_port"),
            readiness={"status": "ready", "probe_url": "http://127.0.0.1:18080/"},
            runtime_spec={"profile": "node"},
        )

    monkeypatch.setattr(RealExecutor, "deploy", fake_deploy)

    _run_pipeline(repo, dep)

    stored = repo.get(dep)
    assert stored is not None
    assert stored.status == DeploymentStatus.COMPLETED, stored.result
    result = stored.result
    # Real executor was actually invoked (never the simulator).
    assert len(calls) == 1
    assert result["execution_mode"] == "real"
    assert result.get("container") == "medha_c1_app"
    assert result.get("readiness", {}).get("status") == "ready"
    # Repository-analysis provenance survived all the way to the result.
    assert isinstance(result.get("repository_analysis"), dict)
    assert result["repository_analysis"]["schema"] == "repository-analysis/v1"
    # Timings are persisted (a real run is not a zero-second run).
    assert result.get("timings", {}).get("totalMs", 0) > 0


def test_real_execute_signature_accepts_repository_analysis():
    import inspect

    params = inspect.signature(PlanningPipeline._run_real_execute).parameters
    assert "repository_analysis" in params


def test_local_git_head_sha_retained_in_analysis_and_deployment(
    tmp_path, real_mode, monkeypatch
):
    db = tmp_path / "t4.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    src = _node_repo(tmp_path)
    sha = _git_commit(src)
    dep = "dep_real_sha"
    repo.create(_record(dep, str(src)))

    async def fake_deploy(self, **kwargs):
        assert kwargs.get("commit_sha") == sha  # pinned to the analyzed commit
        return RealDeployResult(
            ok=True, profile="node", image="x", image_digest="sha256:1",
            container="c1", port=kwargs.get("host_port"),
            readiness={"status": "ready"}, runtime_spec={"profile": "node"},
        )

    monkeypatch.setattr(RealExecutor, "deploy", fake_deploy)
    _run_pipeline(repo, dep)

    stored = repo.get(dep)
    assert stored.status == DeploymentStatus.COMPLETED, stored.result
    result = stored.result
    # Same exact SHA in analysis provenance and deployment provenance.
    assert result["target_sha"] == sha
    analysis = result["repository_analysis"]
    assert analysis["commit_sha"] == sha
    assert analysis["revision"]["sha"] == sha
    assert analysis["revision"]["available"] is True


def test_unsupported_profile_real_failure_preserves_analysis(tmp_path, real_mode, monkeypatch):
    db = tmp_path / "t2.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    src = _node_repo(tmp_path)
    dep = "dep_real_fail"
    repo.create(_record(dep, str(src)))

    async def failing_deploy(self, **kwargs):
        return RealDeployResult(
            ok=False, code="READINESS_FAILED", profile="node",
            container="medha_c1_app", image="medha-app:local",
            readiness={"status": "timed_out", "stage": "connection_refused"},
            message="Application did not become ready.",
        )

    monkeypatch.setattr(RealExecutor, "deploy", failing_deploy)
    monkeypatch.setattr(RealExecutor, "cleanup", lambda self, **kwargs: _noop())

    _run_pipeline(repo, dep)

    stored = repo.get(dep)
    assert stored.status == DeploymentStatus.FAILED
    result = stored.result
    assert result["execution_mode"] == "real"
    assert result["code"] == "READINESS_FAILED"
    # Analysis report is not discarded by a live-execution failure.
    assert result["repository_analysis"]["schema"] == "repository-analysis/v1"
    assert result.get("timings", {}).get("totalMs", 0) > 0


def test_real_build_failure_persists_diagnostics_and_analysis(
    tmp_path, real_mode, monkeypatch
):
    db = tmp_path / "t5.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    src = _node_repo(tmp_path)
    dep = "dep_real_build_fail"
    repo.create(_record(dep, str(src)))

    async def failing_build(self, **kwargs):
        return RealDeployResult(
            ok=False, code="BUILD_FAILED", profile="node", image="medha-app:local",
            message="Image build failed (npm ERESOLVE) (exit=1): peer zod conflict",
            build={
                "stage": "build", "package_manager": "npm", "app_root": ".",
                "command": "RUN npm ci --no-audit --no-fund",
                "exit_code": 1, "error_code": "ERESOLVE",
                "log": "npm error code ERESOLVE", "log_truncated": False,
            },
        )

    monkeypatch.setattr(RealExecutor, "deploy", failing_build)
    monkeypatch.setattr(RealExecutor, "cleanup", lambda self, **kwargs: _noop())

    _run_pipeline(repo, dep)

    stored = repo.get(dep)
    assert stored.status == DeploymentStatus.FAILED
    result = stored.result
    assert result["execution_mode"] == "real"
    assert result["code"] == "BUILD_FAILED"
    # Structured diagnostics reach the persisted result.
    assert result["build"]["error_code"] == "ERESOLVE"
    assert result["build"]["exit_code"] == 1
    # A build failure never fabricates readiness, and analysis survives.
    assert result["readiness"] == {}
    assert result["repository_analysis"]["schema"] == "repository-analysis/v1"
    assert result.get("timings", {}).get("totalMs", 0) > 0


async def _noop():
    return None


def test_real_mode_without_docker_fails_closed_never_simulates(
    tmp_path, real_mode, monkeypatch
):
    from app.execution import docker_ops
    from app.execution.executor import SimulatorExecutor

    db = tmp_path / "t3.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    src = _node_repo(tmp_path)
    dep = "dep_real_nodocker"
    repo.create(_record(dep, str(src)))

    # Docker passes the preflight, but the isolated builder is unavailable at
    # execute time: the run must fail closed, never substitute the simulator.
    monkeypatch.setattr(docker_ops, "docker_cli_available", lambda: True)
    monkeypatch.setattr(docker_ops, "docker_daemon_running", lambda: True)
    # If the pipeline ever tried to simulate, this would blow up the test.
    monkeypatch.setattr(
        SimulatorExecutor, "execute",
        lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("simulator used")),
    )

    async def unavailable(self, **kwargs):
        return RealDeployResult(
            ok=False, code="REAL_BUILDER_UNAVAILABLE",
            message="Isolated runtime unavailable.",
        )

    monkeypatch.setattr(RealExecutor, "deploy", unavailable)

    _run_pipeline(repo, dep)

    stored = repo.get(dep)
    assert stored.status == DeploymentStatus.FAILED
    result = stored.result
    assert result["code"] == "REAL_BUILDER_UNAVAILABLE"
    assert result["execution_mode"] == "real"
    assert result.get("container") is None
    # Live failure still carries the analysis report.
    assert result["repository_analysis"]["schema"] == "repository-analysis/v1"
