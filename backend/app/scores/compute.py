"""Versioned deterministic product scores (Phase 6).

Four scores, each 0-100 or None (unavailable/insufficient evidence).
Higher always means better. Missing evidence is never success.
Deterministic for identical versioned inputs; tied to immutable SHAs.

- deployment_readiness: config/profile/health-check/verification evidence.
- performance: static risk signals only (no invented benchmarks). A measured
  benchmark sub-score is None unless real runtime measurement exists.
- optimization: evidence-backed improvement opportunities; higher = better
  optimized (fewer open opportunities).
- security: scan findings/severity/coverage; missing coverage caps the score.
"""

from __future__ import annotations

from typing import Any

VERSION = "scores-v1"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def compute_deployment_readiness(*, verification: dict | None,
                                 support_code: str | None,
                                 profile_confidence: float | None,
                                 health_hints: list) -> tuple[float | None, dict]:
    evidence: dict[str, Any] = {
        "support_code": support_code,
        "profile_confidence": profile_confidence,
        "health_hints": list(health_hints or []),
    }
    if verification is None:
        return None, {**evidence, "reason": "no verification evidence"}
    checks = verification.get("checks", []) if isinstance(verification, dict) else []
    if not checks:
        return None, {**evidence, "reason": "verification has no checks"}
    score = 100
    blocking = 0
    for check in checks:
        status = (check.get("status") or "").lower()
        severity = (check.get("severity") or "").upper()
        if status == "fail" and severity in {"HIGH", "CRITICAL"}:
            score -= 20
            blocking += 1
        elif status == "fail":
            score -= 12
            blocking += 1
        elif status == "warning":
            score -= 5
    if support_code and support_code != "SUPPORTED":
        score -= 15
        evidence["support_penalty"] = True
    if not health_hints:
        score -= 10
        evidence["no_health_check"] = True
    evidence["blocking_failures"] = blocking
    return max(0, score), evidence


def compute_performance(*, change_intel: dict | None,
                        runtime_measured: dict | None) -> tuple[float | None, dict]:
    """Static estimate only. Measured benchmark is None unless recorded."""
    evidence: dict[str, Any] = {"measured": bool(runtime_measured)}
    risk = _as_dict((change_intel or {}).get("risk"))
    factors = risk.get("factors", []) if isinstance(risk, dict) else []
    score: float | None = 80
    deductions = 0
    for factor in factors if isinstance(factors, list) else []:
        code = str(factor.get("code", ""))
        if "blast" in code or "large" in code or "perf" in code:
            if factor.get("level") == "high":
                deductions += 15
            elif factor.get("level") == "medium":
                deductions += 7
    score -= deductions
    evidence["static_deductions"] = deductions
    evidence["benchmark"] = runtime_measured or "not-measured"
    return max(0, score), evidence


def compute_optimization(*, change_intel: dict | None,
                         verification: dict | None) -> tuple[float | None, dict]:
    evidence: dict[str, Any] = {}
    if change_intel is None and verification is None:
        return None, {"reason": "no analysis evidence"}
    score = 100
    requirements = (change_intel or {}).get("requirements", []) if isinstance(change_intel, dict) else []
    open_reqs = [r for r in requirements if isinstance(r, dict) and r.get("status") != "done"]
    score -= min(30, len(open_reqs) * 3)
    evidence["open_requirements"] = len(open_reqs)
    checks = (verification or {}).get("checks", []) if isinstance(verification, dict) else []
    warnings = [c for c in checks if isinstance(c, dict) and str(c.get("status", "")).lower() == "warning"]
    score -= min(20, len(warnings) * 2)
    evidence["warnings"] = len(warnings)
    return max(0, score), evidence


def compute_security(*, verification: dict | None,
                     critic: dict | None,
                     change_intel: dict | None) -> tuple[float | None, dict]:
    evidence: dict[str, Any] = {}
    checks = (verification or {}).get("checks", []) if isinstance(verification, dict) else []
    if (not checks or len(checks) == 0) and critic is None:
        return None, {"reason": "no security evidence"}
    score = 100
    sec_fails = [c for c in checks
                 if isinstance(c, dict)
                 and str(c.get("status", "")).lower() == "fail"
                 and "sec" in str(c.get("category", "")).lower()]
    score -= len(sec_fails) * 20
    evidence["security_failures"] = len(sec_fails)
    critic_d = _as_dict(critic)
    sec_score = critic_d.get("security")
    if isinstance(sec_score, (int, float)):
        score = round((score + float(sec_score)) / 2)
        evidence["critic_security"] = sec_score
    risk = _as_dict((change_intel or {}).get("risk"))
    if risk.get("level") == "high":
        score -= 10
    unresolved = (change_intel or {}).get("unresolved", []) if isinstance(change_intel, dict) else []
    if isinstance(unresolved, list) and unresolved:
        # Unresolved dependency impact caps confidence: cannot be perfect.
        score = min(score, 85)
        evidence["unresolved_count"] = len(unresolved)
    coverage = (change_intel or {}).get("coverage") if isinstance(change_intel, dict) else None
    if coverage == "partial":
        score = min(score, 90)
        evidence["coverage"] = "partial"
    return max(0, score), evidence


def compute_all(*, verification: dict | None, critic: dict | None,
                change_intel: dict | None, support_code: str | None = None,
                profile_confidence: float | None = None,
                health_hints: list | None = None,
                runtime_measured: dict | None = None) -> dict[str, dict]:
    """Compute all four scores. Returns {name: {value, version, evidence}}."""
    readiness, ev_r = compute_deployment_readiness(
        verification=verification, support_code=support_code,
        profile_confidence=profile_confidence, health_hints=health_hints or [])
    perf, ev_p = compute_performance(
        change_intel=change_intel, runtime_measured=runtime_measured)
    opt, ev_o = compute_optimization(
        change_intel=change_intel, verification=verification)
    sec, ev_s = compute_security(
        verification=verification, critic=critic, change_intel=change_intel)
    return {
        "deployment_readiness": {"value": readiness, "version": VERSION, "evidence": ev_r},
        "performance": {"value": perf, "version": VERSION, "evidence": ev_p},
        "optimization": {"value": opt, "version": VERSION, "evidence": ev_o},
        "security": {"value": sec, "version": VERSION, "evidence": ev_s},
    }
