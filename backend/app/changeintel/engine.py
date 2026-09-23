"""Phase 2 orchestrator: git revisions → ChangeSet → CIG → risk → requirements."""

from __future__ import annotations

from pathlib import Path

from app.changeintel import cig as cig_builder
from app.changeintel.dep_index import build_index
from app.changeintel.git_extract import (
    ChangeIntelError,
    extract_changeset,
    is_git_repository,
    read_blob,
)
from app.changeintel.models import (
    ChangeImpactAnalysis,
    ChangeSet,
    Symbol,
)
from app.changeintel.requirements import generate_requirements
from app.changeintel.risk import assess_risk
from app.changeintel.symbols import extract_file_symbols
from app.core.logging import get_logger
from app.services.workspace import resolve_local_repo_path

logger = get_logger(__name__)

__all__ = ["ChangeIntelError", "analyze_change_impact", "is_local_repository"]


def is_local_repository(repository_url: str) -> bool:
    """Phase 2 supports local git repositories (offline, deterministic)."""
    return resolve_local_repo_path(repository_url) is not None


def _error_for_missing(url: str) -> str:
    """Distinguish 'path not found' (a local-looking path) from a remote URL."""
    stripped = url.strip()
    if "://" in stripped or stripped.startswith(("git@", "ssh@", "git::")):
        return "NOT_LOCAL_REPOSITORY"
    return "REPO_NOT_FOUND"


def analyze_change_impact(
    *,
    repository_url: str,
    base_revision: str,
    target_revision: str,
    deployment_id: str | None = None,
) -> ChangeImpactAnalysis:
    """Run the full deterministic change-impact pipeline over a local git repo."""
    repo_path = resolve_local_repo_path(repository_url)
    if repo_path is None and _error_for_missing(repository_url) == "REPO_NOT_FOUND":
        raise ChangeIntelError(
            "REPO_NOT_FOUND",
            f"Local repository path not found: {repository_url}",
            url=str(repository_url),
        )
    if repo_path is None:
        raise ChangeIntelError(
            "NOT_LOCAL_REPOSITORY",
            "Phase 2 change analysis supports local git repositories only; "
            "remote URLs are analyzed in a later phase.",
        )
    if not is_git_repository(repo_path):
        raise ChangeIntelError(
            "NOT_A_GIT_REPOSITORY",
            f"'{repo_path}' is not a git repository; change analysis requires git history.",
        )

    changeset = extract_changeset(repo_path, base_revision, target_revision, source_method="local")

    # Static, evidence-only pipeline. Never executes repository code.
    index = build_index(repo_path)
    base_side: dict[str, Symbol] = _build_base_side(repo_path, changeset)
    changed_symbols = cig_builder.detect_changed_symbols(changeset, index, base_side)
    graph, traversal, unresolved = cig_builder.build_cig(
        changeset, changed_symbols, index, base_side
    )
    risk = assess_risk(changeset, graph, changed_symbols, unresolved, traversal)
    requirements = generate_requirements(changeset, graph, unresolved, traversal)

    analysis = ChangeImpactAnalysis(
        deployment_id=deployment_id,
        repository_url=str(repo_path),
        changeset=changeset,
        changed_symbols=changed_symbols,
        graph=graph,
        traversal=traversal,
        unresolved=unresolved,
        risk=risk,
        requirements=requirements,
    )
    logger.info(
        "Change impact computed repo=%s base=%s target=%s files=%d nodes=%d edges=%d risk=%s",
        repo_path,
        changeset.base_sha[:8],
        changeset.target_sha[:8],
        len(changeset.files),
        len(graph.nodes),
        len(graph.edges),
        risk.level.value,
    )
    return analysis


def _build_base_side(repo_path: Path, changeset: ChangeSet) -> dict[str, Symbol]:
    """Extract base-side symbols from git blobs for symbol-level diffing.

    Covers files that are modified (compare base vs target symbols), deleted
    (whole-file removal), and renamed-from (old path removed). The returned map
    keyed by symbol_id is used for deletion/rename detection only — it is NOT
    merged into the analysis index so deleted modules can't be "resolved".
    """
    symbols: dict[str, Symbol] = {}
    for fc in changeset.files:
        need_path: str | None = None
        if fc.change_type.value in {"deleted", "renamed"}:
            need_path = fc.old_path if fc.change_type.value == "renamed" else fc.path
        elif fc.change_type.value == "modified":
            need_path = fc.path
        if not need_path:
            continue
        content = read_blob(repo_path, changeset.base_sha, need_path)
        if content is None:
            continue
        parsed = extract_file_symbols(need_path, content)
        for s in parsed.symbols:
            symbols[s.symbol_id] = s
    return symbols