"""Clerk session verification for FastAPI (Clerk is the identity provider).

The frontend (Next.js middleware) only proves a session to the browser layer.
FastAPI independently verifies the Bearer JWT: RS256 signature against Clerk's
JWKS, issuer match, expiry, and `sub` presence. User IDs from request bodies
or arbitrary headers are never trusted.

Modes (MEDHA_AUTH_MODE):
- "off" (default): legacy single-operator behavior. No Bearer required; the
  subject is "local-operator" and no ownership filtering applies.
- "clerk": every /api route except /health and /api/webhooks/* requires a
  valid `Authorization: Bearer <Clerk session token>`. Resources are scoped
  to the verified `sub` (owner_sub) in both SQLite and Postgres.

Production never silently falls back: mode "clerk" without JWKS configuration
fails closed (503); mode "off" keeps the pre-existing MEDHA_API_TOKEN
fail-closed behavior for mutating routes.
"""

from __future__ import annotations

import time
from typing import Any

import httpx
import jwt
from fastapi import Depends, HTTPException, Request

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.repositories import AccountRepository

logger = get_logger(__name__)

LOCAL_SUBJECT = "local-operator"

_jwks_cache: dict[str, Any] = {"keys": None, "fetched_at": 0.0}
_JWKS_TTL_S = 3600.0


def auth_mode() -> str:
    return (get_settings().auth_mode or "off").strip().lower()


def clerk_configured() -> bool:
    settings = get_settings()
    return bool((settings.clerk_jwks_url or "").strip() or (settings.clerk_domain or "").strip())


def jwks_url() -> str:
    settings = get_settings()
    explicit = (settings.clerk_jwks_url or "").strip()
    if explicit:
        return explicit
    domain = (settings.clerk_domain or "").strip().rstrip("/")
    return f"https://{domain}/.well-known/jwks.json"


def expected_issuer() -> str:
    settings = get_settings()
    domain = (settings.clerk_domain or "").strip().rstrip("/")
    if domain and not domain.startswith("http"):
        return f"https://{domain}"
    return domain


def _fetch_jwks(client: httpx.Client | None = None) -> dict[str, Any]:
    now = time.time()
    if _jwks_cache["keys"] is not None and now - _jwks_cache["fetched_at"] < _JWKS_TTL_S:
        return _jwks_cache["keys"]
    url = jwks_url()
    try:
        if client is not None:
            response = client.get(url, timeout=10.0)
        else:
            response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        keys = response.json()
    except Exception as exc:  # noqa: BLE001 - fetch failure is a closed gate
        logger.warning("Clerk JWKS fetch failed: %s", type(exc).__name__)
        raise _unavailable() from exc
    if not isinstance(keys, dict) or not keys.get("keys"):
        raise _unavailable()
    _jwks_cache["keys"] = keys
    _jwks_cache["fetched_at"] = now
    return keys


def _unauthorized(code: str = "UNAUTHENTICATED", message: str = "Valid authentication is required.") -> HTTPException:
    return HTTPException(status_code=401, detail={"code": code, "message": message, "details": {}})


def _unavailable() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "AUTH_NOT_CONFIGURED",
            "message": "Clerk authentication is required but not configured or unreachable.",
            "details": {},
        },
    )


def verify_clerk_token(token: str, *, client: httpx.Client | None = None) -> dict[str, Any]:
    """Verify signature, issuer, and expiry. Returns claims on success."""
    if not clerk_configured():
        raise _unavailable()
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise _unauthorized("INVALID_TOKEN", "Malformed session token.") from exc
    kid = header.get("kid")
    if not kid:
        raise _unauthorized("INVALID_TOKEN", "Session token is missing key ID.")
    jwks = _fetch_jwks(client=client)
    key_data = next((k for k in jwks.get("keys", []) if k.get("kid") == kid), None)
    if key_data is None:
        _jwks_cache["keys"] = None  # force refresh next time (rotation)
        raise _unauthorized("INVALID_TOKEN", "Unknown token signing key.")
    try:
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)  # type: ignore[attr-defined]
    except Exception as exc:
        raise _unauthorized("INVALID_TOKEN", "Unusable signing key.") from exc
    options = {"require": ["exp", "sub"]}
    issuer = expected_issuer()
    decode_kwargs: dict[str, Any] = {"options": options}
    if issuer:
        decode_kwargs["issuer"] = issuer
    try:
        claims = jwt.decode(token, public_key, algorithms=["RS256"], **decode_kwargs)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized("TOKEN_EXPIED", "Session has expired.") from exc
    except jwt.InvalidIssuerError as exc:
        raise _unauthorized("INVALID_TOKEN", "Token issuer mismatch.") from exc
    except jwt.PyJWTError as exc:
        raise _unauthorized("INVALID_TOKEN", "Session token verification failed.") from exc
    if not claims.get("sub"):
        raise _unauthorized("INVALID_TOKEN", "Token has no subject.")
    return claims


def clear_jwks_cache() -> None:
    _jwks_cache["keys"] = None
    _jwks_cache["fetched_at"] = 0.0


async def require_subject(request: Request) -> str:
    """Resolve the authorized subject or raise 401/503.

    Clerk mode: verifies Bearer session, upserts the user row (audit trail),
    and returns the verified `sub`. Off mode: returns LOCAL_SUBJECT.
    """
    if auth_mode() != "clerk":
        return LOCAL_SUBJECT
    if not clerk_configured():
        raise _unavailable()
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    import asyncio

    # verify_clerk_token does sync JWKS HTTP (httpx.get, 10s timeout) and
    # RSA verify — must not block the event loop per request.
    claims = await asyncio.to_thread(verify_clerk_token, token.strip())
    subject = str(claims["sub"])
    try:
        from app.core.events import utc_now_iso

        repo = AccountRepository()
        seen_at = utc_now_iso()
        await asyncio.to_thread(repo.upsert_user, subject, seen_at=seen_at)
    except Exception as exc:  # noqa: BLE001 - audit write must not open the gate
        logger.warning("User upsert failed: %s", type(exc).__name__)
    return subject


async def optional_subject(request: Request) -> str:
    """Like require_subject but returns LOCAL_SUBJECT when no Bearer is sent
    in off mode; in clerk mode a present-but-invalid token still raises."""
    if auth_mode() != "clerk":
        return LOCAL_SUBJECT
    authorization = request.headers.get("authorization", "")
    if not authorization.strip():
        raise _unauthorized()
    return await require_subject(request)


# Re-export for route dependencies.
RequireSubject = Depends(require_subject)
