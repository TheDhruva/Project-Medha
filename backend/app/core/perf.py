"""Lightweight performance instrumentation (stdlib only, bounded memory).

No new dependencies. Uses monotonic clocks. Never logs secrets: callers pass
redacted labels and operation names only — never SQL params, URLs, tokens.
All counters are bounded scalars; per-operation histories are not retained.
"""
from __future__ import annotations

import threading
import time
from contextvars import ContextVar
from typing import Any

_request_id: ContextVar[str] = ContextVar("medha_request_id", default="-")

_SLOW_OP_S = 1.0
_SLOW_QUERY_S = 0.1

_lock = threading.Lock()
_counters: dict[str, int] = {}
_slow_events: int = 0


def set_request_id(value: str) -> None:
    _request_id.set(value)


def get_request_id() -> str:
    return _request_id.get()


def bump(key: str, amount: int = 1) -> int:
    with _lock:
        _counters[key] = _counters.get(key, 0) + amount
        return _counters[key]


def snapshot_counters() -> dict[str, int]:
    with _lock:
        out = dict(_counters)
        out["slow_events"] = _slow_events
        return out


class stage:
    """Monotonic timer for orchestration stages; logs once if slow."""

    def __init__(self, name: str, *, deployment_id: str = "", slow_s: float = _SLOW_OP_S) -> None:
        self.name = name
        self.deployment_id = deployment_id
        self.slow_s = slow_s
        self.t0 = 0.0
        self.elapsed = 0.0

    def __enter__(self) -> stage:
        self.t0 = time.perf_counter()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.elapsed = time.perf_counter() - self.t0
        bump(f"stage.{self.name}")
        if self.elapsed >= self.slow_s:
            global _slow_events
            with _lock:
                _slow_events += 1
            from app.core.logging import get_logger

            # deployment_id is server-generated; safe to log.
            get_logger(__name__).warning(
                "slow stage name=%s deployment_id=%s elapsed_s=%.2f rid=%s",
                self.name,
                self.deployment_id,
                self.elapsed,
                get_request_id(),
            )


def timed_db(op: str, t0: float) -> None:
    """Record one repository-operation duration (bounded counter + slow warn)."""
    elapsed = time.perf_counter() - t0
    bump(f"db.{op}")
    if elapsed >= _SLOW_QUERY_S:
        global _slow_events
        with _lock:
            _slow_events += 1
        from app.core.logging import get_logger

        get_logger(__name__).warning(
            "slow db op=%s elapsed_s=%.3f rid=%s", op, elapsed, get_request_id()
        )
