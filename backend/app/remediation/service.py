"""Remediation orchestration service connecting findings, patchers, sandbox, and delivery."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import DeploymentRepository, FindingRepository, ProjectRepository
from app.remediation.delivery import deliver_verified_repair
from app.remediation.models import (
    RepairDelivery,
    RepairPlan,
    RepairSessionRecord,
    RepairValidation,
    RepairVerification,
)
from app.remediation.patcher import create_deterministic_repair_plan
from app.remediation.worktree import apply_and_verify_in_sandbox, validate_safe_repo_rel_path
from app.services.workspace import workspaces_root

logger = get_logger(__name__)

# In-memory repair sessions cache for fast UI retrieval
_REPAIR_SESSIONS: dict[str, RepairSessionRecord] = {}


def _repairs_dir() -> Path:
    d = workspaces_root() / ".repairs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _save_repair_session(session: RepairSessionRecord) -> None:
    _REPAIR_SESSIONS[session.finding_id] = session
    try:
        path = _repairs_dir() / f"{session.finding_id}.json"
        path.write_text(session.model_dump_json(indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning("Could not persist repair session to disk: %s", exc)


def _get_repair_session(finding_id: str) -> RepairSessionRecord | None:
    if finding_id in _REPAIR_SESSIONS:
        return _REPAIR_SESSIONS[finding_id]
    try:
        path = _repairs_dir() / f"{finding_id}.json"
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            session = RepairSessionRecord.model_validate(data)
            _REPAIR_SESSIONS[finding_id] = session
            return session
    except Exception as exc:
        logger.warning("Could not restore repair session from disk: %s", exc)
    return None


def _resolve_repo_path_for_finding(finding: dict[str, Any], project: Any) -> Path | None:
    """Resolve checkout directory containing the finding's file."""
    rel_path = str(finding.get("path") or "")

    # 1. Check local repo path from project or finding
    from app.services.workspace import resolve_local_repo_path
    repo_url = project.repository if project else finding.get("repository", "")
    local_path = resolve_local_repo_path(repo_url)
    if local_path and (local_path / rel_path).exists():
        return local_path

    # 2. Check deployment workspace if deployment_id is set
    dep_id = finding.get("deployment_id")
    if dep_id:
        ws = workspaces_root() / dep_id
        if (ws / "repo" / rel_path).exists():
            return ws / "repo"
        if (ws / rel_path).exists():
            return ws

    if local_path and local_path.exists():
        return local_path

    return None


