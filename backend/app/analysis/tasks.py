"""Bounded, failure-isolated analysis-task runner.

One task's recoverable failure must never cancel an independent task. Every
task settles into an explicit status; exceptions are recorded as diagnostics,
never swallowed silently. Names are adapted to the run-status vocabulary the
project already uses (succeeded/failed/timed_out/unavailable/skipped/partial).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

PENDING = "pending"
RUNNING = "running"
SUCCEEDED = "succeeded"
COMPLETED_WITH_FINDINGS = "completed_with_findings"
PARTIAL = "partial"
UNAVAILABLE = "unavailable"
FAILED = "failed"
TIMED_OUT = "timed_out"
SKIPPED = "skipped"

# Statuses that are a settled, non-fatal outcome for orchestration purposes.
_SETTLED = frozenset(
    {SUCCEEDED, COMPLETED_WITH_FINDINGS, PARTIAL, UNAVAILABLE, FAILED, TIMED_OUT, SKIPPED}
)


@dataclass
class TaskResult:
    task: str
    status: str
    duration_ms: float = 0.0
    attempts: int = 1
    error: str | None = None
    coverage: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_isolated(
    name: str,
    fn: Callable[[], TaskResult],
    *,
    timeout_s: float = 30.0,
    retries: int = 0,
    retry_on: tuple[type[BaseException], ...] = (TimeoutError, OSError),
    coverage: str | None = None,
    max_retries: int = 2,
) -> TaskResult:
    """Run ``fn`` with a bounded wait and bounded retries. Never raises.

    ``fn`` returns a ``TaskResult`` (its own status is preserved). A raised
    exception becomes a FAILED result with a diagnostic; a timeout becomes
    TIMED_OUT and the detached worker is abandoned (never joined) — the
    recovery thread is bounded by the underlying operation's own limits.
    Retries are capped at ``min(retries, max_retries)`` to prevent storms.
    """
    attempts_allowed = max(1, min(retries, max_retries) + 1)
    t0 = time.perf_counter()
    last_error: str | None = None
    for attempt in range(1, attempts_allowed + 1):
        ex = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"analysis:{name}")
        try:
            future = ex.submit(fn)
            try:
                result = future.result(timeout=timeout_s)
            except TimeoutError:
                return TaskResult(
                    task=name,
                    status=TIMED_OUT,
                    duration_ms=round((time.perf_counter() - t0) * 1000.0, 1),
                    attempts=attempt,
                    error=f"timeout after {timeout_s:g}s",
                    coverage=coverage,
                )
            except BaseException as exc:  # noqa: BLE001 - isolate every failure
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < attempts_allowed and isinstance(exc, retry_on):
                    continue
                return TaskResult(
                    task=name,
                    status=FAILED,
                    duration_ms=round((time.perf_counter() - t0) * 1000.0, 1),
                    attempts=attempt,
                    error=last_error,
                    coverage=coverage,
                )
            if not isinstance(result, TaskResult):
                return TaskResult(
                    task=name,
                    status=FAILED,
                    duration_ms=round((time.perf_counter() - t0) * 1000.0, 1),
                    attempts=attempt,
                    error="task returned an invalid result type",
                    coverage=coverage,
                )
            result.attempts = attempt
            if result.duration_ms == 0.0:
                result.duration_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            if result.coverage is None:
                result.coverage = coverage
            return result
        finally:
            # Abandon (do not block on) a timed-out worker.
            ex.shutdown(wait=False, cancel_futures=True)
    return TaskResult(
        task=name,
        status=FAILED,
        attempts=attempts_allowed,
        error=last_error or "unknown task failure",
        coverage=coverage,
    )


def dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deterministic de-duplication keyed by scanner+rule+path+line+message."""
    seen: set[tuple] = set()
    out: list[dict[str, Any]] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        key = (
            str(f.get("source") or f.get("scanner") or ""),
            str(f.get("rule_id") or ""),
            str(f.get("path") or ""),
            f.get("line"),
            str(f.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out
