"""Live Docker test: pinned Lead_Website revision, real build + readiness.

Runs only when MEDHA_E2E_REAL=1 AND a Docker daemon is reachable. Clones the
exact pinned commit, builds the controlled MEDHA image (pnpm + next build),
and requires the readiness contract to pass. Any failure is reported with
its classified stage — never rewritten as success.
"""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from app.execution import docker_ops

LEAD_URL = "https://github.com/TheDhruva/Lead_Website"
LEAD_SHA = "ad51b8b30ffa550c427f6836b1b64ab0b8393ae4"

LIVE = os.environ.get("MEDHA_E2E_REAL") == "1"
HAS_DOCKER = shutil.which("docker") is not None and docker_ops.docker_daemon_running()

pytestmark = pytest.mark.skipif(
    not (LIVE and HAS_DOCKER),
    reason="live E2E needs MEDHA_E2E_REAL=1 and a Docker daemon",
)


def _git(*args: str, cwd: str) -> None:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, f"git {' '.join(args)} failed: {proc.stderr[:500]}"


def test_lead_website_pinned_revision_ready(tmp_path, monkeypatch):
    import asyncio

    from app.core.config import get_settings
    from app.execution.real_executor import RealExecutor

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()

    checkout = tmp_path / "lead"
    checkout.mkdir()
    _git("init", "-q", cwd=str(checkout))
    _git("remote", "add", "origin", LEAD_URL, cwd=str(checkout))
    _git("fetch", "--depth", "1", "origin", LEAD_SHA, cwd=str(checkout))
    _git("checkout", LEAD_SHA, cwd=str(checkout))
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(checkout), capture_output=True,
        text=True, timeout=30,
    ).stdout.strip().lower()
    assert head == LEAD_SHA, f"checkout {head} != pinned {LEAD_SHA}"

    port = next(
        (p for p in range(18080, 18090) if docker_ops.is_port_available(p)),
        None,
    )
    assert port is not None, "no free loopback port for the live test"

    deployment_id = "dep_leadlive"
    outcome = asyncio.run(
        RealExecutor().deploy(
            deployment_id=deployment_id,
            checkout=checkout,
            target_port=port,
            commit_sha=LEAD_SHA,
            readiness_timeout=180,
            build_timeout=900,
        )
    )
    try:
        assert outcome.ok, (
            f"code={outcome.code} stage={outcome.readiness.get('stage')} "
            f"message={outcome.message[:1500]}"
        )
        assert outcome.readiness.get("stage") == "ready"
        assert outcome.readiness.get("probe_url") == f"http://127.0.0.1:{port}/"
        assert outcome.readiness.get("mapping") == (
            f"host 127.0.0.1:{port} → container:{outcome.runtime_spec['internal_port']}"
        )
        assert outcome.runtime_spec["profile"] == "nextjs"
        assert outcome.runtime_spec["commit_sha"] == LEAD_SHA
        assert outcome.runtime_spec["package_manager"] == "pnpm"
    finally:
        asyncio.run(
            RealExecutor().cleanup(
                deployment_id=deployment_id, container=outcome.container,
                image=outcome.image,
            )
        )
