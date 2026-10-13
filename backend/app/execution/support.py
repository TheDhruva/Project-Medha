"""Plan supportability gate — refuse unsafe/unknown deployments."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.domain import ApplicationProfile


@dataclass
class SupportDecision:
    supported: bool
    code: str | None = None
    message: str = ""


def assess_plan_support(profile: ApplicationProfile) -> SupportDecision:
    """
    MEDHA only executes plans it can understand from manifests.
    Prefer Dockerfile / compose / explicit simple services.

    Low-confidence analysis never silently passes: manifest-backed plans
    below the confidence floor require explicit review, and ambiguous
    multi-application repositories are rejected until a target is chosen.
    """
    stack = profile.inferred_stack
    notes = " ".join(stack.notes or []).lower()
    if "multiple applications" in notes or "ambiguous" in notes:
        return SupportDecision(
            supported=False,
            code="MULTIPLE_APPS_REQUIRE_TARGET",
            message=(
                "Multiple applications detected in this repository. "
                "Choose one explicit deployment target before MEDHA can plan."
            ),
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
