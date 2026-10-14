"""Execution readiness preflight — one place that answers "can this host execute?".

Every caller (GET /api/config/status, the pipeline execute gate, operator
guidance) derives its answer from this module so configuration behaviour is
deterministic across local development, tests, and deployment.

Contract of the returned dict (stable API surface — safe to expose):

- status:        "ready" | "blocked" | "disabled"
- mode:          normalized executor mode ("auto" | "simulator" | "real" |
                 "docker" | "disabled")
- reason_code:   stable machine code (see constants below)
- message:       concise, human-readable explanation (never stack traces,
                 secrets, or environment values — variable names only)
- simulated:     True only for the explicit test-only simulator
- requires_operator: True when resolving needs a developer/operator rather
                 than an ordinary project user
- restart_required:  True when the fix requires restarting the backend
                 (settings are read once at startup)
- next_actions:  short list of supported remedies

The simulator is explicit opt-in (ADR-037): it is never selected implicitly,
never reported as real execution, and its results can never be healthy.
"""

from __future__ import annotations

import time
from typing import Any

from app.core.config import Settings, get_settings

# Stable reason codes (surfaced verbatim in run results and API payloads).
EXECUTION_NOT_CONFIGURED = "EXECUTION_NOT_CONFIGURED"
EXECUTOR_SIMULATOR_EXPLICIT = "EXECUTOR_SIMULATOR_EXPLICIT"
REAL_EXECUTOR_READY = "REAL_EXECUTOR_READY"
REAL_EXECUTION_NOT_ENABLED = "REAL_EXECUTION_NOT_ENABLED"
REAL_BUILDER_UNAVAILABLE = "REAL_BUILDER_UNAVAILABLE"
EXECUTION_DISABLED = "EXECUTION_DISABLED"
EXECUTION_DISABLED_HOSTED = "EXECUTION_DISABLED_HOSTED"
INVALID_EXECUTOR_MODE = "INVALID_EXECUTOR_MODE"

KNOWN_MODES = frozenset({"auto", "simulator", "real", "docker", "disabled"})

_UNCONFIGURED_MESSAGE = (
    "Execution is not configured: set MEDHA_EXECUTOR_MODE=simulator "
    "for explicit test-only runs, or MEDHA_EXECUTOR_MODE=real with "
    "MEDHA_DOCKER_EXECUTE=true and an isolated Docker builder for "
    "genuine deployment. MEDHA does not substitute simulation for "
    "real execution."
)

# Docker probes spawn subprocesses (seconds on cold hosts); cache briefly.
_PROBE: dict[str, Any] = {"cli": None, "daemon": None, "at": 0.0}
_PROBE_TTL_S = 30.0


def _docker_available() -> tuple[bool, bool]:
    """(cli_present, daemon_running) with a short cache; never raises."""
    now = time.monotonic()
    if _PROBE["cli"] is not None and now - float(_PROBE["at"]) < _PROBE_TTL_S:
        return bool(_PROBE["cli"]), bool(_PROBE["daemon"])
    cli = daemon = False
    try:
        from app.execution import docker_ops

        cli = docker_ops.docker_cli_available()
        daemon = docker_ops.docker_daemon_running()
    except Exception:  # noqa: BLE001 - diagnostics must never fail
        cli = daemon = False
    _PROBE["cli"] = cli
    _PROBE["daemon"] = daemon
    _PROBE["at"] = now
    return cli, daemon


def _result(
    *,
    status: str,
    mode: str,
    reason_code: str,
    message: str,
    simulated: bool = False,
    requires_operator: bool = False,
    restart_required: bool = False,
    next_actions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "mode": mode,
        "reason_code": reason_code,
        "message": message,
        "simulated": simulated,
        "requires_operator": requires_operator,
        "restart_required": restart_required,
        "next_actions": list(next_actions or []),
    }