class RemediationService:
    def __init__(
        self,
        finding_repo: FindingRepository | None = None,
        project_repo: ProjectRepository | None = None,
        deploy_repo: DeploymentRepository | None = None,
    ) -> None:
        self.finding_repo = finding_repo or FindingRepository()
        self.project_repo = project_repo or ProjectRepository()
        self.deploy_repo = deploy_repo or DeploymentRepository()

    def get_repair_session(self, finding_id: str) -> RepairSessionRecord | None:
        return _get_repair_session(finding_id)

    async def create_plan(self, project_id: str, finding_id: str) -> RepairPlan:
        """Create a targeted repair plan with diff preview for a finding."""
        finding = await asyncio.to_thread(self.finding_repo.get, finding_id)
        if not finding:
            raise ValueError(f"Finding '{finding_id}' not found.")

        if finding.get("project_id") and finding.get("project_id") != project_id:
            raise ValueError(f"Finding '{finding_id}' does not belong to project '{project_id}'.")

        project = await asyncio.to_thread(self.project_repo.get, project_id)
        repo_path = _resolve_repo_path_for_finding(finding, project)
        if not repo_path:
            raise RuntimeError(f"Repository source workspace not available for finding '{finding_id}'.")

        rel_path = str(finding.get("path") or "")
        full_path = validate_safe_repo_rel_path(repo_path, rel_path)
        if not full_path.exists() or not full_path.is_file():
            raise FileNotFoundError(f"Source file '{rel_path}' does not exist in workspace.")

        file_content = full_path.read_text(encoding="utf-8", errors="ignore")
        plan = create_deterministic_repair_plan(finding, file_content)

        session = RepairSessionRecord(
            repair_id=f"rep_{uuid4().hex[:12]}",
            finding_id=finding_id,
            project_id=project_id,
            repository=project.repository if project else "",
            target_sha=finding.get("last_seen_sha") or "HEAD",
            rule_id=str(finding.get("rule_id") or ""),
            file_path=rel_path,
            status="planned",
            plan=plan,
            diff_hash=plan.diff_hash,
            created_at=utc_now_iso(),
            updated_at=utc_now_iso(),
            audit_events=[{
                "event": "plan_created",
                "at": utc_now_iso(),
                "diff_hash": plan.diff_hash,
                "rule_id": plan.rule_id,
                "can_auto_fix": plan.can_auto_fix,
            }],
        )
        _save_repair_session(session)
        return plan

    async def approve(self, project_id: str, finding_id: str, subject: str = "local-operator") -> RepairSessionRecord:
        """Explicitly approve a verified repair plan for delivery."""
        import hashlib

        session = self.get_repair_session(finding_id)
        if not session or not session.verification or not session.verification.verified:
            raise ValueError("Repair must be verified in the sandbox before it can be approved.")

        finding = await asyncio.to_thread(self.finding_repo.get, finding_id)
        if not finding:
            raise ValueError(f"Finding '{finding_id}' not found.")
        if finding.get("project_id") and finding.get("project_id") != project_id:
            raise ValueError(f"Finding '{finding_id}' does not belong to project '{project_id}'.")
        if finding.get("status") in {"rejected", "accepted_risk"}:
            raise ValueError(f"Finding '{finding_id}' is marked as {finding.get('status')}; approval cannot proceed.")

        current_diff_hash = hashlib.sha256(session.plan.diff_unified.encode("utf-8")).hexdigest()
        session.approved = True
        session.approved_by = subject
        session.approved_at = utc_now_iso()
        session.approved_diff_hash = current_diff_hash
        session.status = "approved"
        session.updated_at = utc_now_iso()
        session.audit_events.append({
            "event": "approved",
            "at": utc_now_iso(),
            "by": subject,
            "approved_diff_hash": current_diff_hash,
        })
        _save_repair_session(session)
        return session

    async def apply_and_verify(
        self, project_id: str, finding_id: str
    ) -> tuple[RepairVerification, str | None, str | None]:
        """Apply patch to an isolated worktree sandbox and verify rule elimination."""
        session = self.get_repair_session(finding_id)
        if not session:
            await self.create_plan(project_id, finding_id)
            session = self.get_repair_session(finding_id)
            if not session:
                raise ValueError("Could not initialize repair plan.")

        finding = await asyncio.to_thread(self.finding_repo.get, finding_id)
        if not finding:
            raise ValueError(f"Finding '{finding_id}' not found.")
        if finding.get("project_id") and finding.get("project_id") != project_id:
            raise ValueError(f"Finding '{finding_id}' does not belong to project '{project_id}'.")
        if finding.get("status") in {"rejected", "accepted_risk"}:
            raise ValueError(f"Finding '{finding_id}' is marked as {finding.get('status')}; repair cannot proceed.")

        project = await asyncio.to_thread(self.project_repo.get, project_id)
        repo_path = _resolve_repo_path_for_finding(finding, project)
        if not repo_path:
            raise RuntimeError(f"Repository source workspace not available for finding '{finding_id}'.")

        verification, branch_name, commit_sha = await asyncio.to_thread(
            apply_and_verify_in_sandbox,
            repo_path,
            session.plan,
        )

        session.verification = verification
        session.branch_name = branch_name
        session.commit_sha = commit_sha
        session.status = "verified" if verification.verified else "failed"
        session.updated_at = utc_now_iso()
        session.audit_events.append({
            "event": "sandbox_verified",
            "at": utc_now_iso(),
            "verified": verification.verified,
            "finding_eliminated": verification.finding_eliminated,
            "branch_name": branch_name,
            "commit_sha": commit_sha,
        })
        _save_repair_session(session)

        if verification.verified:
            # Transition finding status to fixed_unverified
            try:
                await asyncio.to_thread(
                    self.finding_repo.transition,
                    finding_id,
                    "fixed_unverified",
                    reason=f"Automated fix applied and verified in worktree (Rule {session.rule_id} eliminated).",
                    at=utc_now_iso(),
                    evidence=verification.verification_evidence,
                )
            except Exception as exc:
                logger.warning("Finding status transition warning: %s", exc)

        return verification, branch_name, commit_sha

    async def deliver(
        self,
        project_id: str,
        finding_id: str,
        branch_name: str | None = None,
        delivery_method: str = "auto",
        approved: bool = True,
        subject: str = "local-operator",
    ) -> RepairDelivery:
        """Deliver the verified fix via Pull Request or local branch commit."""
        import hashlib

        session = self.get_repair_session(finding_id)
        if not session or not session.verification or not session.verification.verified:
            raise ValueError("Repair must be verified in the sandbox before delivery.")

        finding = await asyncio.to_thread(self.finding_repo.get, finding_id)
        if not finding:
            raise ValueError(f"Finding '{finding_id}' not found.")
        if finding.get("project_id") and finding.get("project_id") != project_id:
            raise ValueError(f"Finding '{finding_id}' does not belong to project '{project_id}'.")
        if finding.get("status") in {"rejected", "accepted_risk"}:
            raise ValueError(f"Finding '{finding_id}' is marked as {finding.get('status')}; delivery cannot proceed.")

        # Ensure explicit approval
        current_diff_hash = hashlib.sha256(session.plan.diff_unified.encode("utf-8")).hexdigest()
        if session.approved_diff_hash and session.approved_diff_hash != current_diff_hash:
            session.approved = False
            session.status = "failed"
            session.updated_at = utc_now_iso()
            session.audit_events.append({
                "event": "approval_invalidated",
                "reason": "diff_changed",
                "at": utc_now_iso(),
            })
            _save_repair_session(session)
            raise ValueError("Patch content has changed since approval. Re-approval required.")

        if not session.approved:
            if approved:
                await self.approve(project_id, finding_id, subject=subject)
                session = self.get_repair_session(finding_id)
            else:
                raise ValueError("Repair must be approved before delivery.")

        project = await asyncio.to_thread(self.project_repo.get, project_id)
        repo_path = _resolve_repo_path_for_finding(finding, project)
        if not repo_path:
            raise RuntimeError(f"Repository source workspace not available for finding '{finding_id}'.")

        # Verify that commit exists in repository before delivery
        if session.commit_sha:
            from app.remediation.worktree import _run_git
            rc, _, _ = await asyncio.to_thread(_run_git, ["cat-file", "-e", session.commit_sha], repo_path)
            if rc != 0:
                raise ValueError("Verified commit is missing from local repository workspace. Re-verification required.")

        branch = branch_name or session.branch_name or f"medha/fix-{session.rule_id.lower()}-{finding_id[:8]}"
        base_branch = project.branch if project else "main"
        repo_url = project.repository if project else ""

        delivery = await asyncio.to_thread(
            deliver_verified_repair,
            repo_path,
            repo_url,
            base_branch,
            branch,
            session.commit_sha,
            session.plan,
            session.verification,
            delivery_method=delivery_method,
        )

        session.delivery = delivery
        session.status = "delivered" if delivery.delivered else "failed"
        session.updated_at = utc_now_iso()
        session.audit_events.append({
            "event": "delivery_attempted",
            "at": utc_now_iso(),
            "method": delivery.delivery_method,
            "delivered": delivery.delivered,
            "pr_number": delivery.pr_number,
            "pr_url": delivery.pr_url,
            "by": subject,
            "message": delivery.message,
        })
        _save_repair_session(session)

        if delivery.delivered:
            # Transition finding status to resolved
            try:
                await asyncio.to_thread(
                    self.finding_repo.transition,
                    finding_id,
                    "resolved",
                    reason=(
                        f"Fix delivered via {delivery.delivery_method} "
                        f"(PR: {delivery.pr_url or delivery.branch_name})."
                    ),
                    at=utc_now_iso(),
                    evidence=session.verification.verification_evidence,
                )
            except Exception as exc:
                logger.warning("Finding status transition to resolved warning: %s", exc)

        return delivery
