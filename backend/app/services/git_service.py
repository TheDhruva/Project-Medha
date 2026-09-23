"""Git / local repository acquisition (shallow clone when needed)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.services.workspace import deployment_workspace, resolve_local_repo_path

logger = get_logger(__name__)


@dataclass
class RepoAcquisition:
    path: Path
    method: str  # local_copy | local_path | shallow_clone
    cleaned_url: str


class GitAcquireError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def acquire_repository(deployment_id: str, repository_url: str) -> RepoAcquisition:
    """
    Acquire a repository into the deployment workspace.

    Supports:
    - local filesystem paths / file:// URIs (offline-friendly)
    - remote git URLs via shallow clone (requires network + git)
    """
    dest = deployment_workspace(deployment_id) / "repo"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)

    local = resolve_local_repo_path(repository_url)
    if local is not None:
        if not local.exists():
            raise GitAcquireError("REPO_NOT_FOUND", f"Local repository path not found: {local}")
        shutil.copytree(
            local,
            dest,
            ignore=shutil.ignore_patterns(
                ".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist"
            ),
        )
        logger.info("Acquired local repo deployment_id=%s path=%s", deployment_id, local)
        return RepoAcquisition(path=dest, method="local_copy", cleaned_url=str(local))

    # Remote git shallow clone
    if not _git_available():
        raise GitAcquireError(
            "GIT_UNAVAILABLE",
            "git executable not found. Install git or pass a local repository path.",
        )

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                repository_url,
                str(dest),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitAcquireError("GIT_TIMEOUT", "Shallow clone timed out") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()[:500]
        raise GitAcquireError(
            "GIT_CLONE_FAILED",
            f"Shallow clone failed: {stderr or exc}",
        ) from exc

    logger.info("Shallow-cloned repo deployment_id=%s url=%s", deployment_id, repository_url)
    return RepoAcquisition(path=dest, method="shallow_clone", cleaned_url=repository_url)


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
