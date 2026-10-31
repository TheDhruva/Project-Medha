"""Server-issued guest sessions (no account, no parallel auth system).

A guest session is one more *subject resolver* feeding the same
`require_subject` dependency that every /api route already uses, so guest
isolation comes for free from the existing `owner_sub` scoping: a guest's
subject is "guest:<session_id>" and every row it creates carries that value.

Verification is server-side, never client-trust:
- the backend generates the token and stores only its SHA-256,
- every request re-reads the row and checks status + expiry,
- an expired/unknown guest token fails closed (401) instead of degrading to
  the shared local-operator subject.

The client keeps the token in sessionStorage, so it survives navigation and
same-tab reloads and dies with the tab. Server-side expiry plus the reaper
below are what actually delete the guest's data — the UI never claims a
deletion that has not happened.
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import threading

from fastapi import HTTPException

from app.core.config import get_settings
from app.core.events import utc_now_iso
from app.core.logging import get_logger
from app.database.repositories import GuestSessionRepository

logger = get_logger(__name__)

# Recognizable prefix: lets `require_subject` tell a guest token apart from a
# Clerk JWT without any database work, and lets an invalid guest token fail
# closed instead of silently falling through to the shared local subject.
GUEST_TOKEN_PREFIX = "medha_guest_"
GUEST_SUBJECT_PREFIX = "guest:"


def new_guest_token() -> str:
    return GUEST_TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def is_guest_token(token: str) -> bool:
    return token.startswith(GUEST_TOKEN_PREFIX)


def guest_subject(session_id: str) -> str:
    return f"{GUEST_SUBJECT_PREFIX}{session_id}"


def expires_at_from(now_iso: str) -> str:
    from datetime import datetime, timedelta, timezone

    ttl_hours = max(0, get_settings().guest_session_ttl_hours)
    start = datetime.fromisoformat(now_iso.replace("Z", "+00:00"))
    return (start + timedelta(hours=ttl_hours)).isoformat().replace("+00:00", "Z")


def _guest_unauthorized(code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail={"code": code, "message": message, "details": {}},
    )


async def resolve_guest(token: str) -> dict:
    """Validate a guest token server-side. Raises 401 when unusable."""
    repo = GuestSessionRepository()
    row = await asyncio.to_thread(repo.get_by_token_hash, hash_token(token))
    if row is None:
        raise _guest_unauthorized(
            "GUEST_SESSION_NOT_FOUND", "This guest session no longer exists."
        )
    now = utc_now_iso()
    if row["status"] != "active":
        raise _guest_unauthorized(
            "GUEST_SESSION_ENDED", "This guest session has ended."
        )
    if row["expires_at"] <= now:
        # Expired: queue for the reaper and refuse immediately.
        await asyncio.to_thread(repo.mark_expired, row["session_id"], at=now)
        raise _guest_unauthorized(
            "GUEST_SESSION_EXPIRED", "This guest session has expired."
        )
    await asyncio.to_thread(repo.touch, row["session_id"], seen_at=now)
    row["subject"] = guest_subject(row["session_id"])
    return row


async def resolve_guest_subject(token: str) -> str | None:
    """Return the guest subject, None when the token is not a guest token.

    A guest-prefixed token that fails validation raises (fail closed) rather
    than returning None — otherwise an expired guest would silently fall back
    to the shared local-operator subject and see other people's data.
    """
    if not is_guest_token(token):
        return None
    return (await resolve_guest(token))["subject"]


def create_guest_session() -> dict:
    """Issue a new guest session. Synchronous; callers run it in a thread."""
    settings = get_settings()
    now = utc_now_iso()
    session_id = f"gs_{secrets.token_hex(12)}"
    token = new_guest_token()
    repo = GuestSessionRepository()
    repo.create(
        session_id=session_id,
        token_hash=hash_token(token),
        created_at=now,
        expires_at=expires_at_from(now),
    )
    logger.info("guest session created session_id=%s ttl_hours=%s",
                session_id, settings.guest_session_ttl_hours)
    return {
        "token": token,
        "session_id": session_id,
        "subject": guest_subject(session_id),
        "expires_at": expires_at_from(now),
        "mode": "guest",
    }


def cleanup_expired_guest_sessions() -> dict:
    """Purge every guest session that is due. Idempotent and retryable.

    Docker resources go first and only through `cleanup_deployment`, which
    verifies MEDHA ownership labels before removing anything — a guest cleanup
    can never touch shared or other-owner containers, networks, or images.
    """
    from app.execution.docker_ops import cleanup_deployment

    repo = GuestSessionRepository()
    now = utc_now_iso()
    due = repo.list_due(now=now)
    cleaned = 0
    failed = 0
    purged_rows = 0
    for row in due:
        session_id = row["session_id"]
        subject = guest_subject(session_id)
        try:
            # Queue first, so a crash mid-purge retries instead of leaving an
            # active session pointing at deleted data.
            repo.mark_expired(session_id, at=now)
            for deployment_id in repo.deployment_ids_for_owner(subject):
                cleanup_deployment(deployment_id)
            counts = repo.purge_guest_data(subject)
            purged_rows += sum(counts.values())
            repo.record_cleanup_success(session_id, at=now)
            cleaned += 1
            logger.info(
                "guest session cleaned session_id=%s rows=%s", session_id, counts
            )
        except Exception as exc:  # noqa: BLE001 - one bad session must not stop the rest
            failed += 1
            try:
                repo.record_cleanup_failure(
                    session_id, at=now, error=f"{type(exc).__name__}: {exc}"
                )
            except Exception:  # noqa: BLE001 - bookkeeping failure must not raise
                logger.exception("guest cleanup bookkeeping failed session_id=%s", session_id)
            logger.warning(
                "guest session cleanup failed session_id=%s error=%s", session_id, exc
            )
    return {
        "due": len(due),
        "cleaned": cleaned,
        "failed": failed,
        "purged_rows": purged_rows,
    }


# --- Background reaper ------------------------------------------------------
# A daemon thread (no Redis, no extra process) so a low-end laptop and a
# single uvicorn worker both get expiry without touching the request path.

_reaper_stop = threading.Event()
_reaper_thread: threading.Thread | None = None


def _reaper_loop() -> None:
    while not _reaper_stop.is_set():
        try:
            summary = cleanup_expired_guest_sessions()
            if summary["due"]:
                logger.info(
                    "guest reaper due=%s cleaned=%s failed=%s rows=%s",
                    summary["due"],
                    summary["cleaned"],
                    summary["failed"],
                    summary["purged_rows"],
                )
        except Exception:  # noqa: BLE001 - the reaper must never die silently
            logger.exception("guest reaper pass failed")
        interval = max(5, get_settings().guest_cleanup_interval_seconds)
        _reaper_stop.wait(interval)


def start_guest_reaper() -> None:
    global _reaper_thread
    if get_settings().guest_cleanup_interval_seconds <= 0:
        # Explicit opt-out (tests, manual-cleanup deployments): cleanup still
        # runs on demand via cleanup_expired_guest_sessions().
        logger.info("guest-session reaper disabled (interval <= 0)")
        return
    if _reaper_thread is not None and _reaper_thread.is_alive():
        return
    # Sessions expired while the process was down are purged immediately.
    try:
        cleanup_expired_guest_sessions()
    except Exception:  # noqa: BLE001 - startup cleanup must never block serving
        logger.exception("startup guest cleanup failed")
    _reaper_stop.clear()
    _reaper_thread = threading.Thread(
        target=_reaper_loop, name="guest-session-reaper", daemon=True
    )
    _reaper_thread.start()


def stop_guest_reaper() -> None:
    global _reaper_thread
    _reaper_stop.set()
    thread = _reaper_thread
    _reaper_thread = None
    if thread is not None and thread.is_alive():
        thread.join(timeout=5.0)
