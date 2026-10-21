"""Durable job worker (Phase 4).

The database (jobs table) is the source of truth. The worker is the single
owner of webhook-triggered analysis: it claims a job, runs the real plan-only
pipeline for the job's deployment, and only then marks the job succeeded or
failed. A job is never reported successful without its analysis and
persistence having completed.

V1 runs a single in-process worker (asyncio task) suitable for the
one-FastAPI-process deployment. Multi-replica coordination is NOT claimed:
deploy exactly one backend replica for webhook-driven analysis.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from app.core.enums import DeploymentStatus
from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import (
    DeploymentRepository,
    JobRepository,
    ProposalRepository,
)

logger = get_logger(__name__)

_worker_task: asyncio.Task | None = None
_stop = asyncio.Event()


def enqueue_job(*, repository: str, branch: str, target_sha: str,
                base_sha: str | None = None, project_id: str | None = None,
                delivery_id: str | None = None,
                deployment_id: str | None = None,
                db_path=None) -> dict | None:
    """Persist a job idempotently and wake the worker. Returns job or None."""
    repo = JobRepository(db_path=db_path)
    job = repo.create(
        job_id=f"job_{uuid4().hex[:16]}",
        repository=repository, branch=branch, target_sha=target_sha,
        base_sha=base_sha, project_id=project_id, delivery_id=delivery_id,
        deployment_id=deployment_id, created_at=utc_now_iso(),
    )
    if job is not None:
        try:
            # Ordering counter is `seq` on SQLite, `seq_num` on Postgres
            # (where `seq` is the row surrogate). Prefer the counter key.
            keep = job.get("seq_num", job.get("seq", 0))
            repo.cancel_queued_superseded(
                repository=repository, branch=branch, keep_seq=int(keep))
        except Exception:
            pass
    return job


_DONE_OK = (
    DeploymentStatus.AWAITING_APPROVAL,
    DeploymentStatus.COMPLETED,
    DeploymentStatus.PARTIAL_RECOVERY,
)


def _settle_proposal(proposal_id: str | None, record, db_path=None) -> None:
    """Mirror the deployment outcome onto its proposal (bookkeeping only)."""
    if not proposal_id or record is None:
        return
    proposals = ProposalRepository(db_path=db_path)
    try:
        if record.status in (DeploymentStatus.AWAITING_APPROVAL,):
            proposals.update(proposal_id, status="ready", deployment_id=record.deployment_id)
        elif record.status in (DeploymentStatus.COMPLETED, DeploymentStatus.PARTIAL_RECOVERY):
            proposals.update(proposal_id, status="executed", execution_id=record.deployment_id)
        elif record.status == DeploymentStatus.FAILED:
            proposals.update(proposal_id, status="failed")
    except Exception:  # noqa: BLE001 - bookkeeping must never raise
        logger.exception("Proposal settle failed proposal=%s", proposal_id)


async def _process_one(job: dict, db_path=None) -> None:
    """Run the real plan-only analysis for one claimed job, then settle it.

    The worker owns the analysis: the job is marked succeeded only after the
    pipeline has completed and its artifacts are persisted. A failure or crash
    leaves the job failed/requeued — never a false success.
    """
    jobs = JobRepository(db_path=db_path)
    job_id = job["job_id"]
    deployment_id = job.get("deployment_id")
    if not deployment_id:
        # A job without an execution target records the push only.
        jobs.finish(job_id, ok=True, updated_at=utc_now_iso())
        return

    deployments = DeploymentRepository(db_path=db_path)
    record = deployments.get(deployment_id)
    if record is None:
        jobs.finish(job_id, ok=False, error="deployment-missing",
                    updated_at=utc_now_iso())
        return
    proposal = ProposalRepository(db_path=db_path).get_by_deployment(deployment_id)
    proposal_id = proposal.proposal_id if proposal is not None else None

    # Idempotency: if analysis already produced a terminal/awaiting state
    # (e.g. this job was requeued after a crash), do not run it twice.
    if record.status in _DONE_OK:
        _settle_proposal(proposal_id, record, db_path)
        jobs.finish(job_id, ok=True, updated_at=utc_now_iso())
        return
    if record.status == DeploymentStatus.FAILED:
        _settle_proposal(proposal_id, record, db_path)
        jobs.finish(job_id, ok=False, error=record.error_summary or "analysis-failed",
                    updated_at=utc_now_iso())
        return

    try:
        from app.workflow.planning import PlanningPipeline

        await PlanningPipeline(repo=deployments).run(
            deployment_id, plan_only=True, proposal_id=proposal_id
        )
    except Exception as exc:  # noqa: BLE001 - bounded retry via finish(ok=False)
        jobs.finish(job_id, ok=False, error=type(exc).__name__,
                    updated_at=utc_now_iso())
        return

    record = deployments.get(deployment_id)
    _settle_proposal(proposal_id, record, db_path)
    if record is not None and record.status in _DONE_OK:
        jobs.finish(job_id, ok=True, updated_at=utc_now_iso())
    else:
        jobs.finish(
            job_id, ok=False,
            error=(record.error_summary if record is not None else "deployment-missing")
            or "analysis-incomplete",
            updated_at=utc_now_iso(),
        )


async def _loop(db_path=None, poll_seconds: float = 2.0) -> None:
    repo = JobRepository(db_path=db_path)
    try:
        recovered = repo.recover_interrupted(
            updated_at=utc_now_iso(), error="worker-restart")
        if recovered:
            logger.info("Job worker recovered %d interrupted job(s)", recovered)
    except Exception as exc:  # noqa: BLE001 - worker must not crash boot
        logger.warning("Job recovery failed: %s", type(exc).__name__)
    while not _stop.is_set():
        try:
            job = await asyncio.to_thread(repo.claim_next)
            if job is None:
                await asyncio.sleep(poll_seconds)
                continue
            await _process_one(job, db_path)
        except asyncio.CancelledError:
            break
        except Exception as exc:  # noqa: BLE001 - worker loop is infallible
            logger.warning("Job worker iteration failed: %s", type(exc).__name__)
            await asyncio.sleep(poll_seconds)


def start_worker(db_path=None) -> None:
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    _stop.clear()
    _worker_task = loop.create_task(_loop(db_path))


async def stop_worker() -> None:
    _stop.set()
    global _worker_task
    if _worker_task is not None:
        _worker_task.cancel()
        try:
            await _worker_task
        except (asyncio.CancelledError, Exception):
            pass
        _worker_task = None
