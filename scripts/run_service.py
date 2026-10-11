"""Single-service process supervisor: FastAPI + Next.js behind one origin.

Runs uvicorn (loopback-only backend) and `next start` (public $PORT frontend,
which proxies /api/* and /health to the backend) as child processes.

Supervision rule: the first child to exit wins. The supervisor terminates the
survivor and exits with the failed child's code (or non-zero), so Render
restarts the service instead of serving half a system. SIGTERM/SIGINT are
forwarded to both children.

Stdlib only (AGENTS.md rule 17: no new dependencies for hosting).
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"

DEFAULT_BACKEND_HOST = "127.0.0.1"
DEFAULT_BACKEND_PORT = "8000"
DEFAULT_PUBLIC_PORT = "3000"
SHUTDOWN_GRACE_SECONDS = 10.0
POLL_INTERVAL_SECONDS = 0.5


def build_backend_command(
    python_exe: str, backend_dir: Path, host: str, port: str
) -> list[str]:
    """Uvicorn serving the FastAPI app. No --reload in production."""
    return [
        python_exe,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        host,
        "--port",
        str(port),
    ]


def build_frontend_command() -> list[str]:
    """`next start` honors $PORT from its environment (set by the caller)."""
    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm not found on PATH; cannot start Next.js frontend")
    return [npm, "start"]


def _terminate(proc: subprocess.Popen, grace: float) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def supervise(
    backend_cmd: list[str],
    frontend_cmd: list[str],
    *,
    backend_dir: Path = BACKEND_DIR,
    frontend_dir: Path = FRONTEND_DIR,
    extra_env: dict[str, str] | None = None,
    grace_seconds: float = SHUTDOWN_GRACE_SECONDS,
    poll_interval: float = POLL_INTERVAL_SECONDS,
) -> int:
    """Start both children; return when either exits. Returns exit code."""
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    stop = False

    procs = {
        "backend": subprocess.Popen(backend_cmd, cwd=str(backend_dir), env=env),
        "frontend": subprocess.Popen(frontend_cmd, cwd=str(frontend_dir), env=env),
    }

    def _on_signal(signum, _frame):  # noqa: ANN001, ANN202
        nonlocal stop
        stop = True
        for proc in procs.values():
            _terminate(proc, grace_seconds)
        sys.exit(128 + signum)

    old_handlers = {}
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            old_handlers[sig] = signal.signal(sig, _on_signal)
        except (OSError, ValueError):
            pass
    try:
        while True:
            if stop:
                return 128 + int(signal.SIGTERM)
            for name, proc in procs.items():
                code = proc.poll()
                if code is not None:
                    print(f"[run_service] {name} exited with code {code}; stopping.", flush=True)
                    for other_name, other in procs.items():
                        if other_name != name:
                            _terminate(other, grace_seconds)
                    return code if code != 0 else 1
            time.sleep(poll_interval)
    finally:
        for sig, handler in old_handlers.items():
            try:
                signal.signal(sig, handler)
            except (OSError, ValueError):
                pass


def main() -> int:
    backend_host = os.environ.get("MEDHA_BACKEND_HOST", DEFAULT_BACKEND_HOST)
    backend_port = os.environ.get("MEDHA_BACKEND_PORT", DEFAULT_BACKEND_PORT)
    public_port = os.environ.get("PORT", DEFAULT_PUBLIC_PORT)

    backend_cmd = build_backend_command(
        sys.executable, BACKEND_DIR, backend_host, backend_port
    )
    frontend_cmd = build_frontend_command()
    print(
        f"[run_service] backend={' '.join(backend_cmd)} "
        f"frontend={' '.join(frontend_cmd)} public_port={public_port}",
        flush=True,
    )
    extra_env = {
        "PORT": public_port,  # honored by `next start`
    }
    return supervise(backend_cmd, frontend_cmd, extra_env=extra_env)


if __name__ == "__main__":
    sys.exit(main())
