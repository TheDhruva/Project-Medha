"""Local workspace helpers for shallow clones and fixture analysis."""

from __future__ import annotations

import shutil
from pathlib import Path

from app.core.config import PROJECT_ROOT


def workspaces_root() -> Path:
    root = PROJECT_ROOT / "data" / "workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root


def deployment_workspace(deployment_id: str) -> Path:
    path = workspaces_root() / deployment_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def cleanup_workspace(deployment_id: str) -> None:
    path = workspaces_root() / deployment_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def resolve_local_repo_path(repository_url: str) -> Path | None:
    """Return a local path if repository_url points at the filesystem."""
    raw = repository_url.strip()
    if raw.startswith("file://"):
        path_part = raw[7:]
        if path_part.startswith("/") and len(path_part) > 2 and path_part[2] == ":":
            path_part = path_part[1:]
        return Path(path_part)
    candidate = Path(raw)
    if candidate.exists() and candidate.is_dir():
        return candidate.resolve()
    rel = (PROJECT_ROOT / raw).resolve()
    if rel.exists() and rel.is_dir():
        return rel
    return None
