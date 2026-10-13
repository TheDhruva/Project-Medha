"""Real Git history service (Phase 7).

Reads actual commit ancestry via bounded `git log` — never synthesizes.
CIG (dependency impact) and CEG (execution causality) stay distinct and
labelled; this module is the only source of Git commit DAG data.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path


MAX_COMMITS = 200
MAX_MESSAGE = 500
_TIMEOUT_S = 30


class HistoryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class CommitEntry:
    sha: str
    parents: list[str] = field(default_factory=list)
    author: str | None = None
    committed_at: str | None = None
    message: str | None = None


def _run_git(args: list[str], cwd: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", *args], check=True, capture_output=True, text=True,
            timeout=_TIMEOUT_S, cwd=str(cwd),
            env={"GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "PATH": __import__("os").environ.get("PATH", "")},
        )
    except subprocess.TimeoutExpired as exc:
        raise HistoryError("GIT_TIMEOUT", "Git history timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise HistoryError("GIT_COMMAND_FAILED", "Git history unavailable") from exc
    except FileNotFoundError as exc:
        raise HistoryError("GIT_UNAVAILABLE", "git executable not found") from exc
    return (completed.stdout or "")


def list_history(repo_path: Path, *, limit: int = 50,
                 since_sha: str | None = None) -> tuple[list[CommitEntry], bool]:
    """Return (entries, is_partial). Bounded; oldest-first paging via skip."""
    bounded = max(1, min(int(limit), MAX_COMMITS))
    args = ["log", f"--max-count={bounded + 1}",
            "--format=%H%x1f%P%x1f%an%x1f%cI%x1f%s%x1e"]
    if since_sha:
        args.append(f"{since_sha}..HEAD")
    else:
        args.append("HEAD")
    out = _run_git(args, cwd=repo_path)
    entries: list[CommitEntry] = []
    for record in out.split("\x1e"):
        record = record.strip()
        if not record:
            continue
        parts = record.split("\x1f")
        if len(parts) < 5:
            continue
        sha, parents, author, committed_at, message = parts[0], parts[1], parts[2], parts[3], parts[4]
        if len(sha) != 40:
            continue
        entries.append(CommitEntry(
            sha=sha.lower(),
            parents=[p.lower() for p in parents.split() if len(p) == 40],
            author=author or None, committed_at=committed_at or None,
            message=(message or "")[:MAX_MESSAGE] or None,
        ))
    partial = len(entries) > bounded
    return entries[:bounded], partial


def changed_files_summary(repo_path: Path, sha: str) -> dict:
    """Diff summary for one commit: files + added/deleted counts."""
    if len(sha) != 40 or any(c not in "0123456789abcdef" for c in sha.lower()):
        raise HistoryError("INVALID_SHA", "Commit SHA must be 40-char hex.")
    out = _run_git(["show", "--numstat", "--format=", sha], cwd=repo_path)
    files: list[dict] = []
    added = deleted = 0
    for line in out.splitlines()[:500]:
        parts = line.split("\t")
        if len(parts) != 3:
            continue
        try:
            a = int(parts[0]) if parts[0] != "-" else 0
            d = int(parts[1]) if parts[1] != "-" else 0
        except ValueError:
            continue
        added += a
        deleted += d
        files.append({"path": parts[2][:260], "added": a, "deleted": d})
    return {"sha": sha.lower(), "files": files[:200], "added": added,
            "deleted": deleted, "truncated": len(files) >= 200}


def github_commit_url(repository_url: str, sha: str) -> str | None:
    low = (repository_url or "").lower()
    if "github.com" not in low:
        return None
    import re as _re

    match = _re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", repository_url.strip())
    if not match:
        return None
    return f"https://github.com/{match.group(1)}/{match.group(2)}/commit/{sha}"
