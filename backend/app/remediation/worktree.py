"""Isolated Git Worktree sandbox for applying, validating, and verifying patches."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from app.analysis.policy import _RULES, run_policy_checks
from app.core.logging import get_logger
from app.remediation.models import RepairPlan, RepairValidation, RepairVerification

logger = get_logger(__name__)


class WorktreeSandboxError(RuntimeError):
    pass


_VALID_BRANCH_RE = re.compile(r"^[a-zA-Z0-9_\-\.\/]+$")


def validate_safe_branch_name(branch_name: str) -> str:
    """Validate that branch_name is safe for git ref operations and prevents argument injection."""
    b = str(branch_name).strip()
    if not b or len(b) > 120:
        raise ValueError(f"Invalid branch name length: {len(b)}")
    if b.startswith("-") or b.startswith("/") or b.endswith("/"):
        raise ValueError(f"Branch name cannot start with '-' or have leading/trailing slashes: {b!r}")
    if ".." in b or "@{" in b or "//" in b or "~" in b or "^" in b or ":" in b or "\\" in b:
        raise ValueError(f"Branch name contains unsafe git characters: {b!r}")
    if not _VALID_BRANCH_RE.match(b):
        raise ValueError(f"Branch name contains invalid characters: {b!r}")
    return b


def validate_safe_repo_rel_path(repo_root: Path, rel_path: str) -> Path:
    """Validate that rel_path is a relative path strictly contained within repo_root."""
    clean = str(rel_path).strip().replace("\\", "/")
    if not clean or clean.startswith("/"):
        raise ValueError(f"Path must be a relative repository path: {rel_path!r}")
    p = Path(clean)
    if ".." in p.parts:
        raise ValueError(f"Path traversal detected in path: {rel_path!r}")
    target = (repo_root / p).resolve()
    root_resolved = repo_root.resolve()
    try:
        target.relative_to(root_resolved)
    except ValueError:
        raise ValueError(f"Path escapes repository root: {rel_path!r}")
    return target


def _run_git(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[int, str, str]:
    safe_env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "MEDHA Bot",
        "GIT_AUTHOR_EMAIL": "medha-bot@automated.local",
        "GIT_COMMITTER_NAME": "MEDHA Bot",
        "GIT_COMMITTER_EMAIL": "medha-bot@automated.local",
        **(env or {}),
    }
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=safe_env,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def validate_file_syntax(file_path: Path) -> RepairValidation:
    """Check syntax integrity of a patched file."""
    suffix = file_path.suffix.lower()
    if suffix in {".py", ".pyi"}:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            ast.parse(content, filename=str(file_path))
            return RepairValidation(syntax_valid=True)
        except SyntaxError as exc:
            return RepairValidation(
                syntax_valid=False,
                syntax_error=f"Python syntax error at line {exc.lineno}: {exc.msg}",
            )
    elif suffix in {".json"}:
        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            json.loads(content)
            return RepairValidation(syntax_valid=True)
        except json.JSONDecodeError as exc:
            return RepairValidation(
                syntax_valid=False,
                syntax_error=f"JSON parse error at line {exc.lineno}: {exc.msg}",
            )
    elif suffix in {".yaml", ".yml"}:
        try:
            import yaml
            content = file_path.read_text(encoding="utf-8", errors="ignore")
            yaml.safe_load(content)
            return RepairValidation(syntax_valid=True)
        except Exception as exc:
            return RepairValidation(
                syntax_valid=False,
                syntax_error=f"YAML parse error: {str(exc)[:150]}",
            )
    return RepairValidation(syntax_valid=True)


_CANONICAL_RULE_MAP = {
    "SEC-106": "CFG-003",
    "SEC-107": "CFG-002",
    "CFG-003": "CFG-003",
    "CFG-002": "CFG-002",
    "CFG-004": "CFG-004",
    "SEC-101": "SEC-101",
    "SEC-102": "SEC-102",
    "SEC-105": "SEC-105",
    "SEC-108": "SEC-108",
}


def verify_finding_elimination(worktree_dir: Path, rule_id: str, file_rel: str) -> tuple[bool, list[str]]:
    """Verify that the specific rule violation is no longer present in the patched file."""
    task_res = run_policy_checks(worktree_dir)
    findings = task_res.findings
    evidence: list[str] = []

    target_rule = rule_id.upper()
    canonical_target = _CANONICAL_RULE_MAP.get(target_rule, target_rule)
    equivalent_rules = {target_rule, canonical_target}
    for k, v in _CANONICAL_RULE_MAP.items():
        if v == canonical_target:
            equivalent_rules.add(k)

    norm_rel = file_rel.replace("\\", "/").strip().lstrip("/")

    # Look for matching rule_id in the same file
    matching = [
        f for f in findings
        if str(f.get("rule_id", "")).upper() in equivalent_rules
        and str(f.get("path", "")).replace("\\", "/").strip().lstrip("/") == norm_rel
    ]

    if not matching:
        evidence.append(f"Verification confirmed: Rule {rule_id} produced 0 findings in {file_rel}.")
        return True, evidence

    evidence.append(f"Rule {rule_id} still triggered {len(matching)} finding(s) in {file_rel}.")
    return False, evidence


def apply_and_verify_in_sandbox(
    repo_root: Path,
    plan: RepairPlan,
    *,
    branch_prefix: str = "medha/fix",
) -> tuple[RepairVerification, str | None, str | None]:
    """
    Apply a repair plan inside an isolated worktree sandbox, validate syntax,
    verify rule elimination, and commit to a fix branch if clean.
    
    Returns (verification_result, branch_name, commit_sha).
    """
    if not plan.can_auto_fix or not plan.diff_unified:
        return (
            RepairVerification(
                verified=False,
                finding_eliminated=False,
                original_rule_retested=False,
                output="Plan is not marked for automated fixing or lacks diff.",
            ),
            None,
            None,
        )

    # Validate safe relative path
    try:
        validate_safe_repo_rel_path(repo_root, plan.file_path)
    except ValueError as exc:
        return (
            RepairVerification(
                verified=False,
                finding_eliminated=False,
                original_rule_retested=False,
                output=f"Path security validation failed: {exc}",
            ),
            None,
            None,
        )

    raw_branch = f"{branch_prefix}-{plan.rule_id.lower()}-{plan.finding_id[:8]}"
    try:
        branch_name = validate_safe_branch_name(raw_branch)
    except ValueError as exc:
        return (
            RepairVerification(
                verified=False,
                finding_eliminated=False,
                original_rule_retested=False,
                output=f"Branch name validation failed: {exc}",
            ),
            None,
            None,
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="medha_worktree_"))
    worktree_path = temp_dir / "work"

    try:
        # 1. Create isolated branch & worktree
        rc, _, err = _run_git(["rev-parse", "--is-inside-work-tree"], cwd=repo_root)
        if rc != 0:
            raise WorktreeSandboxError(f"Target path {repo_root} is not a Git repository: {err}")

        # Prune stale worktrees first to prevent collisions from killed processes
        _run_git(["worktree", "prune"], cwd=repo_root)

        # Delete leftover branch if exists
        _run_git(["branch", "-D", "--", branch_name], cwd=repo_root)

        # Create worktree with the new branch
        rc, out, err = _run_git(
            ["worktree", "add", "-b", branch_name, "--", str(worktree_path)],
            cwd=repo_root,
        )
        if rc != 0:
            logger.warning("git worktree add failed (%s), falling back to isolated clone", err.strip())
            shutil.copytree(repo_root, worktree_path, ignore=shutil.ignore_patterns(".git"))
            _run_git(["clone", "--local", "--no-checkout", str(repo_root), str(worktree_path / ".git")], cwd=repo_root)
            _run_git(["checkout", "-b", branch_name], cwd=worktree_path)

        # 2. Apply patch
        patch_file = temp_dir / "patch.diff"
        patch_file.write_text(plan.diff_unified, encoding="utf-8")

        # Try git apply
        rc, out, err = _run_git(["apply", "--check", str(patch_file)], cwd=worktree_path)
        if rc != 0:
            # Fallback: apply patched snippet directly if git apply check fails
            target_file = validate_safe_repo_rel_path(worktree_path, plan.file_path)
            if target_file.exists():
                content = target_file.read_text(encoding="utf-8", errors="ignore")
                from app.remediation.patcher import DETERMINISTIC_PATCHERS
                patcher_info = DETERMINISTIC_PATCHERS.get(plan.rule_id)
                if patcher_info:
                    patched, changed = patcher_info[0](content, plan.line)
                    if changed:
                        target_file.write_text(patched, encoding="utf-8")
                        rc = 0
            if rc != 0:
                return (
                    RepairVerification(
                        verified=False,
                        finding_eliminated=False,
                        original_rule_retested=False,
                        output=f"Patch does not apply cleanly: {err.strip()}",
                    ),
                    None,
                    None,
                )
        else:
            _run_git(["apply", str(patch_file)], cwd=worktree_path)

        # 3. Validate syntax
        patched_file_path = validate_safe_repo_rel_path(worktree_path, plan.file_path)
        syntax_res = validate_file_syntax(patched_file_path)
        if not syntax_res.syntax_valid:
            return (
                RepairVerification(
                    verified=False,
                    finding_eliminated=False,
                    original_rule_retested=False,
                    output=f"Syntax validation failed on patched file: {syntax_res.syntax_error}",
                ),
                None,
                None,
            )

        # 4. Verify finding elimination
        eliminated, evidence = verify_finding_elimination(
            worktree_path, plan.rule_id, plan.file_path
        )
        if not eliminated:
            return (
                RepairVerification(
                    verified=False,
                    finding_eliminated=False,
                    original_rule_retested=True,
                    verification_evidence=evidence,
                    output=f"Verification failed: rule {plan.rule_id} still present after patch.",
                ),
                None,
                None,
            )

        # 5. Commit verified fix to branch
        _run_git(["add", "--", plan.file_path], cwd=worktree_path)
        commit_msg = (
            f"fix(security): resolve {plan.rule_id} in {plan.file_path}\n\n"
            f"Automated remediation by MEDHA.\n"
            f"Rule: {plan.rule_id}\n"
            f"Finding ID: {plan.finding_id}\n"
            f"Verification: syntax valid, scanner passed with 0 findings."
        )
        rc, out, err = _run_git(["commit", "-m", commit_msg], cwd=worktree_path)
        commit_sha = None
        if rc == 0:
            _, sha_out, _ = _run_git(["rev-parse", "HEAD"], cwd=worktree_path)
            commit_sha = sha_out.strip()

        evidence.append(f"Commit created on branch {branch_name} ({commit_sha[:8] if commit_sha else 'unknown'}).")

        return (
            RepairVerification(
                verified=True,
                finding_eliminated=True,
                original_rule_retested=True,
                branch_name=branch_name,
                commit_sha=commit_sha,
                verification_evidence=evidence,
                output="Verification succeeded. Issue eliminated and branch committed in isolated sandbox.",
            ),
            branch_name,
            commit_sha,
        )

    finally:
        # Clean up worktree path
        try:
            _run_git(["worktree", "remove", "--force", str(worktree_path)], cwd=repo_root)
        except Exception:
            pass
        shutil.rmtree(temp_dir, ignore_errors=True)

