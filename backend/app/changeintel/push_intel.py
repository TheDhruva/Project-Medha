"""Push-payload change intelligence (Phase 2b).

For local git repositories the full diff pipeline (`engine.analyze_change_impact`)
compares base → target revisions. Remote clones arrive as a single checked-out
commit, so this module derives an equivalent, honestly-labelled analysis from
two trusted sources:

1. the verified GitHub push payload (`commits[]` added/removed/modified lists),
2. the exact-SHA checkout produced by `git_service` (files verified present).

Every artifact carries ``source_method="webhook_push"`` and records which
payload files were confirmed in the tree. Files the payload claims but the
tree lacks are reported as unverified, never silently dropped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.changeintel import cig as cig_builder
from app.changeintel.dep_index import build_index
from app.changeintel.models import (
    ChangeImpactAnalysis,
    ChangeSet,
    ChangeType,
    FileChange,
    Symbol,
)
from app.changeintel.requirements import generate_requirements
from app.changeintel.risk import assess_risk
from app.core.events import utc_now_iso
from app.core.logging import get_logger

logger = get_logger(__name__)

ZERO_SHA = "0" * 40
MAX_COMMITS = 20
MAX_PATHS_PER_LIST = 50
MAX_FILES_TOTAL = 200
MAX_MESSAGE_LEN = 200


def _is_zero_sha(value: str | None) -> bool:
    return bool(value) and value.strip().lower() == ZERO_SHA


def _clean_paths(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        path = item.strip().replace("\\", "/")
        while path.startswith("./"):
            path = path[2:]
        if not path or path.startswith("/") or ".." in Path(path).parts:
            continue
        cleaned.append(path)
    return cleaned[:MAX_PATHS_PER_LIST]


def summarize_push(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract a bounded, JSON-safe push summary from a push payload.

    Handles initial pushes (``before`` all-zero → base None), deleted
    branches (``after`` all-zero → deleted True), and empty commit lists.
    """
    after = str(payload.get("after") or "")
    before = str(payload.get("before") or "")
    deleted = _is_zero_sha(after) and bool(after)
    raw_commits = payload.get("commits")
    commits: list[dict[str, Any]] = []
    if isinstance(raw_commits, list):
        for entry in raw_commits[:MAX_COMMITS]:
            if not isinstance(entry, dict):
                continue
            message = str(entry.get("message") or "")[:MAX_MESSAGE_LEN]
            commits.append(
                {
                    "id": str(entry.get("id") or ""),
                    "message": message,
                    "added": _clean_paths(entry.get("added")),
                    "removed": _clean_paths(entry.get("removed")),
                    "modified": _clean_paths(entry.get("modified")),
                }
            )
    truncated = isinstance(raw_commits, list) and len(raw_commits) > MAX_COMMITS
    added: list[str] = []
    modified: list[str] = []
    removed: list[str] = []
    for commit in commits:
        added.extend(commit["added"])
        modified.extend(commit["modified"])
        removed.extend(commit["removed"])
    # De-duplicate while preserving order; deletions win over modifications.
    removed_set = set(removed)
    modified = [p for p in modified if p not in removed_set]
    added = [p for p in added if p not in removed_set]
    seen: set[str] = set()
    files: list[dict[str, str]] = []
    for path in added:
        if path not in seen:
            seen.add(path)
            files.append({"path": path, "change_type": ChangeType.ADDED.value})
    for path in modified:
        if path not in seen:
            seen.add(path)
            files.append({"path": path, "change_type": ChangeType.MODIFIED.value})
    for path in removed:
        if path not in seen:
            seen.add(path)
            files.append({"path": path, "change_type": ChangeType.DELETED.value})
    files_truncated = len(files) >= MAX_FILES_TOTAL
    files = files[:MAX_FILES_TOTAL]
    return {
        "deleted": deleted,
        "base_sha": None if _is_zero_sha(before) or not before else before,
        "target_sha": None if deleted else (after or None),
        "commit_count": len(commits),
        "commits_truncated": truncated,
        "commits": commits,
        "files": files,
        "files_truncated": files_truncated,
    }


def analyze_push_checkout(
    *,
    repository_url: str,
    base_sha: str | None,
    target_sha: str,
    files: list[dict[str, str]],
    checkout_path: Path,
    deployment_id: str | None = None,
) -> ChangeImpactAnalysis:
    """Build a ChangeImpactAnalysis from payload files + the checked-out tree.

    Payload-claimed files are verified against the tree: present files are
    analyzed (symbols indexed from the checkout), missing files are listed in
    ``unsupported`` with a ``missing-in-tree`` note instead of being trusted.
    """
    verified: list[FileChange] = []
    missing: list[str] = []
    for entry in files:
        rel = entry.get("path", "")
        change_type = entry.get("change_type") or ChangeType.MODIFIED.value
        try:
            ctype = ChangeType(change_type)
        except ValueError:
            ctype = ChangeType.MODIFIED
        if ctype == ChangeType.DELETED:
            verified.append(FileChange(path=rel, change_type=ctype))
            continue
        candidate = (checkout_path / rel).resolve()
        try:
            inside = checkout_path.resolve() in candidate.parents
        except OSError:
            inside = False
        if inside and candidate.is_file():
            verified.append(FileChange(path=rel, change_type=ctype))
        else:
            missing.append(f"{rel} (payload-claimed, missing in checked-out tree)")
    changeset = ChangeSet(
        base_revision=(base_sha or target_sha)[:12],
        target_revision=target_sha[:12],
        base_sha=base_sha or target_sha,
        target_sha=target_sha,
        source_method="webhook_push",
        is_git=True,
        files=verified,
        unsupported_files=missing,
    )
    index = build_index(checkout_path)
    base_side: dict[str, Symbol] = {}
    changed_symbols = cig_builder.detect_changed_symbols(changeset, index, base_side)
    graph, traversal, unresolved = cig_builder.build_cig(
        changeset, changed_symbols, index, base_side
    )
    risk = assess_risk(changeset, graph, changed_symbols, unresolved, traversal)
    requirements = generate_requirements(changeset, graph, unresolved, traversal)
    analysis = ChangeImpactAnalysis(
        deployment_id=deployment_id,
        repository_url=repository_url,
        changeset=changeset,
        changed_symbols=changed_symbols,
        graph=graph,
        traversal=traversal,
        unresolved=unresolved,
        risk=risk,
        requirements=requirements,
        generated_at=utc_now_iso(),
    )
    logger.info(
        "Push change intel repo=%s target=%.12s files=%d missing=%d nodes=%d risk=%s",
        repository_url,
        target_sha,
        len(verified),
        len(missing),
        len(graph.nodes),
        risk.level.value,
    )
    return analysis
