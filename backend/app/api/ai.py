"""Safe AI provider status (no secrets, no upstream diagnostics)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.ai.service import AIService
from app.core.clerk_auth import RequireSubject
from app.core.config import get_settings

router = APIRouter(prefix="/api")


@router.get("/ai/status")
async def ai_status(subject: str = RequireSubject):
    _ = subject
    settings = get_settings()
    service = AIService(settings)
    try:
        health = await service.health_check()
    except Exception:  # noqa: BLE001 - status must never raise
        health = {"enabled": bool(settings.ai_enabled), "providers": {}}
    return JSONResponse(
        {
            "enabled": bool(settings.ai_enabled),
            "primary_provider": (settings.ai_primary_provider or "").strip().lower(),
            "fallback_provider": (settings.ai_fallback_provider or "").strip().lower(),
            "primary_model": settings.groq_model
            if (settings.ai_primary_provider or "").strip().lower() == "groq"
            else settings.gemini_model,
            "fallback_model": settings.gemini_model
            if (settings.ai_fallback_provider or "").strip().lower() == "gemini"
            else settings.groq_model,
            "max_calls_per_run": settings.ai_max_calls_per_run,
            "request_timeout_seconds": settings.ai_request_timeout_seconds,
            "max_output_tokens": settings.ai_max_output_tokens,
            "health": health,
        }
    )
