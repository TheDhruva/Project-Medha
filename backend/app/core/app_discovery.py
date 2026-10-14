"""Centralized application discovery and classification (V1).

One authoritative heuristic set shared by the analyzer and the support
gate. Read-only, bounded, deterministic: manifests and repository
structure only — never executes repository code, never follows symlinks
out of the checkout, never scans dependency/build/cache directories.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = frozenset({
    ".git", "node_modules", ".venv", "venv", "__pycache__", ".next",
    "dist", "build", "coverage", ".cache", "vendor", "target", ".idea",
    ".vscode",
})

_MAX_CHILDREN = 20
_MAX_READ_BYTES = 256 * 1024

_FRONTEND_DEPS = frozenset({
    "next", "nuxt", "react", "vue", "vite", "@angular/core",
    "react-scripts", "astro", "svelte", "solid-js",
})
_BACKEND_PY_MARKERS = ("fastapi", "django", "flask", "starlette")
_BACKEND_NODE_MARKERS = ("express", "fastify", "koa", "@nestjs/core", "hono")


@dataclass
class AppCandidate:
    path: str  # "." for root, else relative posix path
    technologies: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    is_frontend: bool = False
    is_backend: bool = False


@dataclass
class DiscoveryResult:
    candidates: list[AppCandidate] = field(default_factory=list)
    relationship: str = "none"  # none|single|fullstack|monorepo
    reason: str = ""


def _read_text(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_READ_BYTES:
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


def _inspect_dir(base: Path, label: str) -> AppCandidate | None:
    try:
        has_pkg = (base / "package.json").is_file()
        has_req = (base / "requirements.txt").is_file()
        has_pyproject = (base / "pyproject.toml").is_file()
        has_go = (base / "go.mod").is_file()
        has_static = (base / "index.html").is_file()
        has_py_entry = any(
            (base / f"{n}.py").is_file()
            for n in ("app", "main", "wsgi", "asgi", "server")
        )
    except OSError:
        return None

    technologies: list[str] = []
    evidence: list[str] = []
    is_frontend = False
    is_backend = False

    if has_pkg:
        data = _read_json(base / "package.json")
        deps: dict = {}
        for key in ("dependencies", "devDependencies"):
            section = data.get(key)
            if isinstance(section, dict):
                deps.update(section)
        scripts = data.get("scripts")
        scripts = scripts if isinstance(scripts, dict) else {}
        evidence.append(f"{label}/package.json")
        if any(d in deps for d in _FRONTEND_DEPS):
            is_frontend = True
            technologies.append("node-frontend")
        elif any(d in deps for d in _BACKEND_NODE_MARKERS):
            is_backend = True
            technologies.append("node-backend")
        elif scripts.get("start") or scripts.get("dev"):
            # package.json with a runnable script is deployable evidence;
            # role stays neutral until dependency markers disambiguate.
            technologies.append("node")
        else:
            # Bare package.json without scripts/deps (e.g. a workspace root
            # manifest) is not an independent deployable application.
            return None
    if (has_req or has_pyproject) and has_py_entry:
        combined = f"{_read_text(base / 'requirements.txt')}\n{_read_text(base / 'pyproject.toml')}".lower()
        marker = next((m for m in _BACKEND_PY_MARKERS if m in combined), None)
        technologies.append(f"python-{marker}" if marker else "python")
        evidence.append(f"{label}/requirements.txt" if has_req else f"{label}/pyproject.toml")
        is_backend = True
    elif (has_req or has_pyproject) and not has_py_entry:
        # Dependency manifest without a web entrypoint is not deployable.
        pass
    if has_static and not has_pkg and not (has_req or has_pyproject):
        technologies.append("static")
        evidence.append(f"{label}/index.html")
    if has_go:
        technologies.append("go")
        evidence.append(f"{label}/go.mod")

    if not technologies:
        return None
    return AppCandidate(
        path=label,
        technologies=sorted(set(technologies)),
        evidence=sorted(set(evidence)),
        is_frontend=is_frontend,
        is_backend=is_backend,
    )


def discover_applications(root: Path) -> DiscoveryResult:
    """Discover deployable application roots at depth 0..1."""
    try:
        if not root.is_dir() or root.is_symlink():
            return DiscoveryResult(candidates=[], relationship="none",
                                   reason="workspace unavailable")
    except OSError:
        return DiscoveryResult(candidates=[], relationship="none",
                               reason="workspace unavailable")

    found: list[AppCandidate] = []
    root_candidate = _inspect_dir(root, ".")
    if root_candidate is not None:
        found.append(root_candidate)
    try:
        children = sorted(
            (c for c in root.iterdir()
             if c.is_dir() and not c.is_symlink() and c.name not in SKIP_DIRS),
            key=lambda p: p.name,
        )[:_MAX_CHILDREN]
    except OSError:
        children = []
    for child in children:
        candidate = _inspect_dir(child, child.name)
        if candidate is not None:
            found.append(candidate)

    # Workspace roots are not independent apps: a root package.json that
    # declares these subdirs as workspaces describes one application.
    if root_candidate is not None and len(found) > 1:
        try:
            data = _read_json(root / "package.json")
            workspaces = data.get("workspaces")
            members: set[str] = set()
            if isinstance(workspaces, list):
                members = {str(m).strip().strip("/") for m in workspaces if isinstance(m, str)}
            elif isinstance(workspaces, dict):
                pkgs = workspaces.get("packages")
                if isinstance(pkgs, list):
                    members = {str(m).strip().strip("/") for m in pkgs if isinstance(m, str)}
            if members:
                sub = [c for c in found if c.path != "." and c.path in members]
                if sub and len(sub) == len(found) - 1:
                    return DiscoveryResult(
                        candidates=[root_candidate],
                        relationship="single",
                        reason="workspace root declares member packages",
                    )
        except OSError:
            pass

    found = sorted(found, key=lambda c: c.path)[:10]
    if len(found) == 0:
        return DiscoveryResult(candidates=[], relationship="none",
                               reason="no application manifests found")
    if len(found) == 1:
        return DiscoveryResult(candidates=found, relationship="single",
                               reason=f"single application at '{found[0].path}'")
    frontends = [c for c in found if c.is_frontend]
    backends = [c for c in found if c.is_backend]
    # Full-stack pair: exactly two complementary candidates (frontend +
    # backend) with no root-level app competing. Evidence-backed, not
    # name-backed: roles come from dependency markers, not directory names.
    if len(found) == 2 and len(frontends) == 1 and len(backends) == 1 \
            and all(c.path != "." for c in found):
        return DiscoveryResult(
            candidates=found,
            relationship="fullstack",
            reason="related frontend and backend applications detected",
        )
    return DiscoveryResult(
        candidates=found,
        relationship="monorepo",
        reason=f"{len(found)} independent application roots detected",
    )
