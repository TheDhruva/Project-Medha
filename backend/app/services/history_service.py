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


def commit_metadata(repo_path: Path, sha: str) -> CommitEntry:
    """Metadata for one pinned commit (message/author/date/parents)."""
    candidate = (sha or "").strip().lower()
    if len(candidate) != 40 or any(c not in "0123456789abcdef" for c in candidate):
        raise HistoryError("INVALID_SHA", "Commit SHA must be 40-char hex.")
    out = _run_git(
        ["show", "-s", "--format=%H%x1f%P%x1f%an%x1f%cI%x1f%s%x1e", candidate],
        cwd=repo_path,
    )
    record = out.split("\x1e")[0].strip()
    parts = record.split("\x1f")
    if len(parts) < 5 or len(parts[0]) != 40:
        raise HistoryError("GIT_COMMAND_FAILED", "Commit metadata unavailable.")
    full_sha, parents, author, committed_at, subject = parts[0], parts[1], parts[2], parts[3], parts[4]
    # Subject is first-line only; fetch the full body for the summary.
    body = _run_git(["show", "-s", "--format=%B", candidate], cwd=repo_path)
    message = body.strip()[:MAX_MESSAGE] or None
    return CommitEntry(
        sha=full_sha.lower(),
        parents=[p.lower() for p in parents.split() if len(p) == 40],
        author=author or None, committed_at=committed_at or None,
        message=message or (subject or "")[:MAX_MESSAGE] or None,
    )


def build_commit_summary(entry: CommitEntry, diff: dict | None) -> str:
    """Deterministic, evidence-based commit summary (no LLM, no paid APIs).

    Headline from the actual commit message plus diff statistics and the
    most-changed paths. Empty diff evidence yields a metadata-only summary —
    never a fabricated claim.
    """
    headline = ((entry.message or "").strip().split("\n")[0].strip()) or "(no commit message recorded)"
    files = (diff or {}).get("files") or [] if isinstance(diff, dict) else []
    added = (diff or {}).get("added", 0) if isinstance(diff, dict) else 0
    deleted = (diff or {}).get("deleted", 0) if isinstance(diff, dict) else 0
    if not files:
        return f"{headline} (file-level diff unavailable for {entry.sha[:12]})."
    dirs: dict[str, int] = {}
    for item in files:
        path = str(item.get("path", ""))
        top = path.rsplit("/", 1)[0] if "/" in path else "(root)"
        dirs[top] = dirs.get(top, 0) + 1
    top_dirs = ", ".join(
        name for name, _ in sorted(dirs.items(), key=lambda kv: -kv[1])[:3]
    )
    ranked = sorted(files, key=lambda f: f.get("added", 0) + f.get("deleted", 0),
                    reverse=True)[:5]
    top_files = ", ".join(str(f.get("path", ""))[:60] for f in ranked)
    pieces = [headline, f"+{added}/-{deleted} across {len(files)} file(s)"]
    if top_dirs:
        pieces.append(f"mostly {top_dirs}")
    if top_files:
        pieces.append(f"top: {top_files}")
    return " — ".join(pieces)[:500]


def github_commit_url(repository_url: str, sha: str) -> str | None:
    low = (repository_url or "").lower()
    if "github.com" not in low:
        return None
    import re as _re

    match = _re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?/?$", repository_url.strip())
    if not match:
        return None
    return f"https://github.com/{match.group(1)}/{match.group(2)}/commit/{sha}"
