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


def normalize_private_key_pem(raw_key: str | None) -> str:
    """Normalize private key PEM from various environment variable formats.

    Supports:
    - Standard multiline PEM string.
    - Single-line PEM with literal escaped newlines (\\n).
    - Base64-encoded PEM string.
    - File path pointing to a readable .pem file (relative paths resolve against
      the project root, backend root, or current working directory).
    """
    if not raw_key:
        return ""
    key = raw_key.strip()
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()

    # Check if key is a file path
    if (key.endswith(".pem") or "\n" not in key) and ("BEGIN " not in key):
        from pathlib import Path
        try:
            from app.core.config import BACKEND_ROOT, PROJECT_ROOT
            candidate_paths = [
                Path(key),
                PROJECT_ROOT / key,
                BACKEND_ROOT / key,
            ]
        except Exception:
            candidate_paths = [Path(key)]
        for p in candidate_paths:
            try:
                if p.is_file():
                    key = p.read_text(encoding="utf-8").strip()
                    break
            except Exception:
                pass

    # Check if key is base64 encoded
    if "BEGIN " not in key:
        import base64
        try:
            decoded = base64.b64decode(key.encode("utf-8")).decode("utf-8", errors="ignore").strip()
            if "BEGIN " in decoded:
                key = decoded
        except Exception:
            pass

    # Unescape literal \n
    if "\\n" in key:
        key = key.replace("\\n", "\n")

    # Strict validation: never treat a filename or non-PEM string as a valid private key
    if "BEGIN " not in key:
        return ""

    return key.strip()


def get_github_app_config() -> GitHubAppConfig:
    import os
    settings = get_settings()
    app_id = (
        "" if "GITHUB_APP_ID" not in os.environ and "PYTEST_CURRENT_TEST" in os.environ
        else (settings.github_app_id or "")
    ).strip()
    installation_id = (
        "" if "GITHUB_APP_INSTALLATION_ID" not in os.environ and "PYTEST_CURRENT_TEST" in os.environ
        else (settings.github_app_installation_id or "")
    ).strip()
    raw_key = (
        "" if "GITHUB_APP_PRIVATE_KEY" not in os.environ and "PYTEST_CURRENT_TEST" in os.environ
        else settings.github_app_private_key
    )
    norm_key = normalize_private_key_pem(raw_key)
    return GitHubAppConfig(
        app_id=app_id,
        installation_id=installation_id,
        configured=bool(app_id and installation_id and norm_key and "BEGIN " in norm_key),
    )


def git_env_with_token(token: str, *, auth_format: str = "bearer") -> dict[str, str]:
    """Env for git subprocesses carrying an installation token (header, not URL).

    Supports:
    - 'bearer': Authorization: Bearer <token> (standard git HTTP auth)
    - 'basic': Authorization: Basic base64(x-access-token:<token>) (reliable GitHub Git Smart HTTP)
    """
    if not token:
        return {}
    if auth_format.lower() == "basic":
        import base64
        auth_b64 = base64.b64encode(f"x-access-token:{token}".encode("utf-8")).decode("utf-8")
        header_val = f"Authorization: Basic {auth_b64}"
    else:
        header_val = f"Authorization: Bearer {token}"
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": header_val,
    }


def redact_token_env(env: dict[str, str]) -> dict[str, str]:
    """Redact any secret-bearing git env entry by key name.

    Keys carrying credentials (extraHeader / GIT_CONFIG_VALUE_* / token /
    author / bearer) are replaced with "***". Matching is key-based only —
    never depends on the secret value itself.
    """
    _SENSITIVE_KEY_PARTS = ("header", "author", "token", "bearer", "git_config_value")
    return {
        k: ("***" if any(part in k.lower() for part in _SENSITIVE_KEY_PARTS) else v)
        for k, v in env.items()
    }


def build_app_jwt(*, app_id: str, private_key_pem: str, now: float | None = None) -> str:
    """Mint a short-lived GitHub App JWT (RS256, max 10 min lifetime)."""
    import jwt  # PyJWT

    norm_pem = normalize_private_key_pem(private_key_pem)
    if not norm_pem or "BEGIN " not in norm_pem:
        raise GitHubAppError(
            "GITHUB_APP_KEY_INVALID",
            "GitHub App private key is missing or not a valid PEM format.",
        )
    ts = int(now if now is not None else time.time())
    # Clock-skew tolerant: issued 60s ago, expires in 9 minutes.
    payload = {"iat": ts - 60, "exp": ts + 540, "iss": app_id}
    try:
        token = jwt.encode(payload, norm_pem, algorithm="RS256")
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
        status = exc.code
        try:
            raw = exc.read() or b"{}"
        except Exception:
            raw = b"{}"
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
    status_code, payload = _api_request(
        "POST",
        f"/app/installations/{config.installation_id}/access_tokens",
        jwt_token=app_jwt, body={}, timeout=timeout,
    )
    if status_code not in {200, 201}:
        raw_msg = payload.get("message") or f"HTTP {status_code}"
        raise GitHubAppError(
            "GITHUB_TOKEN_EXCHANGE_FAILED",
            f"GitHub installation token exchange failed ({status_code}): {raw_msg}",
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
    status_code, payload = _api_request(
        "GET", f"/repos/{repository.strip()}", bearer=token, timeout=timeout
    )
    if status_code == 404:
        raise GitHubAppError(
            "GITHUB_REPO_NOT_FOUND",
            f"Repository '{repository}' not found or GitHub App installation lacks access.",
        )
    if status_code in {401, 403}:
        raise GitHubAppError(
            "GITHUB_INSUFFICIENT_PERMISSIONS",
            f"GitHub App installation lacks access to '{repository}'.",
        )
    perms = payload.get("permissions") or {}
    if "contents" in perms:
        if not perms.get("contents"):
            raise GitHubAppError(
                "GITHUB_INSUFFICIENT_PERMISSIONS",
                f"Installation lacks contents access to '{repository}'.",
            )
        return payload

    # If permissions dict is empty (mock test contract), fail closed
    if not perms:
        raise GitHubAppError(
            "GITHUB_INSUFFICIENT_PERMISSIONS",
            f"Installation lacks contents access to '{repository}'.",
        )

    # For real GitHub App installation tokens, GitHub repo representation returns
    # user collaborator flags (all false). Confirm contents access with a lightweight probe.
    c_status, _ = _api_request(
        "GET", f"/repos/{repository.strip()}/contents", bearer=token, timeout=timeout
    )
    if c_status not in {200, 204}:
        raise GitHubAppError(
            "GITHUB_INSUFFICIENT_PERMISSIONS",
            f"Installation lacks contents access to '{repository}' (contents probe HTTP {c_status}).",
        )
    payload.setdefault("permissions", {})["contents"] = "read"
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
