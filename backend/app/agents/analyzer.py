"""Code Analyzer — manifest-focused stack inference (Phase 4)."""

from __future__ import annotations

import json
import os
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


def build_repository_intelligence(
    profile: ApplicationProfile,
    *,
    commit_sha: str | None,
    repository_url: str | None = None,
) -> dict:
    """Evidence-backed Repository Intelligence from an analyzed revision.

    Deterministic only: every claim cites analyzer evidence (manifest paths,
    entry points, detected services). No LLM, no secret values — env names
    only. Stored on the run result payload (no schema change) and served via
    GET /api/deploy/{id}/repository-intelligence.
    """
    stack = profile.inferred_stack
    services = [
        {
            "name": s.name,
            "role": s.role,
            "evidence_paths": list(s.evidence_paths or []),
            "suggested_port": s.suggested_port,
        }
        for s in (stack.services or [])
    ]
    # Proposed deployment approach mirrors the isolated RealExecutor support
    # matrix (static → nginx, python → uvicorn/gunicorn, node → npm/node)
    # without executing anything: evidence only.
    language = (stack.language_runtime or "").lower()
    _manifests = list(stack.manifests_examined or [])
    if "index.html" in _manifests or "dist/index.html" in _manifests:
        approach, approach_evidence = "static", [
            m for m in _manifests if m in ("index.html", "dist/index.html")
        ] or ["index.html at checkout root"]
    elif language == "node" or "npm" in (stack.package_managers or []):
        approach, approach_evidence = "node", ["package.json with start script"]
    elif language == "python" and any(
        ep.endswith(".py") for ep in (stack.entry_points or [])
    ):
        approach, approach_evidence = "python", [
            *(stack.entry_points or []),
            *[m for m in (stack.manifests_examined or []) if m in ("requirements.txt", "pyproject.toml")],
        ]
    elif language == "python" or any(
        m in ("requirements.txt", "pyproject.toml") for m in (stack.manifests_examined or [])
    ):
        # Dependency manifests without a web entrypoint are not a
        # deployable application — no python approach is proposed.
        approach, approach_evidence = "undecided", [
            *(stack.entry_points or []),
            *[m for m in (stack.manifests_examined or []) if m in ("requirements.txt", "pyproject.toml")],
            "dependency manifests only — no web entrypoint detected",
        ]
    elif stack.has_dockerfile or stack.has_compose:
        approach, approach_evidence = "undecided-containerized", list(stack.manifests_examined or [])
    else:
        approach, approach_evidence = "undecided", list(stack.manifests_examined or [])
    unknowns: list[str] = []
    if not stack.entry_points:
        unknowns.append("No explicit application entrypoint detected in manifests.")
    if not stack.health_hints:
        unknowns.append("No health-check hint found; readiness probes GET / by default.")
    if (stack.app_relationship or "") == "monorepo" and not stack.selected_target:
        unknowns.append("Multiple applications detected without an explicit deployment target.")
    assumptions = [
        f"Inferred from manifests: {', '.join(stack.manifests_examined or ['none'])}.",
        "Repository Dockerfiles are never executed; MEDHA uses controlled build templates.",
    ]
    unsupported: list[str] = []
    if language and language not in ("node", "python", "static", ""):
        unsupported.append(f"Language runtime '{stack.language_runtime}' is outside the static/python/node matrix.")
    return {
        "schema": "repository-intelligence/v1",
        "repository_url": repository_url or profile.repository_url,
        "commit_sha": commit_sha,
        "purpose": profile.intent or "Deploy the analyzed application revision.",
        "tech_stack": {
            "language_runtime": stack.language_runtime,
            "framework": stack.framework,
            "framework_version": stack.framework_version,
            "package_managers": list(stack.package_managers or []),
            "lockfiles": list(stack.lockfiles or []),
        },
        "components": services,
        "entry_points": list(stack.entry_points or []),
        "build_command": None,
        "start_command": None,
        "runtime_requirements": {
            "suggested_ports": list(stack.suggested_ports or []),
            "env_names": list(stack.env_names or []),
            "health_hints": list(stack.health_hints or []),
        },
        "existing_deploy_config": {
            "has_dockerfile": stack.has_dockerfile,
            "has_compose": stack.has_compose,
            "manifests_examined": list(stack.manifests_examined or []),
            "ci_configs": list(stack.ci_configs or []),
        },
        "proposed_approach": approach,
        "approach_evidence": approach_evidence,
        "unknowns": unknowns,
        "assumptions": assumptions,
        "confidence": stack.confidence,
        "unsupported": unsupported,
        "notes": list(stack.notes or []),
    }


