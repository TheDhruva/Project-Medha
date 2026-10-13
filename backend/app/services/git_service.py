"""Git / local repository acquisition (shallow clone when needed).

Exact-commit binding: when a caller passes ``ref_sha`` (e.g. the verified
``after`` SHA of a GitHub push event), acquisition fetches and checks out
that exact commit and asserts ``HEAD == ref_sha`` before returning. Anything
else fails closed — MEDHA never silently analyzes a different commit.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.logging import get_logger
from app.core.repo_url import (
    RepositoryUrlError,
    ensure_approved_github_host,
    resolve_and_recheck,
    validate_repository_url,
)
from app.services.workspace import deployment_workspace, resolve_local_repo_path

logger = get_logger(__name__)

# short: connection boundary — every remote git op must pass _enforce_connection_boundary first.
_APPROVED_GITHUB_HOSTS = frozenset({"github.com", "api.github.com", "objects.githubusercontent.com"})


def _hostname_of(url: str) -> str | None:
    from urllib.parse import urlparse

    try:
        return (urlparse(url).hostname or "").strip().lower() or None
    except Exception:  # noqa: BLE001
        return None


def _enforce_connection_boundary(cleaned_url: str) -> str | None:
    """Enforce SSRF/DNS policy at the actual connection layer.

    Returns the pinned IP for remote hosts (informational — git itself
    connects by name, so callers must refuse redirects away from the
    validated host and must not forward credentials elsewhere).
    Local paths return None (no network involved).
    """
    if resolve_local_repo_path(cleaned_url) is not None:
        return None
    host = _hostname_of(cleaned_url)
    if not host:
        # scp-like syntax git@github.com:org/repo — extract host part
        candidate = cleaned_url.split("@")[-1].split(":")[0].strip().lower()
        host = candidate or None
    if not host:
        raise GitAcquireError("INVALID_REPOSITORY_URL", "Repository URL has no host.")
    pinned = resolve_and_recheck(host)  # fail closed on private/loopback/metadata
    return pinned


def _secure_git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Env for every git subprocess: no prompts, no credential leakage."""
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ASKPASS": "",
    }
    if extra:
        env.update(extra)
    return env

_FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_ZERO_SHA = "0" * 40
_GIT_TIMEOUT_S = 120
_LSREMOTE_TIMEOUT_S = 30
_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


@dataclass
class RepoAcquisition:
    path: Path
    method: str  # local_copy | local_archive | shallow_clone
    cleaned_url: str
    checked_sha: str | None = None  # verified HEAD when ref_sha was requested


class GitAcquireError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _require_full_sha(sha: str | None) -> str:
    """Validate an exact 40-hex commit SHA (fail closed on anything else)."""
    candidate = (sha or "").strip().lower()
    if not candidate or candidate == _ZERO_SHA:
        raise GitAcquireError(
            "SHA_REQUIRED",
            "An exact 40-hex commit SHA is required (got empty or null SHA).",
        )
    if not _FULL_SHA_RE.match(candidate):
        raise GitAcquireError(
            "INVALID_SHA",
            "Commit SHA must be a 40-character hex string.",
        )
    return candidate


def normalize_commit_sha(sha: str | None) -> str:
    """Public SHA validator: normalized 40-hex SHA or GitAcquireError."""
    return _require_full_sha(sha)


