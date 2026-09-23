from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.enums import DeployMode, DeploymentStatus, ScenarioId
from app.database.connection import get_connection
from app.models.deployment import DeploymentRecord
from app.models.events import SystemEvent


def _loads(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)


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
                    change_intel_json, is_demo, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    1 if record.is_demo else 0,
                    record.created_at,
                    record.updated_at,
                ),
            )
            conn.commit()
        return record

    def get(self, deployment_id: str) -> DeploymentRecord | None:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM deployments WHERE deployment_id = ?",
                (deployment_id,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_record(row)

    def list(
        self,
        *,
        status: str | None = None,
        mode: str | None = None,
        repository: str | None = None,
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
            where.append("repository_url LIKE ?")
            params.append(f"%{repository.strip()}%")
        clause = (f" WHERE {' AND '.join(where)}") if where else ""
        params_count = list(params)

        with get_connection(self.db_path) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM deployments{clause}", params_count
            ).fetchone()[0]
            rows = conn.execute(
                f"""
                SELECT * FROM deployments{clause}
                ORDER BY rowid DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        return [self._row_to_record(row) for row in rows], int(total)

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
    ) -> DeploymentRecord | None:
        record = self.get(deployment_id)
        if record is None:
            return None

        new_status = status or record.status
        new_stage = current_stage if current_stage is not None else record.current_stage
        new_simple = (
            explain_simple if explain_simple is not None else record.explain_simple
        )
        new_technical = (
            explain_technical
            if explain_technical is not None
            else record.explain_technical
        )
        new_error = error_summary if error_summary is not None else record.error_summary

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE deployments
                SET status = ?, current_stage = ?, explain_simple = ?,
                    explain_technical = ?, error_summary = ?, updated_at = ?
                WHERE deployment_id = ?
                """,
                (
                    new_status.value,
                    new_stage,
                    new_simple,
                    new_technical,
                    new_error,
                    updated_at,
                    deployment_id,
                ),
            )
            conn.commit()
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
        updated_at: str,
    ) -> DeploymentRecord | None:
        record = self.get(deployment_id)
        if record is None:
            return None

        new_constraints = constraints if constraints is not None else record.constraints
        new_negotiation = negotiation if negotiation is not None else record.negotiation
        new_verification = (
            verification if verification is not None else record.verification
        )
        new_critic = critic if critic is not None else record.critic
        new_graph = graph if graph is not None else record.graph
        # Allow explicit null for rollback via sentinel — use "rollback" key presence
        # Callers pass rollback=None intentionally to clear; distinguish with Ellipsis? 
        # Simpler: always update when provided as argument using a flag pattern.
        # For Phase 3 we only ever set rollback when present in step data merge.
        new_rollback = rollback if rollback is not None else record.rollback
        new_result = result if result is not None else record.result
        new_change_intel = (
            change_intel if change_intel is not None else record.change_intel
        )

        with get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE deployments
                SET result_json = ?, constraints_json = ?, negotiation_json = ?,
                    verification_json = ?, critic_json = ?, graph_json = ?,
                    rollback_json = ?, change_intel_json = ?, updated_at = ?
                WHERE deployment_id = ?
                """,
                (
                    json.dumps(new_result) if new_result is not None else None,
                    json.dumps(new_constraints) if new_constraints is not None else None,
                    json.dumps(new_negotiation) if new_negotiation is not None else None,
                    json.dumps(new_verification) if new_verification is not None else None,
                    json.dumps(new_critic) if new_critic is not None else None,
                    json.dumps(new_graph) if new_graph is not None else None,
                    json.dumps(new_rollback) if new_rollback is not None else None,
                    json.dumps(new_change_intel)
                    if new_change_intel is not None
                    else None,
                    updated_at,
                    deployment_id,
                ),
            )
            conn.commit()
        return self.get(deployment_id)

    def add_event(self, event: SystemEvent) -> SystemEvent:
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

    def list_events(self, deployment_id: str, limit: int = 500) -> list[SystemEvent]:
        with get_connection(self.db_path) as conn:
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
