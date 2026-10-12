from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.connection import ping_db

logger = get_logger(__name__)

router = APIRouter()

# Bounded health-result cache: expensive dependency pings (fresh TCP/TLS
# for Postgres) are cached for 5s so scrapes don't open a connection each
# time. Liveness (process up, config valid) is never cached — only the DB
# reachability bit. A real outage flips to degraded within 5s.
_health_cache: dict[str, object] = {"ok": True, "at": 0.0}
_HEALTH_TTL_S = 5.0


@router.get("/health")
async def health() -> dict:
    import asyncio
    import time as _time

    now = _time.monotonic()
    cached_at = float(_health_cache.get("at") or 0.0)
    if now - cached_at < _HEALTH_TTL_S:
        db_ok = bool(_health_cache.get("ok"))
    else:
        db_ok = await asyncio.to_thread(ping_db)
        _health_cache["ok"] = db_ok
        _health_cache["at"] = now
    settings = get_settings()
    backend = "postgres" if settings.use_postgres else "sqlite"
    if (settings.medha_env or "").strip().lower() == "production" and backend == "sqlite":
        # Loud, not silent: production on the ephemeral SQLite fallback loses
        # history on redeploy. The service still starts (fresh installs),
        # but operators must see this in the health payload and logs.
        logger.warning(
            "Production is using the SQLite fallback (MEDHA_DATABASE_URL unset). "
            "History will not survive redeploys."
        )
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "medha-backend",
        "database": "ok" if db_ok else "unavailable",
        "database_mode": backend,
        "phase": "0-12",
        "note": "College prototype — local only",
    }
