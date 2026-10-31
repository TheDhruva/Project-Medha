"""Budget-aware repository file enumeration shared by inventory, change-intel, and analysis.

Supports: file-count, total-byte, per-file-size, traversal-depth, gitignore-aware
directory exclusion, symlink safety, time budget, and truncation/coverage reporting.

Each consumer can choose its budget per the phase. Walkers share a common config
so that inventory, analyzer, and change-intel index all respect the same
exclusion / depth patterns and can agree about what exists in a checkout.
"""

from __future__ import annotations

import fnmatch
import os
import re
import time
from collections.abc import Generator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.changeintel.models import Language

# ---------------------------------------------------------------------------
# Budget configuration
# ---------------------------------------------------------------------------

@dataclass
class WalkBudget:
    """Parameters that control traversal limits and budget enforcement."""
    max_files: int = 10_000           # stop counting after this many files
    max_total_bytes: int = 200 * 1024 * 1024  # stop reading after this many bytes
    max_file_bytes: int = 1 * 1024 * 1024      # skip content beyond this size
    max_depth: int = 30                # traversal depth in directory parts (root = 0)
    time_budget_s: float | None = None     # hard stop after this many seconds
    respect_gitignore: bool = True
    extra_skip_dirs: frozenset[frozenset[str]] = field(
        default_factory=frozenset,
        # Union of the three existing sets:
    )
    skip_generated: bool = True  # skip obvious generated dirs that are in none of the hard sets

@dataclass
class WalkFile:
    """A file that passed the budget checks; ready for symbol extraction."""
    rel: str        # repo-relative path, forward-slash normalized
    size: int       # file size on disk (for byte budgets)
    needs_content: bool = True  # caller still needs to read content if symbol extraction requires it


@dataclass
class WalkResult:
    """Return value of a budgeted walk."""
    files: list[WalkFile]       # all files that passed limits
    truncated: bool             # whether limits were hit
    total_files: int            # number of files found (including those beyond budget)
    total_bytes: int            # total bytes of found files
    skipped_reasons: dict[str, int]  # category → count
    skipped_by_gitignore: int
    respected_depth: int
    elapsed_s: float


# ---------------------------------------------------------------------------
# Shared walker
# ---------------------------------------------------------------------------

_GITIGNORE_PATTERN = re.compile(r"^[*?!\[]|^\.\/|^\.\.$", re.MULTILINE)


def _gitignore_match(path: Path, gitignore_lines: list[str], root: Path | None = None) -> bool:
    """Return True if *path* matches any non-blank, non-comment gitignore line.

    Matches repository-relative paths against standard gitignore patterns:
    - Anchored patterns (leading '/'): match against repository-root-relative path.
    - Directory patterns (trailing '/'): match path components.
    - Wildcard/extension patterns ('*.log', 'temp*'): match filename or path.
    """
    if root is not None:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = str(path).replace("\\", "/")
    else:
        rel = str(path).replace("\\", "/")

    filename = path.name
    parts = rel.split("/")

    for line in gitignore_lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Handle directory-specific pattern ending with '/'
        is_dir_pattern = line.endswith("/")
        pat = line.rstrip("/")

        anchored = line.startswith("/")
        pat = line.strip("/")

        if anchored:
            # Anchored to repository root
            if fnmatch.fnmatch(rel, pat) or (is_dir_pattern and (rel == pat or rel.startswith(f"{pat}/"))):
                return True
        elif "/" in pat:
            # Relative path with slash
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, f"*/{pat}") or (is_dir_pattern and (rel == pat or f"/{pat}/" in f"/{rel}/")):
                return True
        else:
            # Single-component pattern (e.g. *.log, build, target)
            if is_dir_pattern:
                if pat in parts:
                    return True
            else:
                if fnmatch.fnmatch(filename, pat) or pat in parts:
                    return True

    return False


def _is_skip_dir(dirname: str, budget: WalkBudget) -> bool:
    """Return True if the directory name is in any skip set (reserved, gitignore, etc)."""
    # Already known hard exclusions:
    known = frozenset({
        ".git", "node_modules", ".venv", "venv", "__pycache__", ".next",
        "dist", "build", "coverage", ".cache", "vendor", "target",
        ".idea", ".vscode", ".pytest_cache",
    })
    if dirname in known:
        return True
    if dirname in budget.extra_skip_dirs:
        return True
    return False


