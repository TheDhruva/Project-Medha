"""Secret redaction for AI prompts, errors, and logs.

Repository content, diffs, and upstream error bodies are untrusted: they may
contain credentials. Every string that crosses the AI boundary (prompts,
logged errors, persisted metadata) passes through here. Raw secret values are
never logged, persisted, or returned in API payloads.
"""

from __future__ import annotations

import re
from typing import Any

REDACTED = "[redacted]"

# (?i) patterns operate on text that may contain credentials.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # URL userinfo: scheme://user:password@host
    (
        re.compile(r"(?i)([a-z][a-z0-9+.-]*://)([^/\s@]+)@"),
        lambda m: f"{m.group(1)}{REDACTED}@",
    ),
    # PEM blocks
    (
        re.compile(
            r"-----BEGIN [A-Z0-9 ]+PRIVATE KEY-----.*?-----END [A-Z0-9 ]+PRIVATE KEY-----",
            re.DOTALL,
        ),
        REDACTED,
    ),
    # Provider-shaped tokens
    (re.compile(r"\bgsk_[A-Za-z0-9_-]{8,}"), REDACTED),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"), REDACTED),
    (re.compile(r"\bx-goog-[A-Za-z0-9_-]{8,}"), REDACTED),
    # GitHub-shaped tokens (also covered by core deploy logs)
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+)"), REDACTED),
    (re.compile(r"x-access-token:[^\s]+"), REDACTED),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]+=*"), f"Bearer {REDACTED}"),
    # key = value assignments
    (
        re.compile(
            r'(?i)\b(api[_-]?key|secret|token|password|passwd|pwd)\b\s*[:=]\s*["\']?([^\s"\';,}]+)["\']?'
        ),
        lambda m: f"{m.group(1)}={REDACTED}",
    ),
)


def redact_text(value: str, *, max_len: int | None = None) -> str:
    """Redact credential-like substrings; optionally truncate (no splitting)."""
    text = value if isinstance(value, str) else str(value)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    if max_len is not None and len(text) > max_len:
        text = text[:max_len] + "…[truncated]"
    return text


_SECRET_KEY_HINTS = (
    "key",
    "secret",
    "token",
    "password",
    "passwd",
    "pwd",
    "credential",
    "authorization",
)


def _key_looks_secret(key: str) -> bool:
    lowered = key.lower()
    return any(hint in lowered for hint in _SECRET_KEY_HINTS)


def redact_mapping(value: Any, *, max_len: int = 4000) -> Any:
    """Recursively redact strings in JSON-like structures.

    Values under secret-hint keys are replaced wholesale; all other strings
    are pattern-redacted and truncated. Used before building prompts and
    before persisting AI metadata.
    """
    if isinstance(value, dict):
        return {
            str(key): (
                REDACTED
                if _key_looks_secret(str(key))
                else redact_mapping(item, max_len=max_len)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact_mapping(item, max_len=max_len) for item in value]
    if isinstance(value, str):
        return redact_text(value, max_len=max_len)
    return value