def analyze_repository(
    *,
    deployment_id: str,
    repository_url: str,
    workspace_path: Path,
    target_host: str,
    target_port: int,
    intent: str | None = None,
    deploy_target: str | None = None,
) -> tuple[ApplicationProfile, AgentResult]:
    started = _now()
    root = workspace_path
    # Honest failure instead of an empty successful profile: without a
    # readable workspace there is nothing to infer from.
    if not root.is_dir():
        raise RuntimeError(f"Analysis workspace is not available: {root}")
    from app.core.app_discovery import discover_applications

    discovery = discover_applications(root)
    app_candidates = [c.path for c in discovery.candidates]
    candidate_details = [
        {"path": c.path, "technologies": c.technologies, "evidence": c.evidence}
        for c in discovery.candidates
    ]
    # Explicit target wins; a lone subdir application is selected
    # automatically (Case A). Genuine multi-app repos keep root scope so the
    # support gate can require an explicit target with full candidate detail.
    selected_target: str | None = None
    effective = root
    raw_target = (deploy_target or "").strip().replace("\\", "/").strip("/")
    normalized_target = raw_target
    if raw_target == "." and "." in app_candidates:
        # Explicit root selection: the checkout root itself is a detected
        # application alongside subdirectories. Scope stays root, marked.
        selected_target = "."
        normalized_target = "."
    elif raw_target not in {"", "."}:
        if normalized_target not in app_candidates:
            raise ValueError(
                f"INVALID_DEPLOYMENT_TARGET: '{normalized_target}' is not a detected "
                f"application ({', '.join(app_candidates) or 'none'})."
            )
        scoped = root / normalized_target
        if not scoped.is_dir():
            raise ValueError(
                f"INVALID_DEPLOYMENT_TARGET: '{normalized_target}' is not available in this checkout."
            )
        selected_target = normalized_target
        effective = scoped
    elif len(app_candidates) == 1 and app_candidates[0] != ".":
        selected_target = app_candidates[0]
        scoped = root / app_candidates[0]
        if scoped.is_dir():
            effective = scoped
    examined: list[str] = []
    notes: list[str] = []
    package_managers: list[str] = []
    ports: list[int] = []
    services: list[ServiceHint] = []
    language: str | None = None
    lockfiles: list[str] = []
    entry_points: list[str] = []
    env_names: list[str] = []
    health_hints: list[str] = []
    framework: str | None = None
    framework_version: str | None = None
    if selected_target:
        notes.append(f"Deployment target '{selected_target}' selected for analysis.")

    dockerfile = _find_first(effective, ["Dockerfile", "dockerfile"])
    compose = _find_first(
        effective,
        [
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
        ],
    )
    package_json = effective / "package.json"
    requirements = effective / "requirements.txt"
    pyproject = effective / "pyproject.toml"
    go_mod = effective / "go.mod"
    # Static-site evidence (matches the isolated RealExecutor `static`
    # profile): an index.html at the effective root is deployable via the
    # controlled nginx template — record it as first-class evidence instead
    # of reporting "no known manifests".
    index_html = effective / "index.html"
    dist_index = effective / "dist" / "index.html"
    static_docroot: str | None = None
    if index_html.is_file():
        static_docroot = "index.html"
    elif dist_index.is_file():
        static_docroot = "dist/index.html"
    if static_docroot is not None:
        examined.append(static_docroot)
        language = language or "static"
        entry_points.append(static_docroot)
        health_hints.append("/")
        services.append(
            ServiceHint(
                name="frontend",
                role="web",
                evidence_paths=[static_docroot],
                suggested_port=target_port,
            )
        )
        notes.append(f"Static site detected via {static_docroot} (nginx profile).")

    has_dockerfile = dockerfile is not None
    has_compose = compose is not None
    if has_dockerfile:
        examined.append(str(dockerfile.relative_to(effective)))
        ports.extend(_ports_from_dockerfile(dockerfile))
    if has_compose:
        examined.append(str(compose.relative_to(effective)))
        compose_services, compose_ports = _parse_compose_lightweight(compose)
        services.extend(compose_services)
        ports.extend(compose_ports)

    if package_json.exists():
        examined.append("package.json")
        _pm_notes = _node_package_manager_notes(effective, package_json)
        for _pm in _pm_notes[0]:
            if _pm not in package_managers:
                package_managers.append(_pm)
        notes.extend(_pm_notes[1])
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
        # Python package manifests are language/dependency evidence only: a
        # deployable backend requires an actual web entrypoint module (the
        # runtime spec enforces the same rule as defense-in-depth).
        python_web_entry = _python_web_entry(effective)
        if (
            python_web_entry
            and not any(s.role in {"api", "backend"} for s in services)
            and not has_compose
        ):
            services.append(
                ServiceHint(
                    name="backend",
                    role="api",
                    evidence_paths=[
                        p
                        for p in (
                            "requirements.txt",
                            "pyproject.toml",
                            python_web_entry,
                        )
                        if p and (effective / p).exists()
                    ],
                    suggested_port=target_port,
                )
            )

    if go_mod.exists():
        examined.append("go.mod")
        package_managers.append("go")
        language = language or "go"

    evidence = _gather_evidence(effective, examined)
    lockfiles = evidence["lockfiles"]
    entry_points = evidence["entry_points"]
    env_names = evidence["env_names"]
    health_hints = evidence["health_hints"]
    if evidence["framework"] is not None:
        framework, framework_version = evidence["framework"]
        notes.append(
            f"Framework evidence: {framework}"
            f"{(' ' + framework_version) if framework_version else ''} "
            f"({evidence['framework_source']})."
        )
    if evidence["framework_conflict"]:
        notes.append(
            f"Conflicting framework evidence ({evidence['framework_conflict']}); "
            "no framework assumed."
        )
    for hint in evidence.get("perf_notes", []):
        notes.append(hint)
    for cli in evidence.get("cli_evidence", []):
        notes.append(
            f"CLI script declared ({cli}) — CLI evidence, not a web entrypoint."
        )
    if evidence.get("ci_configs"):
        notes.append(f"CI configuration: {', '.join(evidence['ci_configs'][:3])}.")
    if evidence.get("test_suites"):
        notes.append(f"Test suites: {len(evidence['test_suites'])} file(s) detected.")
    if evidence.get("auth_hints"):
        notes.append(f"Auth-sensitive modules: {', '.join(evidence['auth_hints'][:3])}.")
    if evidence.get("db_hints"):
        notes.append(f"DB/migration hints: {', '.join(evidence['db_hints'][:3])}.")
    if evidence.get("openapi_hints"):
        notes.append(f"OpenAPI hints: {', '.join(evidence['openapi_hints'][:3])}.")
    if len(app_candidates) > 1 and not selected_target:
        if discovery.relationship == "fullstack":
            notes.append(
                "Related frontend and backend detected "
                f"({', '.join(app_candidates)}); V1 deploys one service at a time — "
                "choose an explicit deployment target to continue."
            )
        else:
            notes.append(
                "Multiple applications detected "
                f"({', '.join(app_candidates)}); automatic selection is ambiguous."
            )

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
    if static_docroot is not None:
        confidence += 0.25
    if package_managers:
        confidence += 0.1
    if lockfiles:
        confidence += 0.05
    if entry_points:
        confidence += 0.05
    if len(app_candidates) > 1 and not selected_target:
        # Ambiguity must reduce confidence so the supportability gate blocks.
        confidence -= 0.2
    confidence = min(0.95, max(0.1, confidence))

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
        framework=framework,
        framework_version=framework_version,
        lockfiles=sorted(set(lockfiles)),
        entry_points=entry_points[:10],
        env_names=sorted(set(env_names))[:30],
        health_hints=health_hints[:10],
        app_candidates=app_candidates[:10],
        app_candidate_details=candidate_details[:10],
        app_relationship=discovery.relationship,
        selected_target=selected_target,
        ci_configs=evidence.get("ci_configs", []),
        test_suites=evidence.get("test_suites", []),
        auth_hints=evidence.get("auth_hints", []),
        openapi_hints=evidence.get("openapi_hints", []),
        db_hints=evidence.get("db_hints", []),
        perf_notes=evidence.get("perf_notes", []),
        source_file_count=evidence.get("source_file_count"),
        source_bytes_approx=evidence.get("source_bytes_approx"),
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


