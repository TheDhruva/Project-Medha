"""Typed, versioned runtime specification for real deployment (runtime-spec/v1).

Contract between repository intelligence and the isolated RealExecutor:
evidence-backed detection produces a validated RuntimeSpec (or a clear
unsupported/ambiguous outcome) — the executor never guesses a profile.
Pydantic-validated; secret values are never carried (env names only).
"""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

RUNTIME_SCHEMA = "runtime-spec/v1"

PROFILE_VERSIONS: dict[str, int] = {
    "nextjs": 1,
    "node": 1,
    "static": 1,
    "python-asgi": 1,
}

# App-root / command / env-name validation (untrusted repo input).
_APP_ROOT_RE = re.compile(r"^(?:\.|[A-Za-z0-9][A-Za-z0-9._\-/]{0,127})$")
_CMD_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:+=@]{0,127}$")
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

# Lockfile → package manager (reliable per-manager evidence).
_LOCKFILE_PM = (
    ("pnpm-lock.yaml", "pnpm"),
    ("yarn.lock", "yarn"),
    ("package-lock.json", "npm"),
    ("npm-shrinkwrap.json", "npm"),
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
)

_PM_DECLARE_RE = re.compile(r"^(npm|pnpm|yarn|bun)@(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?)$")


def select_package_manager(
    checkout: Path, pkg: dict,
) -> tuple[str | None, str | None, list[str], list[str], str | None]:
    """Select the package manager from declaration + lockfile evidence.

    Returns (pm, pinned_version, evidence, found_managers, conflict).
    `conflict` is None on a clean selection; otherwise it carries the
    explicit diagnostic (callers fail closed with it instead of guessing).
    A valid `packageManager` declaration wins when consistent with the
    lockfile evidence; conflicting lockfiles without a resolving
    declaration are a diagnostic, not a silent pick.
    """
    evidence: list[str] = []
    present = [name for name, _ in _LOCKFILE_PM if (checkout / name).is_file()]
    found = sorted({pm for name, pm in _LOCKFILE_PM if name in present})
    declared_raw = pkg.get("packageManager")
    declared: str | None = None
    pinned: str | None = None
    if isinstance(declared_raw, str) and declared_raw.strip():
        match = _PM_DECLARE_RE.match(declared_raw.strip())
        if match:
            declared, pinned = match.group(1), match.group(2)
            evidence.append(f"packageManager={declared}@{pinned} (declared)")
        else:
            evidence.append(
                f"packageManager={declared_raw.strip()[:32]} (unparseable; ignored)"
            )
    if (checkout / "pnpm-workspace.yaml").is_file():
        evidence.append("pnpm-workspace.yaml present")

    conflict: str | None = None
    pm: str | None = None
    if declared is not None:
        if not found:
            pm = declared
            evidence.append(f"no lockfile; using declared {declared}@{pinned}")
        elif found == [declared]:
            pm = declared
            evidence.append(f"lockfile={present[0]} agrees with declaration")
        elif declared in found:
            pm = declared
            evidence.append(
                f"declaration {declared}@{pinned} resolves conflicting "
                f"lockfiles ({', '.join(present)}); extra lockfile(s) ignored"
            )
        else:
            conflict = (
                f"packageManager declares {declared}@{pinned} but repository "
                f"evidence shows {', '.join(found)} "
                f"({', '.join(present)}); remove the stale declaration or "
                "lockfile and re-run"
            )
    elif len(found) == 1:
        pm = found[0]
        evidence.append(f"lockfile={present[0]} → {pm}")
    elif not found:
        pm = "npm"
        evidence.append("no lockfile and no declaration; defaulting to npm")
    else:
        conflict = (
            f"conflicting lockfiles ({', '.join(present)}) imply "
            f"{', '.join(found)} with no packageManager declaration to "
            "resolve them; declare packageManager or keep exactly one lockfile"
        )
    return pm, pinned, evidence, found, conflict


