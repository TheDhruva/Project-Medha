"""Provider adapters behind a shared interface (httpx only, no vendor SDKs).

Each provider makes a single bounded attempt per call — retries, fallback,
and budgeting live in app.ai.service. Failures are categorized into sanitized
classes; upstream bodies are never propagated (they may echo credentials or
prompt content).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.ai.redact import redact_text
from app.core.logging import get_logger

logger = get_logger(__name__)

# Sanitized failure categories. Safe for logs, API payloads, and run records.
TIMEOUT = "timeout"
RATE_LIMITED = "rate_limited"
SERVER = "server"
NETWORK = "network"
AUTH = "auth"
CONFIG = "config"
INVALID_RESPONSE = "invalid_response"
BLOCKED = "blocked"

# Retry only transient failures. Auth/config errors are terminal: retrying
# them wastes budget and can trigger abuse throttles.
RETRYABLE = frozenset({TIMEOUT, RATE_LIMITED, SERVER, NETWORK})

# Fallback-eligible: primary failed in a way the other provider may survive.
FALLBACK_ELIGIBLE = frozenset(
    {TIMEOUT, RATE_LIMITED, SERVER, NETWORK, INVALID_RESPONSE, BLOCKED}
)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


@dataclass
class ProviderResult:
    ok: bool
    text: str | None = None
    model: str = ""
    duration_s: float = 0.0
    category: str | None = None
    status_code: int | None = None
    retry_after_s: float | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _retry_after(headers: Any) -> float | None:
    try:
        raw = headers.get("retry-after")
        if raw is None:
            return None
        return max(0.0, min(float(raw), 60.0))
    except (TypeError, ValueError):
        return None


class BaseProvider:
    name = "base"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key or ""
        self.model = (model or "").strip()
        self._client = client
        self._owned_client = client is None

    @property
    def key_present(self) -> bool:
        return bool(self._api_key.strip())

    @property
    def configured(self) -> bool:
        return self.key_present and bool(self.model)

    async def _client_ctx(self) -> Any:
        if self._client is not None:
            from contextlib import asynccontextmanager

            @asynccontextmanager
            async def _reuse():
                yield self._client

            return _reuse()
        return httpx.AsyncClient(timeout=httpx.Timeout(connect=5.0))

    def _unsupported(self, reason: str) -> ProviderResult:
        return ProviderResult(ok=False, category=CONFIG, details={"reason": reason})

    async def complete_json(
        self, *, system: str, user: str, max_tokens: int, timeout_s: float
    ) -> ProviderResult:
        raise NotImplementedError

    async def ping(self, *, timeout_s: float = 10.0) -> ProviderResult:
        """Cheap key validation without generation (for status endpoints)."""
        raise NotImplementedError


class GroqProvider(BaseProvider):
    """Groq Cloud, OpenAI-compatible Chat Completions (JSON object mode)."""

    name = "groq"

    async def complete_json(
        self, *, system: str, user: str, max_tokens: int, timeout_s: float
    ) -> ProviderResult:
        if not self.configured:
            return self._unsupported("missing Groq key or model")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_completion_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        started = time.perf_counter()
        try:
            async with await self._client_ctx() as client:
                response = await client.post(
                    f"{GROQ_BASE_URL}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(connect=5.0, read=timeout_s, write=10.0, pool=5.0),
                )
        except httpx.TimeoutException:
            return ProviderResult(ok=False, category=TIMEOUT, model=self.model,
                                   duration_s=time.perf_counter() - started)
        except httpx.HTTPError as exc:
            logger.warning("Groq network error: %s", type(exc).__name__)
            return ProviderResult(ok=False, category=NETWORK, model=self.model,
                                   duration_s=time.perf_counter() - started)
        duration = time.perf_counter() - started
        if response.status_code in (401, 403):
            return ProviderResult(ok=False, category=AUTH, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if response.status_code == 429:
            return ProviderResult(ok=False, category=RATE_LIMITED, model=self.model,
                                   status_code=429, duration_s=duration,
                                   retry_after_s=_retry_after(response.headers))
        if 400 <= response.status_code < 500:
            logger.warning("Groq client error status=%s", response.status_code)
            return ProviderResult(ok=False, category=CONFIG, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if response.status_code >= 500:
            return ProviderResult(ok=False, category=SERVER, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        try:
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            return ProviderResult(ok=False, category=INVALID_RESPONSE, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if not isinstance(text, str) or not text.strip():
            return ProviderResult(ok=False, category=INVALID_RESPONSE, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        return ProviderResult(ok=True, text=text, model=self.model, duration_s=duration)

    async def ping(self, *, timeout_s: float = 10.0) -> ProviderResult:
        if not self.configured:
            return self._unsupported("missing Groq key or model")
        started = time.perf_counter()
        try:
            async with await self._client_ctx() as client:
                response = await client.get(
                    f"{GROQ_BASE_URL}/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=timeout_s,
                )
        except httpx.TimeoutException:
            return ProviderResult(ok=False, category=TIMEOUT, model=self.model,
                                   duration_s=time.perf_counter() - started)
        except httpx.HTTPError as exc:
            logger.warning("Groq ping network error: %s", type(exc).__name__)
            return ProviderResult(ok=False, category=NETWORK, model=self.model,
                                   duration_s=time.perf_counter() - started)
        duration = time.perf_counter() - started
        if response.status_code in (401, 403):
            return ProviderResult(ok=False, category=AUTH, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if response.status_code == 429:
            return ProviderResult(ok=False, category=RATE_LIMITED, model=self.model,
                                   status_code=429, duration_s=duration)
        if response.status_code >= 500:
            return ProviderResult(ok=False, category=SERVER, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if response.status_code != 200:
            return ProviderResult(ok=False, category=CONFIG, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        return ProviderResult(ok=True, model=self.model, duration_s=duration)


class GeminiProvider(BaseProvider):
    """Google Gemini generateContent (JSON mime mode, key in header)."""

    name = "gemini"

    def _url(self, action: str) -> str:
        return f"{GEMINI_BASE_URL}/models/{self.model}:{action}"

    async def complete_json(
        self, *, system: str, user: str, max_tokens: int, timeout_s: float
    ) -> ProviderResult:
        if not self.configured:
            return self._unsupported("missing Gemini key or model")
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "maxOutputTokens": max_tokens,
                "temperature": 0.2,
            },
        }
        headers = {"x-goog-api-key": self._api_key, "Content-Type": "application/json"}
        started = time.perf_counter()
        try:
            async with await self._client_ctx() as client:
                response = await client.post(
                    self._url("generateContent"),
                    json=payload,
                    headers=headers,
                    timeout=httpx.Timeout(connect=5.0, read=timeout_s, write=10.0, pool=5.0),
                )
        except httpx.TimeoutException:
            return ProviderResult(ok=False, category=TIMEOUT, model=self.model,
                                   duration_s=time.perf_counter() - started)
        except httpx.HTTPError as exc:
            logger.warning("Gemini network error: %s", type(exc).__name__)
            return ProviderResult(ok=False, category=NETWORK, model=self.model,
                                   duration_s=time.perf_counter() - started)
        duration = time.perf_counter() - started
        if response.status_code in (401, 403):
            return ProviderResult(ok=False, category=AUTH, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if response.status_code == 429:
            return ProviderResult(ok=False, category=RATE_LIMITED, model=self.model,
                                   status_code=429, duration_s=duration,
                                   retry_after_s=_retry_after(response.headers))
        if response.status_code == 400:
            # Invalid key surfaces as 400 API_KEY_INVALID; treat as auth.
            return ProviderResult(ok=False, category=AUTH, model=self.model,
                                   status_code=400, duration_s=duration)
        if 400 <= response.status_code < 500:
            logger.warning("Gemini client error status=%s", response.status_code)
            return ProviderResult(ok=False, category=CONFIG, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if response.status_code >= 500:
            return ProviderResult(ok=False, category=SERVER, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        try:
            body = response.json()
        except ValueError:
            return ProviderResult(ok=False, category=INVALID_RESPONSE, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if _was_blocked(body):
            return ProviderResult(ok=False, category=BLOCKED, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        text = _extract_text(body)
        if not text:
            return ProviderResult(ok=False, category=INVALID_RESPONSE, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        return ProviderResult(ok=True, text=text, model=self.model, duration_s=duration)

    async def ping(self, *, timeout_s: float = 10.0) -> ProviderResult:
        if not self.configured:
            return self._unsupported("missing Gemini key or model")
        started = time.perf_counter()
        try:
            async with await self._client_ctx() as client:
                response = await client.get(
                    f"{GEMINI_BASE_URL}/models",
                    headers={"x-goog-api-key": self._api_key},
                    timeout=timeout_s,
                )
        except httpx.TimeoutException:
            return ProviderResult(ok=False, category=TIMEOUT, model=self.model,
                                   duration_s=time.perf_counter() - started)
        except httpx.HTTPError as exc:
            logger.warning("Gemini ping network error: %s", type(exc).__name__)
            return ProviderResult(ok=False, category=NETWORK, model=self.model,
                                   duration_s=time.perf_counter() - started)
        duration = time.perf_counter() - started
        if response.status_code in (401, 403, 400):
            return ProviderResult(ok=False, category=AUTH, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if response.status_code == 429:
            return ProviderResult(ok=False, category=RATE_LIMITED, model=self.model,
                                   status_code=429, duration_s=duration)
        if response.status_code >= 500:
            return ProviderResult(ok=False, category=SERVER, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        if response.status_code != 200:
            return ProviderResult(ok=False, category=CONFIG, model=self.model,
                                   status_code=response.status_code, duration_s=duration)
        return ProviderResult(ok=True, model=self.model, duration_s=duration)


def _was_blocked(body: Any) -> bool:
    """Detect Gemini safety blocks without propagating block prose."""
    try:
        feedback = body.get("promptFeedback", {}) or {}
        if feedback.get("blockReason"):
            return True
        for candidate in body.get("candidates", []) or []:
            if (candidate.get("finishReason") or "") in {"SAFETY", "PROHIBITED_CONTENT"}:
                return True
    except AttributeError:
        return False
    return False


def _extract_text(body: Any) -> str | None:
    try:
        candidates = body.get("candidates", []) or []
        parts: list[str] = []
        for candidate in candidates:
            content = candidate.get("content", {}) or {}
            for part in content.get("parts", []) or []:
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        joined = "".join(parts).strip()
        return joined or None
    except AttributeError:
        return None


def redact_error_for_log(message: str) -> str:
    """Sanitize free-form error text before logging (never leaks secrets)."""
    return redact_text(message, max_len=300)
