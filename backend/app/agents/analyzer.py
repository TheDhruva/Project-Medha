"""Code Analyzer — manifest-focused stack inference (Phase 4)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from app.models.domain import (
    AgentResult,
    ApplicationProfile,
    InferredStack,
    ServiceHint,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def analyze_repository(
    *,
    deployment_id: str,
    repository_url: str,
    workspace_path: Path,
    target_host: str,
    target_port: int,
    intent: str | None = None,
) -> tuple[ApplicationProfile, AgentResult]:
    started = _now()
    root = workspace_path
    examined: list[str] = []
    notes: list[str] = []
    package_managers: list[str] = []
    ports: list[int] = []
    services: list[ServiceHint] = []
    language: str | None = None

    dockerfile = _find_first(root, ["Dockerfile", "dockerfile"])
    compose = _find_first(
        root,
        [
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ],
    )
    package_json = root / "package.json"
    requirements = root / "requirements.txt"
    pyproject = root / "pyproject.toml"
    go_mod = root / "go.mod"

    has_dockerfile = dockerfile is not None
    has_compose = compose is not None
    if has_dockerfile:
        examined.append(str(dockerfile.relative_to(root)))
        ports.extend(_ports_from_dockerfile(dockerfile))
    if has_compose:
        examined.append(str(compose.relative_to(root)))
        compose_services, compose_ports = _parse_compose_lightweight(compose)
        services.extend(compose_services)
        ports.extend(compose_ports)

    if package_json.exists():
        examined.append("package.json")
        package_managers.append("npm")
        language = language or "node"
        pkg_ports = _ports_from_package_json(package_json)
        ports.extend(pkg_ports)
        if not any(s.name == "frontend" for s in services) and not has_compose:
            services.append(
                ServiceHint(
                    name="frontend" if _looks_like_frontend(package_json) else "backend",
                    role="web",
                    evidence_paths=["package.json"],
                    suggested_port=pkg_ports[0] if pkg_ports else target_port,
                )
            )

    if requirements.exists() or pyproject.exists():
        if requirements.exists():
            examined.append("requirements.txt")
            package_managers.append("pip")
        if pyproject.exists():
            examined.append("pyproject.toml")
            package_managers.append("pip")
        language = language or "python"
        if not any(s.role in {"api", "backend"} for s in services) and not has_compose:
            services.append(
                ServiceHint(
                    name="backend",
                    role="api",
                    evidence_paths=[p for p in ["requirements.txt", "pyproject.toml"] if (root / p).exists()],
                    suggested_port=target_port,
                )
            )

    if go_mod.exists():
        examined.append("go.mod")
        package_managers.append("go")
        language = language or "go"

    # Always ensure network + primary app services for planning.
    if not any(s.name == "network" for s in services):
        services.insert(
            0,
            ServiceHint(name="network", role="network", evidence_paths=[], suggested_port=None),
        )

    if not any(s.role in {"api", "backend", "web"} for s in services):
        services.append(
            ServiceHint(
                name="app",
                role="app",
                evidence_paths=examined[:3],
                suggested_port=target_port,
            )
        )
        notes.append("No clear app service detected; added generic app service hint.")

    # Deduplicate ports, prefer target_port first.
    uniq_ports: list[int] = []
    for p in [target_port, *ports]:
        if p and p not in uniq_ports:
            uniq_ports.append(p)

    confidence = 0.4
    if has_dockerfile:
        confidence += 0.2
    if has_compose:
        confidence += 0.25
    if package_managers:
        confidence += 0.1
    confidence = min(0.95, confidence)

    if not examined:
        notes.append("No known manifests found; inference is low confidence.")
        confidence = min(confidence, 0.35)

    stack = InferredStack(
        services=services,
        language_runtime=language,
        has_dockerfile=has_dockerfile,
        has_compose=has_compose,
        package_managers=sorted(set(package_managers)),
        suggested_ports=uniq_ports,
        confidence=confidence,
        manifests_examined=examined,
        notes=notes,
    )
    profile = ApplicationProfile(
        deployment_id=deployment_id,
        repository_url=repository_url,
        workspace_path=str(root),
        intent=intent,
        target_host=target_host,
        target_port=target_port,
        inferred_stack=stack,
        is_demo=False,
    )
    result = AgentResult(
        agent="analyzer",
        ok=True,
        started_at=started,
        finished_at=_now(),
        summary=(
            f"Inferred stack language={language or 'unknown'} "
            f"services={len(services)} confidence={confidence:.2f}"
        ),
        artifacts={"profile": profile.to_public()},
        is_demo=False,
    )
    return profile, result


def _find_first(root: Path, names: list[str]) -> Path | None:
    for name in names:
        path = root / name
        if path.exists() and path.is_file():
            return path
    # Shallow search one level
    for child in root.iterdir() if root.exists() else []:
        if child.is_dir() and child.name not in {".git", "node_modules", ".venv"}:
            for name in names:
                path = child / name
                if path.exists() and path.is_file():
                    return path
    return None


def _ports_from_dockerfile(path: Path) -> list[int]:
    ports: list[int] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ports
    for match in re.finditer(r"^\s*EXPOSE\s+(\d+)", text, flags=re.MULTILINE | re.IGNORECASE):
        ports.append(int(match.group(1)))
    return ports


def _ports_from_package_json(path: Path) -> list[int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    ports: list[int] = []
    scripts = data.get("scripts") or {}
    blob = " ".join(str(v) for v in scripts.values())
    for match in re.finditer(r"(?:PORT|port)=(\d{2,5})", blob):
        ports.append(int(match.group(1)))
    for match in re.finditer(r"--port[=\s]+(\d{2,5})", blob):
        ports.append(int(match.group(1)))
    return ports


def _looks_like_frontend(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    deps = {**(data.get("dependencies") or {}), **(data.get("devDependencies") or {})}
    return any(k in deps for k in ("next", "react", "vue", "vite", "@angular/core"))


def _parse_compose_lightweight(path: Path) -> tuple[list[ServiceHint], list[int]]:
    """Minimal compose parser — no PyYAML dependency required."""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return [], []

    services: list[ServiceHint] = []
    ports: list[int] = []
    current: str | None = None
    in_services = False
    service_indent: int | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        if line.startswith("services:"):
            in_services = True
            continue
        if not in_services:
            continue
        if indent == 0 and line.endswith(":") and not line.startswith("services"):
            # Left services section
            break

        if in_services and line.endswith(":") and not line.startswith("-"):
            name = line[:-1].strip().strip("\"'")
            # service keys are typically indent 2
            if service_indent is None or indent == service_indent or indent <= 2:
                if name in {"build", "image", "ports", "environment", "volumes", "depends_on", "networks"}:
                    continue
                if indent <= 2:
                    service_indent = indent
                    current = name
                    role = "database" if name in {"db", "database", "postgres", "mysql", "mongo"} else "service"
                    if name in {"web", "frontend", "ui"}:
                        role = "web"
                    elif name in {"api", "backend", "app", "server"}:
                        role = "api"
                    services.append(
                        ServiceHint(
                            name=name,
                            role=role,
                            evidence_paths=[path.name],
                        )
                    )
            continue

        if ":" in line and ("ports" in line or line.startswith("-")):
            for match in re.finditer(r"(\d{2,5}):(\d{2,5})", line):
                host_port = int(match.group(1))
                ports.append(host_port)
                if current:
                    for svc in services:
                        if svc.name == current and svc.suggested_port is None:
                            svc.suggested_port = host_port

    return services, ports
