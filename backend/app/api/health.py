from __future__ import annotations

import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.clerk_auth import RequireSubject
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


# Presence-only configuration diagnostics: reports whether required values
# are set and valid without ever exposing values. Safe for operators and for
# the Settings UI (no secrets cross this boundary).
_PRESENCE_VARS = (
    "MEDHA_DATABASE_URL",
    "MEDHA_API_TOKEN",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "GITHUB_WEBHOOK_SECRET",
    "GITHUB_APP_ID",
    "GITHUB_APP_PRIVATE_KEY",
    "GITHUB_APP_INSTALLATION_ID",
    "CLERK_DOMAIN",
    "CLERK_JWKS_URL",
    "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
)


@router.get("/api/config/status")
async def config_status() -> dict:
    settings = get_settings()
    configured = {name: bool((os.environ.get(name) or "").strip()) for name in _PRESENCE_VARS}
    from app.services.github_app import get_github_app_config

    app_config = get_github_app_config()
    docker_cli = False
    docker_daemon = False
    try:
        from app.execution import docker_ops

        docker_cli = docker_ops.docker_cli_available()
        docker_daemon = docker_ops.docker_daemon_running()
    except Exception:  # noqa: BLE001 - diagnostics must never fail
        pass
    mode = (settings.executor_mode or "auto").strip().lower()
    execution = "unconfigured"
    execution_reason = (
        "Set MEDHA_EXECUTOR_MODE=simulator for explicit test-only runs, or "
        "MEDHA_EXECUTOR_MODE=real with MEDHA_DOCKER_EXECUTE=true and an "
        "isolated Docker builder for genuine deployment."
    )
    if mode == "simulator":
        execution = "simulator-explicit"
        execution_reason = "Explicit test-only execution; results are never healthy."
    elif (
        settings.docker_execute
        and mode in {"real", "docker"}
        and (settings.medha_env or "").strip().lower() != "production"
        and docker_daemon
    ):
        execution = "real-ready"
        execution_reason = "Isolated Docker builder reachable; supported profiles can deploy."
    return JSONResponse(
        {
            "env": (settings.medha_env or "development"),
            "auth_mode": (settings.auth_mode or "off"),
            "executor_mode": mode,
            "docker_execute": bool(settings.docker_execute),
            "demo_enabled": bool(settings.enable_demo),
            "configured": configured,
            "github_app_configured": bool(app_config.configured),
            "docker_cli": docker_cli,
            "docker_daemon": docker_daemon,
            "database_mode": "postgres" if settings.use_postgres else "sqlite",
            "execution": execution,
            "execution_reason": execution_reason,
            "production_ready": settings.hosted_security_error() is None
            if (settings.medha_env or "").strip().lower() == "production"
            else None,
        }
    )


@router.get("/api/metrics", response_model=None)
async def operational_metrics(subject: str = RequireSubject) -> dict:
    """Safe operational counters: stage/db/SSE/AI volumes. No secrets,
    source, tokens, or environment values — counter names and counts only."""
    from app.core.perf import snapshot_counters

    counters = snapshot_counters()
    return JSONResponse(
        {
            "counters": counters,
            "budgets": {
                "tier1_llm_calls": 0,
                "tier2_llm_calls": 2,
                "full_run_llm_calls": 6,
                "max_output_tokens_per_call": get_settings().ai_max_output_tokens,
            },
        }
    )
