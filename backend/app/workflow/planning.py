"""Real-mode pipeline: analyze → specialists → CNP → verify → execute → CEG/rollback."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Callable

from app.agents.analyzer import analyze_repository
from app.agents.critic import run_critic
from app.agents.docker_agent import run_docker_agent
from app.agents.nginx_agent import run_nginx_agent
from app.agents.preflight import run_preflight
from app.agents.security_agent import run_security_agent
from app.agents.verifier import run_verifier
from app.cnp.engine import detect_conflicts, run_cnp
from app.core import run_control
from app.core.config import get_settings
from app.core.deploy_lock import release_real_deploy, try_acquire_real_deploy
from app.core.enums import DeploymentStatus, EventType, StageId
from app.core.events import event_bus, make_event, utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import DeploymentRepository
from app.workflow.stages import StageTracker
from app.execution import docker_ops
from app.execution.executor import choose_executor
from app.execution.plan_builder import build_ceg_from_plan, build_execution_plan
from app.execution.readiness import (
    EXECUTION_DISABLED_HOSTED,
    EXECUTION_NOT_CONFIGURED,
    assess_execution_readiness,
)
from app.execution.support import assess_plan_support
from app.models.domain import NegotiatedPlan
from app.models.execution import CriticRecommendation
from app.services.git_service import GitAcquireError, acquire_repository
from app.services.workspace import cleanup_workspace, resolve_local_repo_path

logger = get_logger(__name__)

PHASE_LABEL = "10-11"


def _canonical_plan(exec_plan: Any, *, repository_url: str | None = None, target_sha: str | None = None) -> dict[str, Any]:
    """Stable, serializable plan snapshot for hashing and proposals.

    Phase 2: binds repository identity + resolved source SHA into the plan
    identity so branch-tip movement is detected as STALE on retry/approve.
    """
    try:
        data = exec_plan.model_dump(mode="json")
    except Exception:  # noqa: BLE001 - hash must never break execution
        data = {}
    return {
        "deployment_id": getattr(exec_plan, "deployment_id", None),
        "repository_url": repository_url,
        "target_sha": target_sha,
        "services": data.get("services", []),
        "actions": data.get("actions", []),
        "dependencies": data.get("dependencies", {}),
        "networks": data.get("networks", []),
        "volumes": data.get("volumes", []),
        "compose": data.get("compose", {}),
    }


def _plan_hash(canonical: dict[str, Any]) -> str:
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _exact_sha_or_none(value: str | None) -> str | None:
    """Return the SHA when it is an exact 40-hex commit, else None.

    Non-SHA revisions (branch names, short hashes, None) keep the legacy
    behavior: workspace copy / branch-tip clone without commit binding.
    """
    if not value:
        return None
    candidate = value.strip().lower()
    if len(candidate) == 40 and all(ch in "0123456789abcdef" for ch in candidate):
        return candidate
    return None


def _ai_context(record: Any, settings: Any) -> dict[str, Any]:
    """Per-run AI state: shared service, call budget, notes, owner binding."""
    from app.ai.service import AIBudget, AIService

    return {
        "service": AIService(settings),
        "budget": AIBudget(max_calls=max(0, settings.ai_max_calls_per_run)),
        "notes": {},
        "owner": (record.owner_sub if record is not None else None) or "local",
        "warned_unavailable": False,
    }


def _ai_rollup(notes: dict[str, Any]) -> dict[str, Any] | None:
    """Compact overall AI status for run records and the UI."""
    if not notes:
        return None
    from app.ai.service import PROMPT_VERSION

    rank = {"ai_assisted": 0, "degraded": 1, "unavailable": 2, "rule_based": 3}
    metas = [note["meta"] for note in notes.values()]
    best = min(metas, key=lambda m: rank.get(m.get("outcome", "rule_based"), 3))
    return {
        "outcome": best.get("outcome"),
        "provider": best.get("provider"),
        "model": best.get("model"),
        "fallback_used": any(m.get("fallback_used") for m in metas),
        "failure_category": best.get("failure_category"),
        "prompt_version": PROMPT_VERSION,
        "notes": notes,
    }


def _clamp_timeout(value: float, default: float) -> float:
    """Clamp a configured stage timeout to [1, 3600] seconds."""
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed or parsed == float("inf") or parsed == float("-inf"):
        return default
    return max(1.0, min(parsed, 3600.0))


class PlanningPipeline:
    """Phases 4–11 real path (local only; Docker mutate opt-in)."""

    def __init__(self, repo: DeploymentRepository | None = None) -> None:
        self.repo = repo or DeploymentRepository()
        # Per-run observability: real agent lifecycle + measured stage
        # timings. One pipeline instance serves one run.
        self.tracker = StageTracker()
        self.stage_timings: dict[str, float] = {}
        self._pipeline_t0 = 0.0

    # -- cancellation + terminal handling ------------------------------------

    def _cancel_observed(self, deployment_id: str) -> bool:
        """True when the owner cancelled (flag) or the record is cancelled."""
        if run_control.cancel_requested(deployment_id):
            return True
        try:
            record = self.repo.get(deployment_id)
            return record is not None and record.status == DeploymentStatus.CANCELLED
        except Exception:  # noqa: BLE001 - a failed read must not mask work
            return False

    def _current_status(self, deployment_id: str) -> str | None:
        try:
            record = self.repo.get(deployment_id)
            return record.status.value if record is not None else None
        except Exception:  # noqa: BLE001 - terminal guards degrade to proceed
            return None

    async def _note_cancelled(self, deployment_id: str, where: str) -> None:
        """Record pipeline-observed cancellation and emit one terminal event.

        Idempotent: the cancel endpoint usually already set CANCELLED and
        emitted; `claim_terminal` guarantees exactly one terminal event wins.
        """
        self.repo.update_status(
            deployment_id,
            status=DeploymentStatus.CANCELLED,
            current_stage=StageId.COMPLETE.value,
            explain_simple=(
                f"Deployment cancelled during {where}; remaining stages skipped."
            ),
            explain_technical=f"cancel.observed={where}",
            updated_at=utc_now_iso(),
            allowed_from={
                DeploymentStatus.STARTED.value,
                DeploymentStatus.RUNNING.value,
                DeploymentStatus.QUEUED.value,
                DeploymentStatus.AWAITING_APPROVAL.value,
            },
        )
        self.tracker.cancel_remaining()
        if run_control.claim_terminal(deployment_id):
            await self._emit(
                deployment_id,
                EventType.DEPLOYMENT_CANCELLED,
                f"Deployment cancelled during {where}; remaining stages skipped.",
                stage=StageId.COMPLETE.value,
                status=DeploymentStatus.CANCELLED.value,
                metadata={
                    "simple": "The owner cancelled this run; no further stages started.",
                    "technical": f"cancel.observed={where}",
                },
                include_agents=True,
            )

    def _record_timing(self, name: str, elapsed_s: float) -> None:
        try:
            self.stage_timings[name] = round(
                self.stage_timings.get(name, 0.0) + elapsed_s * 1000.0, 1
            )
        except Exception:  # noqa: BLE001 - instrumentation never breaks runs
            pass

    def _result_timings(self) -> dict[str, Any]:
        timings = dict(self.stage_timings)
        if self._pipeline_t0:
            timings["totalMs"] = round(
                (time.perf_counter() - self._pipeline_t0) * 1000.0, 1
            )
        return timings

    async def run(
        self,
        deployment_id: str,
        *,
        plan_only: bool = False,
        expected_plan_hash: str | None = None,
        proposal_id: str | None = None,
    ) -> None:
        settings = get_settings()
        # Real pipeline never paces for presentation: DemoRunner keeps its
        # own pacing for demo readability; sleeps here only slowed runs.
        delay = 0.0
        record = self.repo.get(deployment_id)
        if record is None:
            logger.error("PlanningPipeline missing deployment_id=%s", deployment_id)
            return
        ai_ctx = _ai_context(record, settings)
        # Evidence-backed Repository Intelligence for this run (built after
        # analysis from the pinned revision; persisted on events + results).
        repository_intelligence: dict | None = None

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
        self._pipeline_t0 = pipeline_t0
        self.tracker = StageTracker()
        self.stage_timings = {}
        run_control.clear_run(deployment_id)
        # One shared HTTP client for all AI assists in this run (keep-alive
        # reuse instead of a new TCP/TLS pool per assist). Closed in finally.
        try:
            import httpx as _httpx

            _ai_client = _httpx.AsyncClient(timeout=_httpx.Timeout(connect=5.0))
        except Exception:  # noqa: BLE001 - AI degrades to rule_based without it
            _ai_client = None
        if _ai_client is not None:
            try:
                ai_ctx["service"]._client = _ai_client
            except Exception:  # noqa: BLE001 - advisory only
                pass
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
            await self._agent_start(
                deployment_id, "preflight", "Checking host prerequisites.")
            preflight = run_preflight(
                require_git_for_remote=True,
                is_remote=is_remote,
                target_port=record.target_port,
                require_docker_for_execute=bool(settings.docker_execute),
            )
            await self._agent_done(
                deployment_id, "preflight", preflight.summary, ok=preflight.ok)
            if self._cancel_observed(deployment_id):
                await self._note_cancelled(deployment_id, "preflight")
                return
            if not preflight.ok:
                raise RuntimeError(preflight.summary)

            await self._stage(deployment_id, StageId.PREFLIGHT, "completed", delay)

            # Source identity: resolve the requested ref (branch/tag/SHA) to an
            # immutable commit SHA before anything else. Fail closed when the
            # ref cannot be resolved to exactly one commit.
            from app.services.git_service import GitAcquireError as _GAE
            from app.services.git_service import resolve_ref_to_sha
            from app.services.github_app import GitHubAppError as _GHE
            from app.services.github_app import prepare_private_access

            # Private GitHub access: mint a short-lived installation token
            # scoped to the requested repo (empty env = public/anonymous path).
            # The token lives only in this run's memory — never persisted,
            # logged, or embedded in URLs.
            try:
                git_auth_env = await asyncio.to_thread(
                    prepare_private_access, record.repository_url
                )
            except _GHE as exc:
                await self._fail(
                    deployment_id,
                    f"Private repository access failed: {exc.message}",
                    technical=f"github.{exc.code}",
                )
                return

            requested_ref = record.target_revision
            resolved_sha: str | None = None
            if requested_ref:
                exact = _exact_sha_or_none(requested_ref)
                if exact:
                    resolved_sha = exact
                else:
                    try:
                        resolved_sha = await asyncio.to_thread(
                            resolve_ref_to_sha,
                            record.repository_url,
                            requested_ref,
                            env=git_auth_env or None,
                        )
                    except _GAE as exc:
                        from app.services.workspace import resolve_local_repo_path as _local

                        if _local(record.repository_url) is not None:
                            # Single-operator local workflow: the checkout is the
                            # operator's own files, not a moving remote tip.
                            # Continue unpinned but say so explicitly.
                            await self._emit(
                                deployment_id,
                                EventType.SYSTEM_MESSAGE,
                                f"Source ref '{requested_ref}' is not a git ref; "
                                "analyzing the working copy without commit binding.",
                                stage=StageId.ANALYZE.value,
                                level="warning",
                                metadata={
                                    "simple": "No commit binding for this local source.",
                                    "technical": (
                                        f"requested_ref={requested_ref} · "
                                        f"resolved_sha=None · code={exc.code}"
                                    ),
                                    "requested_ref": requested_ref,
                                    "resolved_sha": None,
                                },
                            )
                        else:
                            await self._fail(
                                deployment_id,
                                f"Cannot resolve source ref '{requested_ref}': {exc.message}",
                                technical=f"git.{exc.code}",
                            )
                            return
                if resolved_sha:
                    await self._emit(
                        deployment_id,
                        EventType.SYSTEM_MESSAGE,
                        f"Source pinned to commit {resolved_sha[:12]}.",
                        stage=StageId.ANALYZE.value,
                        metadata={
                            "simple": "MEDHA pinned the requested revision to an immutable commit.",
                            "technical": (
                                f"requested_ref={requested_ref} · resolved_sha={resolved_sha}"
                            ),
                            "requested_ref": requested_ref,
                            "resolved_sha": resolved_sha,
                        },
                    )

            # Invariant: every remote real run is bound to exactly one
            # immutable commit SHA before analysis. Runs without an explicit
            # revision resolve the remote HEAD here; unresolvable remotes fail
            # closed — branch-tip clones without a recorded SHA are refused.
            if resolved_sha is None and resolve_local_repo_path(record.repository_url) is None:
                try:
                    resolved_sha = await asyncio.to_thread(
                        resolve_ref_to_sha,
                        record.repository_url,
                        "HEAD",
                        env=git_auth_env or None,
                    )
                except _GAE as exc:
                    await self._fail(
                        deployment_id,
                        "Cannot verify repository access: "
                        f"{exc.message} Run a verification check first, or use a local path.",
                        technical=f"git.{exc.code}",
                    )
                    return
                await self._emit(
                    deployment_id,
                    EventType.SYSTEM_MESSAGE,
                    f"Source pinned to commit {resolved_sha[:12]} (remote HEAD).",
                    stage=StageId.ANALYZE.value,
                    metadata={
                        "simple": "MEDHA pinned the remote HEAD to an immutable commit before analysis.",
                        "technical": f"requested_ref=HEAD · resolved_sha={resolved_sha}",
                        "requested_ref": "HEAD",
                        "resolved_sha": resolved_sha,
                    },
                )

            # ANALYZE
            self._status(
                deployment_id,
                DeploymentStatus.RUNNING,
                StageId.ANALYZE,
                "MEDHA is acquiring and analyzing the repository manifests.",
                "workflow=planning · stage=ANALYZE",
            )
            await self._stage(deployment_id, StageId.ANALYZE, "started", 0)
            ref_sha = resolved_sha
            from app.core.perf import stage as _stage_timer

            with _stage_timer("acquire", deployment_id=deployment_id) as acquire_timer:
                try:
                    # Bounded wait on network-facing acquisition (clone/fetch):
                    # a timeout cancels the wait, not the detached thread,
                    # whose late result is dropped — never accepted after this.
                    async with asyncio.timeout(
                        _clamp_timeout(settings.timeout_acquire_s, 120.0)
                    ):
                        acquisition = await asyncio.to_thread(
                            acquire_repository,
                            deployment_id,
                            record.repository_url,
                            ref_sha=ref_sha,
                            token_env=git_auth_env or None,
                        )
                except TimeoutError:
                    # __exit__ has not run yet, so elapsed is unset — measure
                    # from t0 directly for an honest timeout duration.
                    self._record_timing(
                        "acquire", time.perf_counter() - acquire_timer.t0
                    )
                    # The detached thread may still finish late; its result is
                    # dropped above, so remove any partial clone it leaves.
                    try:
                        cleanup_workspace(deployment_id)
                    except Exception:
                        pass
                    await self._fail(
                        deployment_id,
                        "Repository acquisition timed out; the run fails closed.",
                        technical="TIMEOUT:acquire",
                    )
                    return
            self._record_timing("acquire", acquire_timer.elapsed)
            if ref_sha and acquisition.checked_sha != ref_sha:
                # Defense in depth: acquire_repository already asserts this.
                raise RuntimeError(
                    "SHA_MISMATCH: checked-out commit does not match the requested SHA."
                )
            if self._cancel_observed(deployment_id):
                await self._note_cancelled(deployment_id, "acquisition")
                return
            await self._agent_start(
                deployment_id, "analyzer", "Analyzing repository manifests.")
            # Project-scoped deployment target (persisted per project, never
            # shared across projects). Invalid/stale values fail closed below.
            deploy_target: str | None = None
            if record.project_id:
                try:
                    from app.database.repositories import ProjectRepository

                    _proj = ProjectRepository(db_path=self.repo.db_path).get(record.project_id)
                    if _proj is not None and _proj.deploy_target:
                        deploy_target = _proj.deploy_target
                except Exception:
                    deploy_target = None
            analyze_timer = None
            try:
                # Bounded wait: the analyzer is deterministic and fast; on
                # timeout the run fails closed and any detached thread result
                # is dropped, never accepted late.
                async with asyncio.timeout(
                    _clamp_timeout(settings.timeout_analyze_s, 120.0)
                ):
                    with _stage_timer("analyze", deployment_id=deployment_id) as analyze_timer:
                        profile, analysis = await asyncio.to_thread(
                            analyze_repository,
                            deployment_id=deployment_id,
                            repository_url=record.repository_url,
                            workspace_path=acquisition.path,
                            target_host=record.target_host,
                            target_port=record.target_port,
                            intent=record.intent,
                            deploy_target=deploy_target,
                        )
            except TimeoutError:
                if analyze_timer is not None:
                    self._record_timing("analyze", analyze_timer.elapsed)
                await self._agent_done(
                    deployment_id, "analyzer",
                    "Repository analysis exceeded its stage time budget.",
                    ok=False, status="timed_out", error="timeout")
                await self._fail(
                    deployment_id,
                    "Repository analysis timed out; the run fails closed.",
                    technical="TIMEOUT:analyze",
                )
                return
            except ValueError as exc:
                # Stale/invalid deployment target: actionable, never a crash.
                message = str(exc)
                code = "INVALID_DEPLOYMENT_TARGET"
                if message.startswith("INVALID_DEPLOYMENT_TARGET"):
                    message = message.split(":", 1)[1].strip() if ":" in message else message
                else:
                    code = "ANALYZE_FAILED"
                if analyze_timer is not None:
                    self._record_timing("analyze", analyze_timer.elapsed)
                await self._agent_done(
                    deployment_id, "analyzer", message, ok=False, error="invalid_target")
                result = {
                    "kind": "failed",
                    "title": code,
                    "final_status": "failed",
                    "message": message,
                    "durationLabel": "analyze",
                    "servicesLabel": "0 / 0 started",
                    "verificationScore": None,
                    "constraintsResolved": 0,
                    "rollbackScope": None,
                    "phase": PHASE_LABEL,
                    "is_demo": False,
                    "code": code,
                    "target_selection": {
                        "candidates": [],
                        "reason": "stale or unknown target",
                        "next_actions": ["select_target", "reanalyze"],
                    },
                }
                self.repo.save_artifacts(
                    deployment_id, result=result, updated_at=utc_now_iso()
                )
                await self._fail(
                    deployment_id, message, technical=code, result=result,
                )
                return
            self._record_timing("analyze", analyze_timer.elapsed)
            await self._agent_done(
                deployment_id, "analyzer", analysis.summary, ok=analysis.ok)
            if self._cancel_observed(deployment_id):
                await self._note_cancelled(deployment_id, "analysis")
                return
            change_intel = await self._run_change_intel(
                deployment_id, record, settings, delay
            )
            # Tier 1 (docs-only / no-change) makes zero LLM calls: deterministic
            # evidence is sufficient and budgets forbid model use at tier 1.
            _tier_one = False
            try:
                _fresh_ci = self._fresh_change_intel(deployment_id)
                _tier_one = isinstance(_fresh_ci, dict) and isinstance(
                    _fresh_ci.get("tier"), dict) and _fresh_ci["tier"].get("tier") == 1
            except Exception:
                _tier_one = False
            # change_summary and repo_interpretation are independent payloads
            # (shared budget + semaphore bound them safely) — overlap them.
            # _ai_assist never raises, so gather is latency-only.
            if not _tier_one:
                await asyncio.gather(
                    self._ai_assist(
                        deployment_id,
                        "change_summary",
                        {"change": self._fresh_change_intel(deployment_id)},
                        ai_ctx,
                        stage=StageId.ANALYZE.value,
                    ),
                    self._ai_assist(
                        deployment_id,
                        "repo_interpretation",
                        {"profile": self._dump_profile(profile)},
                        ai_ctx,
                        stage=StageId.ANALYZE.value,
                    ),
                )
            else:
                await self._emit(
                    deployment_id,
                    EventType.SYSTEM_MESSAGE,
                    "Tier 1 analysis: deterministic checks only (0 LLM calls).",
                    stage=StageId.ANALYZE.value,
                    metadata={
                        "simple": "Documentation-only change: no model calls needed.",
                        "technical": "tier=1 · llm_budget=0 · skipped=ai_assist",
                    },
                )
            from app.agents.analyzer import build_repository_intelligence as _build_intel

            repository_intelligence = _build_intel(
                profile,
                commit_sha=acquisition.checked_sha or resolved_sha,
                repository_url=record.repository_url,
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
                        + (
                            f" · checked_sha={acquisition.checked_sha[:12]}"
                            if acquisition.checked_sha
                            else ""
                        )
                    ),
                    "profile": {
                        "language_runtime": profile.inferred_stack.language_runtime,
                        "services": [s.model_dump() for s in profile.inferred_stack.services],
                        "has_dockerfile": profile.inferred_stack.has_dockerfile,
                        "has_compose": profile.inferred_stack.has_compose,
                        "suggested_ports": profile.inferred_stack.suggested_ports,
                        "confidence": profile.inferred_stack.confidence,
                        "app_candidates": profile.inferred_stack.app_candidates,
                        "app_relationship": profile.inferred_stack.app_relationship,
                        "selected_target": profile.inferred_stack.selected_target,
                    },
                    "repository_intelligence": repository_intelligence,
                },
            )
            await self._stage(deployment_id, StageId.ANALYZE, "completed", delay)
            # Persist commit metadata + deterministic summary for the analyzed
            # revision (from this checkout — no extra clone). Advisory only:
            # analysis stands on its own when the checkout has no git history.
            await self._record_analyzed_commit(
                deployment_id, record, acquisition, resolved_sha,
            )

            support = assess_plan_support(profile, selected_target=deploy_target)
            if not support.supported:
                stack = profile.inferred_stack
                candidates = [
                    {"path": c.path, "technologies": c.technologies, "evidence": c.evidence}
                    if hasattr(c, "path") else c
                    for c in []
                ]
                details = support.details or {}
                target_selection = {
                    "candidates": details.get("candidates", [
                        {"path": p, "technologies": [], "evidence": []}
                        for p in (stack.app_candidates or [])
                    ]),
                    "relationship": details.get("relationship", stack.app_relationship),
                    "reason": details.get("reason", "automatic selection is ambiguous"),
                    "next_actions": details.get("next_actions", ["select_target", "reanalyze"]),
                    "supported_targets": details.get("supported_targets", list(stack.app_candidates or [])),
                    "selected_target": deploy_target,
                    "project_id": record.project_id,
                }
                if support.code == "MULTIPLE_APPS_REQUIRE_TARGET":
                    user_message = (
                        support.message
                        + " Set one via project settings or re-run with an explicit "
                        "deployment target; V1 executes exactly one service."
                    )
                else:
                    user_message = support.message
                result = {
                    "kind": "failed",
                    "title": support.code or "DEPLOYMENT_UNSUPPORTED",
                    "final_status": "failed",
                    "message": user_message,
                    "durationLabel": "analyze",
                    "servicesLabel": "0 / 0 started",
                    "verificationScore": None,
                    "constraintsResolved": 0,
                    "rollbackScope": None,
                    "phase": PHASE_LABEL,
                    "is_demo": False,
                    "code": support.code,
                    "target_selection": target_selection,
                    "deployment_id": deployment_id,
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

            # Independent pure functions over the same immutable profile:
            # bounded concurrency, deterministic aggregation order preserved.
            # Each runs in a worker thread (sync CPU/file work off the loop).
            # Bounded wait with honest semantics: a timeout cancels the wait,
            # not the detached threads, whose late results are dropped.
            await self._agent_start(
                deployment_id, "docker", "Publishing container constraints.")
            await self._agent_start(
                deployment_id, "nginx", "Publishing proxy constraints.")
            await self._agent_start(
                deployment_id, "security", "Publishing security policies.")
            spec_timer = None
            try:
                async with asyncio.timeout(
                    _clamp_timeout(settings.timeout_specialists_s, 30.0)
                ):
                    with _stage_timer("specialists", deployment_id=deployment_id) as spec_timer:
                        docker_res, nginx_res, security_res = await asyncio.gather(
                            asyncio.to_thread(run_docker_agent, profile),
                            asyncio.to_thread(run_nginx_agent, profile),
                            asyncio.to_thread(run_security_agent, profile),
                        )
            except TimeoutError:
                if spec_timer is not None:
                    self._record_timing("specialists", spec_timer.elapsed)
                for agent_name in ("docker", "nginx", "security"):
                    await self._agent_done(
                        deployment_id, agent_name,
                        "Specialist exceeded its stage time budget.",
                        ok=False, status="timed_out", error="timeout")
                await self._fail(
                    deployment_id,
                    "Specialist agents timed out; the run fails closed.",
                    technical="TIMEOUT:specialists",
                )
                return
            self._record_timing("specialists", spec_timer.elapsed)
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
                await self._agent_done(
                    deployment_id, agent_name, res.summary, ok=res.ok)

            if self._cancel_observed(deployment_id):
                await self._note_cancelled(deployment_id, "specialists")
                return

            await self._emit(
                deployment_id,
                EventType.CONSTRAINT_PUBLISHED,
                f"Specialists published {len(all_constraints)} typed constraints.",
                stage=StageId.AGENTS.value,
                metadata={
                    "simple": "Specialist agents published typed infrastructure constraints.",
                    "technical": f"constraints={len(all_constraints)} · is_demo=false",
                    "constraints": [c.to_ui() for c in all_constraints],
                    "agents": self.tracker.snapshot(),
                },
            )
            self.repo.save_artifacts(
                deployment_id,
                constraints=[c.to_ui() for c in all_constraints],
                updated_at=utc_now_iso(),
            )
            await self._ai_assist(
                deployment_id,
                "agent_explanation",
                {
                    "agent": "docker",
                    "summary": docker_res.summary,
                    "constraints": [c.to_ui() for c in docker_res.constraints[:4]],
                },
                ai_ctx,
                stage=StageId.AGENTS.value,
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
            await self._agent_start(
                deployment_id, "mediator", "Negotiating typed constraints.")
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
                include_agents=True,
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

            from app.core.perf import stage as _stage_timer

            with _stage_timer("cnp", deployment_id=deployment_id) as cnp_timer:
                negotiation = run_cnp(deployment_id, all_constraints, is_demo=False)
            self._record_timing("cnp", cnp_timer.elapsed)
            if negotiation.status == "resolved":
                method_summary = (
                    negotiation.decisions[-1].rationale
                    if negotiation.decisions
                    else "Constraint set accepted as proposed"
                )
            else:
                method_summary = (
                    f"CNP ended {negotiation.status} after "
                    f"{negotiation.rounds_used} round(s)"
                )
            await self._agent_done(
                deployment_id, "mediator", method_summary,
                ok=negotiation.status == "resolved")
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
                    include_agents=True,
                )

            if self._cancel_observed(deployment_id):
                await self._note_cancelled(deployment_id, "negotiation")
                return

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
                    message=(
                        "CNP found no valid constraints to negotiate. Execution blocked."
                        if negotiation.status == "invalid"
                        else "CNP exhausted without a clean constraint set. Execution blocked."
                    ),
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
                    "Constraint negotiation failed closed without a clean plan.",
                    f"cnp.status={negotiation.status} · rounds={negotiation.rounds_used}",
                    error=plan.message,
                )
                self.tracker.fail_remaining(error=plan.message[:200])
                if run_control.claim_terminal(deployment_id):
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
                        include_agents=True,
                    )
                return

            await self._stage(deployment_id, StageId.NEGOTIATE, "completed", delay)

            await self._ai_assist(
                deployment_id,
                "plan_suggestion",
                {
                    "decisions": ui_negotiation,
                    "constraints": ui_constraints[:8],
                },
                ai_ctx,
                stage=StageId.NEGOTIATE.value,
            )

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
                change_intel=change_intel,
                repository_intelligence=repository_intelligence,
                plan_only=plan_only,
                expected_plan_hash=expected_plan_hash,
                proposal_id=proposal_id,
                ai_ctx=ai_ctx,
                acquisition=acquisition,
                requested_ref=requested_ref,
                resolved_sha=resolved_sha,
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
            run_control.clear_run(deployment_id)
            try:
                service = ai_ctx.get("service") if ai_ctx else None
                client = getattr(service, "_client", None)
                if client is not None:
                    await client.aclose()
                    service._client = None
            except Exception:  # noqa: BLE001 - shutdown must never raise
                pass
            try:
                # Successful real deployments stay alive under MEDHA labels
                # until explicit teardown: never remove a COMPLETED run's
                # containers merely because the pipeline task is exiting.
                # Failed/cancelled workloads are already cleaned at their
                # failure sites; this is a best-effort sweep for leftovers.
                if get_settings().docker_execute and get_settings().docker_cleanup:
                    try:
                        _final = self.repo.get(deployment_id)
                    except Exception:
                        _final = None
                    if _final is None or _final.status != DeploymentStatus.COMPLETED:
                        try:
                            if docker_ops.docker_cli_available():
                                docker_ops.cleanup_deployment(deployment_id)
                        except Exception:  # noqa: BLE001 - best effort
                            pass
            except Exception:  # noqa: BLE001
                logger.exception("Docker cleanup failed deployment_id=%s", deployment_id)
            if not get_settings().medha_debug:
                cleanup_workspace(deployment_id)

    async def _record_analyzed_commit(
        self, deployment_id: str, record, acquisition, resolved_sha: str | None,
    ) -> None:
        """Persist commit metadata + deterministic summary (ANALYZE stage).

        Uses the already-acquired pinned checkout — never re-clones. Runs
        for analysis regardless of later deployment outcome (analysis,
        deployment, and summarization state stay distinct). Best-effort:
        a checkout without git history yields an honest warning, never a
        pipeline failure and never a fabricated summary.
        """
        project_id = getattr(record, "project_id", None)
        sha = ((getattr(acquisition, "checked_sha", None) or resolved_sha) or "")
        sha = sha.strip().lower()
        if not project_id or len(sha) != 40:
            return
        try:
            from app.database.repositories import CommitRepository, ProjectRepository
            from app.services import history_service as _hs

            entry = await _read_commit_evidence(
                record, acquisition, sha, _hs.commit_metadata,
            )
            try:
                diff = await _read_commit_evidence(
                    record, acquisition, sha, _hs.changed_files_summary,
                )
            except _hs.HistoryError:
                diff = None
            summary = _hs.build_commit_summary(entry, diff)
            branch = None
            try:
                proj = await asyncio.to_thread(
                    ProjectRepository(db_path=self.repo.db_path).get, project_id,
                )
                branch = proj.branch if proj is not None else None
            except Exception:  # noqa: BLE001 - branch is decorative
                branch = None
            await asyncio.to_thread(
                CommitRepository(db_path=self.repo.db_path).upsert,
                project_id=project_id, sha=entry.sha, parents=entry.parents,
                author=entry.author, committed_at=entry.committed_at,
                message=entry.message, branch=branch,
                recorded_at=utc_now_iso(), summary=summary,
                files=(diff or {}).get("files") if diff else None,
                added=(diff or {}).get("added", 0) if diff else 0,
                deleted=(diff or {}).get("deleted", 0) if diff else 0,
                deployment_id=deployment_id,
            )
        except Exception as exc:  # noqa: BLE001 - advisory only
            logger.warning(
                "Commit summary unavailable deployment_id=%s: %s",
                deployment_id, type(exc).__name__,
            )
            await self._emit(
                deployment_id,
                EventType.SYSTEM_MESSAGE,
                "Commit summary unavailable for this checkout; "
                "overview will show metadata as unavailable.",
                stage=StageId.ANALYZE.value,
                level="warning",
                metadata={
                    "simple": "Commit details could not be read from this checkout.",
                    "technical": f"commit.summary=unavailable · sha={sha[:12]}",
                },
            )

    def _fresh_change_intel(self, deployment_id: str) -> dict[str, Any] | None:
        try:
            fresh = self.repo.get(deployment_id)
        except Exception:  # noqa: BLE001 - advisory only
            return None
        return fresh.change_intel if fresh is not None else None

    @staticmethod
    def _dump_profile(profile: Any) -> dict[str, Any]:
        try:
            return profile.model_dump(mode="json")
        except Exception:  # noqa: BLE001 - advisory only
            return {"summary": str(profile)[:500]}

    async def _ai_assist(
        self,
        deployment_id: str,
        kind: str,
        payload: dict[str, Any],
        ai_ctx: dict[str, Any] | None,
        *,
        stage: str | None = None,
    ) -> None:
        """Run one advisory AI assist; never alters control flow on failure."""
        if not ai_ctx:
            return
        from app.ai.assist import system_prompt_for

        service = ai_ctx["service"]
        try:
            data, meta = await service.generate_structured(
                kind=kind,
                payload=payload,
                system=system_prompt_for(kind),
                owner_ctx=ai_ctx.get("owner") or "local",
                budget=ai_ctx["budget"],
            )
        except Exception:  # noqa: BLE001 - AI must never break the pipeline
            logger.exception("AI assist failed kind=%s", kind)
            return
        ai_ctx["notes"][kind] = {"data": data, "meta": meta.to_dict()}
        if data is None and meta.outcome == "rule_based":
            return  # disabled/keyless/budget: stay silent and deterministic
        if data is None and ai_ctx.get("warned_unavailable"):
            return  # one honest warning per run, not one per stage
        if data is None:
            ai_ctx["warned_unavailable"] = True
        await self._emit(
            deployment_id,
            EventType.SYSTEM_MESSAGE,
            (
                f"AI {kind} ready (provider={meta.provider})."
                if data is not None
                else "AI unavailable — continuing with deterministic analysis."
            ),
            stage=stage,
            level="info" if data is not None else "warning",
            metadata={
                "simple": (
                    "An AI advisory note is attached to this run."
                    if data is not None
                    else "AI providers unreachable; deterministic pipeline continues."
                ),
                "technical": f"ai.kind={kind} · outcome={meta.outcome}",
                "ai": meta.to_dict(),
                "ai_data": data,
            },
        )

    def _persist_ai(self, deployment_id: str, ai_ctx: dict[str, Any] | None) -> None:
        if not ai_ctx or not ai_ctx.get("notes"):
            return
        summary = _ai_rollup(ai_ctx["notes"])
        if summary is not None:
            self.repo.save_artifacts(
                deployment_id, ai=summary, updated_at=utc_now_iso()
            )

    async def _run_change_intel(self, deployment_id: str, record, settings, delay: float):
        """Phase 2/2b: deterministic change-impact analysis.

        Local git repositories use the full base → target diff pipeline.
        Remote repositories use the push-payload evidence (verified commit
        lists) verified against the exact-SHA checkout. Anything else is
        skipped honestly — the deployment continues with change_intel
        absent rather than faking evidence.

        Returns the analysis (for the verification gate) or None when skipped.
        """
        if resolve_local_repo_path(record.repository_url) is None:
            return await self._run_push_change_intel(deployment_id, record, delay)
        if not record.base_revision or not record.target_revision:
            return None
        try:
            from app.changeintel.engine import analyze_change_impact
            from app.changeintel.git_extract import ChangeIntelError
            from app.core.perf import stage as _stage_timer

            with _stage_timer("change_intel", deployment_id=deployment_id):
                info = await asyncio.to_thread(
                    analyze_change_impact,
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
            return None
        risk_value = info.risk.level.value
        stored = info.model_dump(mode="json")
        stored["deployment_id"] = deployment_id
        try:
            from app.changeintel.tiers import inputs_hash as _inputs_hash
            from app.changeintel.tiers import route as _route

            _decision = _route(
                [f.path for f in info.changeset.files],
                risk_level=risk_value,
                unresolved=len(info.unresolved),
                blast_radius=len(info.graph.nodes),
            )
            stored["tier"] = {
                "tier": _decision.tier,
                "reason": _decision.reason,
                "scope": _decision.scope,
                "llm_budget": _decision.llm_budget,
                "skipped": _decision.skipped,
                "cache_hit": False,
            }
            stored["inputs_hash"] = _inputs_hash(
                base_sha=info.changeset.base_sha,
                target_sha=info.changeset.target_sha,
                file_hashes={},
                tool_version="changeintel-v1",
                config={},
            )
        except Exception:
            pass
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
        return info

    async def _run_push_change_intel(self, deployment_id: str, record, delay: float):
        """Phase 2b: push-evidence analysis for remote repositories.

        Uses the verified push payload's file lists, confirmed against the
        exact-SHA checkout. Skips honestly when there is no push evidence
        or no exact commit to bind it to.
        """
        from app.changeintel.push_intel import analyze_push_checkout
        from app.database.repositories import ProposalRepository
        from app.services.workspace import deployment_workspace

        target_sha = _exact_sha_or_none(record.target_revision)
        if not target_sha:
            await self._emit(
                deployment_id,
                EventType.SYSTEM_MESSAGE,
                "Change-intelligence analysis skipped: no exact commit to bind.",
                stage=StageId.ANALYZE.value,
                metadata={
                    "simple": "Change-intelligence analysis skipped (no exact commit).",
                    "technical": "phase2b=skipped · reason=no_exact_sha",
                },
            )
            return None
        try:
            proposal = ProposalRepository(db_path=self.repo.db_path).get_by_deployment(
                deployment_id
            )
        except Exception:  # noqa: BLE001 - advisory only
            proposal = None
        push = (proposal.push if proposal is not None else None) or {}
        files = push.get("files") if isinstance(push.get("files"), list) else []
        if not files:
            await self._emit(
                deployment_id,
                EventType.SYSTEM_MESSAGE,
                "Change-intelligence analysis skipped: push event carried no file list.",
                stage=StageId.ANALYZE.value,
                metadata={
                    "simple": "Change-intelligence analysis skipped (empty push).",
                    "technical": "phase2b=skipped · reason=no_push_files",
                },
            )
            return None
        checkout = deployment_workspace(deployment_id) / "repo"
        if not checkout.is_dir():
            await self._emit(
                deployment_id,
                EventType.SYSTEM_MESSAGE,
                "Change-intelligence analysis skipped: checkout missing.",
                stage=StageId.ANALYZE.value,
                level="warning",
                metadata={
                    "simple": "Change-intelligence analysis could not run.",
                    "technical": "phase2b=skipped · reason=checkout_missing",
                },
            )
            return None
        try:
            info = await asyncio.to_thread(
                analyze_push_checkout,
                repository_url=record.repository_url,
                base_sha=record.base_revision,
                target_sha=target_sha,
                files=files,
                checkout_path=checkout,
                deployment_id=deployment_id,
            )
        except Exception as exc:  # noqa: BLE001 - advisory only, never block pipeline
            logger.warning("Push change intel failed: %s", type(exc).__name__)
            return None
        risk_value = info.risk.level.value
        stored = info.model_dump(mode="json")
        stored["deployment_id"] = deployment_id
        self.repo.save_artifacts(
            deployment_id, change_intel=stored, updated_at=utc_now_iso()
        )
        await self._emit(
            deployment_id,
            EventType.SYSTEM_MESSAGE,
            f"Change intelligence: {len(info.changeset.files)} file(s) from push "
            f"{target_sha[:8]}, {info.risk.level.value.upper()} risk, "
            f"{len(info.requirements)} requirement(s).",
            stage=StageId.ANALYZE.value,
            metadata={
                "simple": (
                    "MEDHA verified the pushed files against the exact commit "
                    f"(risk={risk_value})."
                ),
                "technical": (
                    f"phase2b=push_intel · target={target_sha[:8]} · "
                    f"files={len(info.changeset.files)} · "
                    f"unverified={len(info.changeset.unsupported_files)} · "
                    f"nodes={len(info.graph.nodes)} · edges={len(info.graph.edges)} · "
                    f"risk={risk_value} · requirements={len(info.requirements)}"
                ),
                "change_intel": info.to_ui(),
            },
        )
        if delay:
            await asyncio.sleep(delay * 0.5)
        return info

    async def _renegotiate_after_replan(
        self,
        *,
        deployment_id: str,
        constraints: list,
        replan_count: int,
    ):
        """Re-run deterministic CNP after a replan round.

        Replanning must not bypass negotiation: the (possibly changed)
        constraint set is re-negotiated and the refreshed artifacts are
        returned as (negotiation, final_constraints, ui_constraints,
        ui_negotiation). Returns None when re-negotiation leaves no clean
        set — the caller then fails closed without executing.
        """
        await self._agent_start(
            deployment_id, "mediator",
            f"Re-negotiating constraints (replan round {replan_count}).")
        from app.core.perf import stage as _renego_timer

        with _renego_timer("renegotiate", deployment_id=deployment_id) as renego_timer:
            renegotiated = run_cnp(deployment_id, constraints, is_demo=False)
        self._record_timing("renegotiate", renego_timer.elapsed)
        await self._agent_done(
            deployment_id, "mediator",
            f"CNP re-run after replan round {replan_count}: {renegotiated.status}.",
            ok=renegotiated.status == "resolved")
        ui_constraints = [c.to_ui() for c in renegotiated.final_constraints]
        ui_negotiation = renegotiated.to_ui()
        await self._emit(
            deployment_id,
            EventType.NEGOTIATION_STARTED,
            f"CNP re-run after replan round {replan_count}: {renegotiated.status}.",
            stage=StageId.VERIFY.value,
            metadata={
                "simple": "MEDHA re-checked negotiated constraints after replanning.",
                "technical": (
                    f"cnp.rerun=true · replan.round={replan_count} · "
                    f"status={renegotiated.status} · "
                    f"rounds={renegotiated.rounds_used}"
                ),
                "constraints": ui_constraints,
                "negotiation": ui_negotiation,
                "replan": {"round": replan_count, "cnp_rerun": True},
            },
            include_agents=True,
        )
        if renegotiated.status != "resolved":
            return None
        return (
            renegotiated,
            list(renegotiated.final_constraints),
            ui_constraints,
            ui_negotiation,
        )

    async def _fail_replan_stopped(
        self,
        *,
        deployment_id: str,
        reason: str,
        fix_report: dict,
        verification,
        constraints_resolved: int,
    ) -> None:
        """Fail closed when replanning cannot proceed honestly.

        Used when no supported fix exists, a fix would repeat, or the plan
        did not meaningfully change — burning further rounds would only
        delay the honest failure. Never invokes the executor.
        """
        message = f"Bounded replan stopped: {reason} Execution blocked."
        await self._fail(
            deployment_id,
            message,
            technical=f"replan.stopped={reason}",
            result={
                "kind": "failed",
                "title": "FAILED",
                "final_status": "failed",
                "message": message,
                "durationLabel": "verify",
                "servicesLabel": "0 / 0 started",
                "verificationScore": verification.score if verification else None,
                "constraintsResolved": constraints_resolved,
                "rollbackScope": None,
                "phase": PHASE_LABEL,
                "is_demo": False,
                "replan": {
                    "applied": fix_report.get("applied", []),
                    "rejected": fix_report.get("rejected", []),
                },
            },
        )

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
        change_intel=None,
        repository_intelligence: dict | None = None,
        plan_only: bool = False,
        expected_plan_hash: str | None = None,
        proposal_id: str | None = None,
        ai_ctx: dict | None = None,
        acquisition=None,
        requested_ref: str | None = None,
        resolved_sha: str | None = None,
    ) -> None:
        settings = get_settings()
        max_rounds = settings.max_verify_rounds
        final_constraints = list(negotiation.final_constraints)
        replan_count = 0
        # Signatures of already-applied replan fixes: a round that would
        # repeat one (or change nothing) stops instead of looping.
        applied_fix_sigs: set = set()
        verification = None
        critic = None
        # CIG → verification: surface change-impact requirements in the gate.
        change_requirements: list[dict] | None = None
        change_risk: str | None = None
        if change_intel is not None:
            try:
                dumped = change_intel.model_dump(mode="json")
                change_requirements = dumped.get("requirements")
                risk = dumped.get("risk") or {}
                change_risk = risk.get("level")
            except Exception:  # noqa: BLE001 - advisory only, never block pipeline
                change_requirements, change_risk = None, None

        intent_l = (intent or "").lower()
        force_fail_env = "force verification failure" in intent_l or "missing env" in intent_l
        fail_service = None
        if "partial failure" in intent_l or "backend fail" in intent_l:
            fail_service = "backend"

        while True:
            if self._cancel_observed(deployment_id):
                await self._note_cancelled(deployment_id, "verify")
                return
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
                include_agents=True,
            )
            await self._agent_start(
                deployment_id, "verifier",
                f"Verification round {replan_count + 1}.")

            from app.core.perf import stage as _verify_timer

            # Verifier/critic are pure in-process deterministic functions:
            # bounded by construction, so no timeout is applied — the cancel
            # check above is the honest bound. Timings are still recorded.
            with _verify_timer("verify", deployment_id=deployment_id) as verify_timer:
                verification = run_verifier(
                    deployment_id=deployment_id,
                    profile=profile,
                    constraints=final_constraints,
                    negotiation=negotiation,
                    config_fragments=config_fragments,
                    replan_count=replan_count,
                    force_fail_env=force_fail_env and replan_count == 0,
                    is_demo=False,
                    change_requirements=change_requirements,
                    change_risk=change_risk,
                )
            self._record_timing("verify", verify_timer.elapsed)
            await self._agent_done(
                deployment_id, "verifier",
                f"Verification {'passed' if verification.passed else 'failed'} "
                f"(round {replan_count + 1}).",
                ok=verification.passed)
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
                    include_agents=True,
                )
                await self._agent_start(
                    deployment_id, "critic", "Scoring the failed verification.")
                with _verify_timer("critic", deployment_id=deployment_id) as critic_timer:
                    critic = run_critic(
                        deployment_id=deployment_id,
                        profile=profile,
                        constraints=final_constraints,
                        negotiation=negotiation,
                        verification=verification,
                        config_fragments=config_fragments,
                    )
                self._record_timing("critic", critic_timer.elapsed)
                await self._agent_done(
                    deployment_id, "critic", critic.summary,
                    ok=critic.recommendation != CriticRecommendation.ESCALATE)
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
                    # Validated deterministic fixes only: supported patches are
                    # applied, everything else is rejected with reasons, and
                    # repeats/no-ops stop the loop instead of burning rounds.
                    fixed, fix_report = _apply_replan_fixes(
                        config_fragments, verification, final_constraints
                    )
                    fix_sig = tuple(
                        sorted(
                            (f.get("kind"), f.get("key"))
                            for f in fix_report["applied"]
                        )
                    )
                    if (
                        (not fix_report["applied"] and fix_report["rejected"])
                        or not fix_report["plan_changed"]
                        or fix_sig in applied_fix_sigs
                    ):
                        reason = (
                            "no supported fix for the blocking checks"
                            if not fix_report["applied"]
                            else (
                                "replan produced no new plan change"
                                if not fix_report["plan_changed"]
                                else "replan would repeat an ineffective fix"
                            )
                        )
                        await self._fail_replan_stopped(
                            deployment_id=deployment_id,
                            reason=reason,
                            fix_report=fix_report,
                            verification=verification,
                            constraints_resolved=constraints_resolved,
                        )
                        return
                    applied_fix_sigs.add(fix_sig)
                    config_fragments = fixed
                    force_fail_env = False
                    # Replanning must not bypass negotiation: re-run CNP over
                    # the current constraint set before re-verification.
                    rerun = await self._renegotiate_after_replan(
                        deployment_id=deployment_id,
                        constraints=final_constraints,
                        replan_count=replan_count,
                    )
                    if rerun is None:
                        await self._fail(
                            deployment_id,
                            "Constraint re-negotiation after replan failed. "
                            "Execution blocked.",
                            technical=(
                                f"cnp.rerun=not_resolved · "
                                f"replan.round={replan_count}"
                            ),
                            result={
                                "kind": "failed",
                                "title": "FAILED",
                                "final_status": "failed",
                                "message": "Constraint re-negotiation after replan "
                                "left no clean set. Execution blocked.",
                                "durationLabel": "verify",
                                "servicesLabel": "0 / 0 started",
                                "verificationScore": verification.score,
                                "constraintsResolved": constraints_resolved,
                                "rollbackScope": None,
                                "phase": PHASE_LABEL,
                                "is_demo": False,
                            },
                        )
                        return
                    (
                        negotiation,
                        final_constraints,
                        ui_constraints,
                        ui_negotiation,
                    ) = rerun
                    constraints_resolved = len(negotiation.decisions)
                    await self._emit(
                        deployment_id,
                        EventType.REPLAN_COMPLETED,
                        "Replan applied corrected configuration fixtures.",
                        stage=StageId.VERIFY.value,
                        metadata={
                            "simple": "Corrected configuration prepared for re-verification.",
                            "technical": f"replan.round={replan_count} · fix=env_present",
                            "replan": {
                                "round": replan_count,
                                "max_rounds": max_rounds,
                                "applied": fix_report["applied"],
                                "rejected": fix_report["rejected"],
                            },
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
                    "timings": self._result_timings(),
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
                self.tracker.fail_remaining(error=result["message"][:200])
                if run_control.claim_terminal(deployment_id):
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
                        include_agents=True,
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
                include_agents=True,
            )
            await self._stage(deployment_id, StageId.VERIFY, "completed", delay * 0.2)

            await self._agent_start(
                deployment_id, "critic", "Scoring the negotiated plan.")
            with _verify_timer("critic", deployment_id=deployment_id) as pass_critic_timer:
                critic = run_critic(
                    deployment_id=deployment_id,
                    profile=profile,
                    constraints=final_constraints,
                    negotiation=negotiation,
                    verification=verification,
                    config_fragments=config_fragments,
                )
            self._record_timing("critic", pass_critic_timer.elapsed)
            await self._agent_done(
                deployment_id, "critic", critic.summary,
                ok=critic.recommendation != CriticRecommendation.ESCALATE)
            ui_critic = critic.to_ui()
            self.repo.save_artifacts(
                deployment_id, critic=ui_critic, verification=ui_verification, updated_at=utc_now_iso()
            )
            await self._ai_assist(
                deployment_id,
                "critic_assist",
                {"verification": ui_verification, "critic": ui_critic},
                ai_ctx,
                stage=StageId.VERIFY.value,
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
                include_agents=True,
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
                fixed, fix_report = _apply_replan_fixes(
                    config_fragments, verification, final_constraints
                )
                fix_sig = tuple(
                    sorted(
                        (f.get("kind"), f.get("key")) for f in fix_report["applied"]
                    )
                )
                if (
                    (not fix_report["applied"] and fix_report["rejected"])
                    or not fix_report["plan_changed"]
                    or fix_sig in applied_fix_sigs
                ):
                    reason = (
                        "no supported fix for the blocking checks"
                        if not fix_report["applied"]
                        else (
                            "replan produced no new plan change"
                            if not fix_report["plan_changed"]
                            else "replan would repeat an ineffective fix"
                        )
                    )
                    await self._fail_replan_stopped(
                        deployment_id=deployment_id,
                        reason=reason,
                        fix_report=fix_report,
                        verification=verification,
                        constraints_resolved=constraints_resolved,
                    )
                    return
                applied_fix_sigs.add(fix_sig)
                config_fragments = fixed
                # Critic-driven replans re-negotiate too: no path may reach
                # execution without a freshly negotiated constraint set.
                rerun = await self._renegotiate_after_replan(
                    deployment_id=deployment_id,
                    constraints=final_constraints,
                    replan_count=replan_count,
                )
                if rerun is None:
                    await self._fail(
                        deployment_id,
                        "Constraint re-negotiation after critic replan failed. "
                        "Execution blocked.",
                        technical=(
                            f"cnp.rerun=not_resolved · "
                            f"replan.round={replan_count} · source=critic"
                        ),
                        result={
                            "kind": "failed",
                            "title": "FAILED",
                            "final_status": "failed",
                            "message": "Constraint re-negotiation after critic "
                            "replan left no clean set. Execution blocked.",
                            "durationLabel": "verify",
                            "servicesLabel": "0 / 0 started",
                            "verificationScore": verification.score,
                            "constraintsResolved": constraints_resolved,
                            "rollbackScope": None,
                            "phase": PHASE_LABEL,
                            "is_demo": False,
                        },
                    )
                    return
                (
                    negotiation,
                    final_constraints,
                    ui_constraints,
                    ui_negotiation,
                ) = rerun
                constraints_resolved = len(negotiation.decisions)
                await self._emit(
                    deployment_id,
                    EventType.REPLAN_COMPLETED,
                    "Critic-driven replan applied.",
                    stage=StageId.VERIFY.value,
                    metadata={
                        "simple": "Corrected configuration prepared for re-verification.",
                        "technical": f"replan.round={replan_count} · source=critic",
                        "replan": {
                            "round": replan_count,
                            "max_rounds": max_rounds,
                            "applied": fix_report["applied"],
                            "rejected": fix_report["rejected"],
                            "source": "critic",
                        },
                    },
                )
                continue

            await self._ai_assist(
                deployment_id,
                "review_brief",
                {
                    "verification": ui_verification,
                    "critic": critic.to_ui() if critic else None,
                    "negotiation": ui_negotiation,
                    "risk": change_risk,
                },
                ai_ctx,
                stage=StageId.VERIFY.value,
            )
            break

        # EXECUTE — real topology only. No synthetic services are ever
        # injected: the plan reflects the actual discovered service topology.
        exec_plan = build_execution_plan(
            deployment_id=deployment_id,
            profile=profile,
            constraints=final_constraints,
            config_fragments=config_fragments,
            fail_service=fail_service,
            is_demo=False,
        )
        synthetic_services: list[str] = []
        expanded_to_canonical = False

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
                "simple": ("MEDHA built the causal execution graph before running actions."),
                "technical": (f"nodes={len(ceg.nodes)} · edges={len(ceg.edges)}"),
                "graph": ceg.to_ui(),
                "synthetic_services": [],
                "expanded_to_canonical": False,
            },
        )
        self.repo.save_artifacts(deployment_id, graph=ceg.to_ui(), updated_at=utc_now_iso())

        _sha_record = self.repo.get(deployment_id)
        canonical_plan = _canonical_plan(
            exec_plan,
            repository_url=_sha_record.repository_url if _sha_record else None,
            # Bind the resolved immutable SHA (not the moving ref) so a
            # moved branch/tag invalidates previously approved plans.
            target_sha=resolved_sha
            or _exact_sha_or_none(_sha_record.target_revision if _sha_record else None),
        )
        canonical_plan["requested_ref"] = requested_ref
        plan_digest = _plan_hash(canonical_plan)
        if expected_plan_hash and expected_plan_hash != plan_digest:
            await self._fail(
                deployment_id,
                "Refusing to execute: the recomputed plan no longer matches the approved proposal.",
                technical="STALE_PLAN",
            )
            return
        # Recheck source identity immediately before execution and retries:
        # a moved branch/tag since ingestion must invalidate the run.
        if requested_ref and resolved_sha and not _exact_sha_or_none(requested_ref):
            try:
                from app.services.git_service import resolve_ref_to_sha as _r2s

                fresh = _r2s(
                    _sha_record.repository_url if _sha_record else "",
                    requested_ref,
                )
            except Exception as exc:  # noqa: BLE001 - fail closed
                await self._fail(
                    deployment_id,
                    f"Source revalidation failed for '{requested_ref}': "
                    f"{getattr(exc, 'message', exc)}",
                    technical=f"git.{getattr(exc, 'code', 'SOURCE_RECHECK_FAILED')}",
                )
                return
            if fresh != resolved_sha:
                await self._fail(
                    deployment_id,
                    f"Source moved during approval: '{requested_ref}' now resolves to "
                    f"{fresh[:12]} (approved {resolved_sha[:12]}). Re-plan required.",
                    technical="STALE_SOURCE",
                )
                return
        # Verified-checkout recheck: HEAD must still equal the approved SHA.
        if resolved_sha and acquisition is not None:
            try:
                from app.services.git_service import _run_git as _git_run

                head = _git_run(["-C", str(acquisition.path), "rev-parse", "HEAD"]).lower()
                if head != resolved_sha and acquisition.method == "shallow_clone":
                    await self._fail(
                        deployment_id,
                        "Checked-out HEAD does not match the approved commit.",
                        technical="SHA_MISMATCH",
                    )
                    return
            except Exception as exc:  # noqa: BLE001 - local check; shallow clones only
                if getattr(exc, "code", "") in {"SHA_MISMATCH"}:
                    await self._fail(
                        deployment_id, str(getattr(exc, "message", exc)),
                        technical="SHA_MISMATCH",
                    )
                    return
        if self._cancel_observed(deployment_id):
            await self._note_cancelled(deployment_id, "execute_gate")
            return
        if plan_only:
            await self._pause_for_approval(
                deployment_id, canonical_plan, plan_digest, proposal_id, ai_ctx
            )
            return

        # Explicit real-execution mode: build + run the supported app profile
        # through the isolated RealExecutor (blocking readiness gate). Never
        # falls back to simulation — structured failure instead.
        _settings = get_settings()
        _real_requested = (
            _settings.docker_execute
            and (_settings.executor_mode or "auto").lower() in {"real", "docker"}
        )
        if _real_requested and acquisition is not None:
            await self._run_real_execute(
                deployment_id=deployment_id,
                profile=profile,
                exec_plan=exec_plan,
                ceg=ceg,
                acquisition=acquisition,
                requested_ref=requested_ref,
                resolved_sha=resolved_sha,
                canonical_plan=canonical_plan,
                plan_digest=plan_digest,
                verification=verification,
                critic=critic,
                constraints_resolved=constraints_resolved,
                delay=delay,
                ai_ctx=ai_ctx,
                synthetic_services=synthetic_services,
                expanded_to_canonical=expanded_to_canonical,
                repository_intelligence=repository_intelligence,
            )
            return

        # Execution readiness is evaluated at the stage boundary — before the
        # run claims execution has started — so an unsupported attempt is
        # reported as a configuration block with a stable reason code, never
        # as an ordinary runtime failure. Analysis, CNP, and verification
        # have already completed and their artifacts stay recorded either way.
        readiness = assess_execution_readiness(_settings)
        if readiness["status"] != "ready" or readiness["mode"] != "simulator":
            _code = readiness["reason_code"]
            _short_message = {
                EXECUTION_DISABLED_HOSTED: "Execution is disabled on the hosted control plane.",
                EXECUTION_NOT_CONFIGURED: "Execution is not configured for genuine deployment.",
            }.get(_code, readiness["message"])
            await self._fail(
                deployment_id,
                readiness["message"],
                technical=_code,
                result={
                    "kind": "failed",
                    "title": _code,
                    "final_status": "failed",
                    "message": _short_message,
                    "durationLabel": "verify",
                    "servicesLabel": "0 / 0 started",
                    "verificationScore": critic.score if critic else None,
                    "constraintsResolved": constraints_resolved,
                    "rollbackScope": None,
                    "phase": PHASE_LABEL,
                    "is_demo": False,
                    "code": _code,
                    "execution_mode": "unconfigured",
                    "repository_intelligence": repository_intelligence,
                    # Structured block markers: the execution stage never ran,
                    # upstream analysis/verification results remain valid.
                    "blocked": True,                    "blocked_stage": "execute",
                    "readiness": readiness,
                    "analysis_preserved": True,
                    "verification_preserved": verification is not None,
                    "repository_url": _sha_record.repository_url if _sha_record else None,
                    "target_sha": resolved_sha,
                    "requested_ref": requested_ref,
                    "plan": canonical_plan,
                    "plan_hash": plan_digest,
                },
            )
            return

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

        # Executor race guard: cancellation observed here wins — the
        # executor is never invoked after a cancel, and completion paths
        # below re-check terminal state before persisting success.
        if self._cancel_observed(deployment_id):
            await self._note_cancelled(deployment_id, "executor_gate")
            return
        await self._agent_start(
            deployment_id, "executor", "Starting gated execution.")
        executor = choose_executor(is_demo=False, prefer_docker=False)

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

        with _verify_timer("execute", deployment_id=deployment_id) as execute_timer:
            graph, exec_result, scope = await executor.execute(exec_plan, ceg, on_event=on_event)
        self._record_timing("execute", execute_timer.elapsed)

        # A cancel that landed during execution wins: no rollback handling,
        # no success persistence, no terminal overwrite from this path.
        if self._cancel_observed(deployment_id):
            await self._agent_done(
                deployment_id, "executor", "Execution superseded by cancellation.",
                ok=False, status="cancelled", error="cancel_requested")
            await self._note_cancelled(deployment_id, "execution")
            return

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
                ai=_ai_rollup(ai_ctx["notes"]) if ai_ctx and ai_ctx.get("notes") else None,
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
            await self._agent_done(
                deployment_id, "executor",
                f"Execution {exec_result.status}; scoped rollback engaged.",
                ok=False)
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
            await self._agent_start(
                deployment_id, "rollback", "Applying scoped rollback.")
            await self._emit(
                deployment_id,
                EventType.ROLLBACK_STARTED,
                "Scoped rollback started.",
                stage=StageId.RECOVER.value,
                metadata={"simple": scope.rationale, "technical": f"scope={scope.nodes_to_rollback}"},
                include_agents=True,
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
                include_agents=True,
            )
            await self._agent_done(
                deployment_id, "rollback",
                "SCOPED ROLLBACK COMPLETE" if rollback_ok else "ROLLBACK FAILED",
                ok=rollback_ok)
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
                include_agents=True,
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
            result["timings"] = self._result_timings()
            if self._current_status(deployment_id) == DeploymentStatus.CANCELLED.value:
                logger.info(
                    "Dropping late rollback terminal for cancelled run deployment_id=%s",
                    deployment_id,
                )
                return
            self.repo.save_artifacts(
                deployment_id,
                graph=graph.to_ui(),
                rollback=ui_scope,
                verification=verification.to_ui() if verification else None,
                critic=critic.to_ui() if critic else None,
                result=result,
                ai=_ai_rollup(ai_ctx["notes"]) if ai_ctx and ai_ctx.get("notes") else None,
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
            if run_control.claim_terminal(deployment_id):
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
                    include_agents=True,
                )
            return

        await self._agent_done(
            deployment_id, "executor", "Execution completed successfully.")
        self.tracker.finish("rollback", "skipped",
                            activity="Rollback not required")
        await self._stage(deployment_id, StageId.EXECUTE, "completed", delay * 0.2)
        message = "Deployment completed successfully."
        result = exec_result.to_deployment_result(
            verification_score=critic.score if critic else None,
            constraints_resolved=constraints_resolved,
            rollback_scope=None,
            message=message,
        )
        result["phase"] = PHASE_LABEL
        result["timings"] = self._result_timings()
        result["execution_mode"] = "controlled_test" if exec_result.executor == "docker" else exec_result.executor
        result["synthetic_services"] = []
        result["expanded_to_canonical"] = False
        result["repository_url"] = _sha_record.repository_url if _sha_record else None
        result["target_sha"] = resolved_sha or _exact_sha_or_none(
            _sha_record.target_revision if _sha_record else None
        )
        result["requested_ref"] = requested_ref
        result["plan"] = canonical_plan
        result["plan_hash"] = plan_digest
        if self._current_status(deployment_id) == DeploymentStatus.CANCELLED.value:
            logger.info(
                "Dropping late success terminal for cancelled run deployment_id=%s",
                deployment_id,
            )
            return
        self.repo.save_artifacts(
            deployment_id,
            graph=graph.to_ui(),
            rollback=None,
            verification=verification.to_ui() if verification else None,
            critic=critic.to_ui() if critic else None,
            result=result,
            ai=_ai_rollup(ai_ctx["notes"]) if ai_ctx and ai_ctx.get("notes") else None,
            updated_at=utc_now_iso(),
        )
        self._status(
            deployment_id,
            DeploymentStatus.COMPLETED,
            StageId.COMPLETE,
            message,
            f"final_status=succeeded · phase={PHASE_LABEL}",
        )
        if run_control.claim_terminal(deployment_id):
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
                include_agents=True,
            )

    async def _run_real_execute(
        self,
        *,
        deployment_id: str,
        profile,
        exec_plan,
        ceg,
        acquisition,
        requested_ref: str | None,
        resolved_sha: str | None,
        canonical_plan: dict[str, Any],
        plan_digest: str,
        verification,
        critic,
        constraints_resolved: int,
        delay: float,
        ai_ctx: dict | None,
        synthetic_services: list[str],
        expanded_to_canonical: bool,
        repository_intelligence: dict | None = None,
    ) -> None:
        """Real application build + run through the isolated RealExecutor."""
        from app.ceg.rollback import apply_scope_to_graph, compute_rollback_scope
        from app.execution.policy import PolicyViolation
        from app.execution.real_executor import RealExecutor
        from app.models.execution import NodeStatus

        settings = get_settings()
        self._status(
            deployment_id,
            DeploymentStatus.RUNNING,
            StageId.EXECUTE,
            "MEDHA is building and running the application in the isolated runtime.",
            "stage=EXECUTE · executor=real",
        )
        if self._cancel_observed(deployment_id):
            await self._note_cancelled(deployment_id, "real_execute")
            return
        await self._stage(deployment_id, StageId.EXECUTE, "started", delay * 0.2)
        await self._agent_start(
            deployment_id, "executor", "Building in the isolated runtime.")
        await self._emit(
            deployment_id,
            EventType.EXECUTION_STARTED,
            "Real execution started (isolated builder).",
            stage=StageId.EXECUTE.value,
            metadata={
                "simple": "MEDHA is building the application image in the isolated runtime.",
                "technical": f"executor=real · resolved_sha={resolved_sha}",
                "graph": ceg.to_ui(),
            },
            include_agents=True,
        )
        target_port = profile.target_port
        # Scoped execution: build the selected application subdirectory, not
        # the repo root, when a deployment target was chosen.
        checkout = acquisition.path
        try:
            _target = (profile.inferred_stack.selected_target or "").strip()
            if _target and _target != ".":
                _scoped = acquisition.path / _target
                if _scoped.is_dir() and acquisition.path in list(_scoped.parents):
                    checkout = _scoped
        except Exception:
            checkout = acquisition.path
        try:
            real = RealExecutor()
            outcome = await real.deploy(
                deployment_id=deployment_id,
                checkout=checkout,
                target_port=target_port,
                readiness_timeout=settings.real_readiness_timeout_seconds,
                build_timeout=settings.real_build_timeout_seconds,
                # Pin execution to the analyzed commit SHA — never deploy a
                # newer revision than the one that was analyzed/verified.
                commit_sha=resolved_sha,
            )
        except PolicyViolation as exc:
            await self._fail(
                deployment_id,
                exc.message,
                technical=exc.code,
                result={
                    "kind": "failed", "title": exc.code, "final_status": "failed",
                    "message": exc.message, "execution_mode": "real",
                    "requested_ref": requested_ref, "target_sha": resolved_sha,
                    "plan": canonical_plan, "plan_hash": plan_digest,
                    "phase": PHASE_LABEL, "is_demo": False, "code": exc.code,
                    "repository_intelligence": repository_intelligence,
                },
            )
            return

        base_provenance = {
            "execution_mode": "real",
            "requested_ref": requested_ref,
            "target_sha": resolved_sha,
            "repository_url": (lambda r: r.repository_url if r else None)(
                self.repo.get(deployment_id)
            ),
            "profile": outcome.profile,
            "image": outcome.image,
            "image_digest": outcome.image_digest,
            "container": outcome.container,
            "port": outcome.port,
            "readiness": outcome.readiness,
            "runtime_spec": outcome.runtime_spec or None,
            "plan": canonical_plan,
            "plan_hash": plan_digest,
            "phase": PHASE_LABEL,
            "is_demo": False,
            "repository_intelligence": repository_intelligence,
        }
        if outcome.ok:
            # Mark CEG app nodes success with real provenance.
            nodes = []
            for node in ceg.nodes:
                updated = node.model_copy(deep=True)
                if updated.status == NodeStatus.PENDING.value:
                    updated.status = NodeStatus.SUCCESS.value
                    updated.metadata = {
                        **updated.metadata,
                        "container": outcome.container,
                        "image_digest": outcome.image_digest,
                        "readiness": outcome.readiness,
                    }
                nodes.append(updated)
            ceg_out = ceg.model_copy(update={"nodes": nodes})
            result = {
                "kind": "success", "title": "SUCCESS", "final_status": "succeeded",
                "message": (
                    f"Application is live on port {outcome.port} "
                    f"(profile={outcome.profile}, readiness=ready)."
                ),
                "durationLabel": "real",
                "servicesLabel": f"1 / 1 healthy ({outcome.profile})",
                "verificationScore": critic.score if critic else None,
                "constraintsResolved": constraints_resolved,
                "rollbackScope": None,
                **base_provenance,
            }
            self.repo.save_artifacts(
                deployment_id, graph=ceg_out.to_ui(),
                verification=verification.to_ui() if verification else None,
                critic=critic.to_ui() if critic else None,
                result=result,
                ai=_ai_rollup(ai_ctx["notes"]) if ai_ctx and ai_ctx.get("notes") else None,
                updated_at=utc_now_iso(),
            )
            # Close the EXECUTE stage in the persisted log: without this the
            # stage reads "running" forever while the run is terminal.
            await self._stage(deployment_id, StageId.EXECUTE, "completed", delay * 0.2)
            self._status(
                deployment_id, DeploymentStatus.COMPLETED, StageId.COMPLETE,
                result["message"], f"final_status=succeeded · executor=real",
            )
            await self._emit(
                deployment_id, EventType.DEPLOYMENT_COMPLETED, result["message"],
                stage=StageId.COMPLETE.value, status=DeploymentStatus.COMPLETED.value,
                metadata={"simple": result["message"],
                          "technical": f"executor=real · digest={outcome.image_digest}",
                          "result": result, "graph": ceg_out.to_ui()},
            )
            return

        # Failure: clean up the failed workload, record CEG-scoped rollback.
        try:
            await RealExecutor().cleanup(
                deployment_id=deployment_id, container=outcome.container,
                image=outcome.image,
            )
        except Exception:  # noqa: BLE001 - cleanup best effort
            pass
        failed_id = ceg.nodes[0].node_id if ceg.nodes else "n_unknown"
        nodes_map = {n.node_id: n.model_copy(deep=True) for n in ceg.nodes}
        if failed_id in nodes_map:
            nodes_map[failed_id].status = NodeStatus.FAILED.value
            nodes_map[failed_id].reason = outcome.message[:500]
        tmp_graph = ceg.model_copy(update={"nodes": list(nodes_map.values())})
        try:
            scope = compute_rollback_scope(tmp_graph, failed_id, is_demo=False)
            graph_out = apply_scope_to_graph(tmp_graph, scope)
            ui_scope = scope.to_ui()
        except Exception:  # noqa: BLE001 - observability only
            graph_out, ui_scope = tmp_graph, None
        result = {
            "kind": "failed", "title": outcome.code or "FAILED",
            "final_status": "failed", "message": outcome.message,
            "durationLabel": "real", "servicesLabel": "0 / 1 healthy",
            "verificationScore": critic.score if critic else None,
            "constraintsResolved": constraints_resolved,
            "rollbackScope": None, "code": outcome.code,
            **base_provenance,
        }
        self.repo.save_artifacts(
            deployment_id, graph=graph_out.to_ui(), rollback=ui_scope,
            verification=verification.to_ui() if verification else None,
            critic=critic.to_ui() if critic else None,
            result=result,
            ai=_ai_rollup(ai_ctx["notes"]) if ai_ctx and ai_ctx.get("notes") else None,
            updated_at=utc_now_iso(),
        )
        # Close the EXECUTE stage as failed in the persisted log so the
        # pipeline agrees with the terminal FAILED status (a failed
        # readiness check after real execution stays a failure here).
        # RECOVER needs no stage event: no rollback container work runs on
        # this path (failed workload is cleaned up above); the persisted
        # rollback scope artifact records the recovery outcome instead.
        await self._stage(
            deployment_id, StageId.EXECUTE, "completed", 0,
            status="failed",
        )
        await self._fail(
            deployment_id, outcome.message,
            technical=f"executor=real · code={outcome.code}",
            result=result,
        )

    async def _pause_for_approval(
        self,
        deployment_id: str,
        canonical_plan: dict[str, Any],
        plan_digest: str,
        proposal_id: str | None,
        ai_ctx: dict | None,
    ) -> None:
        """End a plan-only run: persist the plan, notify, wait for a human."""
        self._persist_ai(deployment_id, ai_ctx)
        result = {
            "kind": "plan_awaiting_approval",
            "title": "AWAITING APPROVAL",
            "final_status": DeploymentStatus.AWAITING_APPROVAL.value,
            "message": "Verified plan ready — waiting for human approval before execution.",
            "plan_hash": plan_digest,
            "plan": canonical_plan,
            "phase": PHASE_LABEL,
            "is_demo": False,
        }
        self.repo.save_artifacts(
            deployment_id, result=result, updated_at=utc_now_iso()
        )
        self._status(
            deployment_id,
            DeploymentStatus.AWAITING_APPROVAL,
            StageId.COMPLETE,
            "Verified plan ready — waiting for human approval before execution.",
            f"plan_hash={plan_digest[:12]} · proposal={proposal_id}",
        )
        await self._emit(
            deployment_id,
            EventType.PROPOSAL_READY,
            "Plan ready — waiting for human approval.",
            stage=StageId.COMPLETE.value,
            status=DeploymentStatus.AWAITING_APPROVAL.value,
            metadata={
                "simple": "The verified plan is ready for human review. Nothing will execute until approved.",
                "technical": f"plan_hash={plan_digest} · proposal={proposal_id}",
                "plan_hash": plan_digest,
                "plan": canonical_plan,
                "proposal_id": proposal_id,
                "result": result,
            },
            include_agents=True,
        )
        if proposal_id:
            try:
                from app.database.repositories import ProposalRepository

                ProposalRepository(db_path=self.repo.db_path).update(
                    proposal_id,
                    status="ready",
                    deployment_id=deployment_id,
                    plan_hash=plan_digest,
                    plan=canonical_plan,
                )
            except Exception:  # noqa: BLE001 - proposal link is bookkeeping
                logger.exception("Proposal ready-update failed proposal=%s", proposal_id)

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
        *,
        status: str | None = None,
    ) -> None:
        et = EventType.STAGE_STARTED if kind == "started" else EventType.STAGE_COMPLETED
        resolved = status or ("running" if kind == "started" else "success")
        await self._emit(
            deployment_id,
            et,
            f"{stage.value} {kind}",
            stage=stage.value,
            status=resolved,
            metadata={
                "simple": f"Stage {stage.value} {kind}.",
                "technical": f"stage={stage.value} · event={et.value}",
                "pipeline": {
                    stage.value: {
                        "status": resolved,
                        "detail": kind,
                    }
                },
            },
            include_agents=True,
        )
        if delay > 0:
            await asyncio.sleep(delay)

    async def _agent_start(
        self,
        deployment_id: str,
        agent: str,
        activity: str,
    ) -> None:
        """Record a real agent start (emitted at the true boundary)."""
        tracker = getattr(self, "tracker", None)
        row = None
        if tracker is not None:
            tracker.start(agent, activity)
            row = tracker.snapshot_row(agent) if hasattr(tracker, "snapshot_row") else None
        await self._emit(
            deployment_id,
            EventType.AGENT_STARTED,
            f"{agent} started",
            metadata={
                "agent": agent,
                "simple": activity,
                "technical": f"agent={agent} · transition=running",
                **({"agent_state": row} if row is not None else {}),
            },
            include_agents=True,
        )

    async def _agent_done(
        self,
        deployment_id: str,
        agent: str,
        summary: str,
        *,
        ok: bool = True,
        status: str | None = None,
        error: str | None = None,
    ) -> None:
        """Record a real agent completion with measured duration."""
        tracker = getattr(self, "tracker", None)
        row = None
        if tracker is not None:
            tracker.finish(agent, status or ("complete" if ok else "failed"),
                           activity=summary, error=error)
            row = tracker.snapshot_row(agent) if hasattr(tracker, "snapshot_row") else None
        await self._emit(
            deployment_id,
            EventType.AGENT_COMPLETED,
            summary,
            status="success" if (status or ("complete" if ok else "failed")) == "complete" else "failed",
            metadata={
                "agent": agent,
                "simple": summary,
                "technical": (
                    f"agent={agent} · transition={status or ('complete' if ok else 'failed')}"
                    + (f" · duration_ms={row['durationMs']}" if row and row.get("durationMs") is not None else "")
                ),
                **({"agent_state": row} if row is not None else {}),
            },
            include_agents=True,
        )

    async def _fail(
        self,
        deployment_id: str,
        message: str,
        *,
        technical: str,
        result: dict | None = None,
    ) -> None:
        # Late-result guard: a cancelled/completed run must never be flipped
        # to failed by a racing stage (cancellation always wins the race).
        # update_status refuses terminal overwrites as a second line of defense.
        current_status = self._current_status(deployment_id)
        if current_status is not None and current_status in {
            DeploymentStatus.CANCELLED.value,
            DeploymentStatus.COMPLETED.value,
            DeploymentStatus.PARTIAL_RECOVERY.value,
            DeploymentStatus.AWAITING_APPROVAL.value,
        }:
            logger.info(
                "Dropping late failure for terminal run deployment_id=%s status=%s",
                deployment_id,
                current_status,
            )
            return
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
        payload.setdefault("timings", self._result_timings())
        tracker = getattr(self, "tracker", None)
        if tracker is not None:
            tracker.fail_remaining(error=message[:200])
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
        if run_control.claim_terminal(deployment_id):
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
                include_agents=True,
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
        include_agents: bool = False,
    ) -> None:
        meta = dict(metadata or {})
        if include_agents and "agents" not in meta:
            tracker = getattr(self, "tracker", None)
            if tracker is not None:
                meta["agents"] = tracker.snapshot()
        event = make_event(
            deployment_id=deployment_id,
            event_type=event_type,
            message=message,
            stage=stage,
            status=status,
            level=level,
            metadata={**meta, "is_demo": False},
            is_demo=False,
        )
        self.repo.add_event(event)
        await event_bus.publish(event)


_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]{1,63}$")


async def _read_commit_evidence(record, acquisition, sha: str, reader):
    """Read SHA-addressed git evidence from the pinned checkout first.

    Local-archive checkouts are `git archive` exports without .git metadata;
    fall back to the operator's local source repo for the same SHA (a commit
    SHA is content-addressed, so the evidence is identical). Remote shallow
    clones carry .git and serve directly. Raises HistoryError when neither
    has the commit — the caller reports unavailable honestly.
    """
    from app.services import history_service as _hs
    from app.services.workspace import resolve_local_repo_path

    try:
        return await asyncio.to_thread(reader, acquisition.path, sha)
    except _hs.HistoryError:
        source = resolve_local_repo_path(getattr(record, "repository_url", "") or "")
        if source is None or source == acquisition.path:
            raise
        return await asyncio.to_thread(reader, Path(source), sha)


def _fragment_hash(fragments: dict) -> str:
    """Stable hash of the replan-mutable plan surface (compose + env refs)."""
    canonical = {
        "compose": (fragments.get("docker") or {}).get("compose_fragment") or {},
        "env_present": fragments.get("env_present") or {},
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _apply_replan_fixes(
    config_fragments: dict, verification, constraints: list | None = None
) -> tuple[dict, dict]:
    """Validated deterministic replan patches (no LLM).

    Returns (fixed_fragments, report) where report holds `applied`,
    `rejected` (with safe reasons), and `plan_changed`. Only `inject_env`
    is supported by the real pipeline: a required ENV_VAR key missing from
    every compose service is provided as a `${KEY}` reference (never an
    inline secret value). All other failures are rejected explicitly —
    security-sensitive and structural settings are never patched.
    """
    fixed = {
        **config_fragments,
        "docker": {**(config_fragments.get("docker") or {})},
        "env_present": {**(config_fragments.get("env_present") or {})},
    }
    applied: list[dict] = []
    rejected: list[dict] = []
    try:
        checks = list(verification.checks or [])
    except AttributeError:
        checks = []

    required_keys: list[str] = []
    for c in constraints or []:
        try:
            is_env = c.type.value == "ENV_VAR"
            key = (c.payload or {}).get("key")
            required = bool((c.payload or {}).get("required"))
            active = c.status.value != "rejected"
        except AttributeError:
            continue
        if is_env and required and active and isinstance(key, str) and _ENV_KEY_RE.match(key):
            if key not in required_keys:
                required_keys.append(key)

    from app.models.execution import CheckStatus

    env_failed = any(
        getattr(ch, "id", "") == "env" and ch.status == CheckStatus.FAIL for ch in checks
    )
    if env_failed and required_keys:
        compose = fixed["docker"].get("compose_fragment") or {"services": {}}
        services = dict(compose.get("services") or {})
        for key in required_keys:
            targets: list[str] = []
            for name, svc in list(services.items()):
                if not isinstance(svc, dict):
                    continue
                env = svc.get("environment") or {}
                if isinstance(env, dict):
                    present = key in env
                elif isinstance(env, list):
                    present = any(str(item).startswith(f"{key}=") for item in env)
                else:
                    present = False
                if not present:
                    env = dict(env) if isinstance(env, dict) else {}
                    env[key] = "${" + key + "}"
                    svc = {**svc, "environment": env}
                    services[name] = svc
                targets.append(name)
            fixed["env_present"][key] = True
            applied.append(
                {"kind": "inject_env", "key": key, "services": targets, "rule": "ENV-001"}
            )
        fixed["docker"]["compose_fragment"] = {**compose, "services": services}
    elif env_failed:
        rejected.append(
            {
                "kind": "inject_env",
                "key": None,
                "reason": "ENV-001 failed but no required ENV_VAR constraint names a key",
            }
        )

    blocking_rules = {
        (getattr(ch, "id", ""), getattr(ch, "rule", ""))
        for ch in checks
        if ch.status == CheckStatus.FAIL and str(getattr(ch, "message", "")).strip()
    }
    for check_id, rule in sorted(blocking_rules):
        if check_id == "env":
            continue
        rejected.append(
            {
                "kind": "none",
                "check": check_id,
                "rule": rule,
                "reason": (
                    f"no supported automated fix for {rule or check_id}; "
                    "bounded replan stops instead of guessing"
                ),
            }
        )

    report = {
        "applied": applied,
        "rejected": rejected,
        "plan_changed": _fragment_hash(fixed) != _fragment_hash(config_fragments),
    }
    return fixed, report


def schedule_planning_pipeline(
    deployment_id: str,
    *,
    create_task: Callable = asyncio.create_task,
    repo: DeploymentRepository | None = None,
    plan_only: bool = False,
    expected_plan_hash: str | None = None,
    proposal_id: str | None = None,
):
    pipeline = PlanningPipeline(repo=repo)
    return create_task(
        pipeline.run(
            deployment_id,
            plan_only=plan_only,
            expected_plan_hash=expected_plan_hash,
            proposal_id=proposal_id,
        )
    )
