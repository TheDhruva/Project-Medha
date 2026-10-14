"""Plan supportability gate — refuse unsafe/unknown deployments."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models.domain import ApplicationProfile


@dataclass
class SupportDecision:
    supported: bool
    code: str | None = None
    message: str = ""
    details: dict = field(default_factory=dict)


def _candidate_details(profile: ApplicationProfile) -> list[dict]:
    stack = profile.inferred_stack
    details = list(stack.app_candidate_details or [])
    if not details and stack.app_candidates:
        details = [{"path": p, "technologies": [], "evidence": []}
                   for p in stack.app_candidates]
    return details


def assess_plan_support(
    profile: ApplicationProfile,
    selected_target: str | None = None,
) -> SupportDecision:
    """
    MEDHA only executes plans it can understand from manifests.
    Prefer Dockerfile / compose / explicit simple services.

    Low-confidence analysis never silently passes: manifest-backed plans
    below the confidence floor require explicit review, and ambiguous
    multi-application repositories are rejected until a target is chosen.
    An explicit, valid target resolves genuine ambiguity for a single
    V1 service; coordinated multi-service deployment stays unsupported.
    """
    stack = profile.inferred_stack
    effective_target = (selected_target or stack.selected_target or "").strip()
    if effective_target == ".":
        effective_target = ""
    candidates = list(stack.app_candidates or [])
    details = _candidate_details(profile)
    relationship = stack.app_relationship or (
        "single" if len(candidates) <= 1 else "monorepo"
    )
    notes = " ".join(stack.notes or []).lower()
    ambiguous_note = "multiple applications" in notes or "ambiguous" in notes

    if len(candidates) > 1 and not effective_target:
        if relationship == "fullstack":
            message = (
                "Related frontend and backend detected in this repository. "
                "V1 deploys one service at a time — choose one explicit "
                "deployment target before MEDHA can plan."
            )
        else:
            message = (
                "Multiple applications detected in this repository. "
                "Choose one explicit deployment target before MEDHA can plan."
            )
        return SupportDecision(
            supported=False,
            code="MULTIPLE_APPS_REQUIRE_TARGET",
            message=message,
            details={
                "candidates": details,
                "relationship": relationship,
                "reason": (
                    "automatic selection is ambiguous"
                    if relationship != "fullstack"
                    else "full-stack pair requires an explicit single-service target"
                ),
                "next_actions": ["select_target", "reanalyze"],
                "supported_targets": [c for c in candidates],
            },
        )
    if len(candidates) > 1 and effective_target:
        if effective_target not in candidates:
            return SupportDecision(
                supported=False,
                code="INVALID_DEPLOYMENT_TARGET",
                message=(
                    f"Deployment target '{effective_target}' is not a detected "
                    f"application ({', '.join(candidates)})."
                ),
                details={
                    "candidates": details,
                    "relationship": relationship,
                    "reason": "stale or unknown target",
                    "next_actions": ["select_target"],
                    "supported_targets": list(candidates),
                },
            )
        # Valid single-service target: fall through to normal manifest
        # checks scoped to that application. Full-stack coordinated
        # deployment remains unsupported — exactly one target executes.
    elif ambiguous_note and len(candidates) > 1 and not effective_target:
        return SupportDecision(
            supported=False,
            code="MULTIPLE_APPS_REQUIRE_TARGET",
            message=(
                "Multiple applications detected in this repository. "
                "Choose one explicit deployment target before MEDHA can plan."
            ),
            details={
                "candidates": details,
                "relationship": relationship,
                "reason": "automatic selection is ambiguous",
                "next_actions": ["select_target", "reanalyze"],
                "supported_targets": list(candidates),
            },
        )
    if stack.has_dockerfile or stack.has_compose:
        if stack.confidence >= 0.5:
            return SupportDecision(supported=True, message="Manifest-backed plan supported")
        if stack.confidence >= 0.35:
            return SupportDecision(
                supported=False,
                code="PLAN_REQUIRES_REVIEW",
                message="Low-confidence manifest analysis — plan requires explicit review.",
            )
        return SupportDecision(
            supported=False,
            code="PLAN_REQUIRES_REVIEW",
            message="Low confidence despite manifests — plan requires review.",
        )

    service_names = [s.name for s in stack.services if s.name != "network"]
    if len(service_names) >= 1 and stack.confidence >= 0.55:
        return SupportDecision(
            supported=True,
            message="Inferred service plan accepted with moderate confidence",
        )

    return SupportDecision(
        supported=False,
        code="DEPLOYMENT_UNSUPPORTED",
        message=(
            "MEDHA cannot safely infer a controlled local Docker plan from this repository. "
            "Provide a Dockerfile or docker-compose.yml. See docs/REAL_EXECUTION_RUNBOOK.md "
            "for supported application profiles."
        ),
    )
