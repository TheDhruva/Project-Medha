"""Lightweight in-process agent/stage lifecycle tracker (no scheduler).

The pipeline in `planning.py` IS the execution order; this module only
records it. Each of the ten logical agents moves through real states
(idle → running → complete/failed/skipped/cancelled/timed_out) with
measured timestamps — the backend snapshot the dashboard renders.
No fake progress: states change only when the pipeline calls start/finish.
"""

from __future__ import annotations

import time

from app.core.events import utc_now_iso

# Stable agent identities, display names, and dependency ordering shown in
# the dashboard orchestration view. Dependencies are informational (the
# pipeline enforces order); the tracker never schedules anything.
AGENT_DEFS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("preflight", "Preflight", ()),
    ("analyzer", "Code Analyzer", ("preflight",)),
    ("docker", "Docker", ("analyzer",)),
    ("nginx", "Nginx", ("analyzer",)),
    ("security", "Security", ("analyzer",)),
    ("mediator", "Mediator", ("docker", "nginx", "security")),
    ("verifier", "Verifier", ("mediator",)),
    ("critic", "Critic", ("verifier",)),
    ("executor", "Executor", ("critic",)),
    ("rollback", "Rollback", ("executor",)),
)

AGENT_NAMES = {aid: name for aid, name, _ in AGENT_DEFS}
AGENT_DEPS = {aid: deps for aid, _, deps in AGENT_DEFS}

VALID_STATUSES = frozenset(
    {"idle", "running", "complete", "failed", "skipped", "cancelled", "timed_out"}
)


class StageTracker:
    """Per-run agent lifecycle state (one instance per pipeline run)."""

    def __init__(self) -> None:
        self._states: dict[str, dict] = {
            aid: {
                "id": aid,
                "name": name,
                "status": "idle",
                "activity": "Waiting",
                "lastEvent": "—",
                "durationMs": None,
                "startedAt": None,
                "finishedAt": None,
                "deps": list(deps),
                "error": None,
            }
            for aid, name, deps in AGENT_DEFS
        }
        self._running_since: dict[str, float] = {}

    def start(self, agent_id: str, activity: str = "Running") -> None:
        state = self._states.get(agent_id)
        if state is None:
            return
        state["status"] = "running"
        state["activity"] = activity
        state["lastEvent"] = activity
        state["startedAt"] = utc_now_iso()
        state["error"] = None
        self._running_since[agent_id] = time.perf_counter()

    def finish(
        self,
        agent_id: str,
        status: str,
        activity: str | None = None,
        error: str | None = None,
    ) -> float:
        """Record completion; returns measured duration in milliseconds."""
        state = self._states.get(agent_id)
        if state is None:
            return 0.0
        started = self._running_since.pop(agent_id, None)
        duration_ms = (
            round((time.perf_counter() - started) * 1000.0, 1)
            if started is not None
            else None
        )
        state["status"] = status if status in VALID_STATUSES else "failed"
        if activity is not None:
            state["activity"] = activity
            state["lastEvent"] = activity
        state["finishedAt"] = utc_now_iso()
        state["durationMs"] = duration_ms
        state["error"] = error
        return duration_ms or 0.0

    def fail_remaining(self, error: str | None = None) -> None:
        """Finalize open agents on a failure terminal: running → failed."""
        for state in self._states.values():
            if state["status"] == "running":
                self.finish(state["id"], "failed",
                            activity=state["activity"], error=error)
            elif state["status"] == "idle":
                state["status"] = "skipped"
                state["activity"] = "Skipped after failure"
                state["lastEvent"] = "Skipped after failure"

    def cancel_remaining(self) -> None:
        """Mark running agents cancelled and idle ones skipped (cancel path)."""
        for state in self._states.values():
            if state["status"] == "running":
                self.finish(state["id"], "cancelled", activity="Cancelled",
                            error="cancel_requested")
            elif state["status"] == "idle":
                state["status"] = "skipped"
                state["activity"] = "Skipped after cancellation"
                state["lastEvent"] = "Skipped after cancellation"

    def snapshot_row(self, agent_id: str) -> dict | None:
        """Single-agent delta row (same shape as snapshot entries)."""
        for row in self.snapshot():
            if row["id"] == agent_id:
                return row
        return None

    def snapshot(self) -> list[dict]:
        """JSON-safe agent rows in stable pipeline order (no secrets)."""
        return [
            {
                "id": aid,
                "name": AGENT_NAMES[aid],
                "status": self._states[aid]["status"],
                "activity": self._states[aid]["activity"],
                "lastEvent": self._states[aid]["lastEvent"],
                "durationMs": self._states[aid]["durationMs"],
                "startedAt": self._states[aid]["startedAt"],
                "finishedAt": self._states[aid]["finishedAt"],
                "deps": list(self._states[aid]["deps"]),
                **({"error": self._states[aid]["error"]}
                   if self._states[aid]["error"] else {}),
            }
            for aid, _, _ in AGENT_DEFS
        ]
