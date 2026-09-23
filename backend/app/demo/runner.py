"""Deterministic Demo Mode runner — emits labelled SSE events, no external I/O."""

from __future__ import annotations

import asyncio
from typing import Callable

from app.core.config import get_settings
from app.core.enums import (
    TERMINAL_STATUSES,
    DeploymentStatus,
    EventType,
    ScenarioId,
    StageId,
)
from app.core.events import event_bus, make_event, utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import DeploymentRepository
from app.demo.models import DemoArtifacts
from app.demo.scenarios import get_scenario

logger = get_logger(__name__)


class DemoRunner:
    """Execute a fixed scenario fixture with deterministic delays."""

    def __init__(
        self,
        repo: DeploymentRepository | None = None,
        *,
        delay_seconds: float | None = None,
    ) -> None:
        self.repo = repo or DeploymentRepository()
        self._delay_override = delay_seconds

    async def run(self, deployment_id: str, scenario_id: ScenarioId) -> None:
        settings = get_settings()
        base_delay = (
            self._delay_override
            if self._delay_override is not None
            else settings.workflow_step_delay_seconds
        )
        artifacts = DemoArtifacts()

        try:
            scenario = get_scenario(scenario_id)
            logger.info(
                "Demo runner start deployment_id=%s scenario=%s steps=%s",
                deployment_id,
                scenario_id.value,
                len(scenario.steps),
            )

            for step in scenario.steps:
                self._merge_artifacts(artifacts, step.data)

                if step.deployment_status is not None or step.stage is not None:
                    self.repo.update_status(
                        deployment_id,
                        status=step.deployment_status,
                        current_stage=step.stage.value if step.stage else None,
                        explain_simple=step.explain_simple,
                        explain_technical=step.explain_technical,
                        updated_at=utc_now_iso(),
                    )

                self.repo.save_artifacts(
                    deployment_id,
                    constraints=artifacts.constraints,
                    negotiation=artifacts.negotiation,
                    verification=artifacts.verification,
                    critic=artifacts.critic,
                    graph=artifacts.graph,
                    rollback=artifacts.rollback,
                    result=artifacts.result,
                    updated_at=utc_now_iso(),
                )

                metadata = {
                    **step.data,
                    "simple": step.explain_simple or step.data.get("simple"),
                    "technical": step.explain_technical or step.data.get("technical"),
                    "is_demo": True,
                    "label": "DEMO/MOCK",
                    "scenario": scenario_id.value,
                }
                await self._emit_and_store(
                    deployment_id,
                    step.event_type,
                    step.message,
                    stage=step.stage.value if step.stage else None,
                    status=step.status,
                    level=step.level,
                    metadata=metadata,
                )

                delay = base_delay if base_delay <= 0 else max(0.0, step.delay_after * (
                    base_delay / 0.35 if base_delay != 0.35 else 1.0
                ))
                # When tests set delay near 0, skip sleeps entirely.
                if base_delay <= 0:
                    delay = 0.0
                elif base_delay < 0.1:
                    delay = min(step.delay_after, base_delay)
                if delay > 0:
                    await asyncio.sleep(delay)

            # Ensure terminal status is persisted even if last step omitted it.
            record = self.repo.get(deployment_id)
            if record and record.status.value not in TERMINAL_STATUSES:
                self.repo.update_status(
                    deployment_id,
                    status=scenario.expected_final_status,
                    current_stage=StageId.COMPLETE.value,
                    updated_at=utc_now_iso(),
                )

            logger.info(
                "Demo runner finished deployment_id=%s scenario=%s",
                deployment_id,
                scenario_id.value,
            )
        except Exception as exc:  # noqa: BLE001 — surface as failed deployment
            logger.exception("Demo runner failed deployment_id=%s", deployment_id)
            self.repo.update_status(
                deployment_id,
                status=DeploymentStatus.FAILED,
                error_summary=str(exc),
                explain_simple="Demo engine failed unexpectedly.",
                explain_technical=f"workflow=demo · error={type(exc).__name__} · is_demo=true",
                updated_at=utc_now_iso(),
            )
            failed_result = {
                "kind": "failed",
                "title": "FAILED",
                "final_status": "failed",
                "message": f"Demo engine error: {exc}",
                "durationLabel": "—",
                "servicesLabel": "n/a",
                "verificationScore": None,
                "constraintsResolved": 0,
                "rollbackScope": None,
                "is_demo": True,
                "label": "DEMO/MOCK",
            }
            self.repo.save_artifacts(
                deployment_id,
                result=failed_result,
                updated_at=utc_now_iso(),
            )
            await self._emit_and_store(
                deployment_id,
                EventType.DEPLOYMENT_FAILED,
                "DEMO deployment failed due to an internal engine error.",
                status=DeploymentStatus.FAILED.value,
                level="error",
                metadata={
                    "error": str(exc),
                    "simple": "Demo engine failed unexpectedly.",
                    "technical": f"error={type(exc).__name__}",
                    "result": failed_result,
                    "is_demo": True,
                    "label": "DEMO/MOCK",
                },
            )

    @staticmethod
    def _merge_artifacts(artifacts: DemoArtifacts, data: dict) -> None:
        if "constraints" in data and data["constraints"] is not None:
            artifacts.constraints = data["constraints"]
        if "negotiation" in data and data["negotiation"] is not None:
            artifacts.negotiation = data["negotiation"]
        if "verification" in data and data["verification"] is not None:
            artifacts.verification = data["verification"]
        if "critic" in data and data["critic"] is not None:
            artifacts.critic = data["critic"]
        if "graph" in data and data["graph"] is not None:
            artifacts.graph = data["graph"]
        if "rollback" in data:
            artifacts.rollback = data["rollback"]
        if "result" in data and data["result"] is not None:
            artifacts.result = data["result"]
        if "agents" in data and data["agents"] is not None:
            artifacts.agents = data["agents"]
        if "selected_node_id" in data:
            artifacts.selected_node_id = data["selected_node_id"]

    async def _emit_and_store(
        self,
        deployment_id: str,
        event_type: EventType | str,
        message: str,
        *,
        stage: str | None = None,
        status: str | None = None,
        level: str = "info",
        metadata: dict | None = None,
    ) -> None:
        event = make_event(
            deployment_id=deployment_id,
            event_type=event_type,
            message=message,
            stage=stage,
            status=status,
            level=level,
            metadata=metadata,
            is_demo=True,
        )
        self.repo.add_event(event)
        await event_bus.publish(event)


def schedule_demo_runner(
    deployment_id: str,
    scenario_id: ScenarioId,
    *,
    create_task: Callable = asyncio.create_task,
    repo: DeploymentRepository | None = None,
) -> asyncio.Task:
    runner = DemoRunner(repo=repo)
    return create_task(runner.run(deployment_id, scenario_id))