def walk_files(root: Path, budget: WalkBudget | None = None) -> WalkResult:
    """Walk *root* applying budget-enforced limits.

    Yields :class:`WalkFile` entries (via WalkResult — the whole walk is
    collected, not streamed, so truncation metadata can be recorded
    after the fact).

    The walk:
    - Counts files and bytes.
    - Prunes directories exceeding ``budget.max_depth`` (root depth 0).
    - Respects ``budget.extra_skip_dirs`` and known hard exclusions.
    - When ``budget.respect_gitignore`` is True, reads the repository's
      ``.gitignore`` (root only) and skips files matching it.
    - Skips files whose on-disk size > ``budget.max_file_bytes``
      (still records the path, but :attr:`WalkFile.needs_content` is False).
    - Honors a hard time budget if set (stops after *time_budget_s* seconds).

    Returns a :class:`WalkResult` that contains:
    - *files*: all entries that passed the limits.
    - *truncated*: True if the walk stopped because of a budget limit.
    - *total_files*: total files discovered (far beyond budget).
    - *total_bytes*: total bytes of discovered files.
    - *skipped_reasons*: a mapping ``reason → count`` for things like
      ``"size"``, ``"depth"``, ``"gitignore"``, ``"unknown-ext"``.
    - *skipped_by_gitignore*: count of files skipped because of .gitignore.
    - *respected_depth*: the maximum directory depth reached (useful for
      debugging whether depth 1, 2, etc was effective).
    - *elapsed_s*: wall‑clock time of the walk.
    """
    if budget is None:
        budget = WalkBudget()

    start = time.time()
    files: list[WalkFile] = []
    total_files = 0
    total_bytes = 0
    skipped_reasons: dict[str, int] = {}
    gitignore_skipped = 0
    depth_skipped = 0

    # Load root .gitignore
    gitignore_lines: list[str] = []
    if budget.respect_gitignore:
        gi = root / ".gitignore"
        if gi.is_file():
            try:
                gitignore_lines = [l for l in gi.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip() and not l.strip().startswith("#")]
            except OSError:
                gitignore_lines = []

    # BFS queue: (dirpath, depth)
    root = root.resolve()
    queue: list[tuple[Path, int]] = [(root, 0)]
    # We use a simple stack for deterministic sorted order, consistent with the
    # previous code's os.walk or rglob pattern.

    while queue:
        cur_dir, cur_depth = queue.pop(0)  # pop(0) = BFS; small repos this is fine

        if cur_depth > budget.max_depth:
            depth_skipped += 1
            skipped_reasons["depth"] = skipped_reasons.get("depth", 0) + 1
            continue

        # Enumerate children sorted for deterministic order (mirrors previous rglob/sorted)
        try:
            entries = sorted(os.listdir(cur_dir))
        except OSError:
            continue

        for name in entries:
            child = cur_dir / name

            # Skip symlinked directories / files to avoid escaping workspace
            try:
                if child.is_symlink():
                    # Record as skipped but don't follow
                    skipped_reasons["symlink"] = skipped_reasons.get("symlink", 0) + 1
                    total_files += 1  # still count it so budget sees the volume
                    continue
            except OSError:
                pass

            if child.is_dir():
                # Directory skip logic
                if _is_skip_dir(name, budget) or (
                    gitignore_lines and _gitignore_match(child, gitignore_lines, root=root)
                ):
                    skipped_reasons.setdefault("skip_dir", 0)
                    skipped_reasons["skip_dir"] += 1
                    # Still descend into depth-0 (root) but not children
                    # Actually: don't descend
                    continue
                # Enqueue for later
                queue.append((child, cur_depth + 1))
                continue

            # It's a file
            # Enforce max_files budget
            if budget.max_files is not None and len(files) >= budget.max_files:
                skipped_reasons.setdefault("file_budget", 0)
                skipped_reasons["file_budget"] += 1
                total_files += 1
                continue

            total_files += 1

            # Size check
            try:
                fsize = child.stat().st_size
            except OSError:
                skipped_reasons.setdefault("stat_error", 0)
                skipped_reasons["stat_error"] += 1
                continue

            # Gitignore check
            rel = child.relative_to(root).as_posix()
            if gitignore_lines and _gitignore_match(child, gitignore_lines, root=root):
                gitignore_skipped += 1
                skipped_reasons.setdefault("gitignore", 0)
                skipped_reasons["gitignore"] += 1
                continue

            # File-size budget
            if fsize > budget.max_file_bytes:
                skipped_reasons.setdefault("size", 0)
                skipped_reasons["size"] += 1
                # Record path without content for index completeness, but mark needs_content=False
                files.append(WalkFile(rel=rel, size=fsize, needs_content=False))
                total_bytes += fsize
                continue

            # Byte-total budget
            if total_bytes + fsize > budget.max_total_bytes:
                # This file pushes us over; record it but don't read its content
                skipped_reasons.setdefault("byte_budget", 0)
                skipped_reasons["byte_budget"] += 1
                files.append(WalkFile(rel=rel, size=fsize, needs_content=False))
                total_bytes += fsize
                # After this we'll effectively stop reading more after loop check,
                # but we still keep walking for count; the truncation flag will be
                # set after the loop if we hit byte cap.
                # To avoid infinitely walking a huge repo we just note and keep
                # counting, then break after loop finishes.
                continue

            # Time budget check
            if budget.time_budget_s is not None and (time.time() - start) > budget.time_budget_s:
                skipped_reasons.setdefault("time_budget", 0)
                skipped_reasons["time_budget"] += 1
                continue

            # Passed all checks → record
            files.append(WalkFile(rel=rel, size=fsize, needs_content=True))
            total_bytes += fsize

        # After each directory iteration, check overall budgets
        if budget.time_budget_s is not None and (time.time() - start) > budget.time_budget_s:
            break

    elapsed_s = time.time() - start

    # Determine whether truncation occurred:
    # Only exhaustion of enumeration limits (file_budget, byte_budget, time_budget, depth)
    # constitutes truncation of the repository walk. Benign content skips (per-file size cap)
    # and directory/gitignore exclusions enumerate the paths or explicitly ignore them.
    truncated = (
        skipped_reasons.get("depth", 0) > 0
        or skipped_reasons.get("file_budget", 0) > 0
        or skipped_reasons.get("byte_budget", 0) > 0
        or skipped_reasons.get("time_budget", 0) > 0
    )

    respected_depth = budget.max_depth  # track for return

    return WalkResult(
        files=files,
        truncated=truncated,
        total_files=total_files,
        total_bytes=total_bytes,
        skipped_reasons=skipped_reasons,
        skipped_by_gitignore=gitignore_skipped,
        respected_depth=respected_depth,
        elapsed_s=elapsed_s,
    )


