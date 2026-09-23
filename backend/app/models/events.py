from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SystemEvent(BaseModel):
    """Serializable deployment event for SSE / logs / persistence."""

    event_id: str
    deployment_id: str
    event_type: str = Field(..., description="Machine-readable type")
    ts: str
    stage: str | None = None
    message: str
    status: str | None = None
    level: str = "info"
    is_demo: bool = True
    data: dict[str, Any] = Field(default_factory=dict)

    def to_sse_payload(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "deployment_id": self.deployment_id,
            "ts": self.ts,
            "stage": self.stage,
            "type": self.event_type,
            "level": self.level,
            "message": self.message,
            "status": self.status,
            "is_demo": self.is_demo,
            "data": self.data,
        }
