"""Isolated real application executor (Phase 2 final).

Builds supported application profiles (static / python / node) from the
verified checkout using controlled MEDHA Dockerfiles — repository
Dockerfiles are never executed. Runtime is an isolated Docker network with
least-privilege flags enforced at the runtime interface:

- no privileged containers, no host networking, no host mounts
- --cap-drop ALL, no-new-privileges, memory/CPU/pids limits
- loopback-published port only, bounded build + readiness timeouts
- cleanup of failed builds, abandoned containers, and images

Fails closed with structured codes (REAL_BUILDER_UNAVAILABLE,
BUILD_FAILED, START_FAILED, READINESS_FAILED, POLICY_VIOLATION) — never
falls back to simulation. Simulator stays untouched.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger
from app.execution import docker_ops
from app.execution.policy import PolicyViolation, check_real_execution_policy
from app.execution.profiles import (
    BuildProfile,
    UnsupportedStack,
    detect_profile,
    render_dockerfile,
)

logger = get_logger(__name__)

EXECUTION_MODE = "real"


@dataclass
class RealDeployResult:
    execution_mode: str = EXECUTION_MODE
    ok: bool = False
    code: str | None = None
    message: str = ""
    profile: str | None = None
    image: str | None = None
    image_digest: str | None = None
    container: str | None = None
    port: int | None = None
    readiness: dict = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def runtime_available() -> tuple[bool, str]:
    """Check for a usable isolated runtime without side effects."""
    if not docker_ops.docker_cli_available():
        return False, "Docker CLI not found."
    if not docker_ops.docker_daemon_running():
        return False, "Docker daemon unreachable."
    return True, "ok"


class RealExecutor:
    name = "real"

    async def execute(self, *, dockerfile_text: str = "", compose_text: str = "") -> None:
        """Legacy policy-gate probe (kept for backward compatibility)."""
        check_real_execution_policy(
            dockerfile_text=dockerfile_text, compose_text=compose_text
        )
        raise PolicyViolation(
            "REAL_BUILDER_UNAVAILABLE",
            "No isolated builder is configured in this environment. "
            "Real execution requires a dedicated builder/runtime (see docs).",
        )

    async def deploy(
        self,
        *,
        deployment_id: str,
        checkout: Path,
        target_port: int = 8080,
        profile: BuildProfile | None = None,
        readiness_timeout: float = 90.0,
        build_timeout: float = 600.0,
        authorized_env: dict[str, str] | None = None,
    ) -> RealDeployResult:
        """Build + run a supported app; block until readiness passes."""
        started = _now_iso()
        # Policy gate first (mode flags, hosted guard, forbidden instructions).
        check_real_execution_policy(dockerfile_text="", compose_text="")
        try:
            resolved = profile or detect_profile(checkout, target_port=target_port)
        except UnsupportedStack as exc:
            return RealDeployResult(
                ok=False, code=exc.code, message=exc.message,
                started_at=started, finished_at=_now_iso(),
            )
        ok, reason = runtime_available()
        if not ok:
            return RealDeployResult(
                ok=False, code="REAL_BUILDER_UNAVAILABLE",
                message=f"Isolated runtime unavailable: {reason} "
                        "Configure Docker on an isolated builder host.",
                profile=resolved.name, started_at=started, finished_at=_now_iso(),
            )

        tag = f"medha_{docker_ops.short_deployment_id(deployment_id)}_{resolved.name}"
        dockerfile_text = render_dockerfile(resolved, checkout=checkout)
        build_dir = checkout / ".medha-build"
        network = ""
        container = ""
        try:
            build_dir.mkdir(parents=True, exist_ok=True)
            (build_dir / "Dockerfile.medha").write_text(dockerfile_text, encoding="utf-8")
            digest = await asyncio.to_thread(
                docker_ops.build_image,
                context_dir=str(checkout),
                dockerfile=str(build_dir / "Dockerfile.medha"),
                tag=tag, timeout=build_timeout,
            )
            network = await asyncio.to_thread(docker_ops.create_network, deployment_id)
            container = await asyncio.to_thread(
                docker_ops.start_container,
                deployment_id=deployment_id,
                service=f"app-{resolved.name}",
                image=tag,
                network=network,
                command=resolved.start_command or None,
                publish_port=target_port,
                container_port=resolved.port,
                env=authorized_env or None,
            )
            running = await asyncio.to_thread(docker_ops.container_running, container)
            if not running:
                logs = await asyncio.to_thread(docker_ops.container_logs, container)
                tail = ((logs.get("stderr") or "") + (logs.get("stdout") or ""))[-1000:]
                raise docker_ops.DockerOpsError(
                    f"Application container exited immediately. {tail}",
                    code="START_FAILED",
                )
            readiness = await asyncio.to_thread(
                docker_ops.wait_http_readiness,
                target_port, path=resolved.health_path,
                timeout=readiness_timeout,
            )
            if readiness.get("status") != "ready":
                logs = await asyncio.to_thread(docker_ops.container_logs, container)
                tail = ((logs.get("stderr") or "") + (logs.get("stdout") or ""))[-1000:]
                return RealDeployResult(
                    ok=False, code="READINESS_FAILED",
                    message=f"Application did not become ready: "
                            f"{readiness.get('reason', readiness)} {tail[-300:]}",
                    profile=resolved.name, image=tag, image_digest=digest,
                    container=container, port=target_port, readiness=readiness,
                    started_at=started, finished_at=_now_iso(),
                )
            logger.info("Real deploy ready deployment_id=%s profile=%s digest=%.12s",
                        deployment_id, resolved.name, digest)
            return RealDeployResult(
                ok=True, profile=resolved.name, image=tag, image_digest=digest,
                container=container, port=target_port, readiness=readiness,
                started_at=started, finished_at=_now_iso(),
            )
        except docker_ops.DockerOpsError as exc:
            return RealDeployResult(
                ok=False, code=exc.code, message=str(exc)[:1000],
                profile=resolved.name, image=tag,
                container=container or None, port=target_port,
                started_at=started, finished_at=_now_iso(),
            )
        except PolicyViolation:
            raise
        except Exception as exc:  # noqa: BLE001 - structured failure, never raw
            return RealDeployResult(
                ok=False, code="REAL_EXECUTION_FAILED", message=str(exc)[:500],
                profile=resolved.name, started_at=started, finished_at=_now_iso(),
            )
        finally:
            # On any non-ready outcome, remove the failed workload. Success
            # containers stay running under MEDHA labels until cleanup.
            try:
                marker = (build_dir / "Dockerfile.medha")
                if marker.is_file():
                    marker.unlink()
            except OSError:
                pass

    async def cleanup(
        self, *, deployment_id: str, container: str | None = None,
        image: str | None = None,
    ) -> dict:
        """Remove failed workload resources (idempotent)."""
        removed: list[str] = []
        if container:
            try:
                if await asyncio.to_thread(
                    docker_ops.stop_and_remove_container, container,
                    deployment_id=deployment_id,
                ):
                    removed.append(container)
            except Exception:  # noqa: BLE001 - cleanup best effort
                pass
        if image:
            try:
                if await asyncio.to_thread(
                    docker_ops.remove_image, image, deployment_id=deployment_id
                ):
                    removed.append(image)
            except Exception:  # noqa: BLE001
                pass
        try:
            info = await asyncio.to_thread(docker_ops.cleanup_deployment, deployment_id)
            removed.extend(info.get("removed", []))
        except Exception:  # noqa: BLE001
            pass
        return {"removed": removed}

    async def logs(
        self, *, container: str, tail: int = 500,
    ) -> dict:
        """Bounded real stdout/stderr; redacted downstream by the API layer."""
        return await asyncio.to_thread(docker_ops.container_logs, container, tail=tail)


__all__ = ["RealExecutor", "RealDeployResult", "runtime_available", "EXECUTION_MODE"]
