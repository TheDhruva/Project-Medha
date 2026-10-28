"""Incremental scan planning: select security scanners from the changeset.

A styling change must not trigger every backend security agent, a lockfile
change must trigger dependency analysis, and an auth-path change must keep
authorization checks in play. The builtin policy checks always run over the
full scope (they are deterministic and cheap); this module only decides
which *external* scanners (semgrep / trivy / gitleaks) to run.

Honesty rules:

- Unknown or empty changesets, truncated payloads, and a repository without
  a recorded full scan always produce a FULL plan.
- A periodic full rescan supersedes incrementality after ``full_rescan_days``.
- Skipped scanners are reported by the caller as coverage gaps — a skipped
  scanner is never silently presented as a clean result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_FULL_RESCAN_DAYS = 7

_CODE_SUFFIXES = frozenset({
    ".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".go", ".rb",
    ".php", ".java", ".kt", ".swift", ".cs", ".c", ".cc", ".cpp", ".h",
    ".vue", ".svelte", ".sql", ".sh", ".bash", ".ps1", ".tf", ".hcl",
})
_STYLE_SUFFIXES = frozenset({
    ".css", ".scss", ".sass", ".less", ".styl", ".stylus",
})
_DOC_SUFFIXES = frozenset({
    ".md", ".markdown", ".rst", ".txt", ".adoc", ".pdf",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
})

_DEPENDENCY_NAMES = frozenset({
    "package-lock.json", "npm-shrinkwrap.json", "yarn.lock",
    "pnpm-lock.yaml", "bun.lockb", "requirements.txt",
    "requirements-dev.txt", "pipfile.lock", "poetry.lock", "pyproject.toml",
    "setup.py", "setup.cfg", "go.sum", "go.mod", "cargo.lock",
    "cargo.toml", "gemfile.lock", "gemfile", "composer.lock",
    "composer.json", "pom.xml", "build.gradle", "build.gradle.kts",
    "packages.lock.json", "mix.lock", "pubspec.lock",
})

# Paths whose contents commonly carry credentials or deployment semantics.
_SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".jks", ".keystore"})
_SECRET_NAMES = frozenset({
    ".npmrc", ".pypirc", ".netrc", "id_rsa", "id_ed25519", "credentials",
    "credentials.json", "service-account.json",
})
_DEPLOY_NAMES = frozenset({
    "dockerfile", "dockerfile.dev", "docker-compose.yml",
    "docker-compose.yaml", "compose.yml", "compose.yaml", "procfile",
    "vercel.json", "render.yaml", "render.yml", "fly.toml", "app.yaml",
    "cloudbuild.yaml", "jenkinsfile", ".gitlab-ci.yml", "nginx.conf",
    "supervisord.conf",
})
_DEPLOY_DIRS = (".github/workflows", ".circleci", "k8s/", "kubernetes/",
                "helm/", "terraform/", "deploy/", "deployment/", ".aws/")

# Shared-authorization path tokens (file or directory name based).
_AUTH_TOKENS = ("auth", "login", "session", "oauth", "jwt", "permission",
                "rbac", "acl", "guard", "identity", "authorize",
                "authorization", "middleware")


@dataclass(frozen=True)
class ScanPlan:
    """Scanner selection for one assessment."""

    mode: str                      # "full" | "incremental"
    scanner_names: list[str] | None = None   # None = every supported scanner
    reasons: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    authorization_touched: bool = False

    @property
    def full(self) -> bool:
        return self.mode == "full"


def _suffix(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _is_secret_path(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    if name.startswith(".env"):
        return True
    if name in _SECRET_NAMES:
        return True
    return _suffix(name) in _SECRET_SUFFIXES


def _is_deploy_path(path: str) -> bool:
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if name in _DEPLOY_NAMES or name.startswith("dockerfile"):
        return True
    return any(f"/{d}" in f"/{lowered}" or lowered.startswith(d)
               for d in _DEPLOY_DIRS)


def _is_dependency_path(path: str) -> bool:
    return path.rsplit("/", 1)[-1].lower() in _DEPENDENCY_NAMES


def _is_auth_path(path: str) -> bool:
    parts = [p.lower() for p in path.split("/") if p]
    for part in parts:
        stem = part.split(".")[0]
        if any(token in stem for token in _AUTH_TOKENS):
            return True
    return False


def _classify(path: str) -> set[str]:
    """Kinds of concern a changed path raises."""
    kinds: set[str] = set()
    lowered = path.lower()
    suffix = _suffix(lowered)
    if _is_dependency_path(lowered):
        kinds.add("dependency")
    if _is_secret_path(lowered):
        kinds.add("secret")
    if _is_deploy_path(lowered):
        kinds.add("deploy")
    if _is_auth_path(lowered):
        kinds.add("authorization")
    if suffix in _STYLE_SUFFIXES:
        kinds.add("style")
    elif suffix in _DOC_SUFFIXES:
        kinds.add("docs")
    elif suffix in _CODE_SUFFIXES:
        kinds.add("code")
    elif not (kinds - {"authorization"}):
        # Unknown extension with no more specific kind: fail safe to SAST
        # (an unrecognized source file must still reach semgrep).
        kinds.add("code")
    return kinds


def _scanner_names_for(kinds: set[str]) -> tuple[list[str], list[str]]:
    """External scanners to run for the classified changeset."""
    selected: set[str] = set()
    if "code" in kinds or "authorization" in kinds:
        selected.add("semgrep")
    if "dependency" in kinds:
        selected.add("trivy")
    if "secret" in kinds or "deploy" in kinds:
        selected.add("gitleaks")
    skipped = sorted(
        {"semgrep", "trivy", "gitleaks"} - selected
    )
    return sorted(selected), skipped


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def plan_scan(
    changed_paths: list[str] | None,
    *,
    last_full_scan_at: str | None = None,
    truncated: bool = False,
    now: str | None = None,
    full_rescan_days: int = DEFAULT_FULL_RESCAN_DAYS,
) -> ScanPlan:
    """Choose a full or incremental scanner plan from the changeset.

    ``changed_paths=None`` means the changeset is unknown — always full.
    """
    if truncated:
        return ScanPlan(
            mode="full",
            reasons=["changeset was truncated by the event payload; "
                     "changed files may be incomplete"],
        )
    if not changed_paths:
        return ScanPlan(
            mode="full",
            reasons=["changeset unknown or empty; defaulting to a full scan"],
        )
    if not last_full_scan_at:
        return ScanPlan(
            mode="full",
            reasons=["no successful full scan recorded yet; first assessment "
                     "must establish baseline coverage"],
        )

    reference = _parse_iso(now) or datetime.now(timezone.utc)
    full_at = _parse_iso(last_full_scan_at)
    if full_at is None:
        return ScanPlan(
            mode="full",
            reasons=["last full-scan timestamp is unreadable; "
                     "running a full scan"],
        )
    age_days = (reference - full_at).total_seconds() / 86400.0
    if age_days >= full_rescan_days:
        return ScanPlan(
            mode="full",
            reasons=[f"periodic full rescan due "
                     f"({age_days:.1f} days since last full scan; "
                     f"cadence {full_rescan_days}d)"],
        )

    kinds: set[str] = set()
    for path in changed_paths:
        if not isinstance(path, str) or not path.strip():
            continue
        kinds.update(_classify(path.replace("\\", "/").lstrip("./")))
    if not kinds:
        return ScanPlan(
            mode="full",
            reasons=["no classifiable paths in the changeset; "
                     "defaulting to a full scan"],
        )

    scanners, skipped = _scanner_names_for(kinds)
    reasons = [
        f"incremental scan: {len(changed_paths)} changed path(s) map to "
        f"kinds={sorted(kinds)}"
    ]
    return ScanPlan(
        mode="incremental",
        scanner_names=scanners,
        reasons=reasons,
        skipped=skipped,
        authorization_touched="authorization" in kinds,
    )
