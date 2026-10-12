from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = BACKEND_ROOT.parent
# Repository root: the canonical local `.env` lives here (see README
# quick start and .env.example). backend/.env remains as a fallback so
# direct `uvicorn` runs behave like `npm run dev` (root wins; later
# env_file entries override earlier ones; shell env wins over both).
REPO_ROOT = PROJECT_ROOT.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "medha.db"


class Settings(BaseSettings):
    """Local configuration for MEDHA. Deterministic, local-first, no API keys."""

    model_config = SettingsConfigDict(
        env_file=(str(PROJECT_ROOT / ".env"), str(REPO_ROOT / ".env")),
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
    database_url: str = Field(default="", alias="MEDHA_DATABASE_URL")
    log_level: str = Field(default="INFO", alias="MEDHA_LOG_LEVEL")
    workflow_step_delay_seconds: float = Field(
        default=0.35,
        alias="MEDHA_WORKFLOW_STEP_DELAY_SECONDS",
    )
    docker_execute: bool = Field(default=False, alias="MEDHA_DOCKER_EXECUTE")
    docker_cleanup: bool = Field(default=True, alias="MEDHA_DOCKER_CLEANUP")
    max_verify_rounds: int = Field(default=3, alias="MEDHA_MAX_VERIFY_ROUNDS")
    executor_mode: str = Field(default="auto", alias="MEDHA_EXECUTOR_MODE")
    api_token: str = Field(default="", alias="MEDHA_API_TOKEN")

    # --- AI provider integration (Groq primary, Gemini fallback) ---
    # Disabled by default: the deterministic pipeline always works without keys.
    ai_enabled: bool = Field(default=False, alias="MEDHA_AI_ENABLED")
    ai_primary_provider: str = Field(default="groq", alias="MEDHA_AI_PRIMARY_PROVIDER")
    ai_fallback_provider: str = Field(default="gemini", alias="MEDHA_AI_FALLBACK_PROVIDER")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    groq_model: str = Field(default="openai/gpt-oss-20b", alias="GROQ_MODEL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.8-flash", alias="GEMINI_MODEL")
    ai_request_timeout_seconds: float = Field(
        default=20.0, alias="MEDHA_AI_REQUEST_TIMEOUT_SECONDS"
    )
    ai_max_retries: int = Field(default=1, alias="MEDHA_AI_MAX_RETRIES")
    ai_max_output_tokens: int = Field(default=1200, alias="MEDHA_AI_MAX_OUTPUT_TOKENS")
    ai_max_calls_per_run: int = Field(default=6, alias="MEDHA_AI_MAX_CALLS_PER_RUN")

    # --- Clerk authentication (frontend identity; backend verifies JWTs) ---
    # "off" keeps the legacy single-operator behavior; "clerk" requires a
    # verified Clerk session for /api access and enforces resource ownership.
    auth_mode: str = Field(default="off", alias="MEDHA_AUTH_MODE")
    clerk_domain: str = Field(default="", alias="CLERK_DOMAIN")
    clerk_jwks_url: str = Field(default="", alias="CLERK_JWKS_URL")

    # --- GitHub webhook (push-triggered proposals; server-only secret) ---
    github_webhook_secret: str = Field(default="", alias="GITHUB_WEBHOOK_SECRET")
    webhook_allowed_repos: str = Field(default="", alias="MEDHA_WEBHOOK_ALLOWED_REPOS")
    webhook_branches: str = Field(default="main", alias="MEDHA_WEBHOOK_BRANCHES")

    # --- GitHub App (private-repo support; server-only, never persisted in plaintext) ---
    github_app_id: str = Field(default="", alias="GITHUB_APP_ID")
    github_app_private_key: str = Field(default="", alias="GITHUB_APP_PRIVATE_KEY")
    github_app_installation_id: str = Field(default="", alias="GITHUB_APP_INSTALLATION_ID")

    # --- Abuse protection ---
    rate_limit_per_minute: int = Field(default=60, alias="MEDHA_RATE_LIMIT_PER_MINUTE")
    trusted_proxy: str = Field(default="", alias="MEDHA_TRUSTED_PROXY")

    # --- Isolated real-execution builder/runtime ---
    real_readiness_timeout_seconds: float = Field(
        default=90.0, alias="MEDHA_REAL_READINESS_TIMEOUT_SECONDS"
    )
    real_build_timeout_seconds: float = Field(
        default=600.0, alias="MEDHA_REAL_BUILD_TIMEOUT_SECONDS"
    )

    def hosted_security_error(self) -> str | None:
        """Fail-closed check for publicly reachable production services."""
        if (self.medha_env or "").strip().lower() != "production":
            return None
        if (self.auth_mode or "off").strip().lower() != "clerk":
            return "MEDHA_AUTH_MODE must be 'clerk' in production."
        if not (self.clerk_domain or self.clerk_jwks_url or "").strip():
            return "CLERK_DOMAIN or CLERK_JWKS_URL must be configured in production."
        if not (self.api_token or "").strip():
            return "MEDHA_API_TOKEN must be configured in production."
        if not (self.database_url or "").strip():
            return "MEDHA_DATABASE_URL (pooled Postgres) must be configured in production."
        if (self.executor_mode or "auto").strip().lower() in {"real", "docker"}:
            return (
                "MEDHA_EXECUTOR_MODE must not be 'real'/'docker' on the hosted "
                "control plane (simulator-only). Run the isolated builder separately."
            )
        return None

    def real_execution_error(self) -> str | None:
        """Fail-closed validation for explicitly requested real execution."""
        mode = (self.executor_mode or "auto").strip().lower()
        if mode not in {"real", "docker"} or not self.docker_execute:
            return None  # real execution not requested — nothing to validate
        if (self.medha_env or "").strip().lower() == "production":
            return "Real execution is disabled on the hosted control plane."
        if self.real_readiness_timeout_seconds <= 0 or self.real_build_timeout_seconds <= 0:
            return "Real-execution timeouts must be positive."
        return None

    @property
    def cors_origins(self) -> list[str]:
        raw = self.frontend_origin.strip()
        if not raw:
            return ["http://localhost:3000"]
        return [part.strip() for part in raw.split(",") if part.strip()]

    @property
    def use_postgres(self) -> bool:
        """True when MEDHA_DATABASE_URL selects a Postgres backend (Supabase).

        Empty/absent means SQLite. An explicit file path passed to
        get_connection()/init_db() always means SQLite regardless of this.
        """
        return is_postgres_dsn(self.database_url)


def is_postgres_dsn(value: str | None) -> bool:
    """Scheme check only — never touches credentials."""
    if not value:
        return False
    text = value.strip()
    if "://" not in text:
        return False
    scheme = text.split("://", 1)[0].lower()
    return scheme in {"postgres", "postgresql"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
