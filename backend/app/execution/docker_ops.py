"""Safe, allowlisted Docker CLI helpers for local MEDHA-owned resources only."""

from __future__ import annotations

import json
import re
import shutil
import socket
import subprocess
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

LABEL_DEPLOYMENT = "com.medha.deployment_id"
LABEL_SERVICE = "com.medha.service"
LABEL_MANAGED = "com.medha.managed"
LABEL_VALUE_MANAGED = "true"

# Only these docker verbs are permitted (no shell, no arbitrary args expansion).
ALLOWED_VERBS = frozenset(
    {
        "version",
        "info",
        "network",
        "run",
        "inspect",
        "rm",
        "stop",
        "ps",
        "compose",
        "pull",
        "logs",
        "images",
        "rmi",
    }
)
# NOTE: `build` is deliberately NOT in ALLOWED_VERBS (V1 invariant: the
# generic gateway never builds). Controlled MEDHA-template builds go through
# build_image(), a purpose-built path with fixed flags below.


class DockerOpsError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str = "DOCKER_ERROR",
        log: str | None = None,
        exit_code: int | None = None,
        error_code: str | None = None,
        log_truncated: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        # Structured, bounded build diagnostics (never a secret; callers redact).
        self.log = log
        self.exit_code = exit_code
        self.error_code = error_code
        self.log_truncated = log_truncated


# npm's own machine-readable error code embedded in build output, e.g.
# "npm error code ERESOLVE". Falls back to well-known npm code tokens.
_NPM_CODE_RE = re.compile(r"npm error code ([A-Z][A-Z0-9_]*)")
_NPM_KNOWN_RE = re.compile(
    r"\b(ERESOLVE|EUSAGE|ELIFECYCLE|ENOENT|EACCES|EPERM|EBADENGINE|"
    r"ETIMEDOUT|ENOTFOUND|EAI_AGAIN|ENOSPC|EINTEGRITY)\b"
)


def _npm_error_code(text: str) -> str | None:
    match = _NPM_CODE_RE.search(text) or _NPM_KNOWN_RE.search(text)
    return match.group(1) if match else None


def _tail(text: str, limit: int) -> str:
    """Keep the END of a log — where the failing command's error lives."""
    cleaned = (text or "").strip()
    return cleaned if len(cleaned) <= limit else "…[earlier output trimmed]\n" + cleaned[-limit:]


def docker_cli_available() -> bool:
    return shutil.which("docker") is not None


def docker_daemon_running(*, timeout: float = 5.0) -> bool:
    if not docker_cli_available():
        return False
    try:
        proc = _run(["version", "--format", "{{.Server.Version}}"], timeout=timeout)
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    except DockerOpsError:
        return False


def short_deployment_id(deployment_id: str) -> str:
    raw = deployment_id.removeprefix("dep_")
    return raw[:12]


def resource_name(deployment_id: str, service: str) -> str:
    """Recognizable MEDHA-owned resource name."""
    safe_svc = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in service)[:40]
    return f"medha_{short_deployment_id(deployment_id)}_{safe_svc}"


def network_name(deployment_id: str) -> str:
    return resource_name(deployment_id, "net")


def is_port_available(port: int, host: str = "127.0.0.1") -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, int(port)))
        return True
    except OSError:
        return False


def probe_http_readiness(port: int, *, host: str = "127.0.0.1", timeout: float = 3.0) -> dict[str, Any]:
    """Bounded HTTP readiness probe against a host-mapped service port.

    Non-blocking by contract: returns a status dict (passed/unreachable) and
    never raises. Only loopback targets are probed in V1.
    """
    import urllib.request

    if host not in {"127.0.0.1", "localhost", "::1"}:
        return {"status": "skipped", "reason": "non_loopback_target"}
    try:
        port_int = int(port)
    except (TypeError, ValueError):
        return {"status": "skipped", "reason": "invalid_port"}
    if not 1 <= port_int <= 65535:
        return {"status": "skipped", "reason": "invalid_port"}
    url = f"http://{host}:{port_int}/"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            code = getattr(resp, "status", 200)
        return {"status": "passed" if code < 500 else "unreachable", "http_status": code}
    except Exception as exc:  # noqa: BLE001 - probe is advisory only
        return {"status": "unreachable", "reason": str(exc)[:200]}


def host_port_of(mapping: str) -> int | None:
    """Extract the host side of a validated 'host:container' or 'port' mapping."""
    parts = mapping.split(":")
    try:
        return int(parts[0]) if parts else None
    except ValueError:
        return None


