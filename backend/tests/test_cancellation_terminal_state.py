"""Task-level cancellation must leave a terminal, honest run state.

A `CancelledError` bypasses every `except Exception` handler; without the
dedicated branch the deployment row would stay `running` forever — a false
active dashboard state. The branch persists a terminal failure (unless the
cancel endpoint already recorded CANCELLED, which always wins) and re-raises.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core.enums import DeploymentStatus
from app.core.events import utc_now_iso
from app.database.connection import init_db
from app.database.repositories import DeploymentRepository
from app.models.deployment import DeploymentRecord
from app.workflow.planning import PlanningPipeline


def test_cancelled_task_persists_terminal_failure(tmp_path, monkeypatch):
    db = tmp_path / "cancel.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    src = tmp_path / "src"
    src.mkdir()
    (src / "package.json").write_text(
        '{"scripts": {"start": "node i.js"}}', encoding="utf-8"
    )
    repo.create(DeploymentRecord(
        deployment_id="dep_cancel", repository_url=str(src),
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))

    pipeline = PlanningPipeline(repo=repo)

    async def cancelled_agent(*args, **kwargs):
        raise asyncio.CancelledError

    # Simulate task cancellation landing at the first awaited stage hook.
    monkeypatch.setattr(pipeline, "_agent_start", cancelled_agent)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(pipeline.run("dep_cancel"))

    stored = repo.get("dep_cancel")
    assert stored is not None
    assert stored.status == DeploymentStatus.FAILED
    result = stored.result or {}
    assert result["code"] == "PIPELINE_CANCELLED"
    assert result["deployment_id"] == "dep_cancel"
    assert result["phase"]
    # Exactly one terminal event — the interruption is recorded once.
    terminal = [
        e for e in repo.list_events("dep_cancel")
        if e.event_type == "deployment.failed"
    ]
    assert len(terminal) == 1