class DetectionOutcome(str, Enum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    AMBIGUOUS = "ambiguous"


class RuntimeBuild(BaseModel):
    required: bool = False
    command: list[str] | None = None


class RuntimeStart(BaseModel):
    command: list[str]
    bind_host: str = "0.0.0.0"


class RuntimeReadiness(BaseModel):
    strategy: Literal["http-get"] = "http-get"
    path: str = "/"
    deadline_s: float = 90.0
    interval_s: float = 2.0


class RuntimeResources(BaseModel):
    memory: str = "512m"
    cpus: str = "1.0"
    pids_limit: int = 256


class RuntimeSpec(BaseModel):
    """Validated build/run/readiness contract for one application root."""

    runtime_schema: str = RUNTIME_SCHEMA
    profile: Literal["nextjs", "node", "static", "python-asgi"]
    profile_version: int = 1
    outcome: DetectionOutcome = DetectionOutcome.SUPPORTED
    reason: str = ""
    commit_sha: str | None = None
    app_root: str = "."
    language: str = ""
    framework: str | None = None
    framework_version: str | None = None
    package_manager: str | None = None
    package_manager_version: str | None = None
    evidence: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    internal_port: int = 8080
    host_port: int = 8080
    env_defaults: dict[str, str] = Field(default_factory=dict)
    required_env_names: list[str] = Field(default_factory=list)
    build: RuntimeBuild = Field(default_factory=RuntimeBuild)
    start: RuntimeStart
    readiness: RuntimeReadiness = Field(default_factory=RuntimeReadiness)
    resources: RuntimeResources = Field(default_factory=RuntimeResources)
    base_image: str = ""
    diagnostics: dict[str, Any] = Field(default_factory=dict)

    @field_validator("runtime_schema")
    @classmethod
    def _check_schema(cls, value: str) -> str:
        if value != RUNTIME_SCHEMA:
            raise ValueError(f"unsupported runtime schema '{value}'")
        return value

    @field_validator("profile_version")
    @classmethod
    def _check_version(cls, value: int, info) -> int:
        expected = PROFILE_VERSIONS.get((info.data or {}).get("profile", ""), 1)
        if value != expected:
            raise ValueError(f"unsupported profile version {value}")
        return value

    @field_validator("app_root")
    @classmethod
    def _check_app_root(cls, value: str) -> str:
        cleaned = (value or ".").strip().replace("\\", "/").strip("/")
        if not cleaned or cleaned == ".":
            return "."
        parts = cleaned.split("/")
        if any(p in {"", ".", ".."} for p in parts):
            raise ValueError(f"unsafe app_root '{value}'")
        if not _APP_ROOT_RE.match(cleaned):
            raise ValueError(f"unsafe app_root '{value}'")
        return cleaned

    @field_validator("internal_port", "host_port")
    @classmethod
    def _check_port(cls, value: int) -> int:
        if not isinstance(value, int) or not 1 <= value <= 65535:
            raise ValueError(f"port out of range: {value!r}")
        return value

    @field_validator("commit_sha")
    @classmethod
    def _check_sha(cls, value: str | None) -> str | None:
        if value is None:
            return None
        candidate = value.strip().lower()
        if len(candidate) != 40 or any(c not in "0123456789abcdef" for c in candidate):
            raise ValueError("commit_sha must be a 40-hex commit or None")
        return candidate

    @field_validator("required_env_names")
    @classmethod
    def _check_env_names(cls, value: list[str]) -> list[str]:
        for name in value:
            if not _ENV_NAME_RE.match(name or ""):
                raise ValueError(f"unsafe env name '{name}'")
        return value

    @field_validator("confidence")
    @classmethod
    def _check_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))

    def to_build_profile(self):
        """Adapter to the legacy BuildProfile render contract (no guessing)."""
        from app.execution.profiles import BuildProfile

        name = {"nextjs": "nextjs", "node": "node",
                "static": "static", "python-asgi": "python"}[self.profile]
        return BuildProfile(
            name=name,
            port=self.internal_port,
            health_path=self.readiness.path,
            base_image=self.base_image,
            start_command=list(self.start.command),
            reason=self.reason or f"runtime-spec {self.profile}",
            env=dict(self.env_defaults),
            framework=self.framework,
            package_manager=self.package_manager or "npm",
            build_command=list(self.build.command) if self.build.command else None,
            app_root=self.app_root,
        )

    def to_evidence(self) -> dict[str, Any]:
        """Persistence-safe summary (names only — never secret values)."""
        return {
            "schema": self.runtime_schema,
            "profile": self.profile,
            "profile_version": self.profile_version,
            "outcome": self.outcome.value,
            "reason": self.reason,
            "commit_sha": self.commit_sha,
            "app_root": self.app_root,
            "language": self.language,
            "framework": self.framework,
            "framework_version": self.framework_version,
            "package_manager": self.package_manager,
            "package_manager_version": self.package_manager_version,
            "evidence": list(self.evidence),
            "confidence": self.confidence,
            "internal_port": self.internal_port,
            "host_port": self.host_port,
            "env_names": sorted(set(self.required_env_names) | set(self.env_defaults)),
            "build_required": self.build.required,
            "readiness": self.readiness.model_dump(),
            "base_image": self.base_image,
        }


