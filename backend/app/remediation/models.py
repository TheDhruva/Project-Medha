"""Data models for automated issue remediation, patch review, and delivery."""

from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class RepairPlan(BaseModel):
    finding_id: str
    rule_id: str
    file_path: str
    line: int | None = None
    title: str
    explanation: str
    remediation_strategy: Literal["deterministic_ast", "pattern_transform", "ai_assisted", "manual_required"]
    can_auto_fix: bool
    risk_level: Literal["low", "medium", "high"]
    original_snippet: str = ""
    patched_snippet: str = ""
    diff_unified: str = ""
    diff_hash: str = ""
    message: str = ""


class RepairValidation(BaseModel):
    syntax_valid: bool
    syntax_error: str | None = None
    linter_passed: bool = True
    linter_output: str = ""


class RepairVerification(BaseModel):
    verified: bool
    finding_eliminated: bool
    original_rule_retested: bool
    branch_name: str | None = None
    commit_sha: str | None = None
    new_findings_introduced: list[dict[str, Any]] = Field(default_factory=list)
    verification_evidence: list[str] = Field(default_factory=list)
    output: str = ""


class RepairDelivery(BaseModel):
    delivered: bool
    delivery_method: Literal["github_pr", "local_branch", "uncommitted_preview"]
    live_delivery_enabled: bool = False
    branch_name: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None
    commit_sha: str | None = None
    message: str = ""


class RepairSessionRecord(BaseModel):
    repair_id: str
    finding_id: str
    project_id: str
    repository: str
    target_sha: str
    rule_id: str
    file_path: str
    status: Literal["planned", "validating", "verified", "failed", "approved", "delivered"]
    plan: RepairPlan
    diff_hash: str = ""
    approved: bool = False
    approved_by: str | None = None
    approved_at: str | None = None
    approved_diff_hash: str | None = None
    branch_name: str | None = None
    commit_sha: str | None = None
    validation: RepairValidation | None = None
    verification: RepairVerification | None = None
    delivery: RepairDelivery | None = None
    audit_events: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str
    updated_at: str