def _node_package_manager_notes(
    effective: Path, package_json: Path,
) -> tuple[list[str], list[str]]:
    """Package-manager evidence shared with the runtime selector.

    Best-effort and total: analysis never fails on strange manifests; a
    conflict is recorded as an explicit note (the executor fails closed
    with the diagnostic later).
    """
    try:
        pkg = json.loads(package_json.read_text(encoding="utf-8"))
        if not isinstance(pkg, dict):
            return ["npm"], ["package.json is not valid JSON; assuming npm."]
        from app.execution.runtime import select_package_manager as _select

        pm, pinned, evidence, found, conflict = _select(effective, pkg)
        managers = [pm] if pm else list(found)
        notes = [f"Package manager: {line}." for line in evidence[:4]]
        if pinned and pm:
            notes.append(f"Pinned {pm}@{pinned} via packageManager.")
        if conflict:
            notes.append(f"Package-manager conflict: {conflict}")
            return managers or ["npm"], notes
        return managers or ["npm"], notes
    except Exception:  # noqa: BLE001 - evidence only, never block analysis
        return ["npm"], ["Package-manager evidence unreadable; assuming npm."]


def _python_web_entry(root: Path) -> str | None:
    """Web-entrypoint evidence for a Python checkout (relative file path).

    A dependency manifest alone never names a web application; only an
    actual entrypoint module (app/main/wsgi/asgi/server, including nested
    ``app/main.py`` / ``src/main.py`` layouts) does. Returns the relative
    path (e.g. ``app/main.py``) for evidence, or None.
    """
    from app.core.app_discovery import find_python_web_entry

    entry = find_python_web_entry(root)
    return entry.path if entry else None


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


