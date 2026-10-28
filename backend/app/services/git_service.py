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
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.ai.redact import redact_text
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
    """Env for every git subprocess: no prompts, no credential leakage.

    `core.longpaths=true` fixes real checkout failures on Windows, where
    git's default MAX_PATH (260) limit aborts clones of repositories with
    deeply nested paths (verified: vercel/next.js). It is a no-op on other
    platforms, so it is safe to pass everywhere.
    """
    env = {
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ASKPASS": "",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.longpaths",
        "GIT_CONFIG_VALUE_0": "true",
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
    """Git failure with structured, sanitized diagnostics.

    `message` is the concise user-facing summary (fatal lines only — never
    progress noise). The full (bounded, redacted) subprocess output and the
    exit code / duration / failing operation live in the dedicated fields so
    callers can persist them without parsing the message string.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        operation: str | None = None,
        exit_code: int | None = None,
        duration_s: float | None = None,
        stderr_tail: str | None = None,
        stdout_tail: str | None = None,
        category: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.operation = operation
        self.exit_code = exit_code
        self.duration_s = duration_s
        self.stderr_tail = stderr_tail
        self.stdout_tail = stdout_tail
        self.category = category or _CATEGORY_BY_CODE.get(code, "unknown")

    def to_diagnostics(self) -> dict:
        """JSON-safe diagnostics for the persisted run failure record."""
        out: dict = {"code": self.code, "category": self.category}
        if self.operation:
            out["operation"] = self.operation
        if self.exit_code is not None:
            out["exit_code"] = self.exit_code
        if self.duration_s is not None:
            out["duration_seconds"] = round(self.duration_s, 3)
        if self.stderr_tail:
            out["stderr_tail"] = self.stderr_tail
        if self.stdout_tail:
            out["stdout_tail"] = self.stdout_tail
        return out


# Coarse failure categories derived from stable error codes. Codes that
# depend on git output text are classified at raise time instead.
_CATEGORY_BY_CODE = {
    "GIT_TIMEOUT": "timeout",
    "GIT_UNAVAILABLE": "unavailable",
    "GIT_CHECKOUT_FAILED": "filesystem",
    "REPO_NOT_FOUND": "not_found",
    "REVISION_NOT_FOUND": "not_found",
    "SHA_NOT_FOUND": "not_found",
}

# Bounded tails: enough for diagnosis, never the whole pack negotiation.
_STDERR_TAIL_CHARS = 4000
_STDOUT_TAIL_CHARS = 2000

# Git progress output (stderr) that carries no diagnostic value. Only used to
# keep the human-readable summary clean — the sanitized tail retains it.
_PROGRESS_RE = re.compile(
    r"^(Cloning into |Updating files:|remote:\s*(Counting|Compressing|Enumerating|"
    r"Total|Finding sources|Flattening|Writing objects)|Receiving objects:|"
    r"Resolving deltas:|fatal:\s*dangling|Filtering content:|Downloading |"
    r"\s*[0-9]+%)"
)


def _classify_git_stderr(stderr: str) -> str:
    """Map git output to a stable failure category (deterministic, bounded)."""
    text = stderr.lower()
    if "clone succeeded, but checkout failed" in text or "filename too long" in text:
        return "filesystem"
    if "cannot create " in text or "unable to create file" in text:
        return "filesystem"
    if "no space left on device" in text or "disk full" in text:
        return "disk"
    if (
        "repository not found" in text
        or "does not appear to be a git repository" in text
        or "404" in text
    ):
        return "not_found"
    if (
        "authentication failed" in text
        or "could not read username" in text
        or "returned error: 401" in text
        or "returned error: 403" in text
        or "permission denied" in text
    ):
        return "auth"
    if (
        "could not resolve host" in text
        or "unable to access" in text
        or "early eof" in text
        or "connection reset" in text
        or "connection timed out" in text
        or "network is unreachable" in text
        or "the remote end hung up" in text
    ):
        return "network"
    return "unknown"


def _git_fatal_summary(stderr: str) -> str:
    """Concise summary: the fatal/error lines, else the last meaningful line.

    Git writes progress ("Updating files: 77%") to stderr ahead of the one
    line that explains the failure — keep the signal, drop the noise.
    Redacted here so the user-facing message can never leak credentials
    embedded in URLs (e.g. https://user:pass@host).
    """
    meaningful = [
        line.strip()
        for line in (stderr or "").splitlines()
        if line.strip() and not _PROGRESS_RE.match(line.strip())
    ]
    if not meaningful:
        return "git exited unsuccessfully without a diagnostic message."
    fatal = [line for line in meaningful if line.lower().startswith(("fatal:", "error:"))]
    chosen = fatal or meaningful
    summary = " / ".join(chosen[-3:])
    if len(summary) > 300:
        summary = f"{summary[:297]}..."
    return redact_text(summary)


def _sanitize_git_output(text: str | None, *, max_chars: int) -> str | None:
    """Redact credentials and bound subprocess output for persistence."""
    if not text:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    redacted = redact_text(stripped)
    if len(redacted) > max_chars:
        redacted = f"[...truncated...]\n{redacted[-max_chars:]}"
    return redacted


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
    env: dict[str, str] | None = None, operation: str | None = None,
) -> str:
    """Run a bounded git command; stdout on success, GitAcquireError otherwise.

    Failures carry the real exit code, elapsed time, and a sanitized stderr
    tail so callers can persist honest diagnostics.
    """
    import os

    merged = {**os.environ, **_secure_git_env(env)}
    # Never let secret-bearing values reach argv/exceptions: scrub before use.
    # Handles both https://user@host/... URLs and scp-like git@host:... syntax.
    def _scrub(arg: str) -> str:
        if "@" in arg and ("://" in arg or ":" in arg):
            return "<redacted-url>"
        return arg

    safe_args = [_scrub(a) for a in args]
    op = operation or "git"
    started = time.monotonic()
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
        stderr_tail = _sanitize_git_output(
            exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr,
            max_chars=_STDERR_TAIL_CHARS,
        )
        raise GitAcquireError(
            "GIT_TIMEOUT",
            f"Git {op} timed out after {timeout}s",
            operation=op,
            duration_s=time.monotonic() - started,
            stderr_tail=stderr_tail,
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode(errors="replace")
        summary = _git_fatal_summary(stderr)
        raise GitAcquireError(
            "GIT_COMMAND_FAILED",
            f"Git {op} failed: {summary}",
            operation=op,
            exit_code=exc.returncode,
            duration_s=time.monotonic() - started,
            stderr_tail=_sanitize_git_output(stderr, max_chars=_STDERR_TAIL_CHARS),
            stdout_tail=_sanitize_git_output(exc.stdout, max_chars=_STDOUT_TAIL_CHARS),
            category=_classify_git_stderr(stderr),
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


def ls_remote_default_branch(url: str) -> str | None:
    """Detect the remote default branch without cloning (bounded).

    Parses `git ls-remote --symref <url> HEAD` for the `ref:
    refs/heads/<branch>` symref line. Returns the branch name, or None
    when it cannot be determined (unreachable, private, no git, or no
    symref advertised). Never raises for network failures — callers fall
    back to an explicit or conventional default.
    """
    try:
        cleaned = validate_repository_url(url)
    except RepositoryUrlError:
        return None
    if resolve_local_repo_path(cleaned) is not None:
        return None
    try:
        _enforce_connection_boundary(cleaned)
    except (GitAcquireError, RepositoryUrlError):
        return None
    if not _git_available():
        return None
    try:
        out = _run_git(
            ["ls-remote", "--symref", cleaned, "HEAD"],
            timeout=_LSREMOTE_TIMEOUT_S,
        )
    except GitAcquireError:
        return None
    for line in out.splitlines():
        stripped = line.strip()
        if not stripped.startswith("ref:"):
            continue
        # Format: "ref: refs/heads/<branch>\tHEAD"
        ref_part = stripped[len("ref:"):].strip().split()[0]
        if ref_part.startswith("refs/heads/"):
            candidate = ref_part[len("refs/heads/"):].strip()
            if 0 < len(candidate) <= 120 and ".." not in candidate:
                return candidate
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
        timeout=timeout, env=env, operation="fetch",
    )
    _run_git(
        ["-C", str(repo_path), "checkout", "--detach", "--force", wanted],
        timeout=timeout, env=env, operation="checkout",
    )
    head = _run_git(["-C", str(repo_path), "rev-parse", "HEAD"], timeout=timeout,
                    env=env, operation="rev-parse").lower()
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
            operation="clone",
        )
    _enforce_connection_boundary(repository_url)

    dest.parent.mkdir(parents=True, exist_ok=True)
    import os

    from app.core.config import get_settings

    clone_env = {**os.environ, **_secure_git_env(token_env)}
    # Disable submodule auto-fetch at clone time; submodules are validated
    # explicitly below and never inherit credentials.
    clone_cmd = [
        "git", "clone", "--depth", "1", "--single-branch",
        "--no-recurse-submodules", "--config",
        "http.followRedirects=false",
        repository_url, str(dest),
    ]
    # Evidence-based bound: cloning + checkout of a 34k-file repository
    # (vercel/next.js) measured ~85s on a mid-range machine; the configured
    # acquire timeout (default 600s) leaves headroom for slower links.
    clone_timeout = max(60.0, float(get_settings().timeout_acquire_s))
    started = time.monotonic()
    try:
        completed = subprocess.run(
            ["git", *clone_cmd[1:]],
            capture_output=True,
            text=True,
            timeout=clone_timeout,
            env=clone_env,
        )
    except subprocess.TimeoutExpired as exc:
        stderr_tail = _sanitize_git_output(
            exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else exc.stderr,
            max_chars=_STDERR_TAIL_CHARS,
        )
        raise GitAcquireError(
            "GIT_TIMEOUT",
            f"Shallow clone timed out after {clone_timeout:.0f}s",
            operation="clone",
            duration_s=time.monotonic() - started,
            stderr_tail=stderr_tail,
        ) from exc
    if completed.returncode != 0:
        stderr = completed.stderr or ""
        # "Clone succeeded, but checkout failed" means the objects arrived but
        # the working tree could not be materialized (e.g. Windows long paths,
        # permissions, disk) — a distinct outcome from a transport failure.
        checkout_failed = "Clone succeeded, but checkout failed" in stderr
        code = "GIT_CHECKOUT_FAILED" if checkout_failed else "GIT_CLONE_FAILED"
        summary = _git_fatal_summary(stderr)
        raise GitAcquireError(
            code,
            f"Shallow clone failed: {summary}",
            operation="checkout" if checkout_failed else "clone",
            exit_code=completed.returncode,
            duration_s=time.monotonic() - started,
            stderr_tail=_sanitize_git_output(stderr, max_chars=_STDERR_TAIL_CHARS),
            stdout_tail=_sanitize_git_output(completed.stdout, max_chars=_STDOUT_TAIL_CHARS),
            category=_classify_git_stderr(stderr),
        )

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
