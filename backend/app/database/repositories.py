from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.enums import DeployMode, DeploymentStatus, ScenarioId
from app.database.connection import get_connection, resolve_backend
from app.models.deployment import DeploymentRecord, ProjectRecord, ProposalRecord
from app.models.events import SystemEvent


def _loads(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so repository filters match literally."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _is_unique_violation(exc: Exception) -> bool:
    import sqlite3

    if isinstance(exc, sqlite3.IntegrityError):
        return True
    name = type(exc).__name__
    return "UniqueViolation" in name or "unique" in str(exc).lower()


class DeploymentRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def create(self, record: DeploymentRecord) -> DeploymentRecord:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO deployments (
                    deployment_id, repository_url, mode, scenario,
                    target_host, target_port, intent, base_revision, target_revision,
                    status, current_stage,
                    explain_simple, explain_technical, error_summary,
                    result_json, constraints_json, negotiation_json,
                    verification_json, critic_json, graph_json, rollback_json,
                    change_intel_json, ai_json, owner_sub, project_id, is_demo, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.deployment_id,
                    record.repository_url,
                    record.mode.value,
                    record.scenario.value if record.scenario else None,
                    record.target_host,
                    record.target_port,
                    record.intent,
                    record.base_revision,
                    record.target_revision,
                    record.status.value,
                    record.current_stage,
                    record.explain_simple,
                    record.explain_technical,
                    record.error_summary,
                    json.dumps(record.result) if record.result is not None else None,
                    json.dumps(record.constraints) if record.constraints is not None else None,
                    json.dumps(record.negotiation) if record.negotiation is not None else None,
                    json.dumps(record.verification) if record.verification is not None else None,
                    json.dumps(record.critic) if record.critic is not None else None,
                    json.dumps(record.graph) if record.graph is not None else None,
                    json.dumps(record.rollback) if record.rollback is not None else None,
                    json.dumps(record.change_intel)
                    if record.change_intel is not None
                    else None,
                    json.dumps(record.ai) if record.ai is not None else None,
                    record.owner_sub,
                    record.project_id,
                    1 if record.is_demo else 0,
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()
        return record

    def get(self, deployment_id: str) -> DeploymentRecord | None:
        import time as _time

        from app.core.perf import timed_db

        _t0 = _time.perf_counter()
        try:
            with get_connection(self.db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM deployments WHERE deployment_id = ?",
                    (deployment_id,),
                ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)
        finally:
            timed_db("get", _t0)

    def list(
        self,
        *,
        status: str | None = None,
        mode: str | None = None,
        repository: str | None = None,
        owner_sub: str | None = None,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[DeploymentRecord], int]:
        """List deployments ordered newest-first with optional filters."""
        where: list[str] = []
        params: list[Any] = []
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if mode is not None:
            where.append("mode = ?")
            params.append(mode)
        if repository is not None and repository.strip():
            where.append("repository_url LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(repository.strip())}%")
        if owner_sub is not None:
            where.append("owner_sub = ?")
            params.append(owner_sub)
        if project_id is not None:
            where.append("project_id = ?")
            params.append(project_id)
        clause = (f" WHERE {' AND '.join(where)}") if where else ""
        params_count = list(params)

        import time as _time

        from app.core.perf import timed_db

        _t0 = _time.perf_counter()
        try:
            with get_connection(self.db_path) as conn:
                # AS count: sqlite3.Row and psycopg dict rows both expose the
                # alias by name; positional [0] only works on sqlite3.Row.
                total = conn.execute(
                    f"SELECT COUNT(*) AS count FROM deployments{clause}", params_count
                ).fetchone()["count"]
                rows = conn.execute(
                    f"""
                    SELECT * FROM deployments{clause}
                    ORDER BY rowid DESC
                    LIMIT ? OFFSET ?
                    """,
                    (*params, limit, offset),
                ).fetchall()
            return [self._row_to_record(row) for row in rows], int(total)
        finally:
            timed_db("list", _t0)

    def update_status(
        self,
        deployment_id: str,
        *,
        status: DeploymentStatus | None = None,
        current_stage: str | None = None,
        explain_simple: str | None = None,
        explain_technical: str | None = None,
        error_summary: str | None = None,
        updated_at: str,
        allowed_from: set[str] | None = None,
    ) -> DeploymentRecord | None:
        from app.core.enums import DeploymentStatus as _DS

        terminal = {
            _DS.COMPLETED.value,
            _DS.FAILED.value,
            _DS.CANCELLED.value,
        }
        new_status = status or None  # resolved after guard read below

        with get_connection(self.db_path) as conn:
            # Atomic conditional transition: a single UPDATE whose WHERE
            # clause refuses to overwrite terminal states and enforces
            # allowed_from. No read-then-write race; rowcount decides.
            where = ["deployment_id = ?"]
            params: list[Any] = []
            if new_status is not None:
                where.append(
                    "(status NOT IN ('completed', 'failed', 'cancelled') OR status = ?)"
                )
                params.append(new_status.value)
            if allowed_from is not None:
                where.append(
                    f"status IN ({', '.join(['?'] * len(allowed_from))})"
                )
                params.extend(sorted(allowed_from))
            # Fetch current values for unchanged-field merge inside the same
            # transaction boundary (single connection, immediate write).
            row = conn.execute(
                "SELECT status, current_stage, explain_simple, explain_technical,"
                " error_summary FROM deployments WHERE deployment_id = ?",
                (deployment_id,),
            ).fetchone()
            if row is None:
                return None
            current = {key: row[key] for key in row.keys()}
            if (
                new_status is not None
                and current["status"] in terminal
                and current["status"] != new_status.value
            ):
                return self.get(deployment_id)
            if allowed_from is not None and current["status"] not in allowed_from:
                return self.get(deployment_id)
            final_status = new_status.value if new_status else current["status"]
            cursor = conn.execute(
                f"""
                UPDATE deployments
                SET status = ?, current_stage = ?, explain_simple = ?,
                    explain_technical = ?, error_summary = ?, updated_at = ?
                WHERE {' AND '.join(where)}
                """,
                (
                    final_status,
                    current_stage if current_stage is not None else current["current_stage"],
                    explain_simple if explain_simple is not None else current["explain_simple"],
                    explain_technical
                    if explain_technical is not None
                    else current["explain_technical"],
                    error_summary if error_summary is not None else current["error_summary"],
                    updated_at,
                    deployment_id,
                    *params,
                ),
            )
            conn.commit()
            try:
                if int(cursor.rowcount or 0) == 0:
                    # Lost a race (state moved under us) — return fresh truth.
                    pass
            except (TypeError, ValueError):
                pass
        return self.get(deployment_id)

    def save_artifacts(
        self,
        deployment_id: str,
        *,
        constraints: list[dict[str, Any]] | None = None,
        negotiation: dict[str, Any] | None = None,
        verification: dict[str, Any] | None = None,
        critic: dict[str, Any] | None = None,
        graph: dict[str, Any] | None = None,
        rollback: dict[str, Any] | None = None,
        result: dict[str, Any] | None = None,
        change_intel: dict[str, Any] | None = None,
        ai: dict[str, Any] | None = None,
        updated_at: str,
    ) -> DeploymentRecord | None:
        import time as _time

        from app.core.perf import timed_db

        _t0 = _time.perf_counter()
        try:
            # Update only explicitly provided columns: callers pass exactly
            # what changed, so unchanged JSON blobs are never re-serialized
            # or rewritten. rollback=None keeps prior value (clear via sentinel
            # not supported in V1 — matches prior behavior).
            updates: dict[str, Any] = {}
            if constraints is not None:
                updates["constraints_json"] = json.dumps(constraints)
            if negotiation is not None:
                updates["negotiation_json"] = json.dumps(negotiation)
            if verification is not None:
                updates["verification_json"] = json.dumps(verification)
            if critic is not None:
                updates["critic_json"] = json.dumps(critic)
            if graph is not None:
                updates["graph_json"] = json.dumps(graph)
            if rollback is not None:
                updates["rollback_json"] = json.dumps(rollback)
            if result is not None:
                updates["result_json"] = json.dumps(result)
            if change_intel is not None:
                updates["change_intel_json"] = json.dumps(change_intel)
            if ai is not None:
                updates["ai_json"] = json.dumps(ai)
            if not updates:
                return self.get(deployment_id)
            set_clause = ", ".join(f"{col} = ?" for col in updates) + ", updated_at = ?"
            with get_connection(self.db_path) as conn:
                cursor = conn.execute(
                    f"UPDATE deployments SET {set_clause} WHERE deployment_id = ?",
                    (*updates.values(), updated_at, deployment_id),
                )
                conn.commit()
                if int(cursor.rowcount or 0) == 0:
                    return None
            return self.get(deployment_id)
        finally:
            timed_db("save_artifacts", _t0)

    def add_event(self, event: SystemEvent) -> SystemEvent:
        import time as _time

        from app.core.perf import timed_db

        _t0 = _time.perf_counter()
        try:
            with get_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO events (
                        event_id, deployment_id, event_type, ts, stage,
                        message, status, level, is_demo, data_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event.event_id,
                        event.deployment_id,
                        event.event_type,
                        event.ts,
                        event.stage,
                        event.message,
                        event.status,
                        event.level,
                        1 if event.is_demo else 0,
                        json.dumps(event.data),
                    ),
                )
                conn.commit()
            return event
        finally:
            timed_db("add_event", _t0)

    def list_events(
        self,
        deployment_id: str,
        limit: int = 500,
        *,
        after_event_id: str | None = None,
    ) -> list[SystemEvent]:
        import time as _time

        from app.core.perf import timed_db

        _t0 = _time.perf_counter()
        try:
            limit = max(1, min(int(limit), 500))
            with get_connection(self.db_path) as conn:
                after_rowid: int | None = None
                if after_event_id:
                    row = conn.execute(
                        "SELECT rowid AS rid FROM events WHERE event_id = ? AND deployment_id = ?",
                        (after_event_id, deployment_id),
                    ).fetchone()
                    if row is not None:
                        try:
                            after_rowid = int(row["rid"])
                        except (KeyError, TypeError, ValueError):
                            after_rowid = None
                    else:
                        # Unknown cursor: caller holds stale state — return
                        # everything up to limit rather than nothing.
                        after_rowid = None
                if after_rowid is not None:
                    rows = conn.execute(
                        """
                        SELECT * FROM events
                        WHERE deployment_id = ? AND rowid > ?
                        ORDER BY rowid ASC
                        LIMIT ?
                        """,
                        (deployment_id, after_rowid, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM events
                        WHERE deployment_id = ?
                        ORDER BY rowid ASC
                        LIMIT ?
                        """,
                        (deployment_id, limit),
                    ).fetchall()
            return [self._row_to_event(row) for row in rows]
        finally:
            timed_db("list_events", _t0)

    @staticmethod
    def _row_to_record(row: Any) -> DeploymentRecord:
        keys = set(row.keys())
        return DeploymentRecord(
            deployment_id=row["deployment_id"],
            repository_url=row["repository_url"],
            mode=DeployMode(row["mode"]),
            scenario=ScenarioId(row["scenario"]) if row["scenario"] else None,
            target_host=row["target_host"],
            target_port=row["target_port"],
            intent=row["intent"],
            base_revision=row["base_revision"]
            if "base_revision" in keys
            else None,
            target_revision=row["target_revision"]
            if "target_revision" in keys
            else None,
            status=DeploymentStatus(row["status"]),
            current_stage=row["current_stage"],
            explain_simple=row["explain_simple"],
            explain_technical=row["explain_technical"],
            error_summary=row["error_summary"],
            result=_loads(row["result_json"], None) if "result_json" in keys else None,
            constraints=_loads(row["constraints_json"], None)
            if "constraints_json" in keys
            else None,
            negotiation=_loads(row["negotiation_json"], None)
            if "negotiation_json" in keys
            else None,
            verification=_loads(row["verification_json"], None)
            if "verification_json" in keys
            else None,
            critic=_loads(row["critic_json"], None) if "critic_json" in keys else None,
            graph=_loads(row["graph_json"], None) if "graph_json" in keys else None,
            rollback=_loads(row["rollback_json"], None)
            if "rollback_json" in keys
            else None,
            change_intel=_loads(row["change_intel_json"], None)
            if "change_intel_json" in keys
            else None,
            ai=_loads(row["ai_json"], None) if "ai_json" in keys else None,
            owner_sub=row["owner_sub"] if "owner_sub" in keys else None,
            project_id=row["project_id"] if "project_id" in keys else None,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_demo=bool(row["is_demo"]),
        )

    @staticmethod
    def _row_to_event(row: Any) -> SystemEvent:
        return SystemEvent(
            event_id=row["event_id"],
            deployment_id=row["deployment_id"],
            event_type=row["event_type"],
            ts=row["ts"],
            stage=row["stage"],
            message=row["message"],
            status=row["status"],
            level=row["level"],
            is_demo=bool(row["is_demo"]),
            data=json.loads(row["data_json"] or "{}"),
        )


class AccountRepository:
    """Minimal ownership store: Clerk subjects keyed by `sub` claim."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def upsert_user(self, clerk_sub: str, *, seen_at: str) -> None:
        with get_connection(self.db_path) as conn:
            if resolve_backend(self.db_path) == "postgres":
                conn.execute(
                    """
                    INSERT INTO users (clerk_sub, created_at, last_seen_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT (clerk_sub) DO UPDATE SET last_seen_at = ?
                    """,
                    (clerk_sub, seen_at, seen_at, seen_at),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO users (clerk_sub, created_at, last_seen_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT (clerk_sub) DO UPDATE SET last_seen_at = excluded.last_seen_at
                    """,
                    (clerk_sub, seen_at, seen_at),
                )
            conn.commit()

    def get_user(self, clerk_sub: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE clerk_sub = ?", (clerk_sub,)
            ).fetchone()
        if row is None:
            return None
        return {key: row[key] for key in row.keys()}


class ProposalRepository:
    """Webhook deliveries (idempotent) + approval proposals."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    # -- deliveries --------------------------------------------------------

    def record_delivery(
        self,
        *,
        delivery_id: str,
        repository: str,
        ref: str | None,
        sha: str | None,
        event: str,
        status: str,
        received_at: str,
        note: str | None = None,
    ) -> bool:
        """Insert a delivery; False when the delivery ID was already seen."""
        try:
            with get_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO webhook_deliveries (
                        delivery_id, source, repository, ref, sha, event,
                        status, received_at, note
                    ) VALUES (?, 'github', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (delivery_id, repository, ref, sha, event, status, received_at, note),
                )
                conn.commit()
        except Exception as exc:
            if _is_unique_violation(exc):
                return False
            raise
        return True

    def bind_delivery(self, delivery_id: str, proposal_id: str, status: str) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE webhook_deliveries SET proposal_id = ?, status = ? WHERE delivery_id = ?",
                (proposal_id, status, delivery_id),
            )
            conn.commit()

    def set_delivery_status(self, delivery_id: str, status: str) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE webhook_deliveries SET status = ? WHERE delivery_id = ?",
                (status, delivery_id),
            )
            conn.commit()

    # -- proposals ---------------------------------------------------------

    def create(self, proposal: ProposalRecord) -> ProposalRecord:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO proposals (
                    proposal_id, repository, branch, base_sha, target_sha,
                    deployment_id, plan_hash, plan_json, push_json, project_id,
                    status, created_by,
                    created_at, decided_by, decided_at, execution_id, idempotency_key
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.proposal_id,
                    proposal.repository,
                    proposal.branch,
                    proposal.base_sha,
                    proposal.target_sha,
                    proposal.deployment_id,
                    proposal.plan_hash,
                    json.dumps(proposal.plan) if proposal.plan is not None else None,
                    json.dumps(proposal.push) if proposal.push is not None else None,
                    proposal.project_id,
                    proposal.status,
                    proposal.created_by,
                    proposal.created_at,
                    proposal.decided_by,
                    proposal.decided_at,
                    proposal.execution_id,
                    proposal.idempotency_key,
                ),
            )
            conn.commit()
        return proposal

    def get(self, proposal_id: str) -> ProposalRecord | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE proposal_id = ?", (proposal_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    def get_by_deployment(self, deployment_id: str) -> ProposalRecord | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM proposals WHERE deployment_id = ? ORDER BY rowid DESC LIMIT 1",
                (deployment_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_proposal(row)

    def list(
        self,
        *,
        repository: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ProposalRecord], int]:
        where: list[str] = []
        params: list[Any] = []
        if repository:
            where.append("repository = ?")
            params.append(repository)
        if status:
            where.append("status = ?")
            params.append(status)
        if created_by:
            where.append("created_by = ?")
            params.append(created_by)
        if project_id:
            where.append("project_id = ?")
            params.append(project_id)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        with get_connection(self.db_path) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS count FROM proposals{clause}", list(params)
            ).fetchone()["count"]
            rows = conn.execute(
                f"SELECT * FROM proposals{clause} ORDER BY rowid DESC LIMIT ? OFFSET ?",
                (*params, limit, offset),
            ).fetchall()
        return [self._row_to_proposal(row) for row in rows], int(total)

    def update(
        self,
        proposal_id: str,
        *,
        status: str | None = None,
        deployment_id: str | None = None,
        plan_hash: str | None = None,
        plan: dict[str, Any] | None = None,
        push: dict[str, Any] | None = None,
        project_id: str | None = None,
        decided_by: str | None = None,
        decided_at: str | None = None,
        execution_id: str | None = None,
    ) -> ProposalRecord | None:
        current = self.get(proposal_id)
        if current is None:
            return None
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE proposals
                SET status = ?, deployment_id = ?, plan_hash = ?, plan_json = ?,
                    push_json = ?, project_id = ?,
                    decided_by = ?, decided_at = ?, execution_id = ?
                WHERE proposal_id = ?
                """,
                (
                    status or current.status,
                    deployment_id if deployment_id is not None else current.deployment_id,
                    plan_hash if plan_hash is not None else current.plan_hash,
                    json.dumps(plan)
                    if plan is not None
                    else (json.dumps(current.plan) if current.plan is not None else None),
                    json.dumps(push)
                    if push is not None
                    else (json.dumps(current.push) if current.push is not None else None),
                    project_id if project_id is not None else current.project_id,
                    decided_by if decided_by is not None else current.decided_by,
                    decided_at if decided_at is not None else current.decided_at,
                    execution_id if execution_id is not None else current.execution_id,
                    proposal_id,
                ),
            )
            conn.commit()
        return self.get(proposal_id)

    def supersede_older(
        self,
        *,
        repository: str,
        branch: str,
        except_proposal_id: str,
        project_id: str | None = None,
    ) -> int:
        """Mark older pending/ready proposals superseded. Returns count.

        Scoped to the same project binding so one owner's push never retires
        another owner's proposals: project-bound proposals only supersede
        rows with the same project_id; legacy (unbound) proposals only
        supersede other unbound rows.
        """
        with get_connection(self.db_path) as conn:
            if project_id is not None:
                cursor = conn.execute(
                    """
                    UPDATE proposals SET status = 'superseded'
                    WHERE repository = ? AND branch = ?
                      AND status IN ('pending', 'analyzing', 'ready')
                      AND proposal_id != ?
                      AND project_id = ?
                    """,
                    (repository, branch, except_proposal_id, project_id),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE proposals SET status = 'superseded'
                    WHERE repository = ? AND branch = ?
                      AND status IN ('pending', 'analyzing', 'ready')
                      AND proposal_id != ?
                      AND project_id IS NULL
                    """,
                    (repository, branch, except_proposal_id),
                )
            conn.commit()
            try:
                return int(cursor.rowcount or 0)
            except (TypeError, ValueError):
                return 0

    @staticmethod
    def _row_to_proposal(row: Any) -> ProposalRecord:
        keys = set(row.keys())
        return ProposalRecord(
            proposal_id=row["proposal_id"],
            repository=row["repository"],
            branch=row["branch"],
            base_sha=row["base_sha"],
            target_sha=row["target_sha"],
            deployment_id=row["deployment_id"],
            plan_hash=row["plan_hash"],
            plan=_loads(row["plan_json"], None),
            push=_loads(row["push_json"], None) if "push_json" in keys else None,
            project_id=row["project_id"] if "project_id" in keys else None,
            status=row["status"],
            created_by=row["created_by"],
            created_at=row["created_at"],
            decided_by=row["decided_by"],
            decided_at=row["decided_at"],
            execution_id=row["execution_id"],
            idempotency_key=row["idempotency_key"],
        )


