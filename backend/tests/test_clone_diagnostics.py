"""Clone-failure diagnostics: classification, sanitized tails, phase snapshot.

Covers the verified vercel/next.js incident: Windows MAX_PATH checkout abort
(exit 128, "Filename too long"), progress-noise-free summaries, structured
failure records, and the authoritative terminal phase snapshot. No real
network or clones: subprocess and the pipeline boundary are mocked.

Terminal-phase invariants asserted here (authoritative, persisted):
- clone/checkout failure  -> preflight completed, analyze failed,
  plan/cnp/verify/execute blocked (prerequisite failed).
- config/target blocks     -> analysis complete, later phases skipped.
- unknown failure point    -> no fabricated "completed" beyond real evidence.
"""

from __future__ import annotations

import subprocess as sp
from pathlib import Path

import pytest

from app.services.git_service import (
    GitAcquireError,
    _classify_git_stderr,
    _git_fatal_summary,
    acquire_repository,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"

# Realistic captured stderr from the next.js clone failure (progress lines
# precede the one diagnostic line that matters).
NEXTJS_STDERR = """Cloning into 'repo'...
remote: Enumerating objects: 123456, done.
remote: Counting objects: 100% (567/567), done.
remote: Compressing objects: 100% (300/300), done.
Receiving objects: 100% (123456/123456), 200.00 MiB | 5.00 MiB/s, done.
Resolving deltas: 100% (90000/90000), completed with 500 open objects.
Updating files:  77% (26500/34485)
fatal: cannot create directory at 'test/production/app-dir/route-scoped-cache/app/(source-hash/[id]': Filename too long
warning: Clone succeeded, but checkout failed.
"""

REPO_URL = "https://github.com/vercel/next.js"


def _patch_remote(monkeypatch, tmp_path, run):
    """Isolate acquire_repository: no network, no real workspace, fake git."""
    import app.services.git_service as gs

    monkeypatch.setattr(gs, "_git_available", lambda: True)
    # Connection boundary does DNS; the URL allowlist is not under test here.
    monkeypatch.setattr(gs, "_enforce_connection_boundary", lambda url: None)
    monkeypatch.setattr(gs, "deployment_workspace", lambda dep: tmp_path / dep)
    monkeypatch.setattr(gs.subprocess, "run", run)


def _completed(returncode: int, stderr: str = "", stdout: str = ""):
    return sp.CompletedProcess(args=["git", "clone"], returncode=returncode,
                               stdout=stdout, stderr=stderr)


# --- classifier + summary -------------------------------------------------


def test_classify_git_stderr_categories():
    assert _classify_git_stderr(
        "fatal: cannot create directory at 'x': Filename too long"
    ) == "filesystem"
    assert _classify_git_stderr(
        "fatal: unable to access 'https://github.com/': Could not resolve host: github.com"
    ) == "network"
    assert _classify_git_stderr("remote: Repository not found.") == "not_found"
    assert _classify_git_stderr(
        "fatal: could not read Username for 'https://github.com': terminal prompts disabled"
    ) == "auth"
    assert _classify_git_stderr("error: disk full") == "disk"
    assert _classify_git_stderr("some unstructured complaint") == "unknown"


def test_fatal_summary_keeps_signal_drops_progress_noise():
    summary = _git_fatal_summary(NEXTJS_STDERR)
    assert "Filename too long" in summary
    assert "Updating files" not in summary
    assert "Receiving objects" not in summary
    assert "Cloning into" not in summary


# --- acquire_repository (mocked subprocess) -------------------------------


def test_checkout_failure_carries_structured_diagnostics(monkeypatch, tmp_path):
    calls: list[dict] = []

    def run(cmd, **kwargs):
        calls.append({"cmd": cmd, "env": kwargs.get("env"),
                      "timeout": kwargs.get("timeout")})
        return _completed(128, stderr=NEXTJS_STDERR)

    _patch_remote(monkeypatch, tmp_path, run)
    with pytest.raises(GitAcquireError) as excinfo:
        acquire_repository("dep_test", REPO_URL)
    err = excinfo.value

    assert err.code == "GIT_CHECKOUT_FAILED"
    assert err.exit_code == 128
    assert err.category == "filesystem"
    assert err.operation == "checkout"
    assert err.duration_s is not None and err.duration_s >= 0
    # User-facing summary: the fatal line, never progress noise.
    assert "Filename too long" in err.message
    assert "Updating files" not in err.message
    # Raw tail retained for diagnosis, bounded.
    assert err.stderr_tail and "Filename too long" in err.stderr_tail
    diag = err.to_diagnostics()
    assert diag["exit_code"] == 128
    assert diag["operation"] == "checkout"
    assert diag["category"] == "filesystem"
    # Long-path fix is injected for every git subprocess (Windows MAX_PATH).
    env = calls[0]["env"]
    assert env["GIT_CONFIG_KEY_0"] == "core.longpaths"
    assert env["GIT_CONFIG_VALUE_0"] == "true"
    assert env["GIT_TERMINAL_PROMPT"] == "0"


def test_transport_failure_is_clone_failed_not_checkout(monkeypatch, tmp_path):
    stderr = ("remote: Repository not found.\n"
              "fatal: repository 'https://github.com/404/nope/' not found\n")
    _patch_remote(monkeypatch, tmp_path,
                  lambda cmd, **kw: _completed(128, stderr=stderr))
    with pytest.raises(GitAcquireError) as excinfo:
        acquire_repository("dep_test", "https://github.com/404/nope")
    err = excinfo.value
    assert err.code == "GIT_CLONE_FAILED"
    assert err.operation == "clone"
    assert err.category == "not_found"
    assert "not found" in err.message


def test_warnings_on_successful_clone_are_not_errors(monkeypatch, tmp_path):
    stderr = "warning: --depth is ignored in local clones; use file:// instead.\n"
    _patch_remote(monkeypatch, tmp_path,
                  lambda cmd, **kw: _completed(0, stderr=stderr))
    result = acquire_repository("dep_test", REPO_URL)
    assert result.method == "shallow_clone"
    assert result.checked_sha is None


def test_clone_timeout_is_classified(monkeypatch, tmp_path):
    def run(cmd, **kw):
        raise sp.TimeoutExpired(cmd="git clone", timeout=600,
                                stderr=b"Cloning into 'repo'...\n")

    _patch_remote(monkeypatch, tmp_path, run)
    with pytest.raises(GitAcquireError) as excinfo:
        acquire_repository("dep_test", REPO_URL)
    err = excinfo.value
    assert err.code == "GIT_TIMEOUT"
    assert err.category == "timeout"
    assert err.operation == "clone"
    assert err.duration_s is not None


def test_diagnostics_redact_credentials(monkeypatch, tmp_path):
    stderr = (
        "fatal: unable to access 'https://user:secret123@github.com/o/r/': "
        "The requested URL returned error: 401\n"
        "hint: Authorization: Bearer ghp_secrettoken99\n"
    )
    _patch_remote(monkeypatch, tmp_path,
                  lambda cmd, **kw: _completed(128, stderr=stderr))
    with pytest.raises(GitAcquireError) as excinfo:
        acquire_repository("dep_test", REPO_URL)
    tail = excinfo.value.stderr_tail or ""
    assert "secret123" not in tail
    assert "ghp_secrettoken99" not in tail
    assert "[redacted]" in tail
    assert "secret123" not in excinfo.value.message


# --- terminal phase snapshot (unit) ---------------------------------------


def _pipeline_with_tracker():
    from app.workflow.planning import PlanningPipeline

    return PlanningPipeline()


def test_terminal_phases_clone_failure_blocks_prerequisites():
    from app.workflow.stages import StageTracker

    pipeline = _pipeline_with_tracker()
    pipeline.tracker = StageTracker()
    pipeline.tracker.finish("preflight", "complete")
    pipeline.tracker.start("analyzer")
    pipeline._active_stage = "ANALYZE"

    phases = {p["id"]: p for p in pipeline._terminal_phases(
        "git.GIT_CHECKOUT_FAILED", "Shallow clone failed: Filename too long")}

    assert phases["preflight"]["status"] == "completed"
    assert phases["analyze"]["status"] == "failed"
    assert "Filename too long" in phases["analyze"]["reason"]
    for later in ("plan", "cnp", "verify", "execute"):
        assert phases[later]["status"] == "blocked", later
        assert phases[later]["reason"]


def test_terminal_phases_execution_not_configured_skips_not_fails():
    from app.workflow.stages import StageTracker

    pipeline = _pipeline_with_tracker()
    pipeline.tracker = StageTracker()
    for aid in ("preflight", "analyzer", "docker", "nginx", "security",
                "mediator", "verifier", "critic"):
        pipeline.tracker.finish(aid, "complete")
    pipeline._active_stage = "EXECUTE"

    phases = {p["id"]: p for p in pipeline._terminal_phases(
        "EXECUTION_NOT_CONFIGURED", "Execution not configured.")}

    for done in ("preflight", "analyze", "plan", "cnp", "verify"):
        assert phases[done]["status"] == "completed", done
    assert phases["execute"]["status"] == "skipped"


def test_terminal_phases_analysis_complete_block_skips_later_phases():
    from app.workflow.stages import StageTracker

    pipeline = _pipeline_with_tracker()
    pipeline.tracker = StageTracker()
    pipeline.tracker.finish("preflight", "complete")
    pipeline.tracker.finish("analyzer", "complete")
    pipeline._active_stage = "ANALYZE"

    phases = {p["id"]: p for p in pipeline._terminal_phases(
        "MULTIPLE_APPS_REQUIRE_TARGET", "Multiple apps require a target.")}

    assert phases["preflight"]["status"] == "completed"
    assert phases["analyze"]["status"] == "completed"
    for later in ("plan", "cnp", "verify", "execute"):
        assert phases[later]["status"] == "skipped", later


def test_terminal_phases_no_failure_point_fabricates_nothing():
    from app.workflow.stages import StageTracker

    pipeline = _pipeline_with_tracker()
    pipeline.tracker = StageTracker()
    pipeline.tracker.finish("preflight", "complete")
    pipeline._active_stage = None  # e.g. failure before ANALYZE was recorded

    phases = {p["id"]: p for p in pipeline._terminal_phases(
        "PIPELINE_ERROR", "Something upstream broke.")}

    assert phases["preflight"]["status"] == "completed"
    # No evidence of completion and no failure point: honest "pending".
    for later in ("analyze", "plan", "cnp", "verify", "execute"):
        assert phases[later]["status"] == "pending", later


# --- pipeline-level: persisted failure record + phases via API ------------


def _wait_terminal(client, deployment_id: str, timeout: float = 60.0) -> dict:
    import time

    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def test_pipeline_clone_failure_persists_failure_and_phases(client, monkeypatch):
    """End-to-end: checkout failure -> structured record, phases, kept SHA.

    Mirrors the real incident (remote repo, SHA pinned via ls-remote, then
    checkout failure on Windows long paths): the run must fail with real
    diagnostics, keep the resolved SHA, and record which phases never ran.
    """
    import app.services.git_service as gs
    import app.workflow.planning as planning
    from tests.conftest import _deploy_payload

    resolved = "a" * 40  # what ls-remote would have pinned before the clone

    monkeypatch.setattr(gs, "resolve_ref_to_sha", lambda *a, **kw: resolved)
    # Public github.com URL, no GitHub App configured -> no token, no network.

    def failing_acquire(deployment_id, url, **kwargs):
        raise GitAcquireError(
            "GIT_CHECKOUT_FAILED",
            "Shallow clone failed: fatal: cannot create directory at "
            "'.../(very/long/path)': Filename too long",
            operation="checkout",
            exit_code=128,
            duration_s=72.5,
            stderr_tail=NEXTJS_STDERR[-500:],
            category="filesystem",
        )

    monkeypatch.setattr(planning, "acquire_repository", failing_acquire)
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(
            mode="real", scenario=None,
            repository_url="https://github.com/vercel/next.js",
        ),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])

    assert final["status"] == "failed"
    result = final.get("result") or {}
    # Code names the real git outcome, not a generic pipeline error.
    assert result.get("code") == "git.GIT_CHECKOUT_FAILED"
    # Structured failure record: operation / exit code / category / tail.
    failure = result.get("failure") or {}
    assert failure.get("exit_code") == 128
    assert failure.get("operation") == "checkout"
    assert failure.get("category") == "filesystem"
    assert "Filename too long" in (final.get("error_summary") or "")
    assert "Updating files" not in (final.get("error_summary") or "")
    # Revision was pinned before acquisition — never "Revision Unknown".
    assert result.get("target_sha") == resolved
    # Authoritative phase snapshot: failed phase vs never-started phases.
    phases = {p["id"]: p for p in (result.get("phases") or [])}
    assert phases, "phases snapshot missing"
    assert phases["preflight"]["status"] == "completed"
    assert phases["analyze"]["status"] == "failed"
    for later in ("plan", "cnp", "verify", "execute"):
        assert phases[later]["status"] == "blocked", later
    # Detail view: result blob carries the structured record + phases.
    assert (result.get("failure") or {}).get("exit_code") == 128
    # List/overview surface (_run_summary) exposes them at the top level.
    listed = client.get("/api/deploys", params={"repository": "github.com/vercel/next.js"}).json()
    match = [r for r in listed["runs"] if r["deployment_id"] == final["deployment_id"]]
    assert match, "run missing from list endpoint"
    assert (match[0].get("failure") or {}).get("exit_code") == 128
    assert match[0].get("phases")


