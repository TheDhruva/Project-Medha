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
    """
    stack = profile.inferred_stack
    if stack.has_dockerfile or stack.has_compose:
        if stack.confidence >= 0.35:
            return SupportDecision(supported=True, message="Manifest-backed plan supported")
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
            "Provide a Dockerfile or docker-compose.yml, or use Demo Mode."
        ),
    )
