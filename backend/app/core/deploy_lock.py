"""Single real-deployment concurrency lock (V1: one at a time)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass
class DeployLockState:
    held: bool = False
    deployment_id: str | None = None


_lock = threading.Lock()
_state = DeployLockState()


class DeployBusyError(RuntimeError):
    def __init__(self, current_deployment_id: str | None) -> None:
        super().__init__(
            f"Another real deployment is in progress: {current_deployment_id or 'unknown'}"
        )
        self.current_deployment_id = current_deployment_id
        self.code = "DEPLOYMENT_BUSY"


def try_acquire_real_deploy(deployment_id: str) -> None:
    """Acquire lock. Re-acquiring the same deployment_id is a no-op (API + pipeline)."""
    with _lock:
        if _state.held and _state.deployment_id == deployment_id:
            return
        if _state.held:
            raise DeployBusyError(_state.deployment_id)
        _state.held = True
        _state.deployment_id = deployment_id


def release_real_deploy(deployment_id: str | None = None) -> None:
    with _lock:
        if deployment_id and _state.deployment_id and deployment_id != _state.deployment_id:
            return
        _state.held = False
        _state.deployment_id = None


def real_deploy_status() -> dict[str, Any]:
    with _lock:
        return {
            "busy": _state.held,
            "deployment_id": _state.deployment_id,
            "limit": "one_real_deployment_at_a_time",
        }
