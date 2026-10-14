"""Canonical GitHub repository identity (V1).

Single authoritative normalization for every project path: duplicate
detection, persistence, lookup, and listing. Structural URL parsing only —
no substring host matching, no unsafe string splits.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_OWNER_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9_.-]{0,38})$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
# scp-like: [user@]host:path  (e.g. git@github.com:owner/repo.git)
_SCP_RE = re.compile(r"^(?:(?P<user>[A-Za-z0-9._-]+)@)?(?P<host>[A-Za-z0-9._-]+):(?P<path>.+)$")


class RepoIdentityError(ValueError):
    """Normalization failure carrying a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _check_owner_name(owner: str, name: str) -> None:
    if not _OWNER_RE.match(owner) or not _NAME_RE.match(name):
        raise RepoIdentityError(
            "INVALID_REPOSITORY_REF",
            "Owner/name contain unsupported characters.",
        )
    if name.lower().endswith(".git"):
        raise RepoIdentityError(
            "INVALID_REPOSITORY_REF",
            "Repository name is not acceptable.",
        )


def _strip_git_suffix(segment: str) -> str:
    if segment.lower().endswith(".git"):
        return segment[: -len(".git")]
    return segment


def _host_is_github(host: str) -> bool:
    normalized = (host or "").strip().lower().rstrip(".")
    return normalized in {"github.com", "www.github.com"}


def canonical_repo_identity(raw: str) -> tuple[str, str, str, str]:
    """Normalize `owner/name` or a github.com URL.

    Returns (owner, name, repository, canonical_url) where `repository` is
    the lowercased `owner/name` identity used for duplicate detection and
    `canonical_url` is the stable clone URL. Anything else raises
    RepoIdentityError with code NON_GITHUB_REPOSITORY or
    INVALID_REPOSITORY_REF.
    """
    value = (raw or "").strip()
    if not value or len(value) > 300:
        raise RepoIdentityError(
            "INVALID_REPOSITORY_REF",
            "Repository reference is empty or too long.",
        )

    # Bare `owner/name` (no scheme, no scp colon-host, no whitespace).
    if "://" not in value and not _SCP_RE.match(value):
        candidate = value.strip().strip("/")
        if candidate.lower().endswith(".git"):
            candidate = candidate[: -len(".git")]
        parts = [p for p in candidate.split("/") if p]
        if len(parts) != 2:
            raise RepoIdentityError(
                "INVALID_REPOSITORY_REF",
                "Repository must look like 'owner/name' or a github.com URL.",
            )
        owner, name = parts[0].strip(), _strip_git_suffix(parts[1].strip())
        if not owner or not name:
            raise RepoIdentityError(
                "INVALID_REPOSITORY_REF",
                "Repository must look like 'owner/name' or a github.com URL.",
            )
        _check_owner_name(owner, name)
        return owner, name, f"{owner.lower()}/{name.lower()}", f"https://github.com/{owner}/{name}.git"

    # scp-like `git@github.com:owner/repo(.git)`.
    scp = _SCP_RE.match(value)
    if scp and "://" not in value:
        host = scp.group("host")
        path = (scp.group("path") or "").strip()
        if not _host_is_github(host):
            raise RepoIdentityError(
                "NON_GITHUB_REPOSITORY",
                "V1 supports github.com repositories only.",
            )
        # Strip query/fragment accidentally pasted, then leading slashes.
        path = path.split("?", 1)[0].split("#", 1)[0].strip().strip("/")
        if path.lower().endswith(".git"):
            path = path[: -len(".git")]
        parts = [p for p in path.split("/") if p]
        if len(parts) != 2:
            raise RepoIdentityError(
                "INVALID_REPOSITORY_REF",
                "Repository must look like 'owner/name' or a github.com URL.",
            )
        owner, name = parts[0].strip(), parts[1].strip()
        _check_owner_name(owner, name)
        return owner, name, f"{owner.lower()}/{name.lower()}", f"https://github.com/{owner}/{name}.git"

    # URL forms: parse structurally, never by substring.
    parsed = urlparse(value)
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "")
    if scheme not in {"https", "http", "ssh", "git", "git+https", "git+ssh"}:
        # Unknown scheme: either non-github or garbage. Distinguish so the
        # API contract keeps NON_GITHUB_REPOSITORY for wrong hosts.
        if scheme and host and not _host_is_github(host):
            raise RepoIdentityError(
                "NON_GITHUB_REPOSITORY",
                "V1 supports github.com repositories only.",
            )
        raise RepoIdentityError(
            "INVALID_REPOSITORY_REF",
            "Repository must look like 'owner/name' or a github.com URL.",
        )
    if not _host_is_github(host):
        raise RepoIdentityError(
            "NON_GITHUB_REPOSITORY",
            "V1 supports github.com repositories only.",
        )
    # Path: first two non-empty segments are the identity; extra segments
    # (tree/blob URLs pasted from the browser) are ignored deterministically.
    segments = [p for p in (parsed.path or "").split("/") if p and p not in {".", ".."}]
    if len(segments) < 2:
        raise RepoIdentityError(
            "INVALID_REPOSITORY_REF",
            "GitHub URL has no owner/name path.",
        )
    owner, name = segments[0].strip(), _strip_git_suffix(segments[1].strip())
    if not owner or not name:
        raise RepoIdentityError(
            "INVALID_REPOSITORY_REF",
            "GitHub URL has no owner/name path.",
        )
    _check_owner_name(owner, name)
    return owner, name, f"{owner.lower()}/{name.lower()}", f"https://github.com/{owner}/{name}.git"


def repo_key_from_url(url: str | None) -> str | None:
    """Lower `owner/name` key for an arbitrary stored repository URL.

    Returns None when the URL is not a recognizable github.com reference
    (local paths, unknown hosts, garbage). Used only to collapse legacy
    run groups into their canonical project for display — never as an
    authorization proof.
    """
    if not url or not isinstance(url, str):
        return None
    try:
        _, _, repository, _ = canonical_repo_identity(url.strip())
        return repository
    except RepoIdentityError:
        return None


def validate_deploy_target(value: str | None) -> str | None:
    """Validate a persisted deployment-target relative path.

    Returns the normalized target ("." for root) or None when unset.
    Raises RepoIdentityError(INVALID_DEPLOYMENT_TARGET) for unsafe values.
    """
    if value is None:
        return None
    candidate = value.strip().replace("\\", "/").strip("/")
    if not candidate or candidate == ".":
        return "."
    if len(candidate) > 120 or candidate.startswith((".", "/", "~")):
        raise RepoIdentityError("INVALID_DEPLOYMENT_TARGET", "Deployment target is not acceptable.")
    if ".." in candidate.split("/") or "//" in value:
        raise RepoIdentityError("INVALID_DEPLOYMENT_TARGET", "Deployment target is not acceptable.")
    if not re.fullmatch(r"[A-Za-z0-9_.\-/]{1,120}", candidate):
        raise RepoIdentityError("INVALID_DEPLOYMENT_TARGET", "Deployment target is not acceptable.")
    return candidate
