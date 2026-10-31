"""Local workspace helpers for shallow clones and fixture analysis."""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from app.core.config import PROJECT_ROOT


def workspaces_root() -> Path:
    root = PROJECT_ROOT / "data" / "workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root


def deployment_workspace(deployment_id: str) -> Path:
    # Deployment ids are server-generated (dep_<hex>); never trust a raw
    # user-supplied path segment here. Reject separators/traversal outright.
    if (
        not deployment_id
        or deployment_id.strip() != deployment_id
        or any(sep in deployment_id for sep in ("/", "\\", "\x00"))
        or deployment_id in {".", ".."}
        or ".." in Path(deployment_id).parts
    ):
        raise ValueError(f"Invalid deployment_id for workspace: {deployment_id!r}")
    path = workspaces_root() / deployment_id
    path.mkdir(parents=True, exist_ok=True)
    return path


import os, stat

def safe_rmtree(path: Path | str) -> None:
    p = Path(path)
    if not os.path.lexists(str(p)):
        return

    def _make_writable(fn, s, exc):
        try:
            os.chmod(s, stat.S_IWRITE)
        except OSError:
            pass
        try:
            fn(s)
        except OSError:
            pass

    for attempt in range(3):
        try:
            if hasattr(shutil, "rmtree") and "onexc" in shutil.rmtree.__code__.co_varnames:
                shutil.rmtree(p, onexc=_make_writable)
            else:
                shutil.rmtree(p, onerror=_make_writable)
            if not os.path.lexists(str(p)):
                return
        except Exception:
            pass
        if attempt < 2:
            time.sleep(0.05)

    if os.name == "nt" and os.path.lexists(str(p)):
        try:
            import subprocess
            subprocess.run(
                ["cmd.exe", "/c", "rd", "/s", "/q", str(p.resolve())],
                capture_output=True,
                timeout=5,
            )
        except Exception:
            pass

def cleanup_workspace(deployment_id: str) -> None:
    path = workspaces_root() / deployment_id
    # Resolve and confine: never delete outside the workspaces root
    # (protects against symlink escape).
    try:
        resolved = path.resolve()
        root = workspaces_root().resolve()
    except OSError:
        return
    if resolved == root or root not in resolved.parents:
        return
    if path.exists() or path.is_symlink():
        safe_rmtree(path)


def prune_stale_workspaces(*, max_age_hours: float = 24) -> int:
    """Remove deployment workspaces older than the TTL. Returns count removed."""
    root = workspaces_root()
    now = time.time()
    removed = 0
    for child in root.iterdir():
        if not child.is_dir() and not child.is_symlink():
            continue
        try:
            age_hours = (now - child.stat().st_mtime) / 3600
        except OSError:
            continue
        if age_hours >= max_age_hours:
            try:
                cleanup_workspace(child.name)
                removed += 1
            except ValueError:
                continue
    return removed


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