def assess_execution_readiness(
    settings: Settings | None = None,
    *,
    docker_cli: bool | None = None,
    docker_daemon: bool | None = None,
) -> dict[str, Any]:
    """Structured execution-readiness result for the configured host.

    Docker is probed only when the configuration actually needs the isolated
    builder, so the common local paths (simulator / auto) stay fast and
    offline. Callers with a fresh cached probe (e.g. /api/config/status) pass
    it in via `docker_cli`/`docker_daemon` to avoid a second probe.
    """
    settings = settings or get_settings()
    mode = str(settings.executor_mode or "auto").strip().lower()
    if mode not in KNOWN_MODES:
        # Normally impossible (Settings validates), but never guess for
        # objects constructed outside the validated path.
        return _result(
            status="blocked",
            mode=mode,
            reason_code=INVALID_EXECUTOR_MODE,
            message=(
                f"Executor mode '{mode}' is not a supported value. Set "
                "MEDHA_EXECUTOR_MODE to auto, simulator, real, docker, or disabled."
            ),
            requires_operator=True,
            restart_required=True,
            next_actions=["Set a supported MEDHA_EXECUTOR_MODE and restart the backend"],
        )

    if (settings.medha_env or "").strip().lower() == "production":
        return _result(
            status="disabled",
            mode=mode,
            reason_code=EXECUTION_DISABLED_HOSTED,
            message=(
                "Execution is disabled on the hosted control plane. "
                "Run analysis locally with an isolated builder."
            ),
            requires_operator=True,
            restart_required=True,
            next_actions=["Run MEDHA locally with an isolated Docker builder"],
        )

    if mode == "disabled":
        return _result(
            status="disabled",
            mode=mode,
            reason_code=EXECUTION_DISABLED,
            message=(
                "Execution is disabled by operator configuration "
                "(MEDHA_EXECUTOR_MODE=disabled). Analysis and verification "
                "still run; deployment execution will not."
            ),
            requires_operator=True,
            restart_required=True,
            next_actions=[
                "Set MEDHA_EXECUTOR_MODE=simulator for explicit test-only runs",
                "Set MEDHA_EXECUTOR_MODE=real with MEDHA_DOCKER_EXECUTE=true "
                "and an isolated Docker builder for genuine deployment",
            ],
        )

    if mode == "simulator":
        return _result(
            status="ready",
            mode=mode,
            reason_code=EXECUTOR_SIMULATOR_EXPLICIT,
            message=(
                "Explicit test-only simulator enabled; results are labelled "
                "test-only and can never be reported healthy."
            ),
            simulated=True,
            next_actions=[
                "Set MEDHA_EXECUTOR_MODE=real with MEDHA_DOCKER_EXECUTE=true "
                "and an isolated Docker builder for genuine deployment"
            ],
        )

    if mode in {"real", "docker"}:
        if not settings.docker_execute:
            return _result(
                status="blocked",
                mode=mode,
                reason_code=REAL_EXECUTION_NOT_ENABLED,
                message=(
                    "Real execution is not enabled. Set MEDHA_EXECUTOR_MODE=real "
                    "and MEDHA_DOCKER_EXECUTE=true with an isolated builder."
                ),
                requires_operator=True,
                restart_required=True,
                next_actions=[
                    "Set MEDHA_EXECUTOR_MODE=real and MEDHA_DOCKER_EXECUTE=true, "
                    "then restart the backend",
                ],
            )
        cli = docker_cli if docker_cli is not None else _docker_available()[0]
        daemon = docker_daemon if docker_daemon is not None else _docker_available()[1]
        if not cli:
            return _result(
                status="blocked",
                mode=mode,
                reason_code=REAL_BUILDER_UNAVAILABLE,
                message=(
                    "Real execution is enabled but the Docker CLI was not found "
                    "on this host; the isolated builder is unavailable."
                ),
                requires_operator=True,
                next_actions=["Install Docker, then start the backend again"],
            )
        if not daemon:
            return _result(
                status="blocked",
                mode=mode,
                reason_code=REAL_BUILDER_UNAVAILABLE,
                message=(
                    "Real execution is enabled but the Docker daemon is not "
                    "running; the isolated builder is unavailable."
                ),
                requires_operator=True,
                next_actions=["Start the Docker daemon, then retry"],
            )
        return _result(
            status="ready",
            mode=mode,
            reason_code=REAL_EXECUTOR_READY,
            message=(
                "Isolated Docker builder reachable; supported profiles "
                "(static, python, node) can deploy."
            ),
        )

    # mode == "auto": fail closed without an isolated builder (ADR-037).
    return _result(
        status="blocked",
        mode=mode,
        reason_code=EXECUTION_NOT_CONFIGURED,
        message=_UNCONFIGURED_MESSAGE,
        requires_operator=True,
        restart_required=True,
        next_actions=[
            "Set MEDHA_EXECUTOR_MODE=simulator for explicit test-only runs",
            "Set MEDHA_EXECUTOR_MODE=real with MEDHA_DOCKER_EXECUTE=true and "
            "an isolated Docker builder for genuine deployment",
        ],
    )
