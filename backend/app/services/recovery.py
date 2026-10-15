"""Startup reconciliation for interrupted workflows (no new infrastructure).

At boot, no pipeline task exists, so any deployment left in a non-terminal
status (queued/started/running) is orphaned by definition, as is any
proposal stuck before `ready`. This module fails such rows closed with an
honest reason and a terminal event — it never invents success and never
executes anything:

- deployments in queued/started/running → `failed` (+ `deployment.failed`
  event so SSE replay terminates honestly);
- proposals in pending/analyzing/approved/executing → `failed`
  (analysis/execution tasks do not survive restart; READY proposals are
  preserved and stay approvable because their plan is fully persisted).

The updates are conditional (only non-terminal rows match), so re-running
is a no-op and two starters cannot double-recover the same row.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.enums import DeploymentStatus, EventType, ProposalStatus
from app.core.events import make_event, utc_now_iso
from app.core.logging import get_logger
from app.database.connection import get_connection, resolve_backend, translate_sql
from app.database.repositories import DeploymentRepository

logger = get_logger(__name__)

INTERRUPTED_ERROR = (
    "Interrupted by service restart: the analysis/execution task did not "
    "survive the restart and no outcome was recorded."
)

_ORPHAN_DEPLOYMENT_STATUSES = (
    DeploymentStatus.QUEUED.value,
    DeploymentStatus.STARTED.value,
    DeploymentStatus.RUNNING.value,
)

_ORPHAN_PROPOSAL_STATUSES = (
    ProposalStatus.PENDING.value,
    ProposalStatus.ANALYZING.value,
    ProposalStatus.APPROVED.value,
    ProposalStatus.EXECUTING.value,
)


def _placeholders(values: tuple[str, ...]) -> str:
    return ", ".join(["?"] * len(values))


def _sql(sql: str, db_path: Path | None) -> str:
    """Translate `?` placeholders only for the Postgres backend."""
    if resolve_backend(db_path) == "postgres":
        return translate_sql(sql)
    return sql


def reconcile_interrupted(db_path: Path | None = None) -> dict[str, int]:
    """Fail orphaned deployments/proposals closed. Returns counts."""
    counts = {"deployments": 0, "proposals": 0, "events": 0}
    now = utc_now_iso()
    with get_connection(db_path) as conn:
        rows = conn.execute(
            _sql(
                "SELECT deployment_id, is_demo FROM deployments "
                f"WHERE status IN ({_placeholders(_ORPHAN_DEPLOYMENT_STATUSES)})",
                db_path,
            ),
            _ORPHAN_DEPLOYMENT_STATUSES,
        ).fetchall()
        orphaned = [
            (row["deployment_id"], bool(row["is_demo"])) for row in rows
        ]
        if orphaned:
            cursor = conn.execute(
                _sql(
                    "UPDATE deployments SET status = ?, error_summary = ?, "
                    f"updated_at = ? WHERE status IN ({_placeholders(_ORPHAN_DEPLOYMENT_STATUSES)})",
                    db_path,
                ),
                (
                    DeploymentStatus.FAILED.value,
                    INTERRUPTED_ERROR,
                    now,
                    *_ORPHAN_DEPLOYMENT_STATUSES,
                ),
            )
            try:
                counts["deployments"] = int(cursor.rowcount or 0)
            except (TypeError, ValueError):
                counts["deployments"] = len(orphaned)
        cursor = conn.execute(
            _sql(
                "UPDATE proposals SET status = ? "
                f"WHERE status IN ({_placeholders(_ORPHAN_PROPOSAL_STATUSES)})",
                db_path,
            ),
            (ProposalStatus.FAILED.value, *_ORPHAN_PROPOSAL_STATUSES),
        )
        try:
            counts["proposals"] = int(cursor.rowcount or 0)
        except (TypeError, ValueError):
            counts["proposals"] = 0
        conn.commit()

    repo = DeploymentRepository(db_path)
    for deployment_id, is_demo in orphaned:
        try:
            event = make_event(
                deployment_id=deployment_id,
                event_type=EventType.DEPLOYMENT_FAILED,
                message=INTERRUPTED_ERROR,
                stage="COMPLETE",
                status=DeploymentStatus.FAILED.value,
                level="error",
                metadata={
                    "simple": INTERRUPTED_ERROR,
                    "technical": "recovery=startup_reconcile",
                },
                is_demo=is_demo,
            )
            repo.add_event(event)
            counts["events"] += 1
        except Exception:  # noqa: BLE001 - bookkeeping must never raise
            logger.exception("Recovery event failed deployment=%s", deployment_id)
    if counts["deployments"] or counts["proposals"]:
        logger.info(
            "Startup recovery reconciled deployments=%d proposals=%d",
            counts["deployments"],
            counts["proposals"],
        )
    # Reclaim abandoned local state without touching live successes:
    # stale workspaces are removed; MEDHA-labelled Docker resources are only
    # reported (successful deployments stay alive until explicit teardown).
    try:
        from app.services.workspace import prune_stale_workspaces

        counts["workspaces_pruned"] = int(prune_stale_workspaces())
    except Exception:  # noqa: BLE001 - bookkeeping must never raise
        logger.exception("Recovery workspace prune failed")
    try:
        from app.execution import docker_ops

        if docker_ops.docker_daemon_running():
            import subprocess as _sp

            _out = _sp.run(
                ["docker", "ps", "-a", "--filter", "label=com.medha.managed=true",
                 "--format", "{{.Names}}"],
                capture_output=True, text=True, timeout=15,
            )
            if _out.returncode == 0:
                _names = [n.strip() for n in (_out.stdout or "").splitlines() if n.strip()]
                counts["labelled_containers_observed"] = len(_names)
                if _names:
                    logger.info("Recovery observed MEDHA-labelled containers: %s", _names[:10])
    except Exception:  # noqa: BLE001 - bookkeeping must never raise
        logger.exception("Recovery container observation failed")
    return counts


def recovery_summary(result: dict[str, Any]) -> str:
    return (
        f"reconciled deployments={result.get('deployments', 0)} "
        f"proposals={result.get('proposals', 0)}"
    )