def create_network(deployment_id: str) -> str:
    name = network_name(deployment_id)
    # Remove leftover MEDHA network with same name only if MEDHA-owned
    if _network_is_medha(name, deployment_id):
        _run(["network", "rm", name], timeout=15, check=False)
    elif _network_exists(name):
        raise DockerOpsError(
            f"Network name {name} exists but is not MEDHA-owned; refusing to reuse/delete",
            code="NETWORK_CONFLICT",
        )
    proc = _run(
        [
            "network",
            "create",
            "--label",
            f"{LABEL_DEPLOYMENT}={deployment_id}",
            "--label",
            f"{LABEL_MANAGED}={LABEL_VALUE_MANAGED}",
            "--label",
            f"{LABEL_SERVICE}=network",
            name,
        ],
        timeout=30,
    )
    if proc.returncode != 0:
        raise DockerOpsError(
            f"Failed to create network: {(proc.stderr or proc.stdout or '').strip()}",
            code="NETWORK_CREATE_FAILED",
        )
    return name


def _network_exists(name: str) -> bool:
    proc = _run(["network", "inspect", name], timeout=15, check=False)
    return proc.returncode == 0


def start_container(
    *,
    deployment_id: str,
    service: str,
    image: str,
    network: str,
    command: list[str] | None = None,
    ports: list[str] | None = None,
    env: dict[str, str] | None = None,
    publish_port: int | None = None,
    container_port: int | None = None,
    memory: str = "512m",
    cpus: str = "1.0",
    pids_limit: int = 256,
    readonly_root: bool = False,
) -> str:
    """Start a labeled container. Image/command must come from verified plan."""
    name = resource_name(deployment_id, service)
    _run(["rm", "-f", name], timeout=20, check=False)

    args: list[str] = [
        "run",
        "-d",
        "--name",
        name,
        "--label",
        f"{LABEL_DEPLOYMENT}={deployment_id}",
        "--label",
        f"{LABEL_SERVICE}={service}",
        "--label",
        f"{LABEL_MANAGED}={LABEL_VALUE_MANAGED}",
        "--network",
        network,
        # Isolation defaults (enforced at the runtime interface, not just policy):
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--memory", memory,
        "--cpus", cpus,
        "--pids-limit", str(pids_limit),
    ]
    if readonly_root:
        args += ["--read-only"]
    if publish_port and container_port:
        mapping = f"127.0.0.1:{int(publish_port)}:{int(container_port)}"
        args.extend(["-p", mapping])
    elif ports:
        for mapping in ports:
            if not _safe_port_mapping(mapping):
                raise DockerOpsError(f"Unsafe port mapping rejected: {mapping}", code="PORT_REJECTED")
            args.extend(["-p", mapping])
    if env:
        for key, value in env.items():
            if not _safe_env_key(key):
                raise DockerOpsError(f"Unsafe env key rejected: {key}", code="ENV_REJECTED")
            # Values from verified plan only; still block newlines
            if "\n" in value or "\r" in value:
                raise DockerOpsError("Env value contains newline", code="ENV_REJECTED")
            args.extend(["-e", f"{key}={value}"])
    if not _safe_image(image):
        raise DockerOpsError(f"Unsafe image rejected: {image}", code="IMAGE_REJECTED")
    args.append(image)
    if command:
        for part in command:
            if not isinstance(part, str) or "\n" in part:
                raise DockerOpsError("Unsafe command rejected", code="CMD_REJECTED")
        args.extend(command)

    proc = _run(args, timeout=120)
    if proc.returncode != 0:
        raise DockerOpsError(
            f"Failed to start {service}: {(proc.stderr or proc.stdout or '').strip()[:500]}",
            code="CONTAINER_START_FAILED",
        )
    return name


def container_running(name: str) -> bool:
    proc = _run(
        ["inspect", "-f", "{{.State.Running}}", name],
        timeout=15,
        check=False,
    )
    return proc.returncode == 0 and (proc.stdout or "").strip().lower() == "true"


def container_state(name: str, *, timeout: float = 15.0) -> dict[str, Any]:
    """Inspect actual container state: liveness, exit code, port bindings.

    Never raises and never fabricates: unavailable containers report
    `available: False` with the daemon's reason. Callers must treat startup
    logs as context only — this state (plus the readiness probe) is the
    health evidence.
    """
    proc = _run(["inspect", name], timeout=timeout, check=False)
    if proc.returncode != 0:
        return {
            "available": False,
            "reason": (proc.stderr or proc.stdout or "").strip()[:200]
            or "inspect failed",
        }
    try:
        data = json.loads(proc.stdout or "")
        info = data[0] if isinstance(data, list) and data else {}
    except (json.JSONDecodeError, IndexError, TypeError):
        return {"available": False, "reason": "unparseable inspect output"}
    if not isinstance(info, dict):
        return {"available": False, "reason": "unparseable inspect output"}
    state = info.get("State") or {}
    ports_raw = (info.get("NetworkSettings") or {}).get("Ports") or {}
    bindings: dict[str, list[dict[str, str]]] = {}
    if isinstance(ports_raw, dict):
        for cport, binds in ports_raw.items():
            if not isinstance(binds, list):
                continue
            bindings[str(cport)] = [
                {"host_ip": str(b.get("HostIp", "")),
                 "host_port": str(b.get("HostPort", ""))}
                for b in binds if isinstance(b, dict)
            ]
    return {
        "available": True,
        "running": bool(state.get("Running", False)),
        "exit_code": state.get("ExitCode", 0),
        "oom_killed": bool(state.get("OOMKilled", False)),
        "started_at": state.get("StartedAt", ""),
        "finished_at": state.get("FinishedAt", ""),
        "error": str(state.get("Error", "") or "")[:200],
        "status": str(state.get("Status", "") or ""),
        "ports": bindings,
    }


