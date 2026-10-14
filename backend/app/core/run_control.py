"""In-process run lifecycle flags: cancellation + terminal-event ownership.

Single FastAPI process (V1): a small guarded registry is sufficient — no
broker. Cancellation is cooperative: the pipeline polls `cancel_requested`
at stage boundaries and refuses to start new work (never the executor)
once set. `claim_terminal` guarantees exactly one terminal SSE event per
run no matter how cancellation, timeouts, and completion race.
"""

from __future__ import annotations

import threading
import time

_lock = threading.Lock()
_cancel_at: dict[str, float] = {}
_terminal_owner: set[str] = set()

_MAX_TRACKED = 512
_RETENTION_S = 3600.0


def _prune_locked(now: float) -> None:
    if len(_cancel_at) <= _MAX_TRACKED:
        return
    cutoff = now - _RETENTION_S
    stale = [dep for dep, at in _cancel_at.items() if at < cutoff]
    if not stale:  # still over budget: drop oldest first
        stale = sorted(_cancel_at, key=_cancel_at.__getitem__)[: len(_cancel_at) - _MAX_TRACKED]
    for dep in stale:
        _cancel_at.pop(dep, None)
        _terminal_owner.discard(dep)


def request_cancel(deployment_id: str) -> None:
    """Record an owner-approved cancellation request (idempotent)."""
    now = time.monotonic()
    with _lock:
        _prune_locked(now)
        _cancel_at[deployment_id] = now


def cancel_requested(deployment_id: str) -> bool:
    with _lock:
        return deployment_id in _cancel_at


def claim_terminal(deployment_id: str) -> bool:
    """True when this caller owns the terminal event for the run.

    The cancel endpoint and the pipeline race here; exactly one of them
    emits the terminal event, so a cancelled run can never later report
    success (or failure) from a late task completion.
    """
    with _lock:
        if deployment_id in _terminal_owner:
            return False
        _terminal_owner.add(deployment_id)
        return True


def clear_run(deployment_id: str) -> None:
    """Forget per-run flags when the pipeline task ends (always in finally)."""
    with _lock:
        _cancel_at.pop(deployment_id, None)
        _terminal_owner.discard(deployment_id)
