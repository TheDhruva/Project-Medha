"""Repository URL validation with baseline SSRF protection (V1).

Single-operator local prototype: local filesystem paths and ``file://`` URIs
are always accepted (existence is checked downstream). Remote URLs are limited
to an allowlisted scheme set, reject embedded credentials on http(s), and
reject literal-IP hosts in private/loopback-except-local-dev/link-local/
reserved ranges plus known cloud-metadata hostnames.

Limitation (documented): hostnames are validated statically — no DNS
resolution happens here, so DNS-rebinding to a private address is not
detected. This is acceptable because V1 binds 127.0.0.1 for a single
operator, but any multi-user/beyond-loopback deployment must add
resolve-and-recheck (pin the resolved IP) before cloning.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from urllib.parse import urlparse

ALLOWED_SCHEMES = frozenset({"https", "http", "git", "ssh", "git+https", "git+ssh"})

# scp-like syntax: [user@]host:path  (e.g. git@github.com:org/repo.git)
_SCP_RE = re.compile(
    r"^(?:(?P<user>[A-Za-z0-9._-]+)@)?(?P<host>[A-Za-z0-9._-]+):(?P<path>.+)$"
)

_BLOCKED_HOSTNAMES = frozenset(
    {
        "metadata",
        "metadata.google.internal",
        "instance-data",
        "instance-data-compute",
    }
)

_MAX_URL_LENGTH = 2000


class RepositoryUrlError(ValueError):
    """Validation failure carrying a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _looks_like_local_path(raw: str) -> bool:
    if raw.startswith("file://"):
        return True
    # Windows drive-letter paths are always local (existence checked downstream).
    if re.match(r"^[A-Za-z]:[\\/]", raw):
        return True
    # Windows drive letter (C:\... / C:/...) or absolute/relative local dir.
    candidate = Path(raw)
    try:
        if candidate.exists() and candidate.is_dir():
            return True
    except OSError:
        return False
    # file:// URIs and plain paths that do not parse as remote URLs with a
    # network host fall through to scheme validation below.
    return False


def _check_host(host: str) -> None:
    normalized = host.strip().lower().rstrip(".")
    if not normalized or any(ch.isspace() or ord(ch) < 32 for ch in normalized):
        raise RepositoryUrlError("INVALID_REPOSITORY_URL", "Repository URL host is invalid.")
    if normalized in _BLOCKED_HOSTNAMES or normalized.endswith(".internal"):
        raise RepositoryUrlError(
            "REPOSITORY_URL_BLOCKED",
            f"Repository host '{host}' is blocked (metadata/internal).",
        )
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        return  # hostname: static check only (see module docstring)
    if ip.is_loopback:
        return  # localhost dev use preserved
    if (
        ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise RepositoryUrlError(
            "REPOSITORY_URL_BLOCKED",
            f"Repository host '{host}' resolves to a non-public address and is blocked.",
        )


def validate_repository_url(raw: str) -> str:
    """Validate a repository URL; return the stripped value or raise."""
    if not isinstance(raw, str):
        raise RepositoryUrlError("INVALID_REPOSITORY_URL", "Repository URL must be a string.")
    value = raw.strip()
    if not value:
        raise RepositoryUrlError("INVALID_REPOSITORY_URL", "Repository URL must not be empty.")
    if len(value) > _MAX_URL_LENGTH:
        raise RepositoryUrlError("INVALID_REPOSITORY_URL", "Repository URL is too long.")
    if any(ord(ch) < 32 for ch in value):
        raise RepositoryUrlError("INVALID_REPOSITORY_URL", "Repository URL contains control characters.")

    if _looks_like_local_path(value):
        return value  # local single-operator workflow; existence checked downstream

    scp = _SCP_RE.match(value)
    if scp and "://" not in value and "/" not in value.split(":")[0]:
        # scp-like [user@]host:path — require an explicit user or a dotted
        # host with a path, so bare `scheme:opaque` values (javascript:, data:)
        # fall through to scheme validation and are rejected.
        host = scp.group("host")
        path = scp.group("path")
        if scp.group("user") or ("." in host and ("/" in path or path.endswith(".git"))):
            _check_host(host)
            return value

    parsed = urlparse(value)
    scheme = parsed.scheme.lower()
    if not scheme or not parsed.netloc:
        raise RepositoryUrlError(
            "INVALID_REPOSITORY_URL",
            "Repository URL must be a local path, file:// URI, or a remote git URL "
            "(https://, http://, ssh://, git://).",
        )
    if scheme == "file":
        return value  # local file URI; existence checked downstream by git_service
    if scheme not in ALLOWED_SCHEMES:
        raise RepositoryUrlError(
            "INVALID_REPOSITORY_URL",
            f"Repository URL scheme '{parsed.scheme}' is not allowed.",
        )
    if scheme in {"http", "https"} and (parsed.username or parsed.password):
        raise RepositoryUrlError(
            "REPOSITORY_URL_BLOCKED",
            "Embedded credentials in repository URLs are not allowed.",
        )
    host = parsed.hostname or ""
    _check_host(host)
    return value
