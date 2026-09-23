from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "medha.db"


class Settings(BaseSettings):
    """Local configuration for MEDHA. Deterministic, local-first, no API keys."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    medha_env: str = Field(default="development", alias="MEDHA_ENV")
    medha_debug: bool = Field(default=True, alias="MEDHA_DEBUG")
    api_host: str = Field(default="127.0.0.1", alias="MEDHA_HOST")
    api_port: int = Field(default=8000, alias="MEDHA_PORT")
    frontend_origin: str = Field(
        default="http://localhost:3000",
        alias="MEDHA_CORS_ORIGINS",
    )
    database_path: Path = Field(default=DEFAULT_DB_PATH, alias="MEDHA_DATABASE_PATH")
    log_level: str = Field(default="INFO", alias="MEDHA_LOG_LEVEL")
    workflow_step_delay_seconds: float = Field(
        default=0.35,
        alias="MEDHA_WORKFLOW_STEP_DELAY_SECONDS",
    )
    docker_execute: bool = Field(default=False, alias="MEDHA_DOCKER_EXECUTE")
    docker_cleanup: bool = Field(default=True, alias="MEDHA_DOCKER_CLEANUP")
    max_verify_rounds: int = Field(default=3, alias="MEDHA_MAX_VERIFY_ROUNDS")
    executor_mode: str = Field(default="auto", alias="MEDHA_EXECUTOR_MODE")

    @property
    def cors_origins(self) -> list[str]:
        raw = self.frontend_origin.strip()
        if not raw:
            return ["http://localhost:3000"]
        return [part.strip() for part in raw.split(",") if part.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
