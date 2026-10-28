"""Publish server-generated GitHub commit status for merge decisions.

Statuses are derived only from persisted MEDHA decisions — client-provided
status or arbitrary commit metadata is never trusted. When the GitHub App is
not configured the result is an explicit ``setup_required`` with the exact
missing configuration, so the UI can show "status checks not configured"
instead of pretending continuous integration is active.

Advisory only: this module reports a decision, it never merges or deploys.
"""

from __future__ import annotations

from app.core.logging import get_logger
from app.services.github_app import (
    GitHubAppError,
    _api_request,
    get_github_app_config,
    mint_installation_token,
)

logger = get_logger(__name__)

CONTEXT = "medha/merge-readiness"
MAX_DESCRIPTION = 140

# Outcome → GitHub state. `error` (not `failure`) for an incomplete
# assessment: the change was not judged unsafe, it was not judged at all.
OUTCOME_TO_STATE = {
    "approved": "success",
    "blocked": "failure",
    "pending": "pending",
    "assessment_incomplete": "error",
}


def decision_status_body(decision: dict) -> dict:
    """Build the GitHub status body from a persisted decision payload."""
    outcome = str(decision.get("outcome") or "pending")
    state = OUTCOME_TO_STATE.get(outcome, "pending")
    reasons = decision.get("reasons") or []
    blocking = next(
        (r.get("message") for r in reasons if isinstance(r, dict)
         and r.get("kind") == "blocking"),
        None,
    )
    message = blocking or f"MEDHA: {outcome.replace('_', ' ')}"
    description = f"MEDHA {outcome}: {message}"[:MAX_DESCRIPTION]
    return {
        "state": state,
        "description": description,
        "context": CONTEXT,
    }


def post_commit_status(
    repository_full_name: str,
    sha: str,
    *,
    state: str,
    description: str,
    context: str = CONTEXT,
    target_url: str | None = None,
    transport=None,
) -> dict:
    """POST a commit status via the GitHub App installation token."""
    config = get_github_app_config()
    if not config.configured:
        return {
            "published": False,
            "reason": "setup_required",
            "detail": (
                "GitHub status checks require the GitHub App: set "
                "GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY and "
                "GITHUB_APP_INSTALLATION_ID, and grant the app "
                "statuses (commit statuses) permission on this repository."
            ),
            "state": state,
        }
    try:
        token = mint_installation_token(transport=transport)
        status_code, _payload = _api_request(
            "POST",
            f"/repos/{repository_full_name}/statuses/{sha}",
            bearer=token,
            body={
                "state": state,
                "description": description[:MAX_DESCRIPTION],
                "context": context,
                **({"target_url": target_url} if target_url else {}),
            },
        )
    except GitHubAppError as exc:
        logger.warning(
            "GitHub status publish failed repo=%s sha=%.12s code=%s",
            repository_full_name, sha, exc.code,
        )
        return {
            "published": False,
            "reason": exc.code,
            "detail": exc.message,
            "state": state,
        }
    return {"published": True, "state": state, "status_code": status_code,
            "context": context}


def publish_decision(
    repository_full_name: str,
    sha: str,
    decision: dict,
    *,
    target_url: str | None = None,
    transport=None,
) -> dict:
    """Translate a merge decision into a commit status and publish it."""
    body = decision_status_body(decision)
    result = post_commit_status(
        repository_full_name,
        sha,
        state=body["state"],
        description=body["description"],
        context=body["context"],
        target_url=target_url,
        transport=transport,
    )
    result["decision_outcome"] = decision.get("outcome")
    return result
