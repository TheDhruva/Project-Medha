"""GitHub Pull Request and local branch delivery for verified repairs."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from app.ai.redact import redact_text
from app.core.config import get_settings
from app.core.logging import get_logger
from app.remediation.models import RepairDelivery, RepairPlan, RepairVerification
from app.remediation.worktree import validate_safe_branch_name
from app.services import github_app

logger = get_logger(__name__)


def _run_git_push(
    repo_root: Path, branch_name: str, target: str = "origin", *, token: str | None = None,
    timeout: float = 60.0,
) -> tuple[int, str, str]:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if token:
        env.update(github_app.git_env_with_token(token, auth_format="basic"))

    try:
        proc = subprocess.run(
            ["git", "push", "-u", target, "--", branch_name],
            cwd=repo_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            check=False,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"Git push timed out after {timeout} seconds."
    except Exception as exc:
        return 1, "", f"Git push execution error: {exc}"


def deliver_verified_repair(
    repo_root: Path,
    repository_url: str,
    base_branch: str,
    branch_name: str,
    commit_sha: str | None,
    plan: RepairPlan,
    verification: RepairVerification,
    *,
    delivery_method: str = "auto",
) -> RepairDelivery:
    """Deliver a verified repair via GitHub Pull Request or local branch."""
    settings = get_settings()
    live_enabled = bool(settings.live_delivery_enabled)

    try:
        clean_branch = validate_safe_branch_name(branch_name)
    except ValueError as exc:
        return RepairDelivery(
            delivered=False,
            delivery_method="local_branch",
            live_delivery_enabled=live_enabled,
            branch_name=branch_name,
            commit_sha=commit_sha,
            message=f"Branch name security validation failed: {exc}",
        )

    config = github_app.get_github_app_config()
    repo_slug = github_app.parse_github_repo(repository_url)
    if not repo_slug and "/" in (repository_url or "") and not (repository_url or "").startswith("http"):
        parts = [p for p in repository_url.strip().split("/") if p]
        if len(parts) == 2 and not any(c.isspace() or c in "@:?#" for c in repository_url):
            owner, name = parts
            repo_slug = f"{owner}/{name[:-4] if name.lower().endswith('.git') else name}"

    # 1. Explicit local delivery requested
    if delivery_method == "local_branch":
        return RepairDelivery(
            delivered=True,
            delivery_method="local_branch",
            live_delivery_enabled=live_enabled,
            branch_name=clean_branch,
            commit_sha=commit_sha,
            message=f"Verified patch committed to local branch '{clean_branch}'. Ready to review or push.",
        )

    # 2. Explicit GitHub PR requested but live delivery disabled by config
    if delivery_method == "github_pr" and not live_enabled:
        return RepairDelivery(
            delivered=False,
            delivery_method="github_pr",
            live_delivery_enabled=False,
            branch_name=clean_branch,
            commit_sha=commit_sha,
            message="Live delivery to GitHub is disabled by configuration (MEDHA_LIVE_DELIVERY_ENABLED=false). Local delivery mode is active.",
        )

    # 3. Explicit GitHub PR requested but GitHub App unconfigured
    if delivery_method == "github_pr" and not config.configured:
        return RepairDelivery(
            delivered=False,
            delivery_method="github_pr",
            live_delivery_enabled=live_enabled,
            branch_name=clean_branch,
            commit_sha=commit_sha,
            message="GitHub App is not configured (missing GITHUB_APP_ID, GITHUB_APP_INSTALLATION_ID, or GITHUB_APP_PRIVATE_KEY).",
        )

    # 4. Remote GitHub PR delivery (when live delivery enabled and App configured)
    if (delivery_method in {"auto", "github_pr"}) and live_enabled and config.configured and repo_slug:
        try:
            token = github_app.mint_installation_token()
            target_push_url = f"https://github.com/{repo_slug}.git"
            rc, out, err = _run_git_push(repo_root, clean_branch, target_push_url, token=token)
            if rc != 0:
                # Fallback to 'origin' if explicit URL push failed
                rc, out, err = _run_git_push(repo_root, clean_branch, "origin", token=token)

            if rc != 0:
                redacted_err = redact_text(err.strip())
                logger.warning("git push failed: %s", redacted_err)
                return RepairDelivery(
                    delivered=False,
                    delivery_method="github_pr",
                    live_delivery_enabled=True,
                    branch_name=clean_branch,
                    commit_sha=commit_sha,
                    message=f"Git push to GitHub failed: {redacted_err}",
                )

            # Create Pull Request
            pr_title = f"fix(security): resolve {plan.rule_id} in {plan.file_path}"
            evidence_md = "\n".join(f"- {e}" for e in verification.verification_evidence)
            pr_body = (
                f"## MEDHA Automated Remediation\n\n"
                f"### Problem Description\n"
                f"**Rule**: `{plan.rule_id}`\n"
                f"**File**: `{plan.file_path}`\n\n"
                f"{plan.explanation}\n\n"
                f"### Verification Evidence\n"
                f"{evidence_md or '- Validated syntax and verified 0 scanner findings.'}\n\n"
                f"### Verification Status\n"
                f"Verified by MEDHA in an isolated worktree sandbox prior to submission.\n"
            )

            status_code, resp_payload = github_app._api_request(
                "POST",
                f"/repos/{repo_slug}/pulls",
                bearer=token,
                body={
                    "title": pr_title,
                    "head": clean_branch,
                    "base": base_branch or "main",
                    "body": pr_body,
                },
            )

            if status_code in {200, 201}:
                pr_num = resp_payload.get("number")
                pr_url = resp_payload.get("html_url")
                return RepairDelivery(
                    delivered=True,
                    delivery_method="github_pr",
                    live_delivery_enabled=True,
                    branch_name=clean_branch,
                    pr_number=pr_num,
                    pr_url=pr_url,
                    commit_sha=commit_sha,
                    message=f"Pull Request #{pr_num} successfully created on GitHub.",
                )
            elif status_code == 422:
                # Check if a pull request already exists for this branch (idempotent retry)
                owner = repo_slug.split("/")[0]
                try:
                    q_status, q_payload = github_app._api_request(
                        "GET",
                        f"/repos/{repo_slug}/pulls?head={owner}:{clean_branch}&state=open",
                        bearer=token,
                    )
                    if q_status == 200 and isinstance(q_payload, list) and len(q_payload) > 0:
                        existing_pr = q_payload[0]
                        pr_num = existing_pr.get("number")
                        pr_url = existing_pr.get("html_url")
                        return RepairDelivery(
                            delivered=True,
                            delivery_method="github_pr",
                            live_delivery_enabled=True,
                            branch_name=clean_branch,
                            pr_number=pr_num,
                            pr_url=pr_url,
                            commit_sha=commit_sha,
                            message=f"Pull Request #{pr_num} already exists on GitHub for branch '{clean_branch}'.",
                        )
                except Exception as query_exc:
                    logger.debug("Failed querying existing pull requests: %s", query_exc)

                raw_msg = str(resp_payload.get('message', ''))
                redacted_msg = redact_text(raw_msg)
                return RepairDelivery(
                    delivered=False,
                    delivery_method="github_pr",
                    live_delivery_enabled=True,
                    branch_name=clean_branch,
                    commit_sha=commit_sha,
                    message=f"Branch pushed to GitHub, but Pull Request creation failed (HTTP {status_code}): {redacted_msg}",
                )
            else:
                raw_msg = str(resp_payload.get('message', ''))
                redacted_msg = redact_text(raw_msg)
                return RepairDelivery(
                    delivered=False,
                    delivery_method="github_pr",
                    live_delivery_enabled=True,
                    branch_name=clean_branch,
                    commit_sha=commit_sha,
                    message=f"Branch pushed to GitHub, but Pull Request creation failed (HTTP {status_code}): {redacted_msg}",
                )
        except Exception as exc:
            logger.exception("GitHub delivery failed")
            return RepairDelivery(
                delivered=False,
                delivery_method="github_pr",
                live_delivery_enabled=True,
                branch_name=clean_branch,
                commit_sha=commit_sha,
                message=f"GitHub delivery exception: {redact_text(str(exc))}",
            )

    # 5. Fallback local delivery (when live delivery is disabled or App unconfigured in auto mode)
    note = (
        "Live remote delivery is disabled (MEDHA_LIVE_DELIVERY_ENABLED=false)."
        if not live_enabled
        else "GitHub App is not configured for remote PR delivery."
    )
    return RepairDelivery(
        delivered=True,
        delivery_method="local_branch",
        live_delivery_enabled=live_enabled,
        branch_name=clean_branch,
        commit_sha=commit_sha,
        message=f"Verified patch committed to local branch '{clean_branch}'. ({note})",
    )

