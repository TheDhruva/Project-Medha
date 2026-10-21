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
    node_install_fragment,
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
    runtime_spec: dict = field(default_factory=dict)
    # Structured build diagnostics (stage/command/exit_code/error_code/log);
    # empty unless the build stage failed. Never carries secrets.
    build: dict = field(default_factory=dict)
    started_at: str | None = None
    finished_at: str | None = None


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _classify_readiness_failure(
    readiness: dict, *, host_port: int, container_port: int, path: str,
) -> str:
    """Distinguishable readiness diagnosis (connection vs HTTP vs timeout).

    Connection-refused means nothing accepted on the published mapping —
    typically the app listening on a different container port — not a slow
    start. Startup log lines are never treated as health evidence.
    """
    probed = f"http://127.0.0.1:{host_port}{path}"
    mapping = f"host 127.0.0.1:{host_port} → container:{container_port}"
    reason = str(readiness.get("reason", "") or "")
    lowered = reason.lower()
    if "refused" in lowered or "errno 111" in lowered or "winerror 10061" in lowered:
        return (
            "Application did not become ready: connection refused at "
            f"{probed} (published {mapping}). The container is running but "
            "nothing accepts connections on the published port — the app is "
            f"likely listening on a different container port. Probe error: {reason}."
        )
    if lowered.startswith("http_"):
        return (
            "Application did not become ready: unhealthy HTTP response probing "
            f"{probed} (published {mapping}). Last probe result: {reason}."
        )
    if readiness.get("status") == "timed_out":
        return (
            "Application did not become ready: readiness timed out probing "
            f"{probed} (published {mapping}). Last probe result: {reason}."
        )
    return (
        "Application did not become ready: "
        f"{reason or readiness} (probed {probed}, published {mapping})."
    )


def _readiness_stage(readiness: dict, *, running: bool | None) -> str:
    """Machine-readable failure stage (facts only, no hypotheses)."""
    if running is False:
        return "container_exited"
    reason = str(readiness.get("reason", "") or "")
    lowered = reason.lower()
    if "refused" in lowered or "errno 111" in lowered or "winerror 10061" in lowered:
        return "connection_refused"
    if lowered.startswith("http_"):
        return "http_error"
    if readiness.get("status") == "timed_out":
        return "timeout"
    return "unknown"


def _log_tail(container: str, *, limit: int = 2000) -> str:
    try:
        logs = docker_ops.container_logs(container)
    except Exception:  # noqa: BLE001 - diagnostics best effort
        return ""
    return ((logs.get("stderr") or "") + (logs.get("stdout") or ""))[-limit:]


