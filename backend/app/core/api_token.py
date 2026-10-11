"""Shared-secret guard for state-changing API routes (single-service hosting).

Local single-operator use stays frictionless: when no token is configured and
the service is not running as production, mutating routes are allowed as
before. On a publicly reachable service the token must be configured —
otherwise mutating routes fail closed instead of executing unauthenticated
work (repository clones, pipelines, evaluation runs).

The token is injected server-side by the Next.js proxy layer
(`frontend/src/middleware.ts`) from process env, so browsers never carry it
and it never enters the client bundle.
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from app.core.config import get_settings

TOKEN_HEADER = "X-Medha-Token"


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={
            "code": "API_TOKEN_REQUIRED",
            "message": "This operation requires a valid API token.",
            "details": {"header": TOKEN_HEADER},
        },
    )


def _not_configured() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail={
            "code": "API_TOKEN_NOT_CONFIGURED",
            "message": (
                "Mutating API routes are disabled: no API token is configured "
                "for this production service."
            ),
            "details": {},
        },
    )


async def require_mutation_token(request: Request) -> None:
    """FastAPI dependency guarding POST/PUT/PATCH/DELETE under /api/*.

    Raises 401 when a configured token is missing/mismatched, and 503 when
    running as production without any token configured (fail closed).
    """
    _ = request
    settings = get_settings()
    expected = (settings.api_token or "").strip()
    if expected:
        provided = request.headers.get(TOKEN_HEADER, "")
        if provided and hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
            return None
        raise _unauthorized()
    if (settings.medha_env or "").strip().lower() == "production":
        raise _not_configured()
    return None
