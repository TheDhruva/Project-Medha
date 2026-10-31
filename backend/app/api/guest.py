"""Guest session endpoints (server-issued, no account).

POST   /api/guest-session  -> create a session and return the bearer token
GET    /api/guest-session  -> validate the current bearer, return its state
DELETE /api/guest-session  -> end the session and purge its data now

The token travels only in the `Authorization` header — never in a URL, so it
cannot land in logs, referrers, or browser history. Cleanup is idempotent:
ending an already-ended session reports `already_ended` instead of failing.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.api_token import require_mutation_token
from app.core.config import get_settings
from app.core.events import utc_now_iso
from app.core.guest_sessions import (
    GUEST_SUBJECT_PREFIX,
    create_guest_session,
    hash_token,
    is_guest_token,
    resolve_guest,
)
from app.core.rate_limit import check_rate_limit, client_ip
from app.database.repositories import GuestSessionRepository

router = APIRouter(prefix="/api")

# Session creation is heavier than an ordinary read (row + token mint), so it
# gets a tighter budget than MEDHA_RATE_LIMIT_PER_MINUTE.
GUEST_CREATE_LIMIT_PER_MINUTE = 10


def _error(status_code: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
    )


def _unauthorized(code: str, message: str) -> JSONResponse:
    return _error(401, code, message)


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


class _GuestProblem(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


async def _current_guest_row(request: Request):
    """Resolve the caller's guest session row, or raise a 401 JSONResponse."""
    token = _bearer(request)
    if not token:
        raise _GuestProblem("NO_GUEST_SESSION", "No guest session was found.")
    if not is_guest_token(token):
        raise _GuestProblem("NOT_A_GUEST_TOKEN", "This token is not a MEDHA guest session.")
    return await resolve_guest(token)


@router.post("/guest-session", dependencies=[Depends(require_mutation_token)])
async def create_session(request: Request):
    settings = get_settings()
    ip = client_ip(request, trusted_proxy=settings.trusted_proxy)
    if not check_rate_limit(
        f"guest-create:{ip}", limit_per_minute=GUEST_CREATE_LIMIT_PER_MINUTE
    ):
        return _error(429, "RATE_LIMITED", "Too many guest sessions; retry later.")
    try:
        session = await asyncio.to_thread(create_guest_session)
    except Exception as exc:  # noqa: BLE001 - surface a clean contract error
        return _error(500, "GUEST_SESSION_FAILED", f"Could not create a guest session: {exc}")
    return JSONResponse(status_code=201, content=session)


@router.get("/guest-session")
async def get_session(request: Request):
    try:
        row = await _current_guest_row(request)
    except _GuestProblem as exc:
        return _unauthorized(exc.code, exc.message)
    return JSONResponse(
        {
            "subject": row["subject"],
            "session_id": row["session_id"],
            "status": row["status"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "mode": "guest",
        }
    )


@router.delete("/guest-session", dependencies=[Depends(require_mutation_token)])
async def end_session(request: Request):
    token = _bearer(request)
    repo = GuestSessionRepository()
    now = utc_now_iso()
    if not token or not is_guest_token(token):
        # Nothing to end: report success so a double-submit or a cleared
        # sessionStorage never surfaces as an error to the user.
        return JSONResponse({"ended": True, "already_ended": True, "purged": {}})
    row = await asyncio.to_thread(repo.get_by_token_hash, hash_token(token))
    if row is None:
        return JSONResponse({"ended": True, "already_ended": True, "purged": {}})
    if row["status"] in ("cleaned", "failed"):
        return JSONResponse({"ended": True, "already_ended": True, "purged": {}})
    subject = f"{GUEST_SUBJECT_PREFIX}{row['session_id']}"
    try:
        # Queue for the reaper first, so a crash mid-purge retries rather
        # than leaving an active session pointing at deleted data.
        await asyncio.to_thread(repo.mark_expired, row["session_id"], at=now)
        counts = await asyncio.to_thread(repo.purge_guest_data, subject)
        await asyncio.to_thread(repo.record_cleanup_success, row["session_id"], at=now)
    except Exception as exc:  # noqa: BLE001 - reaper retries; report honestly
        return _error(500, "GUEST_CLEANUP_FAILED", f"Guest data cleanup failed: {exc}")
    return JSONResponse({"ended": True, "already_ended": False, "purged": counts})
