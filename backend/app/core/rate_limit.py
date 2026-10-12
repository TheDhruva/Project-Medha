"""In-process per-IP rate limiting (V1, no Redis).

Single-instance assumption: buckets live in process memory. Multi-replica
deployments must either pin to one instance or front MEDHA with a shared
(edge/CDN) limiter — documented in config.PRODUCTION_NOTES.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque

_buckets: dict[str, deque[float]] = defaultdict(deque)


def client_ip(request, *, trusted_proxy: str = "") -> str:
    """Resolve the client IP without trusting spoofable headers by default.

    X-Forwarded-For is honored only when MEDHA_TRUSTED_PROXY matches the
    direct peer address (i.e. we are behind a correctly configured proxy).
    """
    direct = request.client.host if getattr(request, "client", None) else "unknown"
    if not trusted_proxy or direct != trusted_proxy:
        return direct
    forwarded = request.headers.get("x-forwarded-for", "")
    first = (forwarded.split(",")[0] if forwarded else "").strip()
    return first or direct


def check_rate_limit(key: str, *, limit_per_minute: int, now: float | None = None) -> bool:
    """Return True when allowed; False when over budget. Window = 60s sliding."""
    ts = now if now is not None else time.time()
    bucket = _buckets[key]
    cutoff = ts - 60.0
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= max(1, limit_per_minute):
        return False
    bucket.append(ts)
    return True


def reset_rate_limits() -> None:
    _buckets.clear()
