"""Node.js build fixes + honest build-failure diagnostics.

Reproduces the reported failure class: a repository whose `.npmrc`
(`legacy-peer-deps=true`) is required for `npm ci` to resolve the lockfile.
The generated Dockerfile must copy `.npmrc`, must not mask npm's error
(`2>/dev/null`), and must not paper over a failing `npm ci` with a blanket
`npm install`. Build failures must persist structured, redacted diagnostics
(exit code, npm error code, bounded log tail) and never fabricate readiness
or fall back to the simulator.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import types
from pathlib import Path

import pytest

from app.execution import docker_ops
from app.execution.real_executor import RealExecutor


# ------------------------- Dockerfile generation -------------------------


def _next_pkg(root: Path, *, lockfile: bool, npmrc: bool) -> None:
    (root / "package.json").write_text(
        json.dumps({
            "name": "site",
            "scripts": {"build": "next build", "start": "next start"},
            "dependencies": {"next": "15.5.7", "react": "19.1.4"},
        }),
        encoding="utf-8",
    )
    if lockfile:
        (root / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    if npmrc:
        (root / ".npmrc").write_text("legacy-peer-deps=true\n", encoding="utf-8")


def _render(root: Path) -> str:
    from app.execution.profiles import detect_profile, render_dockerfile

    return render_dockerfile(detect_profile(root), checkout=root)


def test_npmrc_is_copied_before_install(tmp_path):
    _next_pkg(tmp_path, lockfile=True, npmrc=True)
    text = _render(tmp_path)
    copy_line = next(line for line in text.splitlines() if line.startswith("COPY"))
    assert ".npmrc*" in copy_line
    install_idx = text.index("RUN npm ci")
    assert text.index(".npmrc*") < install_idx


def test_lockfile_project_uses_npm_ci_without_masking_or_fallback(tmp_path):
    _next_pkg(tmp_path, lockfile=True, npmrc=False)
    text = _render(tmp_path)
    assert "RUN npm ci --no-audit --no-fund\n" in text
    # npm's real error must reach the build log, and a failing npm ci must not
    # be silently downgraded to npm install.
    assert "2>/dev/null" not in text
    assert "|| npm install" not in text


def test_missing_lockfile_uses_npm_install(tmp_path):
    _next_pkg(tmp_path, lockfile=False, npmrc=False)
    text = _render(tmp_path)
    assert "RUN npm install --no-audit --no-fund\n" in text
    assert "npm ci" not in text


def test_legacy_generic_node_install_unchanged(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "node server.js"}}), encoding="utf-8"
    )
    text = _render(tmp_path)
    assert "--omit=dev" in text
    assert "RUN npm run build" not in text


def test_unsupported_package_manager_fails_clearly(tmp_path):
    from app.execution.profiles import BuildProfile, render_dockerfile

    profile = BuildProfile(
        name="nextjs", port=3000, health_path="/", base_image="node:22-slim",
        start_command=["next", "start"], reason="test", package_manager="deno",
        build_command=["deno", "task", "build"],
    )
    with pytest.raises(Exception) as exc:
        render_dockerfile(profile, checkout=tmp_path)
    assert "deno" in str(exc.value)


# ------------------------- docker_ops diagnostics -------------------------


def test_npm_error_code_extraction():
    assert docker_ops._npm_error_code("npm error code ERESOLVE\n") == "ERESOLVE"
    assert docker_ops._npm_error_code("... EUSAGE ...") == "EUSAGE"
    assert docker_ops._npm_error_code("no code here") is None


def test_tail_keeps_the_end_where_the_error_is():
    text = "FIRST\n" + ("x" * 5000) + "\nERESOLVE at the end"
    tail = docker_ops._tail(text, 100)
    assert tail.endswith("ERESOLVE at the end")
    assert len(tail) <= 200  # marker + limit


def _fake_completed(*, returncode: int, stdout: str = "", stderr: str = ""):
    return types.SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def test_build_image_failure_carries_structured_diagnostics(monkeypatch):
    monkeypatch.setattr(docker_ops, "docker_cli_available", lambda: True)
    log = "#1 building...\nnpm error code ERESOLVE\npeer zod conflict\n"
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _fake_completed(returncode=1, stdout="", stderr=log),
    )
    with pytest.raises(docker_ops.DockerOpsError) as exc:
        docker_ops.build_image(context_dir=".", dockerfile="Dockerfile.medha", tag="medha_x")
    err = exc.value
    assert err.code == "BUILD_FAILED"
    assert err.exit_code == 1
    assert err.error_code == "ERESOLVE"
    assert "ERESOLVE" in (err.log or "")
    assert err.log_truncated is False


def test_build_image_failure_truncates_tail_and_flags_it(monkeypatch):
    monkeypatch.setattr(docker_ops, "docker_cli_available", lambda: True)
    huge = "A" * 20000 + "\nnpm error code EUSAGE\n"
    monkeypatch.setattr(
        subprocess, "run",
        lambda *a, **k: _fake_completed(returncode=1, stdout="", stderr=huge),
    )
    with pytest.raises(docker_ops.DockerOpsError) as exc:
        docker_ops.build_image(context_dir=".", dockerfile="Dockerfile.medha", tag="medha_x")
    assert exc.value.log_truncated is True
    assert "EUSAGE" in (exc.value.log or "")


# ------------------------- RealExecutor failure handling -------------------------


def _next_checkout(tmp_path: Path) -> Path:
    _next_pkg(tmp_path, lockfile=True, npmrc=True)
    return tmp_path


def _real_mode(monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("MEDHA_ENV", "development")
    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(docker_ops, "docker_cli_available", lambda: True)
    monkeypatch.setattr(docker_ops, "docker_daemon_running", lambda: True)


def test_real_build_failure_persists_diagnostics_and_no_readiness(tmp_path, monkeypatch):
    _real_mode(monkeypatch)

    def _boom(**kwargs):
        raise docker_ops.DockerOpsError(
            "Image build failed (npm ERESOLVE) (exit=1): ...",
            code="BUILD_FAILED",
            log="npm error code ERESOLVE\npeer zod conflict sk-abcdefgh12345678\n",
            exit_code=1,
            error_code="ERESOLVE",
            log_truncated=False,
        )

    monkeypatch.setattr(docker_ops, "build_image", _boom)
    outcome = asyncio.run(
        RealExecutor().deploy(
            deployment_id="dep_noddiag", checkout=_next_checkout(tmp_path),
            target_port=3000,
        )
    )
    assert outcome.ok is False
    assert outcome.code == "BUILD_FAILED"
    assert outcome.execution_mode == "real"
    assert outcome.readiness == {}  # a build failure never fabricates readiness
    build = outcome.build
    assert build["stage"] == "build"
    assert build["exit_code"] == 1
    assert build["error_code"] == "ERESOLVE"
    assert build["package_manager"] == "npm"
    assert "npm ci" in build["command"]
    assert build["log_truncated"] is False
    # Secrets never reach persisted diagnostics.
    assert "sk-abcdefgh12345678" not in build["log"]
    assert "[redacted]" in build["log"]


def test_real_build_failure_never_invokes_simulator(tmp_path, monkeypatch):
    _real_mode(monkeypatch)
    from app.execution.executor import SimulatorExecutor

    def _boom(**kwargs):
        raise docker_ops.DockerOpsError("build failed", code="BUILD_FAILED", log="err")

    monkeypatch.setattr(docker_ops, "build_image", _boom)
    monkeypatch.setattr(
        SimulatorExecutor, "execute",
        lambda self, *a, **k: (_ for _ in ()).throw(AssertionError("simulator used")),
    )
    outcome = asyncio.run(
        RealExecutor().deploy(
            deployment_id="dep_nosim", checkout=_next_checkout(tmp_path),
            target_port=3000,
        )
    )
    assert outcome.ok is False and outcome.execution_mode == "real"
