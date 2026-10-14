from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
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
    # Explicit Postgres opt-in for non-production environments.
    # "" (default) / "auto" / "sqlite": SQLite unless MEDHA_ENV=production.
    # "postgres": use MEDHA_DATABASE_URL when it is a valid Postgres DSN.
    # A dotenv-inherited production URL must never hijack local runs (it
    # hangs startup on unreachable poolers and spends production
    # credentials), so development selects Postgres ONLY via this flag.
    # Unknown values fail fast at Settings construction (all environments).
    database_backend: str = Field(default="", alias="MEDHA_DATABASE_BACKEND")
    log_level: str = Field(default="INFO", alias="MEDHA_LOG_LEVEL")
    workflow_step_delay_seconds: float = Field(
        default=0.35,
        alias="MEDHA_WORKFLOW_STEP_DELAY_SECONDS",
    )
    docker_execute: bool = Field(default=False, alias="MEDHA_DOCKER_EXECUTE")
    docker_cleanup: bool = Field(default=True, alias="MEDHA_DOCKER_CLEANUP")
    max_verify_rounds: int = Field(default=3, alias="MEDHA_MAX_VERIFY_ROUNDS")
    # Bounded in-process stage timeouts (seconds). These bound how long the
    # pipeline *waits* for a stage; detached worker threads cannot be killed
    # and their late results are dropped, never accepted after a timeout or
    # cancellation. Clamped to [1, 3600] at use.
    timeout_analyze_s: float = Field(default=120.0, alias="MEDHA_TIMEOUT_ANALYZE_S")
    timeout_specialists_s: float = Field(default=30.0, alias="MEDHA_TIMEOUT_SPECIALISTS_S")
    timeout_verify_s: float = Field(default=30.0, alias="MEDHA_TIMEOUT_VERIFY_S")
    # Network-facing repository acquisition (clone/fetch) gets its own bound:
    # same wait-not-kill semantics as the other stage timeouts.
    timeout_acquire_s: float = Field(default=120.0, alias="MEDHA_TIMEOUT_ACQUIRE_S")
    executor_mode: str = Field(default="auto", alias="MEDHA_EXECUTOR_MODE")
    api_token: str = Field(default="", alias="MEDHA_API_TOKEN")
    # Demo/scenario engine: disabled by default. The deterministic DemoRunner
    # stays available for isolated automated tests (MEDHA_ENABLE_DEMO=true),
    # but demo runs must never be reachable as successful production runs.
    enable_demo: bool = Field(default=False, alias="MEDHA_ENABLE_DEMO")

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
        if not is_postgres_dsn(self.database_url):
            # A present-but-invalid URL must fail closed: falling back to
            # the ephemeral SQLite file would silently lose history.
            return (
                "MEDHA_DATABASE_URL must be a valid postgresql:// DSN in "
                "production (never silently fall back to SQLite)."
            )
        if self.database_backend.strip().lower() == "sqlite":
            # Explicit contradiction: production requires Postgres, so an
            # explicit sqlite request is refused instead of silently winning
            # over the configured URL (or vice versa).
            return (
                "MEDHA_DATABASE_BACKEND must not be 'sqlite' in production."
            )
        if (self.executor_mode or "auto").strip().lower() in {"real", "docker"}:
            return (
                "MEDHA_EXECUTOR_MODE must not be 'real'/'docker' on the hosted "
                "control plane (execution-disabled). Run the isolated builder separately."
            )
        if self.docker_execute:
            return (
                "MEDHA_DOCKER_EXECUTE must be 'false' on the hosted control "
                "plane (execution-disabled)."
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
        """True when the Postgres backend is selected (Supabase in prod).

        Selection rules (ADR-029 as amended):
        - Invalid/empty MEDHA_DATABASE_URL: always SQLite.
        - MEDHA_ENV=production: a valid URL selects Postgres (missing or
          invalid URLs are refused by hosted_security_error, never SQLite).
        - Any other env: Postgres ONLY with explicit
          MEDHA_DATABASE_BACKEND=postgres. A dotenv-inherited production URL
          alone keeps SQLite, so local runs never hang on (or spend
          credentials against) a remote pooler by accident.
        An explicit file path passed to get_connection()/init_db() always
        means SQLite regardless of this.
        """
        if not is_postgres_dsn(self.database_url):
            return False
        if self._is_production:
            return True
        return self.database_backend.strip().lower() == "postgres"

    @property
    def _is_production(self) -> bool:
        return (self.medha_env or "").strip().lower() == "production"

    def database_url_source(self) -> str:
        """Where the configured URL came from: "shell" | "file" | "unset".

        "shell" = exported in the process environment (operator intent).
        Anything else non-empty arrived via a dotenv file (or direct
        construction) — implicit, never sufficient alone to select Postgres
        outside production. Returns the source name only, never the value.
        """
        if os.environ.get("MEDHA_DATABASE_URL", "").strip():
            return "shell"
        if (self.database_url or "").strip():
            return "file"
        return "unset"

    @property
    def ignored_db_url(self) -> bool:
        """True when a valid Postgres URL is configured but not used.

        Development-only signal for the startup warning: the operator likely
        pasted a production URL into a local .env. Production never ignores
        a URL (it fails closed instead), so this is always False there.
        """
        return (
            not self._is_production
            and is_postgres_dsn(self.database_url)
            and not self.use_postgres
        )

    @field_validator("database_backend")
    @classmethod
    def _check_database_backend(cls, value: str) -> str:
        allowed = {"", "auto", "sqlite", "postgres"}
        if (value or "").strip().lower() not in allowed:
            raise ValueError(
                "MEDHA_DATABASE_BACKEND must be one of "
                "'postgres', 'sqlite', 'auto', or unset."
            )
        return value


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
