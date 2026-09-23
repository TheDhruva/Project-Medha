"""Git revision resolution and deterministic change extraction (Phase 2).

Wraps the system `git` executable (already a MEDHA runtime dependency) and
produces a structured ChangeSet: per-file change type, hunk line ranges, and
added/deleted line counts. Renames are detected so they are not misreported as
delete+add. No fabricated diffs: every result is derived from real `git diff`
output.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.changeintel.models import ChangeSet, ChangeType, FileChange, Hunk
from app.core.logging import get_logger

logger = get_logger(__name__)

_HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

# git name-status letters handled as change types
_STATUS_MAP = {
    "A": ChangeType.ADDED,
    "M": ChangeType.MODIFIED,
    "D": ChangeType.DELETED,
    "T": ChangeType.MODIFIED,  # type change (mode) — treat as modified
    "C": ChangeType.ADDED,  # copy — treat as added for impact purposes
}


class ChangeIntelError(Exception):
    """Typed error surfaced through the API with an explicit code."""

    def __init__(self, code: str, message: str, **details: object) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details: dict[str, object] = details


def _run_git(repo_path: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired as exc:
        raise ChangeIntelError("GIT_TIMEOUT", "git operation timed out") from exc
    except OSError as exc:
        raise ChangeIntelError("GIT_UNAVAILABLE", "git executable not found") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:400]
        raise ChangeIntelError("GIT_COMMAND_FAILED", stderr or proc.returncode)
    return proc.stdout


def is_git_repository(repo_path: Path) -> bool:
    try:
        _run_git(repo_path, "rev-parse", "--git-dir")
        return True
    except ChangeIntelError:
        return False


def resolve_revision(repo_path: Path, revision: str) -> str:
    """Resolve a revision to a full commit sha, with explicit errors."""
    if not revision or not revision.strip():
        raise ChangeIntelError(
            "REVISION_INVALID", "Revision must not be empty", revision=revision
        )
    if not is_git_repository(repo_path):
        raise ChangeIntelError(
            "NOT_A_GIT_REPOSITORY",
            "Workspace is not a git repository; change analysis requires git history.",
        )
    try:
        sha = _run_git(repo_path, "rev-parse", "--verify", f"{revision}^{{commit}}")
    except ChangeIntelError as exc:
        raise ChangeIntelError(
            "REVISION_NOT_FOUND",
            f"Revision '{revision}' could not be resolved to a commit.",
            revision=revision,
        ) from exc
    return sha.strip()


def read_blob(repo_path: Path, revision: str, path: str) -> str | None:
    """Read a file at a revision (used for deleted/renamed base side)."""
    try:
        return _run_git(repo_path, "show", f"{revision}:{path}")
    except ChangeIntelError:
        return None


def extract_changeset(
    repo_path: Path,
    base_revision: str,
    target_revision: str,
    source_method: str,
) -> ChangeSet:
    """Diff base..target and build a structured, evidence-based ChangeSet."""
    if not is_git_repository(repo_path):
        raise ChangeIntelError(
            "NOT_A_GIT_REPOSITORY",
            "Change analysis requires a git repository with commit history.",
        )

    base_sha = resolve_revision(repo_path, base_revision)
    target_sha = resolve_revision(repo_path, target_revision)
    if base_sha == target_sha:
        raise ChangeIntelError(
            "IDENTICAL_REVISIONS",
            "base_revision and target_revision resolve to the same commit.",
            base=base_sha,
            target=target_sha,
        )

    # --no-ext-diff: never invoke external diff drivers. -M: rename detection.
    name_status = _run_git(
        repo_path,
        "diff",
        "--no-ext-diff",
        "-M",
        "--name-status",
        base_sha,
        target_sha,
        "--",
        ".",
    )

    files: list[FileChange] = []
    for raw_line in name_status.splitlines():
        if not raw_line.strip():
            continue
        entry = _parse_name_status(raw_line)
        if entry is None:
            continue
        if len(entry) == 3:
            status, old_path, path = entry
        else:
            status, path = entry
            old_path = None

        change_type = _STATUS_MAP.get(status, ChangeType.MODIFIED)
        if status == "R" and old_path:
            change_type = ChangeType.RENAMED

        added, deleted, hunks = _diff_hunks(repo_path, base_sha, target_sha, path)
        files.append(
            FileChange(
                path=path,
                change_type=change_type,
                old_path=old_path,
                added_lines=added,
                deleted_lines=deleted,
                hunks=hunks,
            )
        )

    return ChangeSet(
        base_revision=base_revision,
        target_revision=target_revision,
        base_sha=base_sha,
        target_sha=target_sha,
        source_method=source_method,
        is_git=True,
        files=files,
    )


def _parse_name_status(line: str) -> tuple[str, str] | tuple[str, str, str] | None:
    if line.startswith("R") or line.startswith("C"):
        parts = line.split("\t")
        if len(parts) == 3:
            return parts[0][0], parts[1], parts[2]
        return None
    parts = line.split("\t")
    if len(parts) == 2:
        return parts[0][0], parts[1]
    return None


def _diff_hunks(
    repo_path: Path,
    base_sha: str,
    target_sha: str,
    path: str,
) -> tuple[int, int, list[Hunk]]:
    """Return (added_lines, deleted_lines, hunks) for a path with 0 context."""
    added = deleted = 0
    hunks: list[Hunk] = []
    try:
        raw = _run_git(
            repo_path,
            "diff",
            "--no-ext-diff",
            "--unified=0",
            base_sha,
            target_sha,
            "--",
            path,
        )
    except ChangeIntelError:
        return added, deleted, hunks

    for line in raw.splitlines():
        match = _HUNK_RE.match(line)
        if not match:
            continue
        old_start = int(match.group(1))
        old_count = int(match.group(2) or "1")
        new_start = int(match.group(3))
        new_count = int(match.group(4) or "1")
        new_end = new_start + new_count - 1 if new_count > 0 else new_start - 1
        old_end = old_start + old_count - 1 if old_count > 0 else old_start - 1
        added += new_count
        deleted += old_count
        hunks.append(
            Hunk(
                new_start=new_start,
                new_end=new_end,
                old_start=old_start,
                old_end=old_end,
            )
        )
    return added, deleted, hunks