def _build_diagnostics(
    exc: docker_ops.DockerOpsError, resolved: BuildProfile, checkout: Path,
) -> dict:
    """Structured, redacted build-failure evidence (empty for non-build errors)."""
    if exc.code != "BUILD_FAILED" and not exc.log:
        return {}
    from app.ai.redact import redact_text

    command: str | None = None
    if resolved.name in ("node", "nextjs"):
        try:
            command = node_install_fragment(resolved, checkout=checkout).strip()
        except UnsupportedStack:
            command = None
    return {
        "stage": "build",
        "profile": resolved.name,
        "app_root": resolved.app_root,
        "package_manager": resolved.package_manager,
        "command": command,
        "exit_code": exc.exit_code,
        "error_code": exc.error_code,
        "log": redact_text(exc.log or ""),
        "log_truncated": bool(exc.log_truncated),
    }


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
        commit_sha: str | None = None,
        # Validated port contract (planning pipeline): the container-internal
        # listen port stays repository-owned while the host-published port may
        # be a negotiated alternative. Absent → legacy single-port behavior.
        host_port: int | None = None,
        internal_port: int | None = None,
    ) -> RealDeployResult:
        """Build + run a supported app; block until the readiness contract passes.

        Deterministic, fail-closed stages: detection → build → start →
        port-binding verification → bounded readiness probes. Success is
        reported only when the probe passes on the published endpoint; every
        failure records its stage, the actual probe target and port mapping,
        container state/exit code, and a concise log tail.
        """
        started = _now_iso()
        # Policy gate first (mode flags, hosted guard, forbidden instructions).
        check_real_execution_policy(dockerfile_text="", compose_text="")
        try:
            from app.execution.runtime import detect_runtime, with_host_port

            # Internal (repository evidence) and host (negotiated publish)
            # sides are distinct: detection learns the internal port, then
            # only the host side is rebound. Legacy callers pass neither and
            # keep the single-port behavior.
            internal = int(internal_port) if internal_port is not None else int(target_port)
            host = int(host_port) if host_port is not None else int(target_port)
            spec = detect_runtime(
                checkout, target_port=internal, commit_sha=commit_sha,
                readiness_deadline_s=readiness_timeout,
            )
            if host != spec.host_port:
                spec = with_host_port(spec, host)
            spec_evidence = spec.to_evidence()
            if profile is not None and (
                host_port is None and internal_port is None
            ):
                resolved = profile
            else:
                # The validated spec owns build/start/publish (an explicit
                # caller profile predates the contract and may pin a stale
                # port — never let it override the negotiated mapping).
                resolved = spec.to_build_profile()
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
                runtime_spec=spec_evidence,
            )

        tag = f"medha_{docker_ops.short_deployment_id(deployment_id)}_{resolved.name}"
        dockerfile_text = render_dockerfile(resolved, checkout=checkout)
        build_dir = checkout / ".medha-build"
        network = ""
        container = ""
        probe_url = f"http://127.0.0.1:{host}{resolved.health_path}"
        mapping = f"host 127.0.0.1:{host} → container:{resolved.port}"

        def _fail(code: str, message: str, **extra) -> RealDeployResult:
            return RealDeployResult(
                ok=False, code=code, message=message,
                profile=resolved.name, image=tag,
                image_digest=extra.pop("image_digest", None),
                container=container or None, port=host,
                started_at=started, finished_at=_now_iso(),
                runtime_spec=spec_evidence, **extra,
            )

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
            # Profile env (e.g. node PORT/HOSTNAME) makes the app listen on
            # the published container port; explicit operator env wins.
            merged_env: dict[str, str] = dict(resolved.env or {})
            merged_env.update(authorized_env or {})
            container = await asyncio.to_thread(
                docker_ops.start_container,
                deployment_id=deployment_id,
                service=f"app-{resolved.name}",
                image=tag,
                network=network,
                command=resolved.start_command or None,
                publish_port=host,
                container_port=resolved.port,
                env=merged_env or None,
            )
            state = await asyncio.to_thread(docker_ops.container_state, container)
            if not state.get("available") or not state.get("running"):
                tail = await asyncio.to_thread(_log_tail, container)
                exit_code = state.get("exit_code", "?") if state.get("available") else "unknown"
                return _fail(
                    "START_FAILED",
                    "Application container exited immediately "
                    f"(exit_code={exit_code}, {mapping}). "
                    f"Container logs (tail, context only): {tail[-500:]}",
                    readiness={
                        "stage": "container_exited", "status": "exited",
                        "probe_url": probe_url, "host_port": host,
                        "container_port": resolved.port, "mapping": mapping,
                        "container": {
                            "running": state.get("running"),
                            "exit_code": state.get("exit_code"),
                            "oom_killed": state.get("oom_killed"),
                        } if state.get("available") else {"available": False},
                        "log_tail": tail[-1000:],
                    },
                )
            # Port-binding verification: the generated container port must
            # actually be published, or the probe target is meaningless.
            bound = await asyncio.to_thread(
                docker_ops.published_host_port, state, resolved.port,
            )
            if bound != host:
                tail = await asyncio.to_thread(_log_tail, container)
                return _fail(
                    "PORT_MAPPING_FAILED",
                    f"Container port {resolved.port} is not published on "
                    f"127.0.0.1:{host} (observed bindings: "
                    f"{state.get('ports') or {}}). Probe target {probe_url} "
                    "cannot reach the app — refusing to probe a dead mapping. "
                    f"Logs (tail, context only): {tail[-300:]}",
                    readiness={
                        "stage": "port_unmapped", "status": "unmapped",
                        "probe_url": probe_url, "host_port": host,
                        "container_port": resolved.port, "mapping": mapping,
                        "observed_ports": state.get("ports") or {},
                        "container": {"running": True,
                                      "exit_code": state.get("exit_code", 0)},
                        "log_tail": tail[-1000:],
                    },
                )
            readiness = await asyncio.to_thread(
                docker_ops.wait_http_readiness,
                host, path=resolved.health_path,
                timeout=readiness_timeout,
            )
            if readiness.get("status") != "ready":
                state = await asyncio.to_thread(docker_ops.container_state, container)
                running = state.get("running") if state.get("available") else None
                stage = _readiness_stage(readiness, running=running)
                tail = await asyncio.to_thread(_log_tail, container)
                cause = _classify_readiness_failure(
                    readiness, host_port=host,
                    container_port=resolved.port, path=resolved.health_path,
                )
                if stage == "container_exited":
                    cause = (
                        "Application container exited during readiness probing "
                        f"(exit_code={state.get('exit_code')}, "
                        f"oom_killed={state.get('oom_killed')}, {mapping}). "
                        f"Last probe result: {readiness.get('reason', '')}."
                    )
                evidence = {
                    "stage": stage,
                    "status": readiness.get("status"),
                    "reason": readiness.get("reason", ""),
                    "http_status": readiness.get("http_status"),
                    "attempts": readiness.get("attempts", 0),
                    "probe_url": readiness.get("probe_url", probe_url),
                    "host_port": host,
                    "container_port": resolved.port,
                    "mapping": mapping,
                    "container": {
                        "running": running,
                        "exit_code": state.get("exit_code"),
                        "oom_killed": state.get("oom_killed"),
                    } if state.get("available") else {"available": False},
                    "log_tail": tail[-1000:],
                }
                return _fail(
                    "READINESS_FAILED",
                    f"{cause} Container logs (tail, context only — "
                    "startup output is not proof of reachability): "
                    f"{tail[-300:]}",
                    image_digest=digest, readiness=evidence,
                )
            logger.info("Real deploy ready deployment_id=%s profile=%s digest=%.12s",
                        deployment_id, resolved.name, digest)
            final_state = await asyncio.to_thread(docker_ops.container_state, container)
            return RealDeployResult(
                ok=True, profile=resolved.name, image=tag, image_digest=digest,
                container=container, port=host,
                readiness={
                    "stage": "ready",
                    "status": "ready",
                    "http_status": readiness.get("http_status"),
                    "attempts": readiness.get("attempts", 0),
                    "probe_url": readiness.get("probe_url", probe_url),
                    "host_port": host,
                    "container_port": resolved.port,
                    "mapping": mapping,
                    "observed_ports": (final_state.get("ports") or {}
                                       if final_state.get("available") else {}),
                },
                runtime_spec=spec_evidence,
                started_at=started, finished_at=_now_iso(),
            )
        except UnsupportedStack as exc:
            return _fail(exc.code, exc.message)
        except docker_ops.DockerOpsError as exc:
            return RealDeployResult(
                ok=False, code=exc.code, message=str(exc)[:1500],
                profile=resolved.name, image=tag,
                container=container or None, port=host,
                runtime_spec=spec_evidence,
                build=_build_diagnostics(exc, resolved, checkout),
                started_at=started, finished_at=_now_iso(),
            )
        except PolicyViolation:
            raise
        except Exception as exc:  # noqa: BLE001 - structured failure, never raw
            return RealDeployResult(
                ok=False, code="REAL_EXECUTION_FAILED", message=str(exc)[:500],
                profile=resolved.name,
                container=container or None, port=host,
                runtime_spec=spec_evidence,
                started_at=started, finished_at=_now_iso(),
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
