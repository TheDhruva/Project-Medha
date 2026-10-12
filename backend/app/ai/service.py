"""AIService: single entry point for all model calls.

Behavior contract:
- Disabled or keyless → deterministic path (`rule_based`), zero network I/O.
- Primary first; bounded retries on transient failures only (never on
  auth/config); eligible failures fall through to the fallback provider.
- Every structured response is JSON-parsed and schema-validated; anything
  else is a sanitized `schema_invalid` failure, never pipeline input.
- Results are cached per authorization context; per-run call budget caps
  cost; concurrency is semaphore-bounded (no retry storms).
- Metadata records exactly what happened (provider/model/fallback/duration/
  sanitized category/schema validity) — surfaced in run history and UI.
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any

from app.ai.cache import AICache, cache_key
from app.ai.providers import (
    AUTH,
    CONFIG,
    FALLBACK_ELIGIBLE,
    RETRYABLE,
    BaseProvider,
    GeminiProvider,
    GroqProvider,
    ProviderResult,
)
from app.ai.redact import REDACTED, redact_mapping, redact_text
from app.ai.schemas import SCHEMA_BY_KIND
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

PROMPT_VERSION = "v1"

# Outcomes reported in run records and the UI.
AI_ASSISTED = "ai_assisted"  # primary provider succeeded
DEGRADED = "degraded"  # fallback provider succeeded after primary failure
RULE_BASED = "rule_based"  # AI disabled/keyless/budget-exhausted: deterministic
UNAVAILABLE = "unavailable"  # enabled but no provider request succeeded

AIOutcome = str

SCHEMA_INVALID = "schema_invalid"


@dataclass
class AIMeta:
    enabled: bool = False
    outcome: AIOutcome = RULE_BASED
    provider: str | None = None
    model: str | None = None
    fallback_used: bool = False
    duration_s: float = 0.0
    failure_category: str | None = None
    schema_valid: bool = False
    cached: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "outcome": self.outcome,
            "provider": self.provider,
            "model": self.model,
            "fallback_used": self.fallback_used,
            "duration_s": round(self.duration_s, 3),
            "failure_category": self.failure_category,
            "schema_valid": self.schema_valid,
            "cached": self.cached,
        }


@dataclass
class AIBudget:
    """Per-run call budget shared across assist stages."""

    max_calls: int = 3
    calls_made: int = 0

    def take(self) -> bool:
        if self.calls_made >= self.max_calls:
            return False
        self.calls_made += 1
        return True


class AIService:
    def __init__(
        self,
        settings: Settings | None = None,
        cache: AICache | None = None,
        *,
        client: Any = None,
        max_concurrency: int = 2,
    ) -> None:
        self.settings = settings or get_settings()
        self.cache = cache or AICache()
        self._client = client
        self._semaphore = asyncio.Semaphore(max(1, max_concurrency))

    # -- provider wiring -------------------------------------------------

    def _provider(self, name: str) -> BaseProvider | None:
        normalized = (name or "").strip().lower()
        if normalized == "groq":
            return GroqProvider(
                api_key=self.settings.groq_api_key,
                model=self.settings.groq_model,
                client=self._client,
            )
        if normalized == "gemini":
            return GeminiProvider(
                api_key=self.settings.gemini_api_key,
                model=self.settings.gemini_model,
                client=self._client,
            )
        if normalized in {"", "none", "off"}:
            return None
        logger.warning("Unknown AI provider name redacted=%s", REDACTED)
        return None

    def _chain(self) -> list[BaseProvider]:
        """Configured providers in attempt order (primary, then fallback)."""
        chain: list[BaseProvider] = []
        primary = self._provider(self.settings.ai_primary_provider)
        if primary is not None and primary not in chain:
            chain.append(primary)
        fallback = self._provider(self.settings.ai_fallback_provider)
        if (
            fallback is not None
            and fallback.name != getattr(primary, "name", None)
            and fallback not in chain
        ):
            chain.append(fallback)
        return [provider for provider in chain if provider.configured]

    # -- public API ------------------------------------------------------

    async def aclose(self) -> None:
        """Close the shared HTTP client, if owned. Safe to call repeatedly."""
        client = self._client
        self._client = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001 - shutdown must never raise
                pass

    async def generate_structured(
        self,
        *,
        kind: str,
        payload: dict[str, Any],
        system: str,
        owner_ctx: str = "local",
        budget: AIBudget | None = None,
    ) -> tuple[dict[str, Any] | None, AIMeta]:
        """Validate-then-generate a schema-conformant advisory object.

        Returns (parsed_dict | None, meta). None data always means "use the
        deterministic path" — callers must never treat it as AI evidence.
        """
        meta = AIMeta(enabled=bool(self.settings.ai_enabled))
        schema_cls = SCHEMA_BY_KIND.get(kind)
        if schema_cls is None:
            meta.failure_category = CONFIG
            return None, meta
        if not self.settings.ai_enabled:
            return None, meta
        chain = self._chain()
        if not chain:
            return None, meta

        safe_payload = redact_mapping(payload)
        key = cache_key(
            prompt_version=PROMPT_VERSION,
            kind=kind,
            provider=chain[0].name,
            model=chain[0].model,
            owner_ctx=owner_ctx or "local",
            payload=safe_payload,
        )
        cached = self.cache.get(key)
        if isinstance(cached, dict) and cached.get("__kind") == kind:
            hit = dict(cached["meta"])
            hit["cached"] = True
            restored = AIMeta(**{k: hit.get(k, getattr(AIMeta(), k)) for k in hit})
            restored.cached = True
            return dict(cached["data"]), restored
        # Budget consumed only on actual provider calls: cache hits are free.
        if budget is not None and not budget.take():
            meta.failure_category = "budget_exhausted"
            return None, meta

        user_text = json.dumps(safe_payload, sort_keys=True, default=str)
        started = time.perf_counter()
        last_category: str | None = None
        used_fallback = False
        for index, provider in enumerate(chain):
            if index > 0:
                used_fallback = True
            result = await self._attempt_with_retry(provider, system, user_text)
            last_category = result.category
            if result.ok and result.text:
                parsed = self._parse_and_validate(kind, schema_cls, result.text)
                if parsed is not None:
                    meta.outcome = AI_ASSISTED if index == 0 else DEGRADED
                    meta.provider = provider.name
                    meta.model = provider.model
                    meta.fallback_used = used_fallback
                    meta.duration_s = time.perf_counter() - started
                    meta.schema_valid = True
                    self.cache.set(
                        key, {"__kind": kind, "data": parsed, "meta": meta.to_dict()}
                    )
                    return parsed, meta
                last_category = SCHEMA_INVALID
                logger.warning(
                    "AI response failed schema validation provider=%s kind=%s",
                    provider.name,
                    kind,
                )
                if index < len(chain) - 1:
                    continue
                break
            # result not ok
            if result.category in (AUTH, CONFIG):
                logger.warning(
                    "AI provider terminal failure provider=%s category=%s",
                    provider.name,
                    result.category,
                )
                break
            if result.category not in FALLBACK_ELIGIBLE:
                break
            # else: fall through to next provider
        meta.outcome = UNAVAILABLE
        meta.failure_category = last_category
        meta.fallback_used = used_fallback and len(chain) > 1
        meta.duration_s = time.perf_counter() - started
        return None, meta

    async def health_check(self) -> dict[str, Any]:
        """Safe provider status (cheap key validation, no generation)."""
        providers: dict[str, Any] = {}
        for provider in self._chain():
            started = time.perf_counter()
            try:
                result = await provider.ping()
            except Exception as exc:  # noqa: BLE001 - status must never raise
                logger.warning("AI health check error: %s", type(exc).__name__)
                result = ProviderResult(ok=False, category="network")
            providers[provider.name] = {
                "configured": True,
                "model": provider.model,
                "reachable": bool(result.ok),
                "latency_s": round(time.perf_counter() - started, 3),
                "failure_category": None if result.ok else result.category,
            }
        # Report known-but-unconfigured providers as such (no secrets).
        for name in ("groq", "gemini"):
            providers.setdefault(name, {"configured": False, "model": None,
                                        "reachable": False, "latency_s": 0.0,
                                        "failure_category": "not_configured"})
        return {
            "enabled": bool(self.settings.ai_enabled),
            "primary": (self.settings.ai_primary_provider or "").strip().lower(),
            "fallback": (self.settings.ai_fallback_provider or "").strip().lower(),
            "providers": providers,
        }

    # -- internals -------------------------------------------------------

    async def _attempt_with_retry(
        self, provider: BaseProvider, system: str, user_text: str
    ) -> ProviderResult:
        settings = self.settings
        attempts = 1 + max(0, settings.ai_max_retries)
        last: ProviderResult = ProviderResult(ok=False, category=CONFIG)
        for attempt in range(attempts):
            async with self._semaphore:
                last = await provider.complete_json(
                    system=system,
                    user=user_text,
                    max_tokens=max(128, settings.ai_max_output_tokens),
                    timeout_s=max(2.0, settings.ai_request_timeout_seconds),
                )
            if last.ok or last.category not in RETRYABLE:
                return last
            if attempt < attempts - 1:
                wait_s = self._backoff_s(attempt, last.retry_after_s)
                logger.warning(
                    "AI transient failure provider=%s category=%s retry_in_s=%.2f",
                    provider.name,
                    last.category,
                    wait_s,
                )
                await asyncio.sleep(wait_s)
        return last

    @staticmethod
    def _backoff_s(attempt: int, retry_after: float | None) -> float:
        if retry_after:
            return min(retry_after, 30.0)
        base = min(2.0**attempt, 8.0)
        return base + random.uniform(0.0, 0.5)

    @staticmethod
    def _parse_and_validate(kind: str, schema_cls: Any, text: str) -> dict | None:
        try:
            raw = json.loads(text)
        except ValueError:
            return None
        if not isinstance(raw, dict):
            return None
        try:
            return schema_cls.model_validate(raw).model_dump()
        except Exception:  # noqa: BLE001 - validation failure is a normal path
            return None


def sanitized_error(message: str) -> str:
    return redact_text(message, max_len=300)
