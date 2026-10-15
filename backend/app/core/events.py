from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.enums import EventType
from app.core.logging import get_logger
from app.models.events import SystemEvent

logger = get_logger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class EventBus:
    """In-process fan-out bus. Events are persisted by the repository layer."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[SystemEvent]]] = defaultdict(set)
        self._lock = asyncio.Lock()
        # Consecutive-drop counter per queue: slow consumers are evicted
        # (dead-stream cleanup) instead of silently missing events forever.
        self._drops: dict[int, int] = {}
        self._max_consecutive_drops = 20

    async def subscribe(self, deployment_id: str) -> asyncio.Queue[SystemEvent]:
        queue: asyncio.Queue[SystemEvent] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers[deployment_id].add(queue)
        from app.core.perf import bump

        bump("sse.subscribe")
        return queue

    def subscriber_count(self, deployment_id: str | None = None) -> int:
        subs = self._subscribers.get(deployment_id, set()) if deployment_id else set().union(*self._subscribers.values()) if self._subscribers else set()
        return len(subs)

    async def unsubscribe(self, deployment_id: str, queue: asyncio.Queue[SystemEvent]) -> None:
        async with self._lock:
            subs = self._subscribers.get(deployment_id)
            if not subs:
                return
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(deployment_id, None)
        self._drops.pop(id(queue), None)

    async def publish(self, event: SystemEvent) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(event.deployment_id, set()))
        from app.core.perf import bump

        bump("sse.published")
        for queue in subscribers:
            try:
                queue.put_nowait(event)
                self._drops.pop(id(queue), None)
            except asyncio.QueueFull:
                bump("sse.dropped")
                consecutive = self._drops.get(id(queue), 0) + 1
                self._drops[id(queue)] = consecutive
                logger.warning(
                    "Dropping event for slow SSE subscriber deployment_id=%s type=%s (%d consecutive)",
                    event.deployment_id,
                    event.event_type,
                    consecutive,
                )
                if consecutive >= self._max_consecutive_drops:
                    # Dead stream: evict so the handler's disconnect check
                    # fires and resources are released on both ends.
                    async with self._lock:
                        subs = self._subscribers.get(event.deployment_id)
                        if subs is not None:
                            subs.discard(queue)
                            if not subs:
                                self._subscribers.pop(event.deployment_id, None)
                    self._drops.pop(id(queue), None)
                    bump("sse.evicted")


event_bus = EventBus()


def make_event(
    *,
    deployment_id: str,
    event_type: EventType | str,
    message: str,
    stage: str | None = None,
    status: str | None = None,
    level: str = "info",
    metadata: dict[str, Any] | None = None,
    is_demo: bool = True,
) -> SystemEvent:
    etype = event_type.value if isinstance(event_type, EventType) else event_type
    return SystemEvent(
        event_id=f"evt_{uuid4().hex[:16]}",
        deployment_id=deployment_id,
        event_type=etype,
        ts=utc_now_iso(),
        stage=stage,
        message=message,
        status=status,
        level=level,
        is_demo=is_demo,
        data=metadata or {},
    )
