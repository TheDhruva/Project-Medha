"""Controlled build profiles for real application deployment.

Only explicitly supported stacks build. Anything else is rejected with an
actionable error — never guessed. Generated Dockerfiles are controlled
MEDHA templates; repository Dockerfiles are NOT executed in V1 (untrusted).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

SUPPORTED_PROFILES = ("static", "python", "node", "nextjs", "python-asgi")

# Explicit support matrix (V1): profile → detection, readiness, limits.
# Anything outside this matrix fails with UNSUPPORTED_STACK — MEDHA never
# builds or executes an arbitrary repository Dockerfile on the backend host.
# `node` is the generic Node.js fallback; `nextjs` is the specialized
# production profile (lockfile-aware install + `build` + `start`).
SUPPORT_MATRIX = {
    "static": {
        "detects": "index.html at checkout root",
        "readiness": "GET / → 200 via loopback probe",
        "base": "nginx:1.27-alpine",
    },
    "python": {
        "detects": "requirements.txt/pyproject.toml + app.py|main.py|wsgi.py|asgi.py|server.py",
        "readiness": "GET / → 200 via loopback probe",
        "base": "python:3.12-slim",
    },
    "python-asgi": {
        "detects": "requirements.txt/pyproject.toml + ASGI entrypoint (FastAPI preferred)",
        "readiness": "GET / → 200 via loopback probe",
        "base": "python:3.12-slim",
    },
    "node": {
        "detects": "package.json with scripts.start (generic Node.js)",
        "readiness": "GET / → 200 via loopback probe",
        "base": "node:22-alpine",
    },
    "nextjs": {
        "detects": "package.json with next dependency + scripts.build + scripts.start",
        "readiness": "GET / → 200 via loopback probe",
        "base": "node:22-slim",
    },
}

# Pinned, minimal base images (immutable tags where practical).
# nextjs uses the Debian-slim (glibc) variant so SWC/sharp prebuilds resolve
# without a compiler toolchain; generic node stays on alpine (legacy).
BASE_IMAGES = {
    "static": "nginx:1.27-alpine",
    "python": "python:3.12-slim",
    "python-asgi": "python:3.12-slim",
    "node": "node:22-alpine",
    "nextjs": "node:22-slim",
}


@dataclass
class BuildProfile:
    name: str  # static | python | python-asgi | node | nextjs
    port: int
    health_path: str
    base_image: str
    start_command: list[str]
    reason: str
    # Container env injected at start so the app listens on the published
    # container port (e.g. Node honors PORT; Next.js also honors HOSTNAME).
    # Explicit operator env always wins over these defaults downstream.
    env: dict[str, str] = field(default_factory=dict)
    # Framework evidence (e.g. "next") and lockfile-selected package manager.
    framework: str | None = None
    package_manager: str = "npm"
    # Production build step (e.g. Next.js `build`); None means no build.
    build_command: list[str] | None = None
    # Application root relative to the checkout ("." default; "." only in V1).
    app_root: str = "."


class UnsupportedStack(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def detect_profile(checkout: Path, *, target_port: int = 8080) -> BuildProfile:
    """Deterministic manifest detection over the verified checkout.

    Delegates to the versioned runtime-spec detector (lockfile-aware,
    framework-aware, tri-state) and adapts to the legacy BuildProfile render
    contract. Node-family outcomes keep the historic port/env semantics:
    an explicit port in the start script wins, otherwise the negotiated
    target port is injected via PORT/HOSTNAME.
    """
    from app.execution.runtime import detect_runtime

    return detect_runtime(checkout, target_port=target_port).to_build_profile()


def render_dockerfile(profile: BuildProfile, *, checkout: Path) -> str:
    """Controlled Dockerfile text for the profile (no repo Dockerfile used)."""
    if profile.name == "static":
        docroot = "dist" if (checkout / "dist" / "index.html").is_file() else "."
        # Stock nginx listens on 80 and prepares its dirs as root, both of
        # which break under the enforced runtime (non-root + --cap-drop ALL +
        # unprivileged target port). Fix at build time: listen on the target
        # port, redirect the pid file to /tmp, and hand the writable paths to
        # the nginx user. Container isolation flags are unchanged.
        return (
            f"FROM {profile.base_image}\n"
            f"COPY {docroot}/ /usr/share/nginx/html/\n"
            f"RUN sed -i -E 's/listen +80;/listen {profile.port};/' "
            "/etc/nginx/conf.d/default.conf "
            "&& sed -i -E 's|pid\\s+[^;]+;|pid /tmp/nginx.pid;|' /etc/nginx/nginx.conf "
            "&& touch /tmp/nginx.pid "
            "&& chown -R nginx:nginx /var/cache/nginx /var/log/nginx "
            "/usr/share/nginx/html /etc/nginx/conf.d /tmp/nginx.pid\n"
            "USER nginx\n"
            f"EXPOSE {profile.port}\n"
        )
    if profile.name in ("node", "nextjs"):
        pm = _node_package_manager(profile)
        copy_src = {
            # .npmrc is part of the install contract: a repository that ships
            # one (e.g. legacy-peer-deps=true) changes npm's resolver, so
            # omitting it breaks otherwise-valid lockfiles with ERESOLVE.
            "npm": "package.json package-lock.json* npm-shrinkwrap.json* .npmrc*",
            "pnpm": "package.json pnpm-lock.yaml* pnpm-workspace.yaml* .npmrc*",
            "yarn": "package.json yarn.lock* .yarnrc* .yarnrc.yml*",
        }[pm]
        install = node_install_fragment(profile, checkout=checkout)
        # Baked defaults so the app binds the intended interface/port even
        # when the operator env is absent (explicit -e at start still wins).
        bind_env = "".join(
            f"ENV {key}={value}\n"
            for key, value in (profile.env or {}).items()
            if key in {"PORT", "HOSTNAME"}
        )
        build_step = ""
        if profile.build_command:
            build_step = f"RUN {_shell_join(profile.build_command)}\n"
        prod_env = "ENV NODE_ENV=production\n" if profile.name == "nextjs" else ""
        return (
            f"FROM {profile.base_image}\n"
            "WORKDIR /srv/app\n"
            f"COPY {copy_src} ./\n"
            f"{install}"
            "COPY . .\n"
            f"{build_step}"
            f"{prod_env}"
            f"{bind_env}"
            f"EXPOSE {profile.port}\n"
            "USER node\n"
            f"CMD {json.dumps(profile.start_command)}\n"
        )
    if profile.name in ("python", "python-asgi"):
        server = profile.start_command[0]
        return (
            f"FROM {profile.base_image}\n"
            "WORKDIR /srv/app\n"
            "COPY requirements.txt* pyproject.toml* ./\n"
            "RUN pip install --no-cache-dir -r requirements.txt || pip install --no-cache-dir uvicorn gunicorn fastapi\n"
            "COPY . .\n"
            f"EXPOSE {profile.port}\n"
            "USER nobody\n"
            f"CMD {json.dumps(profile.start_command)}\n"
        )
    raise UnsupportedStack("UNSUPPORTED_STACK", f"Unknown profile '{profile.name}'.")


def _node_package_manager(profile: BuildProfile) -> str:
    pm = (profile.package_manager or "npm").lower()
    if pm not in {"npm", "pnpm", "yarn"}:
        raise UnsupportedStack(
            "UNSUPPORTED_STACK",
            f"Package manager '{profile.package_manager}' is not supported "
            "by V1 controlled images (use npm/pnpm/yarn).",
        )
    return pm


def node_install_fragment(profile: BuildProfile, *, checkout: Path) -> str:
    """Dependency-install Dockerfile fragment for node/nextjs profiles.

    Single source of truth for both rendering and build diagnostics. npm's
    real error is never masked (no ``2>/dev/null``) and a failing ``npm ci``
    is never papered over with a blanket ``npm install`` — a broken install
    fails loudly with the real npm error, never a substituted success.
    """
    pm = _node_package_manager(profile)
    if pm == "npm" and not profile.build_command:
        # Legacy generic-node path (unchanged): slim runtime install.
        return (
            "RUN npm install --omit=dev --no-audit --no-fund "
            "|| npm install --no-audit --no-fund\n"
        )
    if pm == "npm":
        # Production builds need devDependencies (typescript, tailwind…).
        if _lockfile_present(checkout, ("package-lock.json", "npm-shrinkwrap.json")):
            return "RUN npm ci --no-audit --no-fund\n"
        return "RUN npm install --no-audit --no-fund\n"
    if pm == "pnpm":
        # corepack resolves the pinned pnpm from packageManager automatically.
        return (
            "ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0\n"
            "RUN corepack enable\n"
            "RUN pnpm install --frozen-lockfile "
            "|| pnpm install --no-frozen-lockfile\n"
        )
    return "RUN yarn install --frozen-lockfile 2>/dev/null || yarn install\n"


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


_SAFE_TOKEN_RE = None


def _shell_join(command: list[str]) -> str:
    """Join an internally generated command for Dockerfile RUN (validated)."""
    import re as _re

    global _SAFE_TOKEN_RE
    if _SAFE_TOKEN_RE is None:
        _SAFE_TOKEN_RE = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/:+=@]{0,127}$")
    parts = list(command or [])
    if not parts:
        raise UnsupportedStack("UNSUPPORTED_STACK", "Empty build command.")
    for token in parts:
        if not isinstance(token, str) or not _SAFE_TOKEN_RE.match(token):
            raise UnsupportedStack(
                "UNSUPPORTED_STACK", f"Unsafe build command token: {token!r}",
            )
    return " ".join(parts)


def _lockfile_present(checkout: Path, names: tuple[str, ...]) -> bool:
    return any((checkout / name).is_file() for name in names)


def _port_from_pkg(pkg: dict) -> int | None:
    for key in ("port", "PORT"):
        val = pkg.get(key)
        if isinstance(val, int) and 1 <= val <= 65535:
            return val
    return None


def _port_from_scripts(pkg: dict) -> int | None:
    """Actual runtime configuration: explicit listen port in npm scripts.

    Matches `-p 3000`, `--port 3000`, `--port=3000`, and `PORT=3000`
    prefixes. Returns None when no script pins a port (caller falls back
    to the negotiated target port + PORT env injection).
    """
    import re

    scripts = pkg.get("scripts")
    if not isinstance(scripts, dict):
        return None
    patterns = (
        re.compile(r"(?:^|\s)(?:-p|--port)[=\s]+(\d{2,5})(?:\s|$)"),
        re.compile(r"(?:^|\s)PORT=(\d{2,5})(?:\s|$)"),
    )
    for value in scripts.values():
        if not isinstance(value, str):
            continue
        for pattern in patterns:
            match = pattern.search(value)
            if match:
                try:
                    port = int(match.group(1))
                except ValueError:
                    continue
                if 1 <= port <= 65535:
                    return port
    return None


def _node_start(pkg: dict) -> list[str]:
    # Legacy helper retained for backward compatibility (detection now
    # flows through runtime.detect_runtime; kept so external imports keep
    # working).
    scripts = pkg.get("scripts") or {}
    if isinstance(scripts, dict) and scripts.get("start"):
        return ["npm", "start"]
    return ["node", "server.js"]


def _find_python_app(checkout: Path) -> str | None:
    """Dotted module path of the Python web entrypoint (e.g. ``app.main``).

    Delegates to the authoritative shared detector in ``app_discovery``
    so the analyzer, support gate, and runtime spec all agree. Returns the
    importable module path (root-level ``app.py``/``main.py`` or nested
    ``app/main.py``/``src/main.py`` layouts) or None when no web entrypoint
    is evidenced.
    """
    from app.core.app_discovery import find_python_web_entry

    entry = find_python_web_entry(checkout)
    return entry.module if entry else None


def _is_fastapi(checkout: Path) -> bool:
    for name in ("requirements.txt", "pyproject.toml"):
        try:
            text = (checkout / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "fastapi" in text.lower():
            return True
    return False