def test_retry_creates_a_distinct_traceable_attempt(client, monkeypatch):
    """A retry is a new run that points back at the prior one.

    The prior run and its diagnostics stay untouched, and the link
    (retry_of) is persisted so the attempt chain is auditable.
    """
    import app.workflow.planning as planning
    from app.core.deploy_lock import release_real_deploy
    from app.database.repositories import DeploymentRepository, ProjectRepository

    # The pipeline never runs: we only exercise run creation/traceability.
    monkeypatch.setattr(planning, "schedule_planning_pipeline", lambda *a, **k: None)

    created = client.post("/api/projects", json={"repository": "octo/demo"})
    assert created.status_code == 201, created.text
    pid = created.json()["project_id"]
    ProjectRepository().update(pid, connection_status="connected", updated_at="x")

    first = client.post(f"/api/projects/{pid}/runs", json={})
    assert first.status_code == 202, first.text
    prior_id = first.json()["deployment_id"]
    # The mocked pipeline never settles the lock; production releases it.
    release_real_deploy(prior_id)

    retry = client.post(
        f"/api/projects/{pid}/runs", json={"retry_of": prior_id}
    )
    assert retry.status_code == 202, retry.text
    body = retry.json()
    assert body["retry_of"] == prior_id
    assert body["deployment_id"] != prior_id  # distinct, traceable attempt

    repo = DeploymentRepository()
    prior = repo.get(prior_id)
    attempt = repo.get(body["deployment_id"])
    # Link is persisted on the new attempt...
    assert f"retry_of={prior_id}" in (attempt.explain_technical or "")
    # ...and the prior run's record is untouched.
    assert prior is not None
    assert "retry_of=" not in (prior.explain_technical or "")
    release_real_deploy(body["deployment_id"])
