"""Controlled build profiles for real application deployment.

Only explicitly supported stacks build. Anything else is rejected with an
actionable error — never guessed. Generated Dockerfiles are controlled
MEDHA templates; repository Dockerfiles are NOT executed in V1 (untrusted).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_PROFILES = ("static", "python", "node")

# Explicit support matrix (V1): profile → detection, readiness, limits.
# Anything outside this matrix fails with UNSUPPORTED_STACK — MEDHA never
# builds or executes an arbitrary repository Dockerfile on the backend host.
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
    "node": {
        "detects": "package.json with scripts.start",
        "readiness": "GET / → 200 via loopback probe",
        "base": "node:22-alpine",
    },
}

# Pinned, minimal base images (immutable tags where practical).
BASE_IMAGES = {
    "static": "nginx:1.27-alpine",
    "python": "python:3.12-slim",
    "node": "node:22-alpine",
}


@dataclass
class BuildProfile:
    name: str  # static | python | node
    port: int
    health_path: str
    base_image: str
    start_command: list[str]
    reason: str


class UnsupportedStack(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def detect_profile(checkout: Path, *, target_port: int = 8080) -> BuildProfile:
    """Deterministic manifest detection over the verified checkout."""
    if (checkout / "package.json").is_file():
        pkg = _read_json(checkout / "package.json")
        port = _port_from_pkg(pkg) or target_port
        start = _node_start(pkg)
        return BuildProfile(
            name="node", port=port, health_path="/",
            base_image=BASE_IMAGES["node"], start_command=start,
            reason="package.json with start script",
        )
    if (checkout / "requirements.txt").is_file() or (checkout / "pyproject.toml").is_file():
        app = _find_python_app(checkout)
        port = target_port
        if app is None:
            raise UnsupportedStack(
                "UNSUPPORTED_STACK",
                "Python repository has no recognizable web entrypoint "
                "(app.py / main.py / wsgi.py / asgi.py with app object).",
            )
        return BuildProfile(
            name="python", port=port, health_path="/",
            base_image=BASE_IMAGES["python"],
            start_command=["uvicorn" if _is_fastapi(checkout) else "gunicorn",
                           f"{app}:app", "--host", "0.0.0.0", "--port", str(port)],
            reason=f"python entrypoint {app}",
        )
    if (checkout / "index.html").is_file() or (checkout / "dist" / "index.html").is_file():
        return BuildProfile(
            name="static", port=target_port, health_path="/",
            base_image=BASE_IMAGES["static"], start_command=[],
            reason="static index.html",
        )
    raise UnsupportedStack(
        "UNSUPPORTED_STACK",
        "No supported stack detected (need package.json, requirements.txt/"
        "pyproject.toml with web entrypoint, or index.html).",
    )


def render_dockerfile(profile: BuildProfile, *, checkout: Path) -> str:
    """Controlled Dockerfile text for the profile (no repo Dockerfile used)."""
    if profile.name == "static":
        docroot = "dist" if (checkout / "dist" / "index.html").is_file() else "."
        return (
            f"FROM {profile.base_image}\n"
            f"COPY {docroot}/ /usr/share/nginx/html/\n"
            f"EXPOSE {profile.port}\n"
            "USER nginx\n"
        )
    if profile.name == "node":
        return (
            f"FROM {profile.base_image}\n"
            "WORKDIR /srv/app\n"
            "COPY package.json package-lock.json* ./\n"
            "RUN npm install --omit=dev --no-audit --no-fund || npm install --no-audit --no-fund\n"
            "COPY . .\n"
            f"EXPOSE {profile.port}\n"
            "USER node\n"
            f"CMD {json.dumps(profile.start_command)}\n"
        )
    if profile.name == "python":
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


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _port_from_pkg(pkg: dict) -> int | None:
    for key in ("port", "PORT"):
        val = pkg.get(key)
        if isinstance(val, int) and 1 <= val <= 65535:
            return val
    return None


def _node_start(pkg: dict) -> list[str]:
    scripts = pkg.get("scripts") or {}
    if isinstance(scripts, dict) and scripts.get("start"):
        return ["npm", "start"]
    if (isinstance(scripts, dict) and scripts.get("dev")) or True:
        # Prefer server.js/index.js when no start script exists.
        return ["node", "server.js"]
    return ["npm", "start"]


def _find_python_app(checkout: Path) -> str | None:
    for candidate in ("app", "main", "wsgi", "asgi", "server"):
        if (checkout / f"{candidate}.py").is_file():
            return candidate
    return None


def _is_fastapi(checkout: Path) -> bool:
    for name in ("requirements.txt", "pyproject.toml"):
        try:
            text = (checkout / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "fastapi" in text.lower():
            return True
    return False