def published_host_port(state: dict[str, Any], container_port: int) -> int | None:
    """Host port published for a container port (None when unmapped)."""
    try:
        wanted = int(container_port)
    except (TypeError, ValueError):
        return None
    ports = (state or {}).get("ports") or {}
    if not isinstance(ports, dict):
        return None
    for cport, binds in ports.items():
        try:
            cnum = int(str(cport).split("/")[0])
        except ValueError:
            continue
        if cnum != wanted:
            continue
        for bind in binds if isinstance(binds, list) else []:
            try:
                return int(str((bind or {}).get("host_port", "")))
            except ValueError:
                continue
    return None


def stop_and_remove_container(name: str, *, deployment_id: str) -> bool:
    """Remove container only if it carries MEDHA labels for this deployment."""
    if not _is_medha_owned(name, deployment_id):
        logger.warning("Refusing to remove non-MEDHA or foreign container name=%s", name)
        return False
    proc = _run(["rm", "-f", name], timeout=30, check=False)
    return proc.returncode == 0


def list_medha_containers(deployment_id: str) -> list[str]:
    proc = _run(
        [
            "ps",
            "-a",
            "--filter",
            f"label={LABEL_DEPLOYMENT}={deployment_id}",
            "--format",
            "{{.Names}}",
        ],
        timeout=20,
        check=False,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]


def cleanup_deployment(deployment_id: str) -> dict[str, Any]:
    """Remove only MEDHA-labeled containers/networks for this deployment_id."""
    removed: list[str] = []
    for name in list_medha_containers(deployment_id):
        if stop_and_remove_container(name, deployment_id=deployment_id):
            removed.append(name)
    net = network_name(deployment_id)
    if _network_is_medha(net, deployment_id):
        _run(["network", "rm", net], timeout=20, check=False)
        removed.append(net)
    return {"removed": removed, "deployment_id": deployment_id}


