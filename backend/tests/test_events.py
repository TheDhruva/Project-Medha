from app.core.events import make_event
from app.core.enums import EventType
from app.models.events import SystemEvent


def test_event_serialization_roundtrip():
    event = make_event(
        deployment_id="dep_test",
        event_type=EventType.STAGE_STARTED,
        message="PREFLIGHT started",
        stage="PREFLIGHT",
        status="running",
        metadata={"simple": "Checking host"},
    )
    payload = event.to_sse_payload()
    assert payload["type"] == "stage.started"
    assert payload["stage"] == "PREFLIGHT"
    assert payload["is_demo"] is True
    restored = SystemEvent.model_validate(
        {
            "event_id": payload["event_id"],
            "deployment_id": payload["deployment_id"],
            "event_type": payload["type"],
            "ts": payload["ts"],
            "stage": payload["stage"],
            "message": payload["message"],
            "status": payload["status"],
            "level": payload["level"],
            "is_demo": payload["is_demo"],
            "data": payload["data"],
        }
    )
    assert restored.message == "PREFLIGHT started"
