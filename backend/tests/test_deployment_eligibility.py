"""Deployment eligibility + pipeline diagnostics regressions.

A repository can be analyzed successfully without being deployable:
dependency manifests are language/dependency evidence, never proof of a
web application. Framework, library, and CLI repositories keep their
analysis and are blocked as deployment-not-applicable — never a synthetic
deployable backend, never an execution attempt. Unexpected pipeline
exceptions become persisted terminal failures with a stage-attributed
diagnostic; routine status updates never erase an existing diagnostic.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from tests.conftest import _deploy_payload


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _analyze(tmp_path: Path, **kwargs):
    from app.agents.analyzer import analyze_repository

    return analyze_repository(
        deployment_id="dep_elig",
        repository_url=str(tmp_path),
        workspace_path=tmp_path,
        target_host="localhost",
        target_port=8080,
        **kwargs,
    )


def _wait_terminal(client, deployment_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def _framework_repo(root: Path) -> None:
    """A framework repository's shape: Python package + CLI scripts, no app."""
    _write(root / "requirements.txt", "fastapi\n")
    _write(
        root / "pyproject.toml",
        '[project]\nname = "demo-framework"\n\n'
        '[project.scripts]\ndemo = "demo.cli:main"\n',
    )
    _write(root / "demo" / "__init__.py", "__version__ = '0.1.0'\n")
    _write(root / "tests" / "test_demo.py", "def test_x(): ...\n")


# --- analyzer + support gate -------------------------------------------------


def test_python_framework_repo_analysis_persists_deployment_blocked(tmp_path):
    from app.execution.support import assess_plan_support

    _framework_repo(tmp_path)
    profile, result = _analyze(tmp_path)
    # Analysis succeeds and preserves its evidence ...
    assert result.ok
    assert result.summary
    assert profile.inferred_stack.language_runtime == "python"
    # ... but nothing was synthesized into a deployable backend.
    assert profile.inferred_stack.app_candidates == []
    assert not any(s.role in {"api", "backend"} for s in profile.inferred_stack.services)
    # [project.scripts] is CLI evidence, never a web entrypoint.
    assert all(
        "project.scripts" not in ep for ep in profile.inferred_stack.entry_points
    )
    decision = assess_plan_support(profile)
    assert decision.supported is False
    assert decision.code == "NO_DEPLOYABLE_APP"
    assert "Analysis completed" in decision.message


def test_conventional_python_app_remains_supported(tmp_path):
    from app.execution.runtime import detect_runtime
    from app.execution.support import assess_plan_support

    _write(tmp_path / "requirements.txt", "fastapi\nuvicorn\n")
    _write(tmp_path / "app.py", "app = object()\n")
    profile, _ = _analyze(tmp_path)
    assert profile.inferred_stack.app_candidates == ["."]
    assert any(s.role == "api" for s in profile.inferred_stack.services)
    assert assess_plan_support(profile).supported is True
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.profile == "python-asgi"


def test_python_library_manifest_only_never_deployable(tmp_path):
    from app.execution.support import assess_plan_support

    _write(tmp_path / "requirements.txt", "requests\npydantic\n")
    profile, _ = _analyze(tmp_path)
    assert profile.inferred_stack.app_candidates == []
    assert not any(
        s.role in {"api", "backend"} for s in profile.inferred_stack.services
    )
    assert assess_plan_support(profile).code == "NO_DEPLOYABLE_APP"


def test_python_cli_scripts_not_a_web_service(tmp_path):
    from app.execution.support import assess_plan_support

    _write(tmp_path / "requirements.txt", "fastapi\n")
    _write(tmp_path / "pyproject.toml", '[project.scripts]\nmytool = "mytool.cli:main"\n')
    profile, _ = _analyze(tmp_path)
    assert all(
        "project.scripts" not in ep for ep in profile.inferred_stack.entry_points
    )
    assert any("CLI evidence" in n for n in profile.inferred_stack.notes)
    decision = assess_plan_support(profile)
    assert decision.supported is False
    assert decision.code == "NO_DEPLOYABLE_APP"