def _run_git(
    args: list[str], *, cwd: Path | None = None, timeout: int = _GIT_TIMEOUT_S,
    env: dict[str, str] | None = None,
) -> str:
    """Run a bounded git command; stdout on success, GitAcquireError otherwise."""
    import os

    merged = {**os.environ, **_secure_git_env(env)}
    # Never let secret-bearing values reach argv/exceptions: scrub before use.
    # Handles both https://user@host/... URLs and scp-like git@host:... syntax.
    def _scrub(arg: str) -> str:
        if "@" in arg and ("://" in arg or ":" in arg):
            return "<redacted-url>"
        return arg

    safe_args = [_scrub(a) for a in args]
    try:
        completed = subprocess.run(
            ["git", *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(cwd) if cwd is not None else None,
            env=merged,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitAcquireError("GIT_TIMEOUT", "Git operation timed out") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()[:300]
        raise GitAcquireError(
            "GIT_COMMAND_FAILED",
            f"Git '{' '.join(safe_args[:3])}' failed: {stderr or 'git error'}",
        ) from exc
    return (completed.stdout or "").strip()


def ls_remote_sha(url: str, ref: str = "HEAD") -> str | None:
    """Resolve a remote ref to a SHA without cloning (bounded).

    Returns the SHA, or None when the repository/ref is unreachable or
    private. Never raises for network failures — callers treat None as
    "not verifiably readable".
    """
    try:
        cleaned = validate_repository_url(url)
    except RepositoryUrlError:
        return None
    if resolve_local_repo_path(cleaned) is not None:
        return None  # local paths are not remotes; use rev-parse instead
    try:
        _enforce_connection_boundary(cleaned)
    except (GitAcquireError, RepositoryUrlError):
        return None
    if not _git_available():
        return None
    try:
        out = _run_git(
            ["ls-remote", cleaned, ref], timeout=_LSREMOTE_TIMEOUT_S
        )
    except GitAcquireError:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 2 and _FULL_SHA_RE.match(parts[0]):
            return parts[0].lower()
    return None


def local_rev_parse(local: Path, sha: str) -> str:
    """Assert a commit exists in a local repository; return normalized SHA."""
    wanted = _require_full_sha(sha)
    try:
        out = _run_git(["-C", str(local), "rev-parse", "--verify", f"{wanted}^{{commit}}"])
    except GitAcquireError as exc:
        raise GitAcquireError(
            "SHA_NOT_FOUND",
            "Commit is not present in the local repository.",
        ) from exc
    resolved = out.strip().lower()
    if resolved != wanted:
        raise GitAcquireError(
            "SHA_MISMATCH",
            "Local repository resolved a different commit than requested.",
        )
    return resolved


def checkout_commit(repo_path: Path, sha: str, *, timeout: int = _GIT_TIMEOUT_S,
                    env: dict[str, str] | None = None) -> str:
    """Fetch + detach-checkout an exact commit, then assert HEAD == sha."""
    wanted = _require_full_sha(sha)
    _run_git(
        ["-C", str(repo_path), "-c", "http.followRedirects=false",
         "fetch", "--depth", "1", "--filter=blob:none", "origin", wanted],
        timeout=timeout, env=env,
    )
    _run_git(
        ["-C", str(repo_path), "checkout", "--detach", "--force", wanted],
        timeout=timeout, env=env,
    )
    head = _run_git(["-C", str(repo_path), "rev-parse", "HEAD"], timeout=timeout).lower()
    if head != wanted:
        raise GitAcquireError(
            "SHA_MISMATCH",
            "Checked-out HEAD does not match the requested commit.",
        )
    return head


def _export_local_archive(local: Path, sha: str, dest: Path) -> None:
    """Export one commit of a local repo to dest (zip + slip-guarded extract)."""
    wanted = local_rev_parse(local, sha)
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True, exist_ok=True)
    try:
        completed = subprocess.run(
            ["git", "-C", str(local), "archive", "--format=zip", wanted],
            check=True,
            capture_output=True,
            timeout=_GIT_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitAcquireError("GIT_TIMEOUT", "Git archive timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise GitAcquireError("GIT_COMMAND_FAILED", "Git archive failed") from exc
    data = completed.stdout or b""
    if len(data) > _MAX_ARCHIVE_BYTES:
        raise GitAcquireError("ARCHIVE_TOO_LARGE", "Commit archive exceeds the size bound.")
    import io

    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            target = (dest / member.filename).resolve()
            if dest.resolve() not in target.parents and target != dest.resolve():
                raise GitAcquireError("UNSAFE_ARCHIVE_PATH", "Archive member escapes destination.")
        archive.extractall(dest)


def resolve_ref_to_sha(
    repository_url: str, ref: str | None, *, env: dict[str, str] | None = None
) -> str:
    """Resolve a branch/tag/full-SHA to an immutable 40-hex commit SHA.

    Fails closed on unresolved, ambiguous, or malformed revisions — never
    returns a moving ref. Local repos resolve via rev-parse; remotes via
    ls-remote against the connection boundary (no clone needed).
    """
    if not ref or not ref.strip():
        raise GitAcquireError("SHA_REQUIRED", "A branch, tag, or commit SHA is required.")
    candidate = ref.strip()
    if _FULL_SHA_RE.match(candidate):
        if candidate.lower() == _ZERO_SHA:
            raise GitAcquireError("SHA_REQUIRED", "Null SHA (all zeros) is not a commit.")
        return candidate.lower()
    try:
        cleaned = validate_repository_url(repository_url)
    except RepositoryUrlError as exc:
        raise GitAcquireError(exc.code, exc.message) from exc
    local = resolve_local_repo_path(cleaned)
    if local is not None:
        if not local.exists():
            raise GitAcquireError("REPO_NOT_FOUND", "Local repository path not found.")
        out = _run_git(
            ["-C", str(local), "rev-parse", "--verify", f"{candidate}^{{commit}}"],
            timeout=_LSREMOTE_TIMEOUT_S, env=env,
        ).strip().lower()
        if not _FULL_SHA_RE.match(out):
            raise GitAcquireError("REVISION_NOT_FOUND", f"Ref '{candidate}' did not resolve.")
        return out
    # Remote: validate connection boundary first, then ls-remote the exact ref.
    _enforce_connection_boundary(cleaned)
    if not _git_available():
        raise GitAcquireError("GIT_UNAVAILABLE", "git executable not found.")
    matches: list[str] = []
    for ls_ref in (candidate, f"refs/heads/{candidate}", f"refs/tags/{candidate}"):
        try:
            out = _run_git(["ls-remote", cleaned, ls_ref], timeout=_LSREMOTE_TIMEOUT_S, env=env)
        except GitAcquireError:
            continue
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and _FULL_SHA_RE.match(parts[0]):
                # ls-remote echoes the requested ref name; accept exact matches
                # and peeled tag entries (TAG^{}), reject anything else.
                rname = parts[1]
                if rname in (ls_ref, f"{ls_ref}^{{}}"):
                    matches.append(parts[0].lower())
    unique = sorted(set(matches))
    if len(unique) != 1:
        raise GitAcquireError(
            "REVISION_NOT_FOUND" if not unique else "AMBIGUOUS_REVISION",
            f"Ref '{candidate}' did not resolve to a single commit.",
        )
    return unique[0]


def _reject_unsafe_submodules(checkout: Path) -> None:
    """Fail closed on malicious .gitmodules (unapproved hosts, local paths)."""
    gitmodules = checkout / ".gitmodules"
    if not gitmodules.is_file():
        return
    try:
        text = gitmodules.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise GitAcquireError("SUBMODULE_REJECTED", "Could not inspect .gitmodules.") from exc
    import configparser
    import io

    parser = configparser.ConfigParser()
    try:
        parser.read_file(io.StringIO(text))
    except configparser.Error as exc:
        raise GitAcquireError("SUBMODULE_REJECTED", "Unparseable .gitmodules.") from exc
    for section in parser.sections():
        url = (parser[section].get("url") or "").strip()
        if not url:
            raise GitAcquireError("SUBMODULE_REJECTED", "Submodule without URL.")
        try:
            validate_repository_url(url)
        except RepositoryUrlError as exc:
            raise GitAcquireError("SUBMODULE_REJECTED", f"Submodule blocked: {exc.message}") from exc
        if resolve_local_repo_path(url) is not None:
            raise GitAcquireError("SUBMODULE_REJECTED", "Local-path submodules are not allowed.")
        host = _hostname_of(url)
        # shortcut: only GitHub + already-validated public hosts pass; never
        # forward credentials — submodules fetch anonymously or not at all.
        if host and host not in _APPROVED_GITHUB_HOSTS:
            try:
                _enforce_connection_boundary(url)
            except GitAcquireError as exc:
                raise GitAcquireError("SUBMODULE_REJECTED", exc.message) from exc
    # Nested submodules: one level is enough for V1 — refuse deeper nesting.
    for nested in checkout.rglob(".gitmodules"):
        if nested != gitmodules:
            raise GitAcquireError("SUBMODULE_REJECTED", "Nested submodules are not allowed.")


def acquire_repository(
    deployment_id: str, repository_url: str, *, ref_sha: str | None = None,
    token_env: dict[str, str] | None = None,
) -> RepoAcquisition:
    """
    Acquire a repository into the deployment workspace.

    Supports:
    - local filesystem paths / file:// URIs (offline-friendly)
    - remote git URLs via shallow clone (requires network + git)

    When ``ref_sha`` is given, the exact commit is materialized and
    ``checked_sha`` carries the verified HEAD. Without it, behavior is
    unchanged (workspace copy / branch-tip clone, ``checked_sha=None``).
    """
    dest = deployment_workspace(deployment_id) / "repo"
    if dest.exists():
        shutil.rmtree(dest, ignore_errors=True)

    try:
        repository_url = validate_repository_url(repository_url)
    except RepositoryUrlError as exc:
        raise GitAcquireError(exc.code, exc.message) from exc

    wanted = _require_full_sha(ref_sha) if ref_sha else None

    local = resolve_local_repo_path(repository_url)
    if local is not None:
        if not local.exists():
            raise GitAcquireError("REPO_NOT_FOUND", f"Local repository path not found: {local}")
        if wanted:
            _export_local_archive(local, wanted, dest)
            logger.info(
                "Acquired local repo at commit deployment_id=%s sha=%.12s",
                deployment_id, wanted,
            )
            return RepoAcquisition(
                path=dest, method="local_archive", cleaned_url=str(local),
                checked_sha=wanted,
            )
        shutil.copytree(
            local,
            dest,
            ignore=shutil.ignore_patterns(
                ".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist"
            ),
        )
        logger.info("Acquired local repo deployment_id=%s path=%s", deployment_id, local)
        return RepoAcquisition(path=dest, method="local_copy", cleaned_url=str(local))

    # Remote git shallow clone — connection boundary enforced for real.
    if not _git_available():
        raise GitAcquireError(
            "GIT_UNAVAILABLE",
            "git executable not found. Install git or pass a local repository path.",
        )
    _enforce_connection_boundary(repository_url)

    dest.parent.mkdir(parents=True, exist_ok=True)
    import os

    clone_env = {**os.environ, **_secure_git_env(token_env)}
    # Disable submodule auto-fetch at clone time; submodules are validated
    # explicitly below and never inherit credentials.
    clone_cmd = [
        "git", "clone", "--depth", "1", "--single-branch",
        "--no-recurse-submodules", "--config",
        "http.followRedirects=false",
        repository_url, str(dest),
    ]
    try:
        subprocess.run(
            ["git", *clone_cmd[1:]],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
            env=clone_env,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitAcquireError("GIT_TIMEOUT", "Shallow clone timed out") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()[:500]
        raise GitAcquireError(
            "GIT_CLONE_FAILED",
            f"Shallow clone failed: {stderr or exc}",
        ) from exc

    checked: str | None = None
    if wanted:
        if token_env:
            # Re-validate boundary before the authenticated fetch (TOCTOU).
            _enforce_connection_boundary(repository_url)
        checked = checkout_commit(dest, wanted, env=token_env)
    _reject_unsafe_submodules(dest)

    logger.info("Shallow-cloned repo deployment_id=%s url=%s", deployment_id, repository_url)
    return RepoAcquisition(
        path=dest, method="shallow_clone", cleaned_url=repository_url,
        checked_sha=checked,
    )


def _git_available() -> bool:
    try:
        subprocess.run(
            ["git", "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
