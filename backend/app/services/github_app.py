"""GitHub App integration: JWT -> installation token -> private clone.

No network calls run without explicit App configuration. Tokens are
short-lived, never persisted, never logged, and injected via
GIT_CONFIG http.extraHeader (never URLs).
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings

_API_BASE = "https://api.github.com"


class TokenTransport(Protocol):
    def mint_installation_token(self, *, app_id: str, installation_id: str) -> str: ...


class GitHubAppError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class GitHubAppConfig:
    app_id: str
    installation_id: str
    configured: bool


def get_github_app_config() -> GitHubAppConfig:
    settings = get_settings()
    app_id = (settings.github_app_id or "").strip()
    installation_id = (settings.github_app_installation_id or "").strip()
    has_key = bool((settings.github_app_private_key or "").strip())
    return GitHubAppConfig(
        app_id=app_id,
        installation_id=installation_id,
        configured=bool(app_id and installation_id and has_key),
    )


def git_env_with_token(token: str) -> dict[str, str]:
    """Env for git subprocesses carrying an installation token (header, not URL)."""
    if not token:
        return {}
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {token}",
    }


def redact_token_env(env: dict[str, str]) -> dict[str, str]:
    return {k: ("***" if "header" in k.lower() or "author" in v.lower() else v) for k, v in env.items()}


def build_app_jwt(*, app_id: str, private_key_pem: str, now: float | None = None) -> str:
    """Mint a short-lived GitHub App JWT (RS256, max 10 min lifetime)."""
    import jwt  # PyJWT

    ts = int(now if now is not None else time.time())
    # Clock-skew tolerant: issued 60s ago, expires in 9 minutes.
    payload = {"iat": ts - 60, "exp": ts + 540, "iss": app_id}
    try:
        token = jwt.encode(payload, private_key_pem, algorithm="RS256")
    except Exception as exc:
        raise GitHubAppError("GITHUB_APP_JWT_FAILED", "Could not sign GitHub App JWT.") from exc
    return token if isinstance(token, str) else token.decode("utf-8")


def _api_request(
    method: str, path: str, *, jwt_token: str | None = None,
    bearer: str | None = None, body: dict | None = None,
    timeout: float = 15.0,
) -> tuple[int, dict]:
    url = f"{_API_BASE}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "MEDHA/1.0")
    if jwt_token:
        req.add_header("Authorization", f"Bearer {jwt_token}")
    elif bearer:
        req.add_header("Authorization", f"Bearer {bearer}")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read() or b"{}"
    except urllib.error.HTTPError as exc:
        raise GitHubAppError(
            "GITHUB_API_ERROR",
            f"GitHub API {path} returned HTTP {exc.code}.",
        ) from exc
    except OSError as exc:
        raise GitHubAppError("GITHUB_API_UNREACHABLE", "GitHub API unreachable.") from exc
    try:
        return status, json.loads(raw.decode("utf-8") or "{}")
    except ValueError as exc:
        raise GitHubAppError("GITHUB_API_ERROR", "GitHub API returned invalid JSON.") from exc


def mint_installation_token(
    *, transport: TokenTransport | None = None, timeout: float = 15.0,
) -> str:
    """Obtain a short-lived installation token via the official API.

    A fake transport may be injected in tests; production always uses the
    GitHub API with a freshly minted JWT. Never logs or persists the token.
    """
    config = get_github_app_config()
    if not config.configured:
        raise GitHubAppError(
            "GITHUB_APP_NOT_CONFIGURED",
            "GitHub App is not configured (GITHUB_APP_ID / PRIVATE_KEY / INSTALLATION_ID).",
        )
    if transport is not None:
        token = transport.mint_installation_token(
            app_id=config.app_id, installation_id=config.installation_id
        )
        if not token:
            raise GitHubAppError("GITHUB_TOKEN_EMPTY", "Token transport returned empty token.")
        return token
    settings = get_settings()
    app_jwt = build_app_jwt(
        app_id=config.app_id, private_key_pem=settings.github_app_private_key
    )
    _, payload = _api_request(
        "POST",
        f"/app/installations/{config.installation_id}/access_tokens",
        jwt_token=app_jwt, body={}, timeout=timeout,
    )
    token = str(payload.get("token") or "")
    if not token:
        raise GitHubAppError("GITHUB_TOKEN_EMPTY", "GitHub did not issue an installation token.")
    return token


def check_repository_access(
    *, repository: str, token: str, timeout: float = 15.0,
) -> dict:
    """Verify the installation can access owner/repo with contents:read.

    Returns the repository payload; raises GitHubAppError otherwise. Never
    assume installation-id possession alone proves access.
    """
    if "/" not in (repository or ""):
        raise GitHubAppError("GITHUB_REPO_INVALID", "Repository must be 'owner/name'.")
    _, payload = _api_request(
        "GET", f"/repos/{repository.strip()}", bearer=token, timeout=timeout
    )
    perms = payload.get("permissions") or {}
    if not perms.get("contents"):
        raise GitHubAppError(
            "GITHUB_INSUFFICIENT_PERMISSIONS",
            f"Installation lacks contents access to '{repository}'.",
        )
    return payload


def parse_github_repo(url: str) -> str | None:
    """Return 'owner/repo' for https GitHub URLs, else None.

    Only the https form is ever authenticated (no scp/ssh agent handling,
    no credential embedding). Returns None for local paths and non-GitHub
    hosts so callers keep the anonymous path unchanged.
    """
    from urllib.parse import urlparse

    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in {"https", "git+https"}:
        return None
    if (parsed.hostname or "").lower() != "github.com":
        return None
    if parsed.username or parsed.password:
        return None
    parts = [p for p in (parsed.path or "").split("/") if p not in ("", ".", "..")]
    if len(parts) != 2:
        return None
    owner, name = parts
    if name.lower().endswith(".git"):
        name = name[:-4]
    if not owner or not name or any(c.isspace() or c in "@:?#" for c in owner + name):
        return None
    return f"{owner}/{name}"


def prepare_private_access(
    repository_url: str, *, transport: TokenTransport | None = None
) -> dict[str, str]:
    """Mint a scoped installation token for a GitHub repo, or {} for public path.

    Returns a git env dict carrying the short-lived token via http.extraHeader
    (never in the URL). Fails closed with GitHubAppError when the App is
    configured but the token cannot be minted or the installation lacks access
    to the requested repository. The token is never logged, persisted, or
    included in error messages — callers must keep the returned env out of
    events/records.
    """
    repository = parse_github_repo(repository_url)
    if repository is None:
        return {}
    if not get_github_app_config().configured:
        return {}
    token = mint_installation_token(transport=transport)
    try:
        check_repository_access(repository=repository, token=token)
    except GitHubAppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise GitHubAppError("GITHUB_REPO_CHECK_FAILED", "Repository access check failed.") from exc
    return git_env_with_token(token)


def clone_private_repository(
    *, repository_url: str, repository: str, dest_name: str,
    ref_sha: str | None = None,
    transport: TokenTransport | None = None,
) -> dict[str, str | None]:
    """Clone a private repo at an exact SHA using a short-lived token.

    Returns acquisition metadata (method/token redacted). Delegates the
    actual checkout to git_service.acquire_repository so boundary checks,
    SHA verification, and submodule guards stay in one place.
    """
    from app.services.git_service import GitAcquireError, acquire_repository

    token = mint_installation_token(transport=transport)
    try:
        check_repository_access(repository=repository, token=token)
    except GitHubAppError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise GitHubAppError("GITHUB_REPO_CHECK_FAILED", "Repository access check failed.") from exc
    try:
        acquisition = acquire_repository(
            dest_name, repository_url, ref_sha=ref_sha,
            token_env=git_env_with_token(token),
        )
    except Exception as exc:
        code = getattr(exc, "code", "GIT_CLONE_FAILED")
        raise GitHubAppError(code, "Private repository clone failed.") from exc
    finally:
        del token
    return {
        "path": str(acquisition.path),
        "method": acquisition.method,
        "checked_sha": acquisition.checked_sha,
    }