def test_dockerfile_backed_python_manifests_remain_supported(tmp_path):
    from app.execution.support import assess_plan_support

    _write(tmp_path / "requirements.txt", "requests\n")
    _write(
        tmp_path / "Dockerfile",
        'FROM python:3.12-slim\nCMD ["python", "worker.py"]\n',
    )
    profile, _ = _analyze(tmp_path)
    assert assess_plan_support(profile).supported is True


# --- pipeline: blocked deployment keeps the analysis, never executes ---------


def test_framework_repo_run_blocked_with_analysis_preserved(client, tmp_path):
    _framework_repo(tmp_path)
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(
            mode="real", scenario=None, repository_url=str(tmp_path)
        ),
    )
    assert resp.status_code == 202, resp.text
    deployment_id = resp.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)
    assert final["status"] == "failed"
    result = final["result"]
    assert result["code"] == "NO_DEPLOYABLE_APP"
    assert result["blocked"] is True
    assert result["deployment"]["status"] == "blocked"
    # No fabricated execution/verification success for stages that never ran.
    assert result["verificationScore"] is None
    # Analysis evidence persists on the blocked run.
    assert result["repository_analysis"]["analysis_status"] in {"completed", "partial"}
    assert result["repository_intelligence"] is not None
    health = client.get(f"/api/deploy/{deployment_id}/health").json()
    assert health["health_status"] != "healthy"
    # Execution and verification stages never ran.
    from app.core.config import get_settings
    from app.database.repositories import DeploymentRepository

    repo = DeploymentRepository(db_path=get_settings().database_path)
    events = repo.list_events(deployment_id, 500)
    ran_stages = {(e.stage or "").upper() for e in events}
    assert "EXECUTE" not in ran_stages
    assert "VERIFY" not in ran_stages


# --- pipeline: unexpected errors persist a stage-attributed diagnostic ------


def test_pipeline_unexpected_error_persists_diagnostics(tmp_path, monkeypatch):
    import app.workflow.planning as planning
    from app.core.enums import DeploymentStatus, StageId
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord
    from app.workflow.planning import PlanningPipeline

    db = tmp_path / "t.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    src = tmp_path / "src"
    src.mkdir()
    _write(src / "package.json", '{"scripts": {"start": "node i.js"}}')
    repo.create(DeploymentRecord(
        deployment_id="dep_boom", repository_url=str(src),
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))

    def boom(*args, **kwargs):
        raise RuntimeError("analyzer exploded")

    monkeypatch.setattr(planning, "analyze_repository", boom)
    asyncio.run(PlanningPipeline(repo=repo).run("dep_boom"))

    stored = repo.get("dep_boom")
    assert stored is not None
    assert stored.status == DeploymentStatus.FAILED
    assert stored.current_stage == StageId.COMPLETE.value
    assert "ANALYZE" in (stored.error_summary or "")
    assert "analyzer exploded" in (stored.error_summary or "")
    result = stored.result or {}
    assert result["code"] == "PIPELINE_ERROR"
    assert result["failed_stage"] == "ANALYZE"
    assert result["deployment_id"] == "dep_boom"
    # Exactly one terminal event, no duplicates.
    terminal = [
        e for e in repo.list_events("dep_boom")
        if e.event_type == "deployment.failed"
    ]
    assert len(terminal) == 1


def test_routine_status_update_preserves_existing_error_summary(tmp_path):
    from app.core.enums import DeploymentStatus, StageId
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord
    from app.workflow.planning import PlanningPipeline

    db = tmp_path / "t.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id="dep_stat", repository_url="x", mode="real", scenario=None,
        target_host="localhost", target_port=8080, intent=None,
        status=DeploymentStatus.RUNNING, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    repo.update_status(
        "dep_stat",
        status=DeploymentStatus.RUNNING,
        current_stage=StageId.VERIFY.value,
        explain_simple="readiness failed",
        explain_technical="READINESS_FAILED",
        error_summary="probe timed out",
        updated_at=utc_now_iso(),
    )
    # A routine status update with no supplied error must not erase it.
    PlanningPipeline(repo=repo)._status(
        "dep_stat", DeploymentStatus.RUNNING, StageId.EXECUTE,
        "continuing", "workflow=planning",
    )
    stored = repo.get("dep_stat")
    assert stored.error_summary == "probe timed out"
    assert stored.current_stage == StageId.EXECUTE.value
    assert stored.status == DeploymentStatus.RUNNING