def detect_runtime(
    checkout: Path,
    *,
    target_port: int = 8080,
    commit_sha: str | None = None,
    readiness_deadline_s: float = 90.0,
) -> RuntimeSpec:
    """Evidence-backed detection → validated RuntimeSpec (never guesses).

    Raises UnsupportedStack for unsupported/ambiguous checkouts with an
    actionable reason (codes UNSUPPORTED_STACK / AMBIGUOUS_TARGET).
    """
    from app.execution.profiles import UnsupportedStack

    if not checkout.is_dir():
        raise UnsupportedStack(
            "UNSUPPORTED_STACK",
            f"Application root is not available: {checkout}",
        )
    if not 1 <= int(target_port) <= 65535:
        raise UnsupportedStack(
            "UNSUPPORTED_STACK", f"Target port out of range: {target_port}",
        )

    pkg_path = checkout / "package.json"
    if pkg_path.is_file():
        return _node_spec(
            checkout, pkg_path, target_port=target_port, commit_sha=commit_sha,
            readiness_deadline_s=readiness_deadline_s,
        )
    if (checkout / "requirements.txt").is_file() or (checkout / "pyproject.toml").is_file():
        return _python_spec(
            checkout, target_port=target_port, commit_sha=commit_sha,
            readiness_deadline_s=readiness_deadline_s,
        )
    if (checkout / "index.html").is_file() or (checkout / "dist" / "index.html").is_file():
        return RuntimeSpec(
            profile="static", profile_version=PROFILE_VERSIONS["static"],
            reason="static index.html",
            commit_sha=commit_sha, app_root=".",
            language="static", evidence=["index.html at checkout root"],
            confidence=0.9, internal_port=target_port, host_port=target_port,
            start={"command": [], "bind_host": "0.0.0.0"},
            readiness={"path": "/", "deadline_s": readiness_deadline_s},
            base_image="nginx:1.27-alpine",
        )
    # Monorepo root without a selected target is ambiguous — never auto-pick.
    sub_apps = sorted(
        p.name for p in checkout.iterdir() if p.is_dir() and _is_app_dir(p)
    )[:10]
    if sub_apps:
        raise UnsupportedStack(
            "AMBIGUOUS_TARGET",
            "Multiple applications detected "
            f"({', '.join(sub_apps)}); select an explicit deployment target — "
            "V1 executes exactly one service and never auto-picks.",
        )
    raise UnsupportedStack(
        "UNSUPPORTED_STACK",
        "No supported stack detected (need package.json, requirements.txt/"
        "pyproject.toml with web entrypoint, or index.html).",
    )


def _is_app_dir(path: Path) -> bool:
    if path.name.startswith(".") or path.name in {"node_modules", "dist", "build"}:
        return False
    return (
        (path / "package.json").is_file()
        or (path / "requirements.txt").is_file()
        or (path / "pyproject.toml").is_file()
        or (path / "index.html").is_file()
    )


