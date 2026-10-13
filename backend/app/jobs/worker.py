"""Durable job worker (Phase 4).

The database (jobs table) is the source of truth; this module only wakes
workers. V1 runs a single in-process worker (asyncio task) suitable for the
one-FastAPI-process deployment. Multi-replica coordination is NOT claimed:
deploy exactly one backend replica for webhook-driven analysis.
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import JobRepository

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
            repo.cancel_queued_superseded(
                repository=repository, branch=branch, keep_seq=int(job.get("seq", 0)))
        except Exception:
            pass
    return job


async def _process_one(job: dict, db_path=None) -> None:
    """Execute one claimed job: currently marks intent; heavy pipeline runs
    through the existing proposal/deployment path keyed by deployment_id."""
    repo = JobRepository(db_path=db_path)
    try:
        # The proposal/deployment pipeline is scheduled by the webhook path
        # with the same deployment_id; the job row tracks ordering/dedup.
        # If no deployment was attached, the job still records the push.
        repo.finish(job["job_id"], ok=True, updated_at=utc_now_iso())
    except Exception as exc:  # noqa: BLE001 - bounded retry via finish(ok=False)
        repo.finish(job["job_id"], ok=False, error=type(exc).__name__,
                    updated_at=utc_now_iso())


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
