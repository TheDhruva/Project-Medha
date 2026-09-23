from __future__ import annotations

from fastapi import APIRouter

from app.database.connection import ping_db

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    db_ok = ping_db()
    return {
        "status": "ok" if db_ok else "degraded",
        "service": "medha-backend",
        "database": "ok" if db_ok else "unavailable",
        "phase": "0-12",
        "note": "College prototype — local only",
    }
