"""Incremental analysis tiers (Phase 5).

Tier 1 — fast deterministic checks, zero LLM calls. Runs on every commit.
Tier 2 — targeted analysis of changed modules + dependents. <=2 LLM calls.
Tier 3 — expanded/deep analysis. <=6 LLM calls per run (existing AI budget).

Routing is conservative: uncertainty expands the scope, never shrinks it.
Every decision records tier, reason, scope, cache hits, and skipped checks
so the UI can explain what ran and why.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


TIER_BUDGETS = {1: 0, 2: 2, 3: 6}
SCORE_VERSION = "scores-v1"

_DOC_EXTS = {".md", ".rst", ".txt"}
_CSS_EXTS = {".css", ".scss", ".less"}
_LOCK_NAMES = {
    "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    "poetry.lock", "Pipfile.lock", "go.sum", "Gemfile.lock",
    "Cargo.lock", "composer.lock",
}
_DEP_MANIFESTS = {
    "package.json", "requirements.txt", "pyproject.toml", "go.mod",
    "Gemfile", "Cargo.toml", "composer.json",
}
_AUTH_MARKERS = ("auth", "login", "session", "oauth", "password", "token", "permission", "acl")
_DEPLOY_MARKERS = (
    "dockerfile", "docker-compose.yml", "docker-compose.yaml",
    "compose.yml", "compose.yaml", "nginx.conf",
)
_SCHEMA_MARKERS = ("migration", "migrations", "alembic", "schema.sql", "prisma")


@dataclass
class TierDecision:
    tier: int
    reason: str
    scope: list[str] = field(default_factory=list)
    llm_budget: int = 0
    skipped: list[dict[str, str]] = field(default_factory=list)
    cache_hit: bool = False


def _ext(path: str) -> str:
    low = path.lower()
    dot = low.rfind(".")
    return low[dot:] if dot != -1 else ""


def route(changed_files: list[str], *, risk_level: str = "none",
          unresolved: int = 0, blast_radius: int = 0,
          explicit_full: bool = False) -> TierDecision:
    """Choose the analysis tier for a commit. Pure + deterministic."""
    files = [f or "" for f in changed_files]
    lowers = [f.lower() for f in files]
    if explicit_full:
        return TierDecision(tier=3, reason="explicit-full-analysis-requested",
                            scope=sorted(files), llm_budget=TIER_BUDGETS[3])
    if not files:
        return TierDecision(tier=1, reason="no-changed-files",
                            scope=[], llm_budget=0,
                            skipped=[{"check": "targeted-agents", "reason": "no changed files"}])
    if all(_ext(f) in _DOC_EXTS for f in files):
        return TierDecision(tier=1, reason="documentation-only",
                            scope=sorted(files), llm_budget=0,
                            skipped=[{"check": "targeted-agents", "reason": "docs do not affect runtime"}])
    if all(_ext(f) in _CSS_EXTS for f in files):
        return TierDecision(tier=2, reason="style-only",
                            scope=sorted(files), llm_budget=0,
                            skipped=[{"check": "backend-agents", "reason": "no backend files changed"}])
    basenames = {f.split("/")[-1] for f in lowers}
    if basenames & _LOCK_NAMES or any(f in _DEP_MANIFESTS or f.split("/")[-1] in _DEP_MANIFESTS for f in lowers):
        return TierDecision(tier=2, reason="dependency-manifest-change",
                            scope=sorted(files), llm_budget=TIER_BUDGETS[2])
    if any(any(m in f for m in _AUTH_MARKERS) for f in lowers):
        return TierDecision(tier=3, reason="auth-security-sensitive-change",
                            scope=sorted(files), llm_budget=TIER_BUDGETS[3])
    if any(any(m in f for m in _DEPLOY_MARKERS) for f in lowers):
        return TierDecision(tier=3, reason="deployment-config-change",
                            scope=sorted(files), llm_budget=TIER_BUDGETS[3])
    if any(any(m in f for m in _SCHEMA_MARKERS) for f in lowers):
        return TierDecision(tier=3, reason="database-schema-change",
                            scope=sorted(files), llm_budget=TIER_BUDGETS[3])
    if risk_level == "high" or unresolved > 0 or blast_radius >= 5:
        return TierDecision(
            tier=3,
            reason=f"uncertain-or-broad-impact(risk={risk_level},unresolved={unresolved},blast={blast_radius})",
            scope=sorted(files), llm_budget=TIER_BUDGETS[3])
    if risk_level == "medium" or blast_radius >= 2:
        return TierDecision(tier=2, reason=f"moderate-impact(risk={risk_level},blast={blast_radius})",
                            scope=sorted(files), llm_budget=TIER_BUDGETS[2])
    return TierDecision(tier=2, reason="small-code-change",
                        scope=sorted(files), llm_budget=TIER_BUDGETS[2])


def inputs_hash(*, base_sha: str | None, target_sha: str, file_hashes: dict[str, str],
                 tool_version: str, config: dict, extra: dict | None = None) -> str:
    """Stable hash over every input that affects a cached result."""
    canonical = json.dumps({
        "base": base_sha, "target": target_sha,
        "files": sorted(file_hashes.items()),
        "tool": tool_version, "config": sorted((config or {}).items()),
        "extra": sorted((extra or {}).items()),
    }, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_content_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()
