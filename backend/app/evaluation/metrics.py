"""Evaluation metric helpers — safe division, project-defined rates."""

from __future__ import annotations

from typing import Any


def safe_rate(numerator: int | float, denominator: int | float) -> float | None:
    """Return rate or None when denominator is zero (avoid misleading %)."""
    if denominator == 0:
        return None
    return float(numerator) / float(denominator)


def summarize_cnp(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(cases)
    passed = sum(1 for c in cases if c.get("passed"))
    failed = total - passed
    conflicts_detected = sum(int(c.get("conflicts_detected", 0)) for c in cases)
    conflicts_resolved = sum(int(c.get("conflicts_resolved", 0)) for c in cases)
    rounds = [int(c.get("rounds_used", 0)) for c in cases]
    avg_rounds = (sum(rounds) / len(rounds)) if rounds else 0.0
    methods: dict[str, int] = {}
    for c in cases:
        for m, n in (c.get("resolution_methods") or {}).items():
            methods[m] = methods.get(m, 0) + int(n)
    return {
        "total_cases": total,
        "passed": passed,
        "failed": failed,
        "conflicts_detected": conflicts_detected,
        "conflicts_resolved": conflicts_resolved,
        "conflict_resolution_rate": safe_rate(conflicts_resolved, conflicts_detected),
        "average_rounds": round(avg_rounds, 3),
        "resolution_methods": methods,
        "note": "Rates are None when denominator is zero. Project-defined metrics only.",
    }


def summarize_ceg(cases: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(cases)
    passed = sum(1 for c in cases if c.get("passed"))
    medha_rollback = sum(int(c.get("medha_rollback_count", 0)) for c in cases)
    global_rollback = sum(int(c.get("global_rollback_count", 0)) for c in cases)
    preserved = sum(int(c.get("preserved_count", 0)) for c in cases)
    return {
        "total_cases": total,
        "passed": passed,
        "failed": total - passed,
        "medha_rollback_nodes_total": medha_rollback,
        "global_rollback_nodes_total": global_rollback,
        "preserved_nodes_total": preserved,
        "mean_scope_efficiency": _mean(
            [c.get("scope_efficiency") for c in cases if c.get("scope_efficiency") is not None]
        ),
        "note": (
            "scope_efficiency is a project-defined ratio "
            "(rollback_nodes / active_nodes), not an established academic metric."
        ),
    }


def _mean(values: list[Any]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 4)
