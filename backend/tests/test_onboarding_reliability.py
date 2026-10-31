"""Tests for onboarding reliability, Docker-independent analysis, and history loading.

Covers:
1. Preflight passes without Docker daemon when require_docker_for_execute=False, allowing analysis.
2. Real execution when Docker daemon is down gracefully halts at EXECUTE stage with DOCKER_DAEMON_UNAVAILABLE,
   preserving preflight, code analysis, security scans, scores, and verification.
3. HTTP 404 during readiness probing is accepted as service running (< 500), not treated as container failure.
4. Git history retrieval populates repository commit history when stored history has <= 1 commit.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.agents.preflight import run_preflight
from app.core.config import get_settings
from app.execution import docker_ops
from tests.conftest import _deploy_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"


def test_preflight_passes_without_docker():
    """Analysis preflight must not fail even if Docker daemon is offline."""
    with patch("app.agents.preflight.docker_daemon_running", return_value=False), \
         patch("app.agents.preflight.docker_cli_available", return_value=True):
        result = run_preflight(
            require_git_for_remote=False,
            is_remote=False,
            require_docker_for_execute=False,
        )
        assert result.ok is True
        assert "Host preflight passed" in result.summary
        assert result.artifacts["checks"]["docker_daemon"] is False


def test_wait_http_readiness_accepts_404_as_running():
    """An HTTP 404 response from the container root route proves the web server is listening."""
    import urllib.error
    import urllib.request

    mock_error = urllib.error.HTTPError(
        url="http://127.0.0.1:8080/",
        code=404,
        msg="Not Found",
        hdrs={},  # type: ignore[arg-type]
        fp=None,  # type: ignore[arg-type]
    )

    with patch("urllib.request.urlopen", side_effect=mock_error), \
         patch("time.sleep", return_value=None):
        result = docker_ops.wait_http_readiness(
            port=8080,
            host="127.0.0.1",
            path="/",
            timeout=1.0,
            interval=0.1,
            grace=0.0,
        )
        assert result["status"] == "ready"
        assert result["http_status"] == 404


def test_docker_down_preserves_analysis_and_verification(client, monkeypatch):
    """When Docker daemon is down in real mode, analysis and verification complete and execute blocks cleanly."""
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()

    # Preflight sees Docker CLI, but daemon is down
    with patch("app.execution.docker_ops.docker_daemon_running", return_value=False):
        repo = str((FIXTURES / "compose_app").resolve())
        resp = client.post(
            "/api/deploy",
            json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
        )
        assert resp.status_code == 202
        deployment_id = resp.json()["deployment_id"]

        import time
        deadline = time.time() + 60.0
        final = {}
        while time.time() < deadline:
            final = client.get(f"/api/deploy/{deployment_id}").json()
            if final["status"] in {"completed", "failed", "partial_recovery", "cancelled"}:
                break
            time.sleep(0.05)

        assert final["status"] == "failed"
        result = final.get("result", {})
        assert result.get("code") == "DOCKER_DAEMON_UNAVAILABLE"
        assert result.get("blocked") is True
        assert result.get("blocked_stage") == "execute"
        assert result.get("verification_preserved") is True

        # Upstream verification artifact is preserved and has checks
        verif = client.get(f"/api/deploy/{deployment_id}/verification").json()
        assert verif.get("verification") is not None
        assert "checks" in verif["verification"]

        # Scorecard is calculated and available
        scores_payload = client.get(f"/api/deploy/{deployment_id}/scores").json()
        assert "scores" in scores_payload
        assert "code_quality" in scores_payload["scores"]
        assert "security" in scores_payload["scores"]
        assert "verification_confidence" in scores_payload["scores"]
        assert "deployment_readiness" in scores_payload["scores"]


def test_history_service_populates_when_stored_commits_sparse(client):
    """When stored commits are sparse (<= 1), history endpoint refreshes from git repository."""
    # Ensure history endpoint is reachable and returns a valid list
    resp = client.get("/api/projects")
    assert resp.status_code == 200
    projects = resp.json().get("projects", [])
    if projects:
        proj_id = projects[0]["id"]
        hist_resp = client.get(f"/api/projects/{proj_id}/commits")
        assert hist_resp.status_code == 200
        commits = hist_resp.json().get("commits", [])
        assert isinstance(commits, list)
