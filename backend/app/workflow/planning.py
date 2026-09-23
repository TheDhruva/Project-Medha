"""Real-mode pipeline: analyze → specialists → CNP → verify → execute → CEG/rollback."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from app.agents.analyzer import analyze_repository
from app.agents.critic import run_critic
from app.agents.docker_agent import run_docker_agent
from app.agents.nginx_agent import run_nginx_agent
from app.agents.preflight import run_preflight
from app.agents.security_agent import run_security_agent
from app.agents.verifier import run_verifier
from app.cnp.engine import detect_conflicts, run_cnp
from app.core.config import get_settings
from app.core.deploy_lock import release_real_deploy, try_acquire_real_deploy
from app.core.enums import DeploymentStatus, EventType, StageId
from app.core.events import event_bus, make_event, utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import DeploymentRepository
from app.execution import docker_ops
from app.execution.executor import choose_executor
from app.execution.plan_builder import build_ceg_from_plan, build_execution_plan
from app.execution.support import assess_plan_support
from app.models.domain import NegotiatedPlan
from app.models.execution import CriticRecommendation
from app.services.git_service import GitAcquireError, acquire_repository
from app.services.workspace import cleanup_workspace, resolve_local_repo_path

logger = get_logger(__name__)

PHASE_LABEL = "10-11"


class PlanningPipeline:
    """Phases 4–11 real path (local only; Docker mutate opt-in)."""

    def __init__(self, repo: DeploymentRepository | None = None) -> None:
        self.repo = repo or DeploymentRepository()

    async def run(self, deployment_id: str) -> None:
        settings = get_settings()
        delay = settings.workflow_step_delay_seconds
        record = self.repo.get(deployment_id)
        if record is None:
            logger.error("PlanningPipeline missing deployment_id=%s", deployment_id)
            return

        try:
            try_acquire_real_deploy(deployment_id)
        except Exception as exc:  # DeployBusyError
            await self._fail(
                deployment_id,
                str(exc),
                technical=getattr(exc, "code", "DEPLOYMENT_BUSY"),
            )
            return

        pipeline_t0 = time.perf_counter()
        try:
            await self._emit(
                deployment_id,
                EventType.DEPLOYMENT_STARTED,
                "Real deployment pipeline started (Phases 4–11).",
                status=DeploymentStatus.RUNNING.value,
                metadata={
                    "simple": "MEDHA is starting real repository analysis through local execution.",
                    "technical": f"workflow=planning · phases={PHASE_LABEL} · docker_execute={settings.docker_execute}",
                },
            )
            self._status(
                deployment_id,
                DeploymentStatus.RUNNING,
                StageId.PREFLIGHT,
                "MEDHA is checking planning and host prerequisites.",
                "workflow=planning · stage=PREFLIGHT",
            )

            is_remote = resolve_local_repo_path(record.repository_url) is None
            preflight = run_preflight(
                require_git_for_remote=True,
                is_remote=is_remote,
                target_port=record.target_port,
                require_docker_for_execute=bool(settings.docker_execute),
            )
            await self._agent_events(deployment_id, "preflight", preflight.summary, delay)
            if not preflight.ok:
                raise RuntimeError(preflight.summary)

            await self._stage(deployment_id, StageId.PREFLIGHT, "completed", delay)

            # ANALYZE
            self._status(
                deployment_id,
                DeploymentStatus.RUNNING,
                StageId.ANALYZE,
                "MEDHA is acquiring and analyzing the repository manifests.",
                "workflow=planning · stage=ANALYZE",
            )
            await self._stage(deployment_id, StageId.ANALYZE, "started", 0)
            acquisition = acquire_repository(deployment_id, record.repository_url)
            profile, analysis = analyze_repository(
                deployment_id=deployment_id,
                repository_url=record.repository_url,
                workspace_path=acquisition.path,
                target_host=record.target_host,
                target_port=record.target_port,
                intent=record.intent,
            )
            await self._agent_events(deployment_id, "analyzer", analysis.summary, delay)
            await self._run_change_intel(
                deployment_id, record, settings, delay
            )
            await self._emit(
                deployment_id,
                EventType.SYSTEM_MESSAGE,
                analysis.summary,
                stage=StageId.ANALYZE.value,
                metadata={
                    "simple": "MEDHA identified the application's deployment structure from manifests.",
                    "technical": (
                        f"method={acquisition.method} · language={profile.inferred_stack.language_runtime} "
                        f"· confidence={profile.inferred_stack.confidence} · "
                        f"manifests={profile.inferred_stack.manifests_examined}"
                    ),
                    "profile": {
                        "language_runtime": profile.inferred_stack.language_runtime,
                        "services": [s.model_dump() for s in profile.inferred_stack.services],
                        "has_dockerfile": profile.inferred_stack.has_dockerfile,
                        "has_compose": profile.inferred_stack.has_compose,
                        "suggested_ports": profile.inferred_stack.suggested_ports,
                        "confidence": profile.inferred_stack.confidence,
                    },
                },
            )
            await self._stage(deployment_id, StageId.ANALYZE, "completed", delay)

            support = assess_plan_support(profile)
            if not support.supported:
                result = {
                    "kind": "failed",
                    "title": support.code or "DEPLOYMENT_UNSUPPORTED",
                    "final_status": "failed",
                    "message": support.message,
                    "durationLabel": "analyze",
                    "servicesLabel": "0 / 0 started",
                    "verificationScore": None,
                    "constraintsResolved": 0,
                    "rollbackScope": None,
                    "phase": PHASE_LABEL,
                    "is_demo": False,
                    "code": support.code,
                }
                self.repo.save_artifacts(
                    deployment_id, result=result, updated_at=utc_now_iso()
                )
                await self._fail(
                    deployment_id,
                    support.message,
                    technical=support.code or "DEPLOYMENT_UNSUPPORTED",
                    result=result,
                )
                return

            # PLAN
            self._status(
                deployment_id,
                DeploymentStatus.RUNNING,
                StageId.PLAN,
                "MEDHA is drafting a task specification from the inferred stack.",
                "workflow=planning · stage=PLAN",
            )
            await self._stage(deployment_id, StageId.PLAN, "started", delay * 0.5)
            await self._stage(deployment_id, StageId.PLAN, "completed", delay)

            # AGENTS
            self._status(
                deployment_id,
                DeploymentStatus.RUNNING,
                StageId.AGENTS,
                "Specialist agents are preparing deployment requirements.",
                "workflow=planning · stage=AGENTS",
            )
            await self._stage(deployment_id, StageId.AGENTS, "started", 0)

            docker_res = run_docker_agent(profile)
            nginx_res = run_nginx_agent(profile)
            security_res = run_security_agent(profile)
            agent_results = [preflight, analysis, docker_res, nginx_res, security_res]

            all_constraints = [
                *docker_res.constraints,
                *nginx_res.constraints,
                *security_res.constraints,
            ]
            for agent_name, res in (
                ("docker", docker_res),
                ("nginx", nginx_res),
                ("security", security_res),
            ):
                await self._agent_events(deployment_id, agent_name, res.summary, delay * 0.5)

            await self._emit(
                deployment_id,
                EventType.CONSTRAINT_PUBLISHED,
                f"Specialists published {len(all_constraints)} typed constraints.",
                stage=StageId.AGENTS.value,
                metadata={
                    "simple": "Specialist agents published typed infrastructure constraints.",
                    "technical": f"constraints={len(all_constraints)} · is_demo=false",
                    "constraints": [c.to_ui() for c in all_constraints],
                    "agents": _agents_snapshot(agent_results),
                },
            )
            self.repo.save_artifacts(
                deployment_id,
                constraints=[c.to_ui() for c in all_constraints],
                updated_at=utc_now_iso(),
            )
            await self._stage(deployment_id, StageId.AGENTS, "completed", delay)

            # NEGOTIATE (CNP)
            self._status(
                deployment_id,
                DeploymentStatus.RUNNING,
                StageId.NEGOTIATE,
                "MEDHA is negotiating typed constraints before execution.",
                "workflow=planning · stage=NEGOTIATE · cnp=deterministic",
            )
            await self._stage(deployment_id, StageId.NEGOTIATE, "started", 0)
            await self._emit(
                deployment_id,
                EventType.NEGOTIATION_STARTED,
                "CNP started — collecting and grouping constraints.",
                stage=StageId.NEGOTIATE.value,
                metadata={
                    "simple": "MEDHA is collecting typed constraints before execution.",
                    "technical": "cnp.phase=COLLECT · max_rounds=3",
                    "constraints": [c.to_ui() for c in all_constraints],
                    "negotiation": {
                        "status": "detecting",
                        "round": 1,
                        "maxRounds": 3,
                        "conflictSummary": "Collecting typed constraints",
                        "simpleExplanation": "CNP collect/validate phase.",
                        "involvedConstraintIds": [c.constraint_id for c in all_constraints],
                    },
                },
            )

            # Emit conflicts before resolution for UI visibility
            preview = detect_conflicts([c.model_copy(deep=True) for c in all_constraints])
            if preview:
                for conflict in preview:
                    await self._emit(
                        deployment_id,
                        EventType.CONSTRAINT_CONFLICT,
                        conflict.reason,
                        stage=StageId.NEGOTIATE.value,
                        level="warning",
                        status="warning",
                        metadata={
                            "simple": conflict.reason,
                            "technical": (
                                f"conflict_id={conflict.conflict_id} · key={conflict.resource_key} · "
                                f"priorities={conflict.priority_span}"
                            ),
                            "conflict": conflict.model_dump(),
                            "constraints": [
                                c.to_ui()
                                for c in all_constraints
                                if c.constraint_id in conflict.constraint_ids
                            ],
                        },
                    )
                    if delay:
                        await asyncio.sleep(delay)

            negotiation = run_cnp(deployment_id, all_constraints, is_demo=False)
            ui_constraints = [c.to_ui() for c in negotiation.final_constraints]
            ui_negotiation = negotiation.to_ui()

            for decision in negotiation.decisions:
                await self._emit(
                    deployment_id,
                    EventType.NEGOTIATION_RESOLVED
                    if negotiation.status == "resolved"
                    else EventType.SYSTEM_MESSAGE,
                    decision.rationale,
                    stage=StageId.NEGOTIATE.value,
                    metadata={
                        "simple": decision.rationale,
                        "technical": (
                            f"method={decision.method} · winners={decision.winner_ids} · "
                            f"losers={decision.loser_ids} · updates={decision.updates}"
                        ),
                        "decision": decision.model_dump(),
                        "constraints": ui_constraints,
                        "negotiation": ui_negotiation,
                    },
                )

            if negotiation.status != "resolved":
                plan = NegotiatedPlan(
                    deployment_id=deployment_id,
                    profile=profile,
                    agent_results=agent_results,
                    negotiation=negotiation,
                    config_fragments={
                        "docker": docker_res.artifacts,
                        "nginx": nginx_res.artifacts,
                        "security": security_res.artifacts,
                    },
                    message="CNP exhausted without a clean constraint set. Execution blocked.",
                    is_demo=False,
                )
                self.repo.save_artifacts(
                    deployment_id,
                    constraints=ui_constraints,
                    negotiation=ui_negotiation,
                    result=plan.to_result(),
                    updated_at=utc_now_iso(),
                )
                self._status(
                    deployment_id,
                    DeploymentStatus.FAILED,
                    StageId.COMPLETE,
                    "Constraint negotiation exhausted. Plan failed closed.",
                    f"cnp.status=exhausted · rounds={negotiation.rounds_used}",
                    error=plan.message,
                )
                await self._emit(
                    deployment_id,
                    EventType.DEPLOYMENT_FAILED,
                    plan.message,
                    stage=StageId.COMPLETE.value,
                    status=DeploymentStatus.FAILED.value,
                    level="error",
                    metadata={
                        "simple": plan.message,
                        "technical": f"cnp.status={negotiation.status}",
                        "result": plan.to_result(),
                        "constraints": ui_constraints,
                        "negotiation": ui_negotiation,
                    },
                )
                return

            await self._stage(deployment_id, StageId.NEGOTIATE, "completed", delay)

            plan = NegotiatedPlan(
                deployment_id=deployment_id,
                profile=profile,
                agent_results=agent_results,
                negotiation=negotiation,
                config_fragments={
                    "docker": docker_res.artifacts,
                    "nginx": nginx_res.artifacts,
                    "security": security_res.artifacts,
                },
                message="Negotiated plan ready — entering verification gate.",
                is_demo=False,
            )

            await self._run_verify_execute(
                deployment_id=deployment_id,
                profile=profile,
                negotiation=negotiation,
                ui_constraints=ui_constraints,
                ui_negotiation=ui_negotiation,
                config_fragments=plan.config_fragments,
                constraints_resolved=len(negotiation.decisions),
                delay=delay,
                intent=record.intent,
            )
            logger.info(
                "Planning+execution pipeline completed deployment_id=%s duration=%.2fs",
                deployment_id,
                time.perf_counter() - pipeline_t0,
            )
        except GitAcquireError as exc:
            await self._fail(deployment_id, exc.message, technical=f"git.{exc.code}")
        except Exception as exc:  # noqa: BLE001
            logger.exception("Planning pipeline failed deployment_id=%s", deployment_id)
            await self._fail(deployment_id, str(exc), technical=type(exc).__name__)
        finally:
            release_real_deploy(deployment_id)
            try:
                if get_settings().docker_execute and get_settings().docker_cleanup:
                    docker_ops.cleanup_deployment(deployment_id)
            except Exception:  # noqa: BLE001
                logger.exception("Docker cleanup failed deployment_id=%s", deployment_id)
            if not get_settings().medha_debug:
                cleanup_workspace(deployment_id)

    async def _run_change_intel(self, deployment_id: str, record, settings, delay: float) -> None:
        """Phase 2: deterministic change-impact analysis against the original
        local git repository (base_revision → target_revision).

        The acquired workspace copy has git history stripped by the shallow
        clone, so analysis runs against the local repo path. Remote URLs and
        missing revisions are skipped honestly — the deployment continues with
        change_intel absent rather than faking evidence.
        """
        if not record.base_revision or not record.target_revision:
            return
        if resolve_local_repo_path(record.repository_url) is None:
            await self._emit(
                deployment_id,
                EventType.SYSTEM_MESSAGE,
                "Change-intelligence analysis skipped: remote URL not supported in Phase 2.",
                stage=StageId.ANALYZE.value,
                metadata={
                    "simple": "Change-intelligence analysis skipped (remote repository).",
                    "technical": "phase2=local-git-only · change_intel=not_computed",
                },
            )
            return
        try:
            from app.changeintel.engine import analyze_change_impact
            from app.changeintel.git_extract import ChangeIntelError

            info = analyze_change_impact(
                repository_url=record.repository_url,
                base_revision=record.base_revision,
                target_revision=record.target_revision,
                deployment_id=deployment_id,
            )
        except ChangeIntelError as exc:
            await self._emit(
                deployment_id,
                EventType.SYSTEM_MESSAGE,
                f"Change-intelligence analysis skipped: {exc.message}",
                stage=StageId.ANALYZE.value,
                level="warning",
                metadata={
                    "simple": "Change-intelligence analysis could not run for this repository.",
                    "technical": f"phase2=skipped · code={exc.code}",
                },
            )
            return
        risk_value = info.risk.level.value
        stored = info.model_dump(mode="json")
        stored["deployment_id"] = deployment_id
        self.repo.save_artifacts(
            deployment_id, change_intel=stored, updated_at=utc_now_iso()
        )
        await self._emit(
            deployment_id,
            EventType.SYSTEM_MESSAGE,
            f"Change intelligence: {len(info.changeset.files)} file(s) changed, "
            f"{info.risk.level.value.upper()} risk, {len(info.requirements)} requirement(s).",
            stage=StageId.ANALYZE.value,
            metadata={
                "simple": (
                    "MEDHA computed a change-impact graph from git history "
                    f"(risk={risk_value})."
                ),
                "technical": (
                    f"phase2=change_intel · base={info.changeset.base_sha[:8]} · "
                    f"target={info.changeset.target_sha[:8]} · files={len(info.changeset.files)} · "
                    f"nodes={len(info.graph.nodes)} · edges={len(info.graph.edges)} · "
                    f"risk={risk_value} · requirements={len(info.requirements)}"
                ),
                "change_intel": info.to_ui(),
            },
        )
        if delay:
            await asyncio.sleep(delay * 0.5)

    async def _run_verify_execute(
        self,
        *,
        deployment_id: str,
        profile,
        negotiation,
        ui_constraints: list,
        ui_negotiation: dict,
        config_fragments: dict,
        constraints_resolved: int,
        delay: float,
        intent: str | None,
    ) -> None:
        settings = get_settings()
        max_rounds = settings.max_verify_rounds
        final_constraints = list(negotiation.final_constraints)
        replan_count = 0
        verification = None
        critic = None

        intent_l = (intent or "").lower()
        force_fail_env = "force verification failure" in intent_l or "missing env" in intent_l
        fail_service = None
        if "partial failure" in intent_l or "backend fail" in intent_l:
            fail_service = "backend"

        while True:
            self._status(
                deployment_id,
                DeploymentStatus.RUNNING,
                StageId.VERIFY,
                "MEDHA is checking the generated configuration before execution.",
                f"stage=VERIFY · round={replan_count + 1}/{max_rounds}",
            )
            await self._stage(deployment_id, StageId.VERIFY, "started", delay * 0.3)
            await self._emit(
                deployment_id,
                EventType.VERIFICATION_STARTED,
                "Verification started.",
                stage=StageId.VERIFY.value,
                metadata={
                    "simple": "MEDHA is checking the generated configuration before execution.",
                    "technical": f"gate=pre_exec · replan_count={replan_count}",
                },
            )

            verification = run_verifier(
                deployment_id=deployment_id,
                profile=profile,
                constraints=final_constraints,
                negotiation=negotiation,
                config_fragments=config_fragments,
                replan_count=replan_count,
                force_fail_env=force_fail_env and replan_count == 0,
                is_demo=False,
            )
            ui_verification = verification.to_ui()
            self.repo.save_artifacts(
                deployment_id,
                verification=ui_verification,
                constraints=ui_constraints,
                negotiation=ui_negotiation,
                updated_at=utc_now_iso(),
            )

            if not verification.passed:
                await self._emit(
                    deployment_id,
                    EventType.VERIFICATION_FAILED,
                    verification.blocking_failures[0]
                    if verification.blocking_failures
                    else "Verification failed",
                    stage=StageId.VERIFY.value,
                    status="failed",
                    level="error",
                    metadata={
                        "simple": (
                            "MEDHA found a configuration problem and may attempt a bounded replan."
                        ),
                        "technical": f"passed=false · failures={verification.blocking_failures}",
                        "verification": ui_verification,
                    },
                )
                critic = run_critic(
                    deployment_id=deployment_id,
                    profile=profile,
                    constraints=final_constraints,
                    negotiation=negotiation,
                    verification=verification,
                    config_fragments=config_fragments,
                )
                self.repo.save_artifacts(
                    deployment_id, critic=critic.to_ui(), updated_at=utc_now_iso()
                )

                if (
                    critic.recommendation
                    in {CriticRecommendation.REPLAN, CriticRecommendation.WARN}
                    or not verification.passed
                ) and replan_count + 1 < max_rounds:
                    replan_count += 1
                    await self._emit(
                        deployment_id,
                        EventType.REPLAN_STARTED,
                        f"REPLAN ROUND {replan_count}",
                        stage=StageId.VERIFY.value,
                        metadata={
                            "simple": (
                                "MEDHA found a configuration problem before execution and is "
                                "replanning within the allowed retry limit."
                            ),
                            "technical": f"replan.round={replan_count} · max={max_rounds}",
                            "replan": {"round": replan_count, "max_rounds": max_rounds},
                        },
                    )
                    # Deterministic fix: inject required env into compose fragment
                    config_fragments = _apply_replan_fixes(config_fragments, verification)
                    force_fail_env = False
                    await self._emit(
                        deployment_id,
                        EventType.REPLAN_COMPLETED,
                        "Replan applied corrected configuration fixtures.",
                        stage=StageId.VERIFY.value,
                        metadata={
                            "simple": "Corrected configuration prepared for re-verification.",
                            "technical": f"replan.round={replan_count} · fix=env_present",
                        },
                    )
                    continue

                # Exhausted / escalate
                result = {
                    "kind": "failed",
                    "title": "FAILED",
                    "final_status": "failed",
                    "message": "Verification/critic blocked execution after bounded attempts.",
                    "durationLabel": "verify",
                    "servicesLabel": "0 / 0 started",
                    "verificationScore": critic.score if critic else verification.score,
                    "constraintsResolved": constraints_resolved,
                    "rollbackScope": None,
                    "phase": PHASE_LABEL,
                    "is_demo": False,
                }
                self.repo.save_artifacts(
                    deployment_id,
                    verification=ui_verification,
                    critic=critic.to_ui() if critic else None,
                    result=result,
                    updated_at=utc_now_iso(),
                )
                self._status(
                    deployment_id,
                    DeploymentStatus.FAILED,
                    StageId.COMPLETE,
                    result["message"],
                    "gate=blocked",
                    error=result["message"],
                )
                await self._emit(
                    deployment_id,
                    EventType.DEPLOYMENT_FAILED,
                    result["message"],
                    stage=StageId.COMPLETE.value,
                    status=DeploymentStatus.FAILED.value,
                    level="error",
                    metadata={
                        "simple": result["message"],
                        "technical": "recommendation=ESCALATE",
                        "result": result,
                        "verification": ui_verification,
                        "critic": critic.to_ui() if critic else None,
                    },
                )
                return

            await self._emit(
                deployment_id,
                EventType.VERIFICATION_PASSED,
                "Verification passed.",
                stage=StageId.VERIFY.value,
                status="success",
                metadata={
                    "simple": "Configuration checks passed. Execution is allowed.",
                    "technical": f"passed=true · replan_count={replan_count}",
                    "verification": ui_verification,
                },
            )
            await self._stage(deployment_id, StageId.VERIFY, "completed", delay * 0.2)

            await self._emit(
                deployment_id,
                EventType.CRITIC_STARTED,
                "Critic started.",
                stage=StageId.VERIFY.value,
                metadata={"simple": "MEDHA critic is scoring the negotiated plan."},
            )
            critic = run_critic(
                deployment_id=deployment_id,
                profile=profile,
                constraints=final_constraints,
                negotiation=negotiation,
                verification=verification,
                config_fragments=config_fragments,
            )
            ui_critic = critic.to_ui()
            self.repo.save_artifacts(
                deployment_id, critic=ui_critic, verification=ui_verification, updated_at=utc_now_iso()
            )
            await self._emit(
                deployment_id,
                EventType.CRITIC_COMPLETED,
                critic.summary,
                stage=StageId.VERIFY.value,
                metadata={
                    "simple": critic.summary,
                    "technical": f"score={critic.score} · recommendation={critic.recommendation.value}",
                    "critic": ui_critic,
                    "verification": ui_verification,
                },
            )

            if critic.recommendation == CriticRecommendation.ESCALATE:
                result = {
                    "kind": "failed",
                    "title": "ESCALATED",
                    "final_status": "failed",
                    "message": critic.summary,
                    "durationLabel": "verify",
                    "servicesLabel": "blocked",
                    "verificationScore": critic.score,
                    "constraintsResolved": constraints_resolved,
                    "rollbackScope": None,
                    "phase": PHASE_LABEL,
                    "is_demo": False,
                }
                self.repo.save_artifacts(deployment_id, result=result, updated_at=utc_now_iso())
                await self._fail(
                    deployment_id,
                    critic.summary,
                    technical="critic=ESCALATE",
                    result=result,
                )
                return

            if critic.recommendation == CriticRecommendation.REPLAN and replan_count + 1 < max_rounds:
                replan_count += 1
                await self._emit(
                    deployment_id,
                    EventType.REPLAN_STARTED,
                    f"REPLAN ROUND {replan_count} (critic)",
                    stage=StageId.VERIFY.value,
                    metadata={
                        "simple": "Critic requested a bounded replan before execution.",
                        "technical": f"replan.round={replan_count} · source=critic",
                    },
                )
                config_fragments = _apply_replan_fixes(config_fragments, verification)
                await self._emit(
                    deployment_id,
                    EventType.REPLAN_COMPLETED,
                    "Critic-driven replan applied.",
                    stage=StageId.VERIFY.value,
                    metadata={
                        "simple": "Corrected configuration prepared for re-verification.",
                        "technical": f"replan.round={replan_count} · source=critic",
                    },
                )
                continue

            break

        # EXECUTE
        exec_plan = build_execution_plan(
            deployment_id=deployment_id,
            profile=profile,
            constraints=final_constraints,
            config_fragments=config_fragments,
            fail_service=fail_service,
            is_demo=False,
        )
        # Ensure controlled research graph services exist for CEG demo quality
        services = {a.service for a in exec_plan.actions}
        required = {"network", "database", "backend", "frontend", "analytics"}
        if not required.issubset(services):
            from app.models.domain import InferredStack, ServiceHint

            profile.inferred_stack = InferredStack(
                services=[
                    ServiceHint(name="network", role="network"),
                    ServiceHint(name="database", role="database"),
                    ServiceHint(name="backend", role="api", suggested_port=profile.target_port),
                    ServiceHint(name="frontend", role="web"),
                    ServiceHint(name="analytics", role="service"),
                ],
                language_runtime=profile.inferred_stack.language_runtime,
                has_dockerfile=profile.inferred_stack.has_dockerfile,
                has_compose=profile.inferred_stack.has_compose,
                package_managers=profile.inferred_stack.package_managers,
                suggested_ports=profile.inferred_stack.suggested_ports,
                confidence=profile.inferred_stack.confidence,
                manifests_examined=profile.inferred_stack.manifests_examined,
                notes=[*profile.inferred_stack.notes, "Expanded to canonical CEG services"],
            )
            exec_plan = build_execution_plan(
                deployment_id=deployment_id,
                profile=profile,
                constraints=final_constraints,
                config_fragments=config_fragments,
                fail_service=fail_service,
                is_demo=False,
            )

        ceg = build_ceg_from_plan(exec_plan)

        # Pre-execution safety: port still usable (do not silently remapped).
        # Hard-fail only when real Docker mutate is enabled.
        if get_settings().docker_execute and not docker_ops.is_port_available(profile.target_port):
            await self._fail(
                deployment_id,
                (
                    f"Negotiated target port {profile.target_port} is no longer available. "
                    "Returning without undocumented plan mutation."
                ),
                technical="PORT_UNAVAILABLE",
            )
            return

        # Pre-execution gate confirmation
        if not verification or not verification.passed:
            await self._fail(
                deployment_id,
                "Refusing to execute an unverified plan.",
                technical="UNVERIFIED_PLAN",
            )
            return
        if critic and critic.recommendation == CriticRecommendation.ESCALATE:
            await self._fail(
                deployment_id,
                "Critic escalated — execution blocked.",
                technical="CRITIC_ESCALATE",
            )
            return

        await self._emit(
            deployment_id,
            EventType.CEG_CREATED,
            "Causal execution graph created from ExecutionPlan.",
            stage=StageId.EXECUTE.value,
            metadata={
                "simple": "MEDHA built the causal execution graph before running actions.",
                "technical": f"nodes={len(ceg.nodes)} · edges={len(ceg.edges)}",
                "graph": ceg.to_ui(),
            },
        )
        self.repo.save_artifacts(deployment_id, graph=ceg.to_ui(), updated_at=utc_now_iso())

        self._status(
            deployment_id,
            DeploymentStatus.RUNNING,
            StageId.EXECUTE,
            "MEDHA is executing the verified plan and recording CEG nodes.",
            "stage=EXECUTE · executor=local",
        )
        await self._stage(deployment_id, StageId.EXECUTE, "started", delay * 0.2)
        await self._emit(
            deployment_id,
            EventType.EXECUTION_STARTED,
            "Execution started.",
            stage=StageId.EXECUTE.value,
            metadata={
                "simple": "MEDHA is applying the verified plan.",
                "technical": (
                    f"executor=choose_executor · docker_mutate={get_settings().docker_execute}"
                ),
                "graph": ceg.to_ui(),
            },
        )

        executor = choose_executor(is_demo=False, prefer_docker=True)

        async def on_event(etype: str, message: str, meta: dict) -> None:
            mapping = {
                "execution.node.started": EventType.EXECUTION_NODE_STARTED,
                "execution.node.completed": EventType.EXECUTION_NODE_COMPLETED,
                "execution.node.failed": EventType.EXECUTION_NODE_FAILED,
                "rollback.node": EventType.ROLLBACK_NODE,
            }
            event_type = mapping.get(etype, EventType.SYSTEM_MESSAGE)
            await self._emit(
                deployment_id,
                event_type,
                message,
                stage=StageId.EXECUTE.value
                if etype.startswith("execution")
                else StageId.RECOVER.value,
                status="failed" if "failed" in etype else "running",
                level="error" if "failed" in etype else "info",
                metadata={
                    "simple": message,
                    "technical": f"event={etype}",
                    **meta,
                },
            )
            if "graph" in meta:
                self.repo.save_artifacts(
                    deployment_id, graph=meta["graph"], updated_at=utc_now_iso()
                )

        graph, exec_result, scope = await executor.execute(exec_plan, ceg, on_event=on_event)

        if scope is None and exec_result.status not in {"SUCCESS", "PARTIAL_FAILURE"}:
            message = "; ".join(exec_result.errors) or f"Execution failed ({exec_result.status})"
            result = exec_result.to_deployment_result(
                verification_score=critic.score if critic else None,
                constraints_resolved=constraints_resolved,
                rollback_scope=None,
                message=message,
            )
            result["phase"] = PHASE_LABEL
            self.repo.save_artifacts(
                deployment_id,
                graph=graph.to_ui(),
                result=result,
                verification=verification.to_ui() if verification else None,
                critic=critic.to_ui() if critic else None,
                updated_at=utc_now_iso(),
            )
            await self._fail(
                deployment_id,
                message,
                technical=f"executor={exec_result.executor} · status={exec_result.status}",
                result=result,
            )
            return

        if scope is not None:
            await self._stage(deployment_id, StageId.EXECUTE, "completed", 0)
            rollback_ok = exec_result.status != "ROLLBACK_FAILED"
            self._status(
                deployment_id,
                DeploymentStatus.RUNNING,
                StageId.RECOVER,
                "Service failed. MEDHA is applying scoped rollback.",
                f"failed={scope.failed_node_id}",
            )
            await self._stage(deployment_id, StageId.RECOVER, "started", delay * 0.2)
            await self._emit(
                deployment_id,
                EventType.ROLLBACK_STARTED,
                "Scoped rollback started.",
                stage=StageId.RECOVER.value,
                metadata={"simple": scope.rationale, "technical": f"scope={scope.nodes_to_rollback}"},
            )
            ui_scope = scope.to_ui()
            details = getattr(scope, "_details", None)
            if details:
                ui_scope["details"] = details
            if not rollback_ok:
                ui_scope["headline"] = "ROLLBACK FAILED"
            await self._emit(
                deployment_id,
                EventType.ROLLBACK_SCOPE,
                "Rollback scope determined.",
                stage=StageId.RECOVER.value,
                metadata={
                    "simple": scope.rationale,
                    "technical": (
                        f"failed={scope.failed_nodes} · rollback={scope.nodes_to_rollback} · "
                        f"preserved={scope.nodes_preserved}"
                    ),
                    "rollback": ui_scope,
                    "graph": graph.to_ui(),
                },
            )
            await self._emit(
                deployment_id,
                EventType.ROLLBACK_COMPLETED,
                "SCOPED ROLLBACK COMPLETE" if rollback_ok else "ROLLBACK FAILED",
                stage=StageId.RECOVER.value,
                status="success" if rollback_ok else "failed",
                level="info" if rollback_ok else "error",
                metadata={
                    "simple": scope.rationale
                    if rollback_ok
                    else "Scoped rollback did not fully complete.",
                    "technical": f"rolled_back={exec_result.rolled_back_services} · status={exec_result.status}",
                    "rollback": ui_scope,
                    "graph": graph.to_ui(),
                },
            )
            await self._stage(deployment_id, StageId.RECOVER, "completed", delay * 0.2)
            message = scope.rationale if rollback_ok else "ROLLBACK_FAILED: " + scope.rationale
            result = exec_result.to_deployment_result(
                verification_score=critic.score if critic else None,
                constraints_resolved=constraints_resolved,
                rollback_scope=",".join(exec_result.rolled_back_services) or None,
                message=message,
            )
            result["phase"] = PHASE_LABEL
            self.repo.save_artifacts(
                deployment_id,
                graph=graph.to_ui(),
                rollback=ui_scope,
                verification=verification.to_ui() if verification else None,
                critic=critic.to_ui() if critic else None,
                result=result,
                updated_at=utc_now_iso(),
            )
            final_status = (
                DeploymentStatus.FAILED
                if not rollback_ok
                else DeploymentStatus.PARTIAL_RECOVERY
            )
            self._status(
                deployment_id,
                final_status,
                StageId.COMPLETE,
                message,
                f"final_status={final_status.value}",
            )
            await self._emit(
                deployment_id,
                EventType.DEPLOYMENT_COMPLETED
                if rollback_ok
                else EventType.DEPLOYMENT_FAILED,
                message,
                stage=StageId.COMPLETE.value,
                status=final_status.value,
                level="error" if not rollback_ok else "info",
                metadata={
                    "simple": message,
                    "technical": f"final_status={final_status.value} · phase={PHASE_LABEL}",
                    "result": result,
                    "graph": graph.to_ui(),
                    "rollback": ui_scope,
                    "verification": verification.to_ui() if verification else None,
                    "critic": critic.to_ui() if critic else None,
                    "pipeline": {
                        "VERIFY": {"status": "success", "detail": "Gate passed"},
                        "EXECUTE": {"status": "failed", "detail": "Partial failure"},
                        "RECOVER": {
                            "status": "success" if rollback_ok else "failed",
                            "detail": "Scoped rollback complete"
                            if rollback_ok
                            else "Rollback failed",
                        },
                        "COMPLETE": {
                            "status": "warning" if rollback_ok else "failed",
                            "detail": "Partial recovery" if rollback_ok else "Rollback failed",
                        },
                    },
                },
            )
            return

        await self._stage(deployment_id, StageId.EXECUTE, "completed", delay * 0.2)
        message = "Deployment completed successfully."
        result = exec_result.to_deployment_result(
            verification_score=critic.score if critic else None,
            constraints_resolved=constraints_resolved,
            rollback_scope=None,
            message=message,
        )
        result["phase"] = PHASE_LABEL
        self.repo.save_artifacts(
            deployment_id,
            graph=graph.to_ui(),
            rollback=None,
            verification=verification.to_ui() if verification else None,
            critic=critic.to_ui() if critic else None,
            result=result,
            updated_at=utc_now_iso(),
        )
        self._status(
            deployment_id,
            DeploymentStatus.COMPLETED,
            StageId.COMPLETE,
            message,
            f"final_status=succeeded · phase={PHASE_LABEL}",
        )
        await self._emit(
            deployment_id,
            EventType.DEPLOYMENT_COMPLETED,
            message,
            stage=StageId.COMPLETE.value,
            status=DeploymentStatus.COMPLETED.value,
            metadata={
                "simple": message,
                "technical": f"final_status=succeeded · phase={PHASE_LABEL}",
                "result": result,
                "graph": graph.to_ui(),
                "verification": verification.to_ui() if verification else None,
                "critic": critic.to_ui() if critic else None,
                "pipeline": {
                    "VERIFY": {"status": "success", "detail": "Gate passed"},
                    "EXECUTE": {"status": "success", "detail": "Services running"},
                    "RECOVER": {"status": "skipped", "detail": "Not required"},
                    "COMPLETE": {"status": "success", "detail": "Deployment finished"},
                },
            },
        )

    def _status(
        self,
        deployment_id: str,
        status: DeploymentStatus,
        stage: StageId | None,
        simple: str,
        technical: str,
        error: str | None = None,
    ) -> None:
        self.repo.update_status(
            deployment_id,
            status=status,
            current_stage=stage.value if stage else None,
            explain_simple=simple,
            explain_technical=technical,
            error_summary=error,
            updated_at=utc_now_iso(),
        )

    async def _stage(
        self,
        deployment_id: str,
        stage: StageId,
        kind: str,
        delay: float,
    ) -> None:
        et = EventType.STAGE_STARTED if kind == "started" else EventType.STAGE_COMPLETED
        await self._emit(
            deployment_id,
            et,
            f"{stage.value} {kind}",
            stage=stage.value,
            status="running" if kind == "started" else "success",
            metadata={
                "simple": f"Stage {stage.value} {kind}.",
                "technical": f"stage={stage.value} · event={et.value}",
                "pipeline": {
                    stage.value: {
                        "status": "running" if kind == "started" else "success",
                        "detail": kind,
                    }
                },
            },
        )
        if delay > 0:
            await asyncio.sleep(delay)

    async def _agent_events(
        self,
        deployment_id: str,
        agent: str,
        summary: str,
        delay: float,
    ) -> None:
        await self._emit(
            deployment_id,
            EventType.AGENT_STARTED,
            f"{agent} started",
            metadata={"agent": agent, "simple": f"{agent} agent started."},
        )
        if delay > 0:
            await asyncio.sleep(delay * 0.4)
        await self._emit(
            deployment_id,
            EventType.AGENT_COMPLETED,
            summary,
            status="success",
            metadata={"agent": agent, "simple": summary, "technical": f"agent={agent}"},
        )

    async def _fail(
        self,
        deployment_id: str,
        message: str,
        *,
        technical: str,
        result: dict | None = None,
    ) -> None:
        payload = result or {
            "kind": "failed",
            "title": "FAILED",
            "final_status": "failed",
            "message": message,
            "durationLabel": "planning",
            "servicesLabel": "n/a",
            "verificationScore": None,
            "constraintsResolved": 0,
            "rollbackScope": None,
            "phase": PHASE_LABEL,
            "is_demo": False,
        }
        payload.setdefault("message", message)
        payload.setdefault("phase", PHASE_LABEL)
        payload.setdefault("code", technical)
        self.repo.update_status(
            deployment_id,
            status=DeploymentStatus.FAILED,
            current_stage=StageId.COMPLETE.value,
            explain_simple=message,
            explain_technical=technical,
            error_summary=message,
            updated_at=utc_now_iso(),
        )
        self.repo.save_artifacts(deployment_id, result=payload, updated_at=utc_now_iso())
        await self._emit(
            deployment_id,
            EventType.DEPLOYMENT_FAILED,
            message,
            status=DeploymentStatus.FAILED.value,
            level="error",
            metadata={
                "simple": message,
                "technical": technical,
                "result": payload,
            },
        )

    async def _emit(
        self,
        deployment_id: str,
        event_type: EventType,
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
            metadata={**(metadata or {}), "is_demo": False},
            is_demo=False,
        )
        self.repo.add_event(event)
        await event_bus.publish(event)


def _apply_replan_fixes(config_fragments: dict, verification) -> dict:
    """Deterministic bounded replan patches (no LLM)."""
    fixed = {
        **config_fragments,
        "docker": {**(config_fragments.get("docker") or {})},
        "env_present": {**(config_fragments.get("env_present") or {})},
    }
    compose = fixed["docker"].get("compose_fragment") or {"services": {}}
    services = dict(compose.get("services") or {})
    for failure in verification.blocking_failures:
        if "DATABASE_URL" in failure:
            fixed["env_present"]["DATABASE_URL"] = True
            for name, svc in list(services.items()):
                if not isinstance(svc, dict):
                    continue
                env = dict(svc.get("environment") or {})
                env["DATABASE_URL"] = "${DATABASE_URL}"
                svc = {**svc, "environment": env}
                services[name] = svc
    fixed["docker"]["compose_fragment"] = {**compose, "services": services}
    return fixed


def _agents_snapshot(results) -> list[dict]:
    by = {r.agent: r for r in results}
    order = [
        ("preflight", "Preflight"),
        ("analyzer", "Code Analyzer"),
        ("docker", "Docker"),
        ("nginx", "Nginx"),
        ("security", "Security"),
        ("mediator", "Mediator"),
        ("verifier", "Verifier"),
        ("critic", "Critic"),
        ("executor", "Executor"),
        ("rollback", "Rollback"),
    ]
    rows = []
    for aid, name in order:
        if aid in by:
            r = by[aid]
            rows.append(
                {
                    "id": aid,
                    "name": name,
                    "status": "complete" if r.ok else "failed",
                    "activity": r.summary,
                    "lastEvent": r.summary,
                }
            )
        elif aid == "mediator":
            rows.append(
                {
                    "id": aid,
                    "name": name,
                    "status": "running",
                    "activity": "Ready for CNP",
                    "lastEvent": "—",
                }
            )
        else:
            rows.append(
                {
                    "id": aid,
                    "name": name,
                    "status": "skipped",
                    "activity": "Deferred to later phase",
                    "lastEvent": "—",
                }
            )
    return rows


def schedule_planning_pipeline(
    deployment_id: str,
    *,
    create_task: Callable = asyncio.create_task,
    repo: DeploymentRepository | None = None,
):
    pipeline = PlanningPipeline(repo=repo)
    return create_task(pipeline.run(deployment_id))