def _read_pkg(pkg_path: Path) -> dict:
    try:
        data = json.loads(pkg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _node_spec(
    checkout: Path, pkg_path: Path, *, target_port: int,
    commit_sha: str | None, readiness_deadline_s: float,
) -> RuntimeSpec:
    from app.execution.profiles import (
        UnsupportedStack,
        _port_from_pkg,
        _port_from_scripts,
    )

    pkg = _read_pkg(pkg_path)
    if not pkg:
        # Legacy contract: a present-but-empty/unparseable package.json still
        # yields the generic node fallback (never a crash); the container
        # start then fails closed with real Docker evidence if server.js
        # cannot run.
        return RuntimeSpec(
            profile="node", profile_version=PROFILE_VERSIONS["node"],
            reason="generic node application (empty package.json)",
            commit_sha=commit_sha, app_root=".",
            language="node", package_manager="npm",
            evidence=["package.json present but empty/unparseable"],
            confidence=0.4,
            internal_port=target_port, host_port=target_port,
            env_defaults={"PORT": str(target_port), "HOSTNAME": "0.0.0.0"},
            build=RuntimeBuild(required=False, command=None),
            start={"command": ["node", "server.js"], "bind_host": "0.0.0.0"},
            readiness={"path": "/", "deadline_s": readiness_deadline_s},
            base_image="node:22-alpine",
        )
    deps: dict = {}
    for key in ("dependencies", "devDependencies"):
        section = pkg.get(key)
        if isinstance(section, dict):
            deps.update(section)
    framework = "next" if "next" in deps else None
    framework_version = str(deps["next"])[:24] if framework else None
    is_next = framework == "next"

    # Package manager from declaration + lockfile evidence (never guessed).
    pm, pinned, pm_evidence, _found, conflict = select_package_manager(checkout, pkg)
    evidence = ["package.json with start script" if (pkg.get("scripts") or {}).get("start")
                else "package.json"]
    evidence.extend(pm_evidence)
    if conflict is not None:
        raise UnsupportedStack("UNSUPPORTED_STACK", conflict)
    assert pm is not None  # selector returns a pm whenever conflict is None
    if pinned is not None:
        evidence.append(f"pinned {pm}@{pinned} via Corepack")

    if pm == "bun":
        raise UnsupportedStack(
            "UNSUPPORTED_STACK",
            "Bun lockfile detected but the bun toolchain is not available in "
            "V1 controlled images (node base). Use npm/pnpm/yarn.",
        )

    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    start_script = scripts.get("start")
    internal = _port_from_scripts(pkg) or _port_from_pkg(pkg) or target_port
    env_defaults = {"PORT": str(internal), "HOSTNAME": "0.0.0.0"}
    required_env = _env_example_names(checkout)

    if is_next:
        confidence = 0.9 if _found else 0.8
        build_script = scripts.get("build")
        has_next_out = (checkout / ".next" / "BUILD_ID").is_file()
        if build_script and not has_next_out:
            run = {"npm": ["npm", "run", "build"], "pnpm": ["pnpm", "run", "build"],
                   "yarn": ["yarn", "build"]}[pm]
            build = RuntimeBuild(required=True, command=run)
            evidence.append(f"scripts.build={str(build_script)[:80]} → production build required")
        elif has_next_out and not build_script:
            build = RuntimeBuild(required=False, command=None)
            evidence.append("committed .next output present; build step skipped")
        elif has_next_out and build_script:
            run = {"npm": ["npm", "run", "build"], "pnpm": ["pnpm", "run", "build"],
                   "yarn": ["yarn", "build"]}[pm]
            build = RuntimeBuild(required=True, command=run)
            evidence.append("scripts.build present; rebuilding production output")
        else:
            raise UnsupportedStack(
                "UNSUPPORTED_STACK",
                "Next.js application has no build script and no .next production "
                "output — `next start` cannot serve without a production build.",
            )
        if not start_script:
            raise UnsupportedStack(
                "UNSUPPORTED_STACK",
                "Next.js application has no scripts.start — no validated "
                "production start command.",
            )
        start_cmd = {"npm": ["npm", "start"], "pnpm": ["pnpm", "start"],
                     "yarn": ["yarn", "start"]}[pm]
        return RuntimeSpec(
            profile="nextjs", profile_version=PROFILE_VERSIONS["nextjs"],
            reason="Next.js production application (package.json + next dependency)",
            commit_sha=commit_sha, app_root=".",
            language="node", framework="next", framework_version=framework_version,
            package_manager=pm, package_manager_version=pinned,
            evidence=evidence, confidence=confidence,
            internal_port=internal, host_port=target_port,
            env_defaults=env_defaults, required_env_names=required_env,
            build=build,
            start={"command": start_cmd, "bind_host": "0.0.0.0"},
            readiness={"path": "/", "deadline_s": readiness_deadline_s},
            base_image="node:22-slim",
        )

    # Generic Node.js: preserve the legacy contract (start script or server.js).
    if start_script:
        start_cmd = {"npm": ["npm", "start"], "pnpm": ["pnpm", "start"],
                     "yarn": ["yarn", "start"]}[pm]
    else:
        start_cmd = ["node", "server.js"]
        evidence.append("no scripts.start; legacy fallback node server.js")
    return RuntimeSpec(
        profile="node", profile_version=PROFILE_VERSIONS["node"],
        reason="package.json with start script" if start_script else "generic node application",
        commit_sha=commit_sha, app_root=".",
        language="node", framework=_generic_js_framework(deps),
        package_manager=pm, package_manager_version=pinned,
        evidence=evidence,
        confidence=0.7 if start_script else 0.4,
        internal_port=internal, host_port=target_port,
        env_defaults=env_defaults, required_env_names=required_env,
        build=RuntimeBuild(required=False, command=None),
        start={"command": start_cmd, "bind_host": "0.0.0.0"},
        readiness={"path": "/", "deadline_s": readiness_deadline_s},
        base_image="node:22-alpine",
    )


def _generic_js_framework(deps: dict) -> str | None:
    for cand in ("express", "fastify", "koa", "nestjs", "@nestjs/core", "nuxt"):
        if cand in deps:
            return cand.lstrip("@").split("/")[0]
    return None


def _python_spec(
    checkout: Path, *, target_port: int, commit_sha: str | None,
    readiness_deadline_s: float,
) -> RuntimeSpec:
    from app.execution.profiles import UnsupportedStack, _find_python_app, _is_fastapi

    app = _find_python_app(checkout)
    if app is None:
        raise UnsupportedStack(
            "UNSUPPORTED_STACK",
            "Python repository has no recognizable web entrypoint "
            "(app.py / main.py / wsgi.py / asgi.py with app object).",
        )
    combined = ""
    for name in ("requirements.txt", "pyproject.toml"):
        try:
            combined += (checkout / name).read_text(encoding="utf-8", errors="replace").lower()
        except OSError:
            continue
    is_fastapi = "fastapi" in combined
    framework = "fastapi" if is_fastapi else ("flask" if "flask" in combined else None)
    server = "uvicorn" if is_fastapi else "gunicorn"
    evidence = [f"python entrypoint {app}", "requirements.txt/pyproject.toml"]
    if framework:
        evidence.append(f"framework={framework}")
    return RuntimeSpec(
        profile="python-asgi", profile_version=PROFILE_VERSIONS["python-asgi"],
        reason=f"python entrypoint {app}",
        commit_sha=commit_sha, app_root=".",
        language="python", framework=framework,
        package_manager="pip", evidence=evidence, confidence=0.8,
        internal_port=target_port, host_port=target_port,
        env_defaults={}, required_env_names=_env_example_names(checkout),
        build=RuntimeBuild(required=False, command=None),
        start={"command": [server, f"{app}:app", "--host", "0.0.0.0",
                           "--port", str(target_port)], "bind_host": "0.0.0.0"},
        readiness={"path": "/", "deadline_s": readiness_deadline_s},
        base_image="python:3.12-slim",
    )


def _env_example_names(checkout: Path) -> list[str]:
    """Required env *names* from .env.example (never values)."""
    try:
        text = (checkout / ".env.example").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    names: list[str] = []
    for line in text.splitlines()[:100]:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name = line.split("=", 1)[0].strip().strip("\"'")
        if _ENV_NAME_RE.match(name) and name not in names:
            names.append(name)
    return names[:30]
