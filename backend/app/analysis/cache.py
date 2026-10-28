"""Validated reuse of revision-scoped repository inventory results.

Key design: the cache key commits to everything that can change the result —
the exact commit SHA, the selected target, which scanners run, the scanner
timeout, and a signature of the installed scanner binaries (path, mtime,
size — so a tool upgrade invalidates). A new commit or a changed
configuration naturally produces a new key; there is no time-based staleness.

Reads/writes are best-effort and never raise: a cache problem degrades to a
fresh analysis, never to a failed run. Results for runs without an immutable
commit SHA are never cached (nothing guarantees invalidation).
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from app.core.events import utc_now_iso
from app.database.repositories import AnalysisCacheRepository

CACHE_KIND = "repository-inventory/v1"


def tool_signature() -> str:
    """Identity of each optional scanner binary (absent or path+mtime+size)."""
    from app.security import scanners

    parts: list[str] = []
    for name in scanners.supported_scanners():
        exe = shutil.which(name)
        if not exe:
            parts.append(f"{name}=absent")
            continue
        try:
            st = Path(exe).stat()
            parts.append(f"{name}={st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{name}=unknown")
    return ";".join(parts)


def inventory_cache_key(*, commit_sha: str | None, selected_target: str | None,
                        scan_security: bool, scanner_names: list[str] | None,
                        scanner_timeout_s: float) -> str | None:
    """Cache key for an inventory build, or None when it must not be cached."""
    if not commit_sha:
        return None
    payload = json.dumps(
        {
            "kind": CACHE_KIND,
            "commit_sha": commit_sha,
            "selected_target": selected_target,
            "scan_security": scan_security,
            "scanner_names": scanner_names,
            "scanner_timeout_s": scanner_timeout_s,
            "tools": tool_signature(),
        },
        sort_keys=True,
        default=str,
    )
    return "inv:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_inventory(cache_key: str | None) -> dict[str, Any] | None:
    """Return a cached inventory payload, or None on miss/error."""
    if not cache_key:
        return None
    try:
        row = AnalysisCacheRepository().get(cache_key)
    except Exception:  # noqa: BLE001 - cache is best-effort
        return None
    if not row:
        return None
    payload = row.get("payload")
    if not isinstance(payload, dict) or payload.get("schema") != "repository-analysis/v1":
        return None
    return payload


def store_inventory(cache_key: str | None, payload: dict[str, Any], *,
                    project_id: str | None, target_sha: str) -> None:
    """Persist an inventory payload for reuse. Never raises."""
    if not cache_key or not isinstance(payload, dict):
        return
    if payload.get("schema") != "repository-analysis/v1":
        return
    if payload.get("analysis_status") == "failed":
        # A failed analysis is not a reusable result.
        return
    try:
        AnalysisCacheRepository().put(
            cache_key=cache_key,
            project_id=project_id,
            kind=CACHE_KIND,
            inputs_hash=cache_key,
            target_sha=target_sha or "",
            created_at=utc_now_iso(),
            payload=payload,
        )
    except Exception:  # noqa: BLE001 - cache is best-effort
        return
