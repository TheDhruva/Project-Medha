from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.change_impact import router as change_intel_router
from app.api.assessment import router as assessment_router
from app.api.deploy import router as deploy_router
from app.api.evaluation import router as evaluation_router
from app.api.health import router as health_router
from app.api.history import router as history_router
from app.api.ai import router as ai_router
from app.api.projects import router as projects_router
from app.api.scores import router as scores_router
from app.api.webhooks import router as webhooks_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.database.connection import describe_db, init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    import asyncio as _asyncio
    import time as _time

    _t_start = _time.perf_counter()
    settings = get_settings()
    setup_logging(settings.log_level)
    problem = settings.hosted_security_error()
    if problem is not None:
        raise RuntimeError(f"Refusing to start hosted production: {problem}")
    _t_db = _time.perf_counter()
    if settings.ignored_db_url:
        # A dotenv-inherited production URL must never silently hijack local
        # runs: stay on SQLite and say so loudly (label only, never the URL).
        logger.warning(
            "MEDHA_DATABASE_URL is set but ignored in development "
            "(source=%s): using SQLite at %s. Set "
            "MEDHA_DATABASE_BACKEND=postgres to use Postgres locally.",
            settings.database_url_source(),
            settings.database_path,
        )
    try:
        init_db()
    except Exception as exc:  # noqa: BLE001 - fail closed, redacted, no secrets
        raise RuntimeError(
            f"Database initialization failed for {describe_db()}: "
            f"{type(exc).__name__}. Refusing to serve without a database."
        ) from exc
    _db_s = _time.perf_counter() - _t_db
    try:
        from app.services.recovery import reconcile_interrupted, recovery_summary

        recovered = reconcile_interrupted()
    except Exception:  # noqa: BLE001 - recovery must never block startup
        logger.exception("Startup recovery failed")
        recovered = {}
    # Non-critical workspace cleanup runs in the background AFTER the
    # service is ready, so slow filesystems never delay readiness.
    def _deferred_prune() -> None:
        try:
            from app.services.workspace import prune_stale_workspaces

            pruned = prune_stale_workspaces(max_age_hours=24)
            logger.info("Deferred workspace prune removed=%s", pruned)
        except Exception:  # noqa: BLE001 - cleanup must never crash serving
            logger.exception("Deferred workspace prune failed")

    _asyncio.get_running_loop().run_in_executor(None, _deferred_prune)
    logger.info(
        "MEDHA backend starting env=%s db=%s cors=%s db_init_s=%.2f total_init_s=%.2f recovery=%s",
        settings.medha_env,
        describe_db(),
        settings.cors_origins,
        _db_s,
        _time.perf_counter() - _t_start,
        recovery_summary(recovered) if recovered else "none",
    )
    try:
        from app.jobs.worker import start_worker

        start_worker()
    except Exception:  # noqa: BLE001 - worker must never block startup
        logger.exception("Job worker failed to start")
    yield
    try:
        from app.jobs.worker import stop_worker

        await stop_worker()
    except Exception:  # noqa: BLE001 - shutdown must not raise
        logger.exception("Job worker failed to stop")
    logger.info("MEDHA backend shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="MEDHA Backend",
        version="0.10.0",
        description="Phases 0–12 — local pipeline (analyze → CNP → verify → execute) + evaluation instrumentation",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Medha-Token", "X-GitHub-Delivery", "X-Hub-Signature-256"],
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        import time as _time
        from uuid import uuid4 as _uuid4

        from app.core.perf import bump, set_request_id

        rid = request.headers.get("x-request-id") or f"req_{_uuid4().hex[:12]}"
        set_request_id(rid)
        t0 = _time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            raise
        elapsed = _time.perf_counter() - t0
        bump(f"http.{request.method}")
        response.headers["X-Request-ID"] = rid
        response.headers["Server-Timing"] = f"app;dur={elapsed * 1000:.1f}"
        if elapsed >= 1.0:
            logger.warning(
                "slow request method=%s path=%s elapsed_s=%.2f rid=%s",
                request.method,
                request.url.path,
                elapsed,
                rid,
            )
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_handler(_request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed",
                    "details": {"errors": jsonable_encoder(exc.errors())},
                }
            },
        )

    @application.exception_handler(Exception)
    async def unhandled_handler(_request: Request, exc: Exception):
        logger.exception("Unhandled server error: %s", exc)
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": "Unexpected server error",
                    "details": {},
                }
            },
        )

    application.include_router(health_router)
    application.include_router(history_router)
    application.include_router(deploy_router)
    application.include_router(evaluation_router)
    application.include_router(change_intel_router)
    application.include_router(ai_router)
    application.include_router(projects_router)
    application.include_router(assessment_router)
    application.include_router(scores_router)
    application.include_router(webhooks_router)
    return application


app = create_app()
