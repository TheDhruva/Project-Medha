"""Execution policy gate for real application builds (Phase 2).

Real builds are allowed only when an isolated builder is explicitly
configured. Until then every real-build request fails closed with a precise,
actionable error — never silently substituted with the simulator.
"""
from __future__ import annotations

import re

from app.core.config import get_settings

_FORBIDDEN_INSTRUCTIONS = (
    re.compile(r"^\s*ADD\s+", re.IGNORECASE | re.MULTILINE),
    re.compile(r"--privileged", re.IGNORECASE),
    re.compile(r"cap_add", re.IGNORECASE),
    re.compile(r"network_mode\s*:\s*host", re.IGNORECASE),
    re.compile(r"/var/run/docker\.sock", re.IGNORECASE),
)


class PolicyViolation(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def check_real_execution_policy(*, dockerfile_text: str = "", compose_text: str = "") -> None:
    settings = get_settings()
    if (settings.medha_env or "").strip().lower() == "production":
        raise PolicyViolation(
            "REAL_EXECUTION_DISABLED_HOSTED",
            "Real builds are disabled on the hosted control plane (simulator-only). "
            "Configure a separate isolated builder.",
        )
    if (settings.executor_mode or "auto").lower() not in {"real", "docker"} or not settings.docker_execute:
        raise PolicyViolation(
            "REAL_EXECUTION_NOT_ENABLED",
            "Real execution is not enabled. Set MEDHA_EXECUTOR_MODE=real and "
            "MEDHA_DOCKER_EXECUTE=true with an isolated builder.",
        )
    combined = f"{dockerfile_text}\n{compose_text}"
    for pattern in _FORBIDDEN_INSTRUCTIONS:
        if pattern.search(combined):
            raise PolicyViolation(
                "POLICY_VIOLATION",
                f"Build rejected by execution policy (matched {pattern.pattern}).",
            )
