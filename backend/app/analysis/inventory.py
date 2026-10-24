"""Comprehensive, revision-specific repository inventory.

Read-only and bounded: manifests, structure and static configuration only —
repository build instructions and Dockerfiles are never executed. Every
sub-task is isolated (see ``tasks.run_isolated``) so one recoverable failure
never discards the rest of the report. Nothing is reported as "clean" unless a
check actually ran over its intended scope.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.analysis.tasks import (
    COMPLETED_WITH_FINDINGS,
    FAILED,
    PARTIAL,
    SUCCEEDED,
    TIMED_OUT,
    UNAVAILABLE,
    TaskResult,
    dedupe_findings,
    run_isolated,
)
from app.core.repo_files import walk_language_index, walk_inventory_budget

_EMPTY_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist",
     "build", "coverage", ".cache", "vendor", "target", ".idea", ".vscode"}
)
_MAX_FILES = 5000
_MAX_BYTES = 100 * 1024 * 1024
_MAX_READ = 256 * 1024

# Language families for common ecosystems; extensions map to a canonical name.
_EXT_LANG = {
    ".py": "python", ".pyi": "python",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".php": "php", ".cs": "csharp", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".swift": "swift",
    ".sh": "shell", ".sql": "sql", ".html": "html", ".css": "css",
    ".scss": "css", ".vue": "vue", ".svelte": "svelte", ".md": "markdown",
    ".yml": "yaml", ".yaml": "yaml", ".json": "json", ".toml": "toml",
}
# Runtime families the V1 executor has a controlled profile for.
_SUPPORTED_RUNTIMES = frozenset({"static", "python", "node"})


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_READ:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(_read_text(path) or "{}")
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _discover(root: Path) -> TaskResult:
    from app.core.app_discovery import discover_applications

    discovery = discover_applications(root)
    apps = [
        {"path": c.path, "technologies": c.technologies, "evidence": c.evidence}
        for c in discovery.candidates
    ]
    return TaskResult(
        task="discovery",
        status=SUCCEEDED,
        evidence={
            "applications": apps,
            "relationship": discovery.relationship,
            "reason": discovery.reason,
        },
        coverage=f"{len(apps)} application root(s) at depth 0..1",
    )


def _languages(root: Path) -> TaskResult:
    counts, walk_result = walk_language_index(root, walk_inventory_budget(root))
    truncated = walk_result.truncated
    # Map the walk result into the exact same envelope the downstream code
    # expects. counts maps language string (e.g. "python") to file counts.
    languages = sorted(
        ({"language": k, "files": v} for k, v in counts.items()),
        key=lambda x: (-x["files"], x["language"]),
    ) if counts else []
    status = PARTIAL if truncated else SUCCEEDED
    return TaskResult(
        task="languages",
        status=status,
        evidence={
            "languages": languages,
            "totals": {"files": walk_result.total_files, "bytes": walk_result.total_bytes},
            "truncated": truncated,
            "unmapped_extensions": [],  # walker handles all extensions
        },
        coverage=(
            f"scanned {walk_result.total_files} file(s); capped at {_MAX_FILES} files / ~100MB"
            if truncated else f"scanned {walk_result.total_files} file(s)"
        ),
    )


def _commands_for(effective: Path) -> dict[str, str]:
    cmds: dict[str, str] = {}
    pkg = _read_json(effective / "package.json")
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    for key in ("build", "test", "lint", "typecheck", "start", "dev"):
        val = scripts.get(key)
        if isinstance(val, str) and val.strip():
            cmds[key] = f"npm run {key}"
    if (effective / "Makefile").is_file():
        cmds.setdefault("make", "make")
    if (effective / "pyproject.toml").is_file() or (effective / "pytest.ini").is_file():
        cmds.setdefault("test", "pytest")
    return cmds


def _app_detail(root: Path, app: dict[str, Any]) -> dict[str, Any]:
    rel = app.get("path") or "."
    effective = root if rel in ("", ".") else root / rel
    detail = dict(app)
    detail["effective_path"] = rel
    if not effective.is_dir():
        detail["available"] = False
        return detail
    detail["available"] = True
    manifests: list[str] = []
    for name in (
        "package.json", "requirements.txt", "pyproject.toml", "go.mod",
        "Cargo.toml", "pom.xml", "build.gradle", "composer.json", "Gemfile",
        "Dockerfile", "docker-compose.yml", "compose.yml",
    ):
        if (effective / name).is_file():
            manifests.append(name)
    detail["manifests"] = manifests
    detail["lockfiles"] = [
        n for n in ("package-lock.json", "pnpm-lock.yaml", "yarn.lock",
                    "poetry.lock", "Pipfile.lock", "go.sum", "Cargo.lock")
        if (effective / n).is_file()
    ]
    detail["commands"] = _commands_for(effective)
    entry_points: list[str] = []
    pkg = _read_json(effective / "package.json")
    main = pkg.get("main")
    if isinstance(main, str) and main:
        entry_points.append(f"package.json:main={main[:120]}")
    for cand in ("app.py", "main.py", "server.py", "manage.py", "index.html",
                 "src/index.ts", "src/main.ts", "src/index.js", "src/main.js"):
        if (effective / cand).is_file():
            entry_points.append(cand)
    detail["entry_points"] = entry_points[:10]
    detail["env_names"] = _env_names(effective)[:30]
    return detail


def _env_names(root: Path) -> list[str]:
    """Environment variable NAMES only — never values."""
    names: set[str] = set()
    for cand in (".env.example", ".env.sample", ".env.template"):
        text = _read_text(root / cand)
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key = line.split("=", 1)[0].strip()
            if key and key.replace("_", "").isalnum():
                names.add(key)
    compose = _find(root, ["docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"])
    if compose is not None:
        text = _read_text(compose)
        import re

        for m in re.finditer(r"^\s*-\s*([A-Za-z_][A-Za-z0-9_]*)\s*[=:]", text, re.MULTILINE):
            names.add(m.group(1))
    return sorted(names)


def _find(root: Path, names: list[str]) -> Path | None:
    for name in names:
        p = root / name
        if p.is_file():
            return p
    return None


def _container_evidence(root: Path) -> TaskResult:
    dockerfiles: list[str] = []
    composes: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EMPTY_DIRS]
        try:
            depth = len(Path(dirpath).relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth > 2:
            dirnames[:] = []
            continue
        for fn in filenames:
            rel = str((Path(dirpath) / fn).relative_to(root)).replace("\\", "/")
            low = fn.lower()
            if low == "dockerfile" or low.startswith("dockerfile."):
                dockerfiles.append(rel)
            elif low in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"):
                composes.append(rel)
    return TaskResult(
        task="container",
        status=SUCCEEDED,
        evidence={
            "dockerfiles": sorted(set(dockerfiles))[:20],
            "compose_files": sorted(set(composes))[:20],
            "note": "Static evidence only; repository build instructions are never executed.",
        },
    )


def _config_files(root: Path) -> TaskResult:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EMPTY_DIRS]
        try:
            depth = len(Path(dirpath).relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth > 1:
            dirnames[:] = []
            continue
        for fn in filenames:
            low = fn.lower()
            if low in (".env.example", ".env.sample", ".env.template", "pytest.ini",
                       "tox.ini", "setup.cfg", "tsconfig.json", ".eslintrc",
                       ".eslintrc.json", ".eslintrc.js", ".prettierrc", "ruff.toml",
                       "mypy.ini", "jest.config.js", "vitest.config.ts", "next.config.js",
                       "next.config.mjs"):
                found.append(str((Path(dirpath) / fn).relative_to(root)).replace("\\", "/"))
    return TaskResult(
        task="config_files",
        status=SUCCEEDED,
        evidence={"config_files": sorted(set(found))[:40]},
    )


def _scanner_task(name: str, target: Path, timeout_s: float) -> TaskResult:
    from app.security import scanners

    res = scanners.run_scanner(name, target, timeout_s=timeout_s)
    status_map = {
        scanners.CLEAN: SUCCEEDED,
        scanners.FINDINGS: COMPLETED_WITH_FINDINGS,
        scanners.UNAVAILABLE: UNAVAILABLE,
        scanners.FAILED: FAILED,
    }
    findings = []
    for f in res.findings:
        findings.append(
            {
                "source": f"scanner:{name}",
                "scanner": name,
                "rule_id": f.rule_id,
                "severity": f.severity,
                "path": f.path,
                "line": f.line,
                "message": f.message,
            }
        )
    return TaskResult(
        task=f"security:{name}",
        status=status_map.get(res.status, FAILED),
        evidence={"scanner": name, "scanner_status": res.status, "message": res.message},
        findings=findings,
        duration_ms=round(res.duration_s * 1000.0, 1),
        coverage=f"scanner '{name}' over {target.name or target}",
    )


def build_repository_inventory(
    workspace_path: str | Path,
    *,
    commit_sha: str | None = None,
    selected_target: str | None = None,
    scan_security: bool = True,
    scanner_timeout_s: float = 120.0,
    scanner_names: list[str] | None = None,
) -> dict[str, Any]:
    """Build the consolidated, revision-scoped repository analysis report."""
    root = Path(workspace_path)
    if not root.is_dir():
        return {
            "schema": "repository-analysis/v1",
            "analysis_status": FAILED,
            "commit_sha": commit_sha,
            "error": f"workspace unavailable: {root}",
            "tasks": [],
            "applications": [],
            "languages": [],
            "findings": [],
            "coverage": {"gaps": ["workspace unavailable"]},
        }

    tasks: list[TaskResult] = []
    discovery = run_isolated("discovery", lambda: _discover(root), timeout_s=30.0)
    tasks.append(discovery)
    languages = run_isolated("languages", lambda: _languages(root), timeout_s=60.0)
    tasks.append(languages)
    container = run_isolated("container", lambda: _container_evidence(root), timeout_s=30.0)
    tasks.append(container)
    config_files = run_isolated("config_files", lambda: _config_files(root), timeout_s=30.0)
    tasks.append(config_files)

    apps_raw = discovery.evidence.get("applications", []) if discovery.status != FAILED else []
    details: list[dict[str, Any]] = []
    for app in apps_raw:
        res = run_isolated(
            f"application:{app.get('path', '?')}",
            lambda a=app: TaskResult(
                task=f"application:{a.get('path', '?')}",
                status=SUCCEEDED,
                evidence={"application": _app_detail(root, a)},
            ),
            timeout_s=30.0,
        )
        tasks.append(res)
        if res.status == SUCCEEDED:
            details.append(res.evidence["application"])
        else:
            # Keep the discovered candidate even when its detail task failed.
            details.append({**app, "available": False, "detail_error": res.error})

    findings: list[dict[str, Any]] = []
    if scan_security:
        from app.security import scanners

        names = scanner_names if scanner_names is not None else scanners.supported_scanners()
        scope = root
        if selected_target and selected_target not in (".", "") and (root / selected_target).is_dir():
            scope = root / selected_target
        for name in names:
            st = run_isolated(
                f"security:{name}",
                lambda n=name: _scanner_task(n, scope, scanner_timeout_s),
                timeout_s=scanner_timeout_s + 10.0,
            )
            tasks.append(st)
            findings.extend(st.findings)

    findings = dedupe_findings(findings)

    # Security coverage is tracked separately from the aggregate: an absent
    # optional scanner is a coverage limitation, never a clean result, and
    # never downgrades the aggregate of tasks that actually ran.
    security_tasks = [t for t in tasks if t.task.startswith("security:")]
    scanners = [
        {"name": t.task.split(":", 1)[1], "status": t.status,
         "error": t.error, "duration_ms": t.duration_ms}
        for t in security_tasks
    ]
    scanners_ran = [s["name"] for s in scanners if s["status"] in {SUCCEEDED, COMPLETED_WITH_FINDINGS}]
    scanners_failed = [s["name"] for s in scanners if s["status"] in {FAILED, TIMED_OUT}]
    if not security_tasks:
        security_scan = "not_requested"
    elif scanners_ran and not scanners_failed and len(scanners_ran) == len(security_tasks):
        security_scan = "complete"
    elif scanners_ran:
        security_scan = "partial"
    else:
        security_scan = "none"

    gaps: list[str] = []
    if languages.status == PARTIAL:
        gaps.append("file/language scan was truncated at the safety cap")
    if discovery.status == FAILED or not apps_raw:
        gaps.append("no application roots discovered")
    for t in tasks:
        if t.status in {FAILED, TIMED_OUT, UNAVAILABLE, PARTIAL}:
            gaps.append(f"{t.task}: {t.status}" + (f" ({t.error})" if t.error else ""))
    if security_scan == "none":
        gaps.append("no security scanner executed; security coverage is unknown")
    # Unsupported runtime families present in the tree.
    langs = {l["language"] for l in languages.evidence.get("languages", [])}
    runtime_map = {"javascript": "node", "typescript": "node", "vue": "node", "svelte": "node",
                   "python": "python", "html": "static"}
    if not langs & {"python", "javascript", "typescript", "html", "vue", "svelte"}:
        gaps.append("no files in the supported static/python/node families were found")

    has_runtime = bool(langs & {"python", "javascript", "typescript"}) or "html" in langs
    # Aggregate reflects only tasks that were applicable and actually ran: an
    # optional, absent scanner is recorded as UNAVAILABLE and as a coverage
    # gap, but does not make an otherwise-complete analysis look stopped.
    fatal = discovery.status == FAILED and not apps_raw
    if fatal:
        analysis_status = FAILED
    elif any(t.status in {FAILED, TIMED_OUT, PARTIAL} for t in tasks):
        analysis_status = PARTIAL
    else:
        analysis_status = "completed"

    return {
        "schema": "repository-analysis/v1",
        "analysis_status": analysis_status,
        "commit_sha": commit_sha,
        "selected_target": selected_target,
        "applications": details,
        "relationship": discovery.evidence.get("relationship") if discovery.status != FAILED else None,
        "languages": languages.evidence.get("languages", []),
        "totals": languages.evidence.get("totals", {}),
        "env_names": sorted({n for d in details for n in d.get("env_names", [])}),
        "container": container.evidence if container.status != FAILED else {},
        "config_files": config_files.evidence.get("config_files", []),
        "tasks": [t.to_dict() for t in tasks],
        "findings": findings,
        "finding_count": len(findings),
        "scanners": scanners,
        "coverage": {
            "gaps": gaps,
            "supported_runtime_present": has_runtime,
            "security_scan": security_scan,
            "scanner_scope": str(scope.relative_to(root)) if scope != root else ".",
        },
        "notes": [
            "Static, read-only analysis. Repository Dockerfiles/build commands are "
            "recorded as evidence and never executed.",
            "Scanner findings are separate from scan execution status; an "
            "unavailable scanner is not a clean result.",
        ],
    }