class ProjectRepository:
    """Owner-scoped GitHub repository connections (no credentials stored)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def create(self, project: ProjectRecord) -> ProjectRecord:
        try:
            with get_connection(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO projects (
                        project_id, owner_sub, name, provider,
                        repo_owner, repo_name, repository, canonical_url,
                        branch, visibility, connection_status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project.project_id,
                        project.owner_sub,
                        project.name,
                        project.provider,
                        project.repo_owner,
                        project.repo_name,
                        project.repository,
                        project.canonical_url,
                        project.branch,
                        project.visibility,
                        project.connection_status,
                        project.created_at,
                        project.updated_at,
                    ),
                )
                conn.commit()
        except Exception as exc:
            if _is_unique_violation(exc):
                raise ProjectConflictError(
                    f"Repository '{project.repository}' is already connected "
                    "for this owner."
                ) from exc
            raise
        return project

    def get(self, project_id: str) -> ProjectRecord | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_project(row)

    def list_for_owner(self, owner_sub: str) -> list[ProjectRecord]:
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE owner_sub = ? ORDER BY rowid DESC",
                (owner_sub,),
            ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def has_any(self) -> bool:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM projects"
            ).fetchone()
        return int(row["count"]) > 0

    def find_connected_by_repo(self, repository: str) -> list[ProjectRecord]:
        """All connected projects for a repo full_name (multi-user safe).

        Matching is case-insensitive; disconnected/failed projects never
        route webhooks or runs.
        """
        with get_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT * FROM projects
                WHERE lower(repository) = lower(?)
                  AND connection_status = 'connected'
                """,
                (repository.strip(),),
            ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def update(
        self,
        project_id: str,
        *,
        name: str | None = None,
        branch: str | None = None,
        visibility: str | None = None,
        connection_status: str | None = None,
        updated_at: str,
    ) -> ProjectRecord | None:
        current = self.get(project_id)
        if current is None:
            return None
        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE projects
                SET name = ?, branch = ?, visibility = ?,
                    connection_status = ?, updated_at = ?
                WHERE project_id = ?
                """,
                (
                    name if name is not None else current.name,
                    branch if branch is not None else current.branch,
                    visibility if visibility is not None else current.visibility,
                    connection_status
                    if connection_status is not None
                    else current.connection_status,
                    updated_at,
                    project_id,
                ),
            )
            conn.commit()
        return self.get(project_id)

    def delete(self, project_id: str) -> bool:
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM projects WHERE project_id = ?", (project_id,)
            )
            conn.commit()
            try:
                return int(cursor.rowcount or 0) > 0
            except (TypeError, ValueError):
                return False

    @staticmethod
    def _row_to_project(row: Any) -> ProjectRecord:
        return ProjectRecord(
            project_id=row["project_id"],
            owner_sub=row["owner_sub"],
            name=row["name"],
            provider=row["provider"],
            repo_owner=row["repo_owner"],
            repo_name=row["repo_name"],
            repository=row["repository"],
            canonical_url=row["canonical_url"],
            branch=row["branch"],
            visibility=row["visibility"],
            connection_status=row["connection_status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


class ProjectConflictError(ValueError):
    """Duplicate (owner, repository) connection attempt (maps to 409)."""


_JOB_SEQ_SQL = "COALESCE((SELECT MAX(seq) FROM jobs WHERE repository = ? AND branch = ?), -1) + 1"


class JobRepository:
    """Durable commit-aware analysis jobs. The DB is the source of truth."""

    VALID = {"queued", "running", "succeeded", "failed", "cancelled", "superseded", "dead_letter"}

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def create(
        self, *, job_id: str, repository: str, branch: str, target_sha: str,
        base_sha: str | None = None, project_id: str | None = None,
        delivery_id: str | None = None, deployment_id: str | None = None,
        created_at: str,
    ) -> dict[str, Any] | None:
        """Idempotent insert. Returns the job dict, or None on duplicate delivery."""
        with get_connection(self.db_path) as conn:
            try:
                seq_row = conn.execute(
                    f"SELECT {_JOB_SEQ_SQL} AS seq", (repository, branch)
                ).fetchone()
                seq = int(seq_row["seq"] if seq_row else 0)
                conn.execute(
                    """INSERT INTO jobs (job_id, delivery_id, project_id, repository,
                        branch, base_sha, target_sha, seq, status, attempts,
                        max_attempts, deployment_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', 0, 3, ?, ?, ?)""",
                    (job_id, delivery_id, project_id, repository, branch,
                     base_sha, target_sha, seq, deployment_id, created_at, created_at),
                )
                conn.commit()
            except Exception as exc:
                if _is_unique_violation(exc):
                    return None
                raise
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return dict(row) if row else None

    def claim_next(self) -> dict[str, Any] | None:
        """Atomically claim the oldest queued job whose backoff has expired."""
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """SELECT * FROM jobs WHERE status = 'queued'
                   AND (not_before IS NULL OR not_before <= strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                   ORDER BY created_at ASC LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                    "UPDATE jobs SET status='running', attempts=attempts+1,"
                    " updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE job_id=? AND status='queued'",
                    (row["job_id"],),
                )
            conn.commit()
            updated = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (row["job_id"],)).fetchone()
        return dict(updated) if updated else None

    def finish(self, job_id: str, *, ok: bool, error: str | None = None,
               updated_at: str) -> None:
        with get_connection(self.db_path) as conn:
            row = conn.execute("SELECT attempts, max_attempts FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                return
            if ok:
                conn.execute(
                    "UPDATE jobs SET status='succeeded', last_error=NULL, updated_at=? WHERE job_id=?",
                    (updated_at, job_id),
                )
            elif int(row["attempts"]) >= int(row["max_attempts"]):
                conn.execute(
                    "UPDATE jobs SET status='dead_letter', last_error=?, updated_at=? WHERE job_id=?",
                    (error, updated_at, job_id),
                )
            else:
                backoff_min = min(2 ** int(row["attempts"]), 30)
                conn.execute(
                    "UPDATE jobs SET status='queued', last_error=?,"
                    " not_before=strftime('%Y-%m-%dT%H:%M:%fZ','now', ?), updated_at=? WHERE job_id=?",
                    (error, f"+{backoff_min} minutes", updated_at, job_id),
                )
            conn.commit()

    def cancel_queued_superseded(self, *, repository: str, branch: str, keep_seq: int) -> int:
        """Mark older queued jobs superseded when a newer push arrives."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='superseded' WHERE repository=? AND branch=?"
                " AND seq < ? AND status='queued'",
                (repository, branch, keep_seq),
            )
            conn.commit()
            try:
                return int(cursor.rowcount or 0)
            except (TypeError, ValueError):
                return 0

    def latest_for_branch(self, repository: str, branch: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE repository=? AND branch=? ORDER BY seq DESC LIMIT 1",
                (repository, branch),
            ).fetchone()
        return dict(row) if row else None

    def recover_interrupted(self, *, updated_at: str, error: str) -> int:
        """Requeue running jobs after a worker/backend restart (bounded retry)."""
        with get_connection(self.db_path) as conn:
            cursor = conn.execute(
                "UPDATE jobs SET status='queued', last_error=? , updated_at=? WHERE status='running'",
                (error, updated_at),
            )
            conn.commit()
            try:
                return int(cursor.rowcount or 0)
            except (TypeError, ValueError):
                return 0


class ScoreRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def save(self, *, run_id: str, score_name: str, value: float | None,
             version: str, computed_at: str, inputs_hash: str,
             target_sha: str, project_id: str | None,
             evidence: dict[str, Any]) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """INSERT INTO scores (run_id, score_name, value, value_null, version,
                    computed_at, inputs_hash, target_sha, project_id, evidence_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(run_id, score_name) DO UPDATE SET
                    value=excluded.value, value_null=excluded.value_null,
                    version=excluded.version, computed_at=excluded.computed_at,
                    inputs_hash=excluded.inputs_hash, target_sha=excluded.target_sha,
                    project_id=excluded.project_id, evidence_json=excluded.evidence_json""",
                (run_id, score_name, value, 1 if value is None else 0, version,
                 computed_at, inputs_hash, target_sha, project_id, json.dumps(evidence)),
            )
            conn.commit()

    def history(self, *, project_id: str | None = None, run_id: str | None = None,
                limit: int = 50) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as conn:
            if run_id:
                rows = conn.execute(
                    "SELECT * FROM scores WHERE run_id=? ORDER BY score_name ASC", (run_id,)
                ).fetchall()
            elif project_id:
                rows = conn.execute(
                    "SELECT * FROM scores WHERE project_id=? ORDER BY computed_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM scores ORDER BY computed_at DESC LIMIT ?", (limit,)
                ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["evidence"] = _loads(item.pop("evidence_json", "{}"), {})
            item["value"] = None if item.get("value_null") else item.get("value")
            out.append(item)
        return out


class CommitRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def upsert(self, *, project_id: str, sha: str, parents: list[str],
               author: str | None, committed_at: str | None,
               message: str | None, branch: str | None, recorded_at: str) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """INSERT INTO commits (project_id, sha, parents_json, author,
                    committed_at, message, branch, recorded_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_id, sha) DO UPDATE SET
                    parents_json=excluded.parents_json, author=excluded.author,
                    committed_at=excluded.committed_at, message=excluded.message,
                    branch=excluded.branch, recorded_at=excluded.recorded_at""",
                (project_id, sha, json.dumps(parents), author, committed_at,
                 message, branch, recorded_at),
            )
            conn.commit()

    def history(self, *, project_id: str, since: str | None = None,
                limit: int = 50) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as conn:
            if since:
                rows = conn.execute(
                    "SELECT * FROM commits WHERE project_id=? AND committed_at > ?"
                    " ORDER BY committed_at DESC LIMIT ?",
                    (project_id, since, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM commits WHERE project_id=? ORDER BY committed_at DESC LIMIT ?",
                    (project_id, limit),
                ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["parents"] = _loads(item.pop("parents_json", "[]"), [])
            out.append(item)
        return out


class AnalysisCacheRepository:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path

    def get(self, cache_key: str) -> dict[str, Any] | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM analysis_cache WHERE cache_key=?", (cache_key,)
            ).fetchone()
        if not row:
            return None
        item = dict(row)
        item["payload"] = _loads(item.pop("payload_json", "{}"), {})
        return item

    def put(self, *, cache_key: str, project_id: str | None, kind: str,
            inputs_hash: str, target_sha: str, created_at: str,
            payload: dict[str, Any]) -> None:
        with get_connection(self.db_path) as conn:
            conn.execute(
                """INSERT INTO analysis_cache (cache_key, project_id, kind, inputs_hash,
                    target_sha, created_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cache_key) DO UPDATE SET inputs_hash=excluded.inputs_hash,
                    target_sha=excluded.target_sha, created_at=excluded.created_at,
                    payload_json=excluded.payload_json""",
                (cache_key, project_id, kind, inputs_hash, target_sha, created_at,
                 json.dumps(payload)),
            )
            conn.commit()
