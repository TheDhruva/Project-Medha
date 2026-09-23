"""Preflight agent — host readiness for planning and optional Docker execution."""

from __future__ import annotations

import os
import platform
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from app.execution.docker_ops import docker_cli_available, docker_daemon_running, is_port_available
from app.models.domain import AgentResult


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def run_preflight(
    *,
    require_git_for_remote: bool,
    is_remote: bool,
    target_port: int | None = None,
    require_docker_for_execute: bool = False,
) -> AgentResult:
    started = _now()
    errors: list[str] = []
    warnings: list[str] = []

    workspace_ok = False
    try:
        tmp = Path(tempfile.gettempdir()) / "medha_preflight_probe"
        tmp.mkdir(parents=True, exist_ok=True)
        probe = tmp / "write_test.txt"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        workspace_ok = True
    except OSError:
        workspace_ok = False
        errors.append("Temporary workspace is not writable")

    checks: dict[str, object] = {
        "os": platform.system(),
        "local_target": True,
        "workspace_writable": workspace_ok,
        "git_available": shutil.which("git") is not None,
        "docker_cli": docker_cli_available(),
        "docker_daemon": False,
        "target_port_available": None,
        "disk_free_mb": None,
    }

    if is_remote and require_git_for_remote and not checks["git_available"]:
        errors.append("git is required for remote repository URLs")

    daemon_ok = docker_daemon_running() if checks["docker_cli"] else False
    checks["docker_daemon"] = daemon_ok
    checks["docker_available"] = bool(checks["docker_cli"] and daemon_ok)

    if require_docker_for_execute:
        if not checks["docker_cli"]:
            errors.append("Docker CLI is required for real Docker execution")
        elif not daemon_ok:
            errors.append("Docker daemon is not running")
    elif not checks["docker_available"]:
        warnings.append("Docker unavailable — real execution will use SimulatorExecutor")

    if target_port is not None:
        port_ok = is_port_available(int(target_port))
        checks["target_port_available"] = port_ok
        if not port_ok:
            # Soft warning at preflight; CNP may remapped; hard check again before execute
            warnings.append(f"Target port {target_port} appears occupied at preflight")

    try:
        usage = shutil.disk_usage(tempfile.gettempdir())
        checks["disk_free_mb"] = int(usage.free / (1024 * 1024))
        if usage.free < 100 * 1024 * 1024:
            warnings.append("Low free disk space (<100MB)")
    except OSError:
        pass

    ok = len(errors) == 0
    if ok and require_docker_for_execute:
        summary = "Host preflight passed for real Docker execution."
    elif ok:
        summary = "Host preflight passed."
    else:
        summary = "; ".join(errors)

    return AgentResult(
        agent="preflight",
        ok=ok,
        started_at=started,
        finished_at=_now(),
        summary=summary,
        artifacts={"checks": checks, "warnings": warnings, "pid": os.getpid()},
        errors=errors,
        is_demo=False,
    )
