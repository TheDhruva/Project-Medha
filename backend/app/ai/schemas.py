"""Strict schemas for AI advisory outputs.

Every model response is validated against one of these before use. Unknown
fields are rejected (extra="forbid") and lengths are bounded, so oversized or
malformed output lands in the sanitized `schema_invalid` path instead of the
pipeline. Model output is advisory only: it never authorizes deployment,
changes permissions, or executes commands.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class _Strict(BaseModel):
    model_config = {"extra": "forbid"}


class ChangeSummary(_Strict):
    summary: str = Field(..., max_length=600)
    changed_areas: list[str] = Field(default_factory=list, max_length=8)
    risk_level: Literal["low", "medium", "high"] = "medium"
    notable_risks: list[str] = Field(default_factory=list, max_length=5)


class RepoInterpretation(_Strict):
    summary: str = Field(default="", max_length=400)
    runtime: str = Field(default="", max_length=80)
    deploy_shape: str = Field(default="", max_length=200)
    implications: list[str] = Field(default_factory=list, max_length=6)
    missing_evidence: list[str] = Field(default_factory=list, max_length=6)


class PlanAction(_Strict):
    action: str = Field(..., max_length=40)
    target: str = Field(default="", max_length=120)
    reason: str = Field(default="", max_length=240)


class PlanSuggestion(_Strict):
    actions: list[PlanAction] = Field(default_factory=list, max_length=6)
    open_questions: list[str] = Field(default_factory=list, max_length=4)


class AgentExplanation(_Strict):
    finding: str = Field(..., max_length=300)
    why: str = Field(default="", max_length=500)
    tradeoffs: list[str] = Field(default_factory=list, max_length=4)


class CriticAssist(_Strict):
    omissions: list[str] = Field(default_factory=list, max_length=5)
    contradictions: list[str] = Field(default_factory=list, max_length=5)
    confidence: Literal["low", "medium", "high"] = "medium"


class ReviewBrief(_Strict):
    risk_explanation: str = Field(..., max_length=600)
    assumptions: list[str] = Field(default_factory=list, max_length=5)
    next_steps: list[str] = Field(default_factory=list, max_length=5)


SCHEMA_BY_KIND: dict[str, type[_Strict]] = {
    "change_summary": ChangeSummary,
    "repo_interpretation": RepoInterpretation,
    "plan_suggestion": PlanSuggestion,
    "agent_explanation": AgentExplanation,
    "critic_assist": CriticAssist,
    "review_brief": ReviewBrief,
}
