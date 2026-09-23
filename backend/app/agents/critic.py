"""Critic agent — deterministic quality gate (Phase 7)."""

from __future__ import annotations

from typing import Any

from app.models.domain import ApplicationProfile, Constraint, NegotiationResult
from app.models.execution import CriticRecommendation, CriticResult, VerificationResult


def run_critic(
    *,
    deployment_id: str,
    profile: ApplicationProfile,
    constraints: list[Constraint],
    negotiation: NegotiationResult,
    verification: VerificationResult,
    config_fragments: dict[str, Any] | None = None,
    is_demo: bool = False,
) -> CriticResult:
    """
    Deterministic scoring (prototype, not scientifically validated):

    Start each category at 100, deduct for failures/warnings/intent mismatches.
    """
    _ = config_fragments
    security = 100
    completeness = 100
    constraint_score = 100
    intent = 100
    findings: list[str] = []

    for check in verification.checks:
        if check.status.value == "fail":
            if check.category == "security":
                security -= 35
                findings.append(f"Security check failed: {check.rule} — {check.message}")
            elif check.category in {"schema", "config", "compose"}:
                completeness -= 25
                findings.append(f"Completeness issue: {check.message}")
            elif check.category == "constraints":
                constraint_score -= 30
                findings.append(f"Constraint issue: {check.message}")
            else:
                completeness -= 15
                findings.append(check.message)
        elif check.status.value == "warning":
            if check.category == "security":
                security -= 10
            else:
                completeness -= 5
            findings.append(f"Warning: {check.message}")

    if negotiation.status != "resolved":
        constraint_score -= 40
        findings.append("Negotiation did not resolve cleanly")

    intent_text = (profile.intent or "").lower()
    if "secure" in intent_text:
        # Reward accepted security policies
        sec_ok = any(
            c.type.value == "SECURITY_POLICY" and c.status.value == "accepted" for c in constraints
        )
        if not sec_ok:
            intent -= 20
            findings.append("Intent asks for secure deploy but security policies are weak")
        else:
            findings.append("Intent asks for secure deploy — security policies present")

    if verification.replan_count:
        findings.append(f"Bounded replan count={verification.replan_count}")

    security = max(0, min(100, security))
    completeness = max(0, min(100, completeness))
    constraint_score = max(0, min(100, constraint_score))
    intent = max(0, min(100, intent))
    overall = int(round((security + completeness + constraint_score + intent) / 4))

    if not verification.passed or security < 50:
        recommendation = CriticRecommendation.ESCALATE
        summary = "Critic blocks execution due to critical verification/security issues."
    elif overall < 70 or verification.blocking_failures:
        recommendation = CriticRecommendation.REPLAN
        summary = "Critic recommends a bounded replan before execution."
    elif overall < 85:
        recommendation = CriticRecommendation.WARN
        summary = "Critic allows execution with warnings."
    else:
        recommendation = CriticRecommendation.PASS
        summary = "Critic recommendation PASS."

    if not findings:
        findings.append("No material issues found by deterministic critic heuristics")

    return CriticResult(
        deployment_id=deployment_id,
        score=overall,
        security_score=security,
        completeness_score=completeness,
        constraint_score=constraint_score,
        intent_alignment_score=intent,
        recommendation=recommendation,
        findings=findings,
        summary=summary,
        is_demo=is_demo,
    )
