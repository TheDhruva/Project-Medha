from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.core.logging import get_logger
from app.database.connection import ping_db

logger = get_logger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    db_ok = ping_db()
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
