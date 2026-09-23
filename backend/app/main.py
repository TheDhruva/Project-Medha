from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.change_impact import router as change_intel_router
from app.api.deploy import router as deploy_router
from app.api.evaluation import router as evaluation_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.database.connection import init_db

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    init_db(settings.database_path)
    logger.info(
        "MEDHA backend starting env=%s db=%s cors=%s",
        settings.medha_env,
        settings.database_path,
        settings.cors_origins,
    )
    yield
    logger.info("MEDHA backend shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title="MEDHA Backend",
        version="0.10.0",
        description="Phases 10–11 — real local Docker execution + evaluation instrumentation",
        lifespan=lifespan,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

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
    application.include_router(deploy_router)
    application.include_router(evaluation_router)
    application.include_router(change_intel_router)
    return application


app = create_app()
