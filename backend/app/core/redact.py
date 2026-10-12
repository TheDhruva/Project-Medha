"""Redaction helpers — strip secrets before events/logs/persistence."""
from __future__ import annotations

import re
from typing import Any

_SECRET_KEYS = ("token", "secret", "password", "api_key", "apikey", "private_key", "authorization")
_URL_CRED_RE = re.compile(r"(https?://)([^/\s:@]+)(:[^/\s@]+)?@", re.IGNORECASE)
_TOKEN_VALUE_RE = re.compile(r"(gh[pousr]_[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|x-access-token:[^\s]+)")


def redact_text(value: str, *, max_len: int = 2000) -> str:
    text = value if isinstance(value, str) else str(value)
    text = _URL_CRED_RE.sub(r"\1***@", text)
    text = _TOKEN_VALUE_RE.sub("***", text)
    if len(text) > max_len:
        return text[:max_len] + "…[truncated]"
    return text


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, val in data.items():
        lowered = str(key).lower()
        if any(s in lowered for s in _SECRET_KEYS):
            clean[key] = "***"
        elif isinstance(val, str):
            clean[key] = redact_text(val)
        elif isinstance(val, dict):
            clean[key] = redact_mapping(val)
        else:
            clean[key] = val
    return clean