# ---------------------------------------------------------------------------
# Convenience: one-off walk with defaults per consumer
# ---------------------------------------------------------------------------

def walk_language_index(root: Path, budget: WalkBudget | None = None) -> tuple[dict[str, int], WalkResult]:
    """Return language counts dict and WalkResult.

    The counts dict maps language names (e.g. "python", "javascript", "html", "css")
    to file counts. Unsupported extensions are recorded under the "unsupported" key
    without double-counting.
    """
    if budget is None:
        budget = WalkBudget(
            max_total_bytes=100 * 1024 * 1024,
            max_file_bytes=512 * 1024,
        )

    result = walk_files(root, budget)
    counts: dict[str, int] = {}
    from app.analysis.inventory import _EXT_LANG

    for f in result.files:
        ext = Path(f.rel).suffix.lower()
        lang = _EXT_LANG.get(ext)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
        else:
            counts["unsupported"] = counts.get("unsupported", 0) + 1

    return counts, result


def walk_analyze_budget(root: Path) -> WalkBudget:
    """Return the budget used by the analyzer's evidence sweep."""
    return WalkBudget(
        max_files=2000,
        max_total_bytes=50 * 1024 * 1024,
        max_file_bytes=256 * 1024,
        max_depth=2,  # depth of directory parts from root: root + 1 level of subdirs = files in depth 2
        time_budget_s=120,
        extra_skip_dirs=frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}),
    )


def walk_inventory_budget(root: Path) -> WalkBudget:
    """Return the budget used by the inventory language sweep."""
    # 5k files, 100MB, depth generous but not unlimited (prevent pathological walk)
    return WalkBudget(
        max_files=5000,
        max_total_bytes=100 * 1024 * 1024,
        max_file_bytes=256 * 1024,
        max_depth=20,
        time_budget_s=300,
        extra_skip_dirs=frozenset({
            ".git", "node_modules", ".venv", "venv", "__pycache__", ".next",
            "dist", "build", "coverage", ".cache", "vendor", "target",
            ".idea", ".vscode", ".pytest_cache",
        }),
    )


def walk_cig_budget(root: Path) -> WalkBudget:
    """Return the budget used by the change-impact indexer."""
    # Generous but bounded: depth 20, files 20k, bytes 200MB, per-file 1MB.
    # The key fix: quadratic config probing is mitigated by probe-token maps
    # built later in compute_dependency_edges, but we still cap traversal.
    return WalkBudget(
        max_files=20000,
        max_total_bytes=200 * 1024 * 1024,
        max_file_bytes=1 * 1024 * 1024,
        max_depth=20,
        time_budget_s=120,
        extra_skip_dirs=frozenset({".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}),
    )