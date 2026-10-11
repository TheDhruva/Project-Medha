"""Unit tests for scripts/run_service.py (stdlib supervisor, no network)."""

from __future__ import annotations

import sys
from pathlib import Path

import run_service


def _stub(code: int = 0, sleep_seconds: float = 0.0) -> list[str]:
    # A child that exits (almost) immediately, or sleeps for supervision tests.
    if sleep_seconds:
        return [
            sys.executable,
            "-c",
            f"import time; time.sleep({sleep_seconds})",
        ]
    return [sys.executable, "-c", f"raise SystemExit({code})"]


def test_build_backend_command_shape(tmp_path: Path):
    cmd = run_service.build_backend_command(sys.executable, tmp_path, "127.0.0.1", "8000")
    assert cmd[:3] == [sys.executable, "-m", "uvicorn"]
    assert "app.main:app" in cmd
    assert "--reload" not in cmd
    assert cmd[cmd.index("--host") + 1] == "127.0.0.1"
    assert cmd[cmd.index("--port") + 1] == "8000"


def test_build_frontend_command_uses_npm_start():
    cmd = run_service.build_frontend_command()
    assert cmd[-2:] == ["npm", "start"] or cmd[-1] == "start"


def test_first_exit_wins_and_propagates_code(tmp_path: Path):
    code = run_service.supervise(
        _stub(code=3),
        _stub(sleep_seconds=60),
        backend_dir=tmp_path,
        frontend_dir=tmp_path,
        poll_interval=0.05,
    )
    assert code == 3


def test_zero_exit_still_counts_as_failure(tmp_path: Path):
    # A child exiting 0 on its own means the pair is broken (e.g. instant
    # crash-loop); the supervisor must not report healthy.
    code = run_service.supervise(
        _stub(sleep_seconds=60),
        _stub(code=0),
        backend_dir=tmp_path,
        frontend_dir=tmp_path,
        poll_interval=0.05,
    )
    assert code != 0
