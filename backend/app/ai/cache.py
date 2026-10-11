"""Bounded in-process cache for AI results (no Redis in V1).

Keys bind the stable hash of: prompt/schema version, provider, model,
authorization context (owner), and the canonicalized input. Results are never
shared across different authorization contexts, so private repository content
cannot leak between users through cache hits.
"""

from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from threading import Lock
from typing import Any


def cache_key(
    *,
    prompt_version: str,
    kind: str,
    provider: str,
    model: str,
    owner_ctx: str,
    payload: dict[str, Any],
) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    raw = "|".join([prompt_version, kind, provider, model, owner_ctx, canonical])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class AICache:
    """Tiny LRU cache. All operations are O(1); eviction is oldest-first."""

    def __init__(self, max_entries: int = 128) -> None:
        self.max_entries = max(1, max_entries)
        self._store: OrderedDict[str, Any] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._store:
                return None
            self._store.move_to_end(key)
            return self._store[key]

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = value
            self._store.move_to_end(key)
            while len(self._store) > self.max_entries:
                self._store.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)
