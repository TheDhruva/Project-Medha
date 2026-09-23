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

    async def subscribe(self, deployment_id: str) -> asyncio.Queue[SystemEvent]:
        queue: asyncio.Queue[SystemEvent] = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subscribers[deployment_id].add(queue)
        return queue

    async def unsubscribe(self, deployment_id: str, queue: asyncio.Queue[SystemEvent]) -> None:
        async with self._lock:
            subs = self._subscribers.get(deployment_id)
            if not subs:
                return
            subs.discard(queue)
            if not subs:
                self._subscribers.pop(deployment_id, None)

    async def publish(self, event: SystemEvent) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(event.deployment_id, set()))
        for queue in subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "Dropping event for slow SSE subscriber deployment_id=%s type=%s",
                    event.deployment_id,
                    event.event_type,
                )


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