def _is_medha_owned(container_name: str, deployment_id: str) -> bool:
    proc = _run(
        ["inspect", "--format", "{{json .Config.Labels}}", container_name],
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        return False
    try:
        labels = json.loads((proc.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        return False
    return (
        labels.get(LABEL_DEPLOYMENT) == deployment_id
        and labels.get(LABEL_MANAGED) == LABEL_VALUE_MANAGED
    )


def _network_is_medha(name: str, deployment_id: str) -> bool:
    proc = _run(
        ["network", "inspect", "--format", "{{json .Labels}}", name],
        timeout=15,
        check=False,
    )
    if proc.returncode != 0:
        return False
    try:
        labels = json.loads((proc.stdout or "").strip() or "{}")
    except json.JSONDecodeError:
        return False
    return (
        labels.get(LABEL_DEPLOYMENT) == deployment_id
        and labels.get(LABEL_MANAGED) == LABEL_VALUE_MANAGED
    )


def _safe_image(image: str) -> bool:
    if not image or len(image) > 200:
        return False
    # Allow registry/name:tag with limited charset
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-/:")
    return all(ch in allowed for ch in image)


def _safe_port_mapping(mapping: str) -> bool:
    # host:container or container only
    parts = mapping.split(":")
    if len(parts) not in (1, 2):
        return False
    return all(p.isdigit() and 1 <= int(p) <= 65535 for p in parts)


def _safe_env_key(key: str) -> bool:
    if not key or len(key) > 64:
        return False
    return key.replace("_", "").isalnum()


def build_image(*, context_dir: str, dockerfile: str, tag: str, timeout: float = 600) -> str:
    """Build a controlled image; returns the image digest (Id) or tag.

    Purpose-built path (not the generic _run gateway): fixed `docker build`
    shape, no shell, validated tag/dockerfile args. Only MEDHA-generated
    Dockerfiles are ever built — never repository Dockerfiles.
    """
    if not _safe_image(tag):
        raise DockerOpsError(f"Unsafe image tag rejected: {tag}", code="IMAGE_REJECTED")
    if "\n" in dockerfile or "\r" in dockerfile or len(dockerfile) > 500:
        raise DockerOpsError("Unsafe dockerfile path rejected", code="BUILD_REJECTED")
    if not docker_cli_available():
        raise DockerOpsError("Docker CLI not available", code="DOCKER_UNAVAILABLE")
    import subprocess as _sp

    try:
        proc = _sp.run(
            ["docker", "build", "-t", tag, "-f", dockerfile, context_dir],
            capture_output=True, text=True, timeout=timeout, shell=False, check=False,
        )
    except _sp.TimeoutExpired as exc:
        raise DockerOpsError("Image build timed out", code="BUILD_TIMEOUT") from exc
    except OSError as exc:
        raise DockerOpsError(f"Docker CLI error: {exc}", code="OS_ERROR") from exc
    if proc.returncode != 0:
        # Keep both streams and the TAIL: docker logs the failing npm error at
        # the end, so a head-truncated blob hides the real cause.
        combined = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        npm_code = _npm_error_code(combined)
        summary = _tail(combined, 800)
        label = f" (npm {npm_code})" if npm_code else ""
        raise DockerOpsError(
            f"Image build failed{label} (exit={proc.returncode}): {summary}",
            code="BUILD_FAILED",
            log=_tail(combined, 8000),
            exit_code=proc.returncode,
            error_code=npm_code,
            log_truncated=len(combined) > 8000,
        )
    inspect = _run(["inspect", "--format", "{{.Id}}", tag], timeout=30, check=False)
    digest = (inspect.stdout or "").strip() if inspect.returncode == 0 else ""
    return digest or tag


def remove_image(tag: str, *, deployment_id: str) -> bool:
    """Remove only MEDHA-tagged images for this deployment."""
    if short_deployment_id(deployment_id) not in tag:
        logger.warning("Refusing to remove foreign image tag=%s", tag)
        return False
    proc = _run(["rmi", "-f", tag], timeout=60, check=False)
    return proc.returncode == 0


def container_logs(name: str, *, tail: int = 500, timeout: float = 15.0) -> dict[str, Any]:
    """Bounded stdout/stderr retrieval; never raises, never fabricates."""
    try:
        tail_n = max(1, min(int(tail), 2000))
    except (TypeError, ValueError):
        tail_n = 500
    try:
        proc = _run(["logs", "--tail", str(tail_n), name], timeout=timeout, check=False)
    except DockerOpsError as exc:
        return {"available": False, "code": exc.code, "stdout": "", "stderr": ""}
    if proc.returncode != 0:
        return {"available": False, "code": "LOGS_UNAVAILABLE",
                "stdout": "", "stderr": (proc.stderr or "").strip()[:500]}
    # docker logs multiplexes: stdout->stdout, stderr->stderr
    return {"available": True, "stdout": (proc.stdout or "")[-20000:],
            "stderr": (proc.stderr or "")[-20000:]}


def wait_http_readiness(
    port: int, *, host: str = "127.0.0.1", path: str = "/",
    expect_below: int = 500, timeout: float = 60.0,
    interval: float = 2.0, grace: float = 5.0,
) -> dict[str, Any]:
    """Blocking readiness gate: poll until 2xx/3xx/4xx or timeout. Never raises."""
    import time as _time
    import urllib.request

    if host not in {"127.0.0.1", "localhost", "::1"}:
        return {"status": "failed", "reason": "non_loopback_target"}
    deadline = _time.monotonic() + max(1.0, timeout)
    _time.sleep(max(0.0, grace))
    attempts = 0
    last_error = ""
    url = f"http://{host}:{int(port)}{path}"
    while _time.monotonic() < deadline:
        attempts += 1
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:
                code = getattr(resp, "status", 200)
            if code < expect_below:
                return {"status": "ready", "http_status": code, "attempts": attempts,
                        "probe_url": url}
            last_error = f"http_{code}"
        except Exception as exc:  # noqa: BLE001 - readiness polling
            last_error = str(exc)[:150]
        _time.sleep(interval)
    return {"status": "timed_out", "reason": last_error[:200], "attempts": attempts,
            "probe_url": url}


def _run(
    args: list[str],
    *,
    timeout: float = 60,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    if not args or args[0] not in ALLOWED_VERBS:
        raise DockerOpsError(f"Docker verb not allowlisted: {args[:1]}", code="VERB_REJECTED")
    if not docker_cli_available():
        raise DockerOpsError("Docker CLI not available", code="DOCKER_UNAVAILABLE")
    cmd = ["docker", *args]
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DockerOpsError(f"Docker command timed out: {args[0]}", code="TIMEOUT") from exc
    except OSError as exc:
        raise DockerOpsError(f"Docker CLI error: {exc}", code="OS_ERROR") from exc