# --- Evidence gathering (read-only, bounded; never executes repo code) ---

_MAX_READ_BYTES = 256 * 1024
_MAX_SCAN_FILES = 2000
_MAX_SCAN_BYTES = 50 * 1024 * 1024
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build"}


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_READ_BYTES:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _gather_evidence(root: Path, examined: list[str]) -> dict:
    """Collect lockfiles, frameworks, entry points, env names, health hints.

    Only names and versions are recorded — never secret values. Files are
    read with a size cap and never executed.
    """
    lockfiles: list[str] = []
    entry_points: list[str] = []
    env_names: list[str] = []
    health_hints: list[str] = []
    framework: tuple[str, str | None] | None = None
    framework_source = ""
    framework_conflict = ""

    for name in (
        "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
        "poetry.lock", "Pipfile.lock", "go.sum",
    ):
        if (root / name).is_file():
            lockfiles.append(name)
            examined.append(name)

    pkg_path = root / "package.json"
    if pkg_path.is_file():
        try:
            data = json.loads(_read_text(pkg_path) or "{}")
        except ValueError:
            data = {}
        deps = {}
        for key in ("dependencies", "devDependencies"):
            section = data.get(key)
            if isinstance(section, dict):
                deps.update(section)
        for cand, source in (
            ("next", "package.json:dependencies"),
            ("nuxt", "package.json:dependencies"),
            ("@nestjs/core", "package.json:dependencies"),
            ("express", "package.json:dependencies"),
            ("fastify", "package.json:dependencies"),
            ("koa", "package.json:dependencies"),
        ):
            if cand in deps:
                framework = (cand.lstrip("@").split("/")[0], str(deps[cand])[:24])
                framework_source = source
                break
        if framework is None and any(k in deps for k in ("react", "vue", "@angular/core")):
            lib = next(k for k in ("react", "vue", "@angular/core") if k in deps)
            framework = (lib.lstrip("@").split("/")[0], str(deps[lib])[:24])
            framework_source = "package.json:dependencies (client library; server entrypoint unresolved)"
        scripts = data.get("scripts")
        if isinstance(scripts, dict):
            if scripts.get("start"):
                entry_points.append(f"package.json:scripts.start={str(scripts['start'])[:120]}")
            for key in scripts:
                if "health" in str(key).lower():
                    health_hints.append(f"package.json:scripts.{key}")
        main = data.get("main")
        if isinstance(main, str) and main:
            entry_points.append(f"package.json:main={main[:120]}")

    req_text = _read_text(root / "requirements.txt")
    pyproject_text = _read_text(root / "pyproject.toml")
    combined_py = f"{req_text}\n{pyproject_text}".lower()
    cli_evidence: list[str] = []
    if req_text or pyproject_text:
        found = [name for name in ("fastapi", "django", "flask") if name in combined_py]
        if len(found) == 1:
            framework = (found[0], _version_hint(combined_py, found[0]))
            framework_source = "requirements.txt/pyproject.toml"
        elif len(found) > 1:
            framework_conflict = ", ".join(sorted(found))
        from app.core.app_discovery import find_python_web_entry as _py_entry

        py_entry = _py_entry(root)
        if py_entry:
            # Web-entrypoint evidence — the same rule the runtime spec
            # validates before execution.
            entry_points.append(py_entry.path)
        try:
            import re as _re

            scripts = _re.findall(r"\[project\.scripts\](.*?)(?:^\[|\Z)", pyproject_text,
                                  flags=_re.MULTILINE | _re.DOTALL)
            for block in scripts:
                for line in block.splitlines():
                    if "=" in line and not line.strip().startswith("#"):
                        # [project.scripts] declares CLI commands, not a
                        # web-server entrypoint — never positive deploy
                        # confidence.
                        cli_evidence.append(
                            f"pyproject:[project.scripts] {line.strip()[:120]}"
                        )
        except (OSError, ValueError):
            pass

    go_text = _read_text(root / "go.mod")
    if go_text and framework is None and not framework_conflict:
        import re as _re

        mod = _re.search(r"^module\s+(\S+)", go_text, flags=_re.MULTILINE)
        gov = _re.search(r"^go\s+(\S+)", go_text, flags=_re.MULTILINE)
        if mod:
            framework = ("go-module", gov.group(1) if gov else None)
            framework_source = "go.mod"

    dockerfile = _find_first(root, ["Dockerfile", "dockerfile"])
    if dockerfile is not None:
        text = _read_text(dockerfile)
        import re as _re

        for match in _re.finditer(r"^\s*(?:CMD|ENTRYPOINT)\s+(.+)$", text,
                                  flags=_re.MULTILINE | re.IGNORECASE):
            entry_points.append(f"Dockerfile:{match.group(0).strip()[:120]}")
        for match in _re.finditer(r"^\s*ENV\s+([A-Za-z_][A-Za-z0-9_]*)", text,
                                  flags=_re.MULTILINE):
            env_names.append(match.group(1))
        if _re.search(r"^\s*HEALTHCHECK\s+", text, flags=_re.MULTILINE | re.IGNORECASE):
            health_hints.append("Dockerfile:HEALTHCHECK")

    compose = _find_first(
        root,
        ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"],
    )
    if compose is not None:
        text = _read_text(compose)
        import re as _re

        if _re.search(r"healthcheck\s*:", text, flags=_re.IGNORECASE):
            health_hints.append(f"{compose.name}:healthcheck")
        in_env = False
        for raw_line in text.splitlines()[:400]:
            stripped = raw_line.strip()
            if _re.match(r"(?i)^environment\s*:", stripped):
                in_env = True
                continue
            if in_env:
                if not stripped or stripped.startswith("#"):
                    continue
                item = _re.match(r"^-\s*([A-Za-z_][A-Za-z0-9_]*)\s*[=:]", stripped)
                plain = _re.match(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:", stripped)
                if item:
                    env_names.append(item.group(1))
                    continue
                if plain and not stripped.startswith("-"):
                    env_names.append(plain.group(1))
                    continue
                if stripped and not raw_line.startswith((" ", "\t")):
                    in_env = False

    procfile = root / "Procfile"
    if procfile.is_file():
        for line in _read_text(procfile).splitlines()[:20]:
            if line.strip().lower().startswith("web:"):
                entry_points.append(f"Procfile:{line.strip()[:120]}")

    # --- Bounded supplemental evidence (CI, tests, auth, OpenAPI, DB, budgets) ---
    ci_configs: list[str] = []
    test_suites: list[str] = []
    auth_hints: list[str] = []
    openapi_hints: list[str] = []
    db_hints: list[str] = []
    perf_notes: list[str] = []
    file_count = 0
    byte_total = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            # Keep depth shallow (root + 2 levels) for the budget scan.
            try:
                depth = len(Path(dirpath).relative_to(root).parts)
            except ValueError:
                depth = 0
            if depth > 2:
                dirnames[:] = []
                continue
            for fn in filenames:
                if file_count >= _MAX_SCAN_FILES or byte_total >= _MAX_SCAN_BYTES:
                    break
                file_count += 1
                fpath = Path(dirpath) / fn
                try:
                    byte_total += fpath.stat().st_size
                except OSError:
                    continue
                rel = str(fpath.relative_to(root))
                low = rel.lower()
                if low in (".github/workflows/ci.yml", ".github/workflows/ci.yaml") or low.startswith(".github/workflows/"):
                    if fn.endswith((".yml", ".yaml")) and "workflow" in low:
                        ci_configs.append(rel[:160])
                elif low in ("jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml"):
                    ci_configs.append(rel[:160])
                elif low in ("openapi.json", "openapi.yaml", "openapi.yml", "swagger.json", "swagger.yaml"):
                    openapi_hints.append(rel[:160])
                elif low.startswith("migrations/") or low.startswith("migrate/") or "alembic" in low:
                    db_hints.append(rel[:160])
                if fn in ("pytest.ini", "tox.ini") or low.startswith("tests/") or low.startswith("test/") or fn.startswith("test_") and fn.endswith(".py"):
                    if rel not in test_suites:
                        test_suites.append(rel[:160])
                if fn == "package.json":
                    pass  # already examined
                elif "auth" in low and fn.endswith((".py", ".ts", ".js")):
                    auth_hints.append(rel[:160])
            if file_count >= _MAX_SCAN_FILES or byte_total >= _MAX_SCAN_BYTES:
                break
    except OSError:
        pass
    # Auth-sensitive filenames at root level (bounded, names only).
    for name in ("auth.py", "auth.ts", "users.py", "login.py", "session.py", "oauth.py"):
        if (root / name).is_file() and f"{name}" not in auth_hints:
            auth_hints.append(name)
    # OpenAPI references inside package manifests (names only).
    if "swagger" in combined_py or "openapi" in combined_py:
        openapi_hints.append("requirements.txt/pyproject.toml:openapi-reference")
    for marker in ("alembic", "migrate", "schema.sql", "prisma"):
        if marker in combined_py and marker not in " ".join(db_hints):
            db_hints.append(f"python-deps:{marker}")
    if file_count >= _MAX_SCAN_FILES:
        perf_notes.append(f"Source scan capped at {_MAX_SCAN_FILES} files; results are partial.")
    if byte_total >= _MAX_SCAN_BYTES:
        perf_notes.append("Source scan capped at ~50MB; results are partial.")

    return {
        "lockfiles": lockfiles,
        "entry_points": entry_points,
        "cli_evidence": cli_evidence[:10],
        "env_names": env_names,
        "health_hints": health_hints,
        "framework": framework,
        "framework_source": framework_source,
        "framework_conflict": framework_conflict,
        "ci_configs": sorted(set(ci_configs))[:10],
        "test_suites": sorted(set(test_suites))[:20],
        "auth_hints": sorted(set(auth_hints))[:20],
        "openapi_hints": sorted(set(openapi_hints))[:10],
        "db_hints": sorted(set(db_hints))[:10],
        "perf_notes": perf_notes[:5],
        "source_file_count": file_count,
        "source_bytes_approx": byte_total,
    }


def _version_hint(text: str, name: str) -> str | None:
    import re as _re

    match = _re.search(rf"{re.escape(name)}\s*([=<>!~]+\s*[^,;\s]+)?", text, flags=_re.IGNORECASE)
    if match and match.group(1):
        return match.group(1).strip()[:24]
    return None


def _detect_app_candidates(root: Path) -> list[str]:
    """Legacy entry point — delegates to centralized discovery."""
    from app.core.app_discovery import discover_applications

    return [c.path for c in discover_applications(root).candidates]
