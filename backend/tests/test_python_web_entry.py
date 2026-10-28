"""Python web-entrypoint detection (Case A FastAPI / Case C library-only).

Covers the layouts that previously produced ``unsupported, python``: nested
``app/main.py`` and ``src/main.py``, ASGI application objects with a non-``app``
name, and ``create_app()`` factories. A dependency manifest alone must never be
treated as a deployable web application (Case C).
"""

from __future__ import annotations

import pytest

from app.core.app_discovery import discover_applications, find_python_web_entry
from app.execution.profiles import UnsupportedStack, detect_profile
from app.execution.runtime import detect_runtime
from app.execution.support import assess_plan_support

REQ = "fastapi==0.115.0\nuvicorn[standard]==0.30.0\npydantic==2.9.0\n"

FASTAPI_BODY = (
    "from fastapi import FastAPI\n\n"
    "app = FastAPI()\n\n"
    '@app.get("/")\n'
    "def root():\n"
    '    return {"status": "ok"}\n'
)


def _write(root, rel: str, content: str):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_flat_main_py_detected(tmp_path):
    _write(tmp_path, "main.py", FASTAPI_BODY)
    _write(tmp_path, "requirements.txt", REQ)

    entry = find_python_web_entry(tmp_path)
    assert entry is not None
    assert (entry.module, entry.path, entry.object_name, entry.factory) == (
        "main", "main.py", "app", False,
    )

    disc = discover_applications(tmp_path)
    assert disc.relationship == "single"
    assert [c.path for c in disc.candidates] == ["."]

    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.profile == "python-asgi"
    assert spec.framework == "fastapi"
    assert spec.start.command[:2] == ["uvicorn", "main:app"]


def test_nested_app_main_detected(tmp_path):
    _write(tmp_path, "requirements.txt", REQ)
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/main.py", FASTAPI_BODY)

    entry = find_python_web_entry(tmp_path)
    assert entry is not None
    assert (entry.module, entry.path) == ("app.main", "app/main.py")

    disc = discover_applications(tmp_path)
    assert [c.path for c in disc.candidates] == ["."], (
        "nested layout must be a single root app"
    )


def test_nested_src_main_detected(tmp_path):
    _write(tmp_path, "requirements.txt", REQ)
    _write(tmp_path, "src/main.py", FASTAPI_BODY)

    entry = find_python_web_entry(tmp_path)
    assert entry is not None
    assert (entry.module, entry.path) == ("src.main", "src/main.py")

    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.start.command[1] == "src.main:app"


def test_non_app_object_name(tmp_path):
    _write(tmp_path, "requirements.txt", REQ)
    _write(
        tmp_path,
        "main.py",
        "from fastapi import FastAPI\n"
        "application = FastAPI()\n"
        '@application.get("/")\n'
        "def root():\n"
        '    return {"ok": True}\n',
    )

    entry = find_python_web_entry(tmp_path)
    assert entry is not None
    assert entry.object_name == "application"

    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.start.command[1] == "main:application"


def test_factory_create_app_uses_uvicorn_factory(tmp_path):
    _write(tmp_path, "requirements.txt", REQ)
    _write(
        tmp_path,
        "main.py",
        "from fastapi import FastAPI\n"
        "def create_app():\n"
        "    application = FastAPI()\n"
        "    return application\n",
    )

    entry = find_python_web_entry(tmp_path)
    assert entry is not None
    assert entry.factory is True
    assert entry.object_name == "create_app"

    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.start.command[:3] == ["uvicorn", "--factory", "main:create_app"]


def test_module_level_factory_call_is_not_factory(tmp_path):
    # `app = create_app()` builds the instance at import time; no --factory.
    _write(tmp_path, "requirements.txt", REQ)
    _write(
        tmp_path,
        "app/main.py",
        "from fastapi import FastAPI\n"
        "def create_app():\n"
        "    return FastAPI()\n"
        "app = create_app()\n",
    )
    entry = find_python_web_entry(tmp_path)
    assert entry is not None
    assert entry.factory is False
    assert entry.object_name == "app"


def test_library_only_repo_stays_undeployable(tmp_path):
    _write(tmp_path, "requirements.txt", "requests==2.32.0\n")

    assert find_python_web_entry(tmp_path) is None
    assert discover_applications(tmp_path).candidates == []
    with pytest.raises(UnsupportedStack) as exc:
        detect_runtime(tmp_path)
    assert exc.value.code == "UNSUPPORTED_STACK"


def test_nested_stray_main_without_app_object_is_not_evidence(tmp_path):
    # A nested CLI `main.py` with no framework object is not deployable.
    _write(tmp_path, "requirements.txt", "requests==2.32.0\n")
    _write(tmp_path, "src/main.py", "def main():\n    print('hi')\n")
    assert find_python_web_entry(tmp_path) is None


def test_manifest_subdir_is_separate_root(tmp_path):
    # Root has tooling deps; backend/ has its own manifest + entrypoint.
    _write(tmp_path, "requirements.txt", "black\n")
    _write(tmp_path, "backend/requirements.txt", REQ)
    _write(tmp_path, "backend/app.py", FASTAPI_BODY)

    disc = discover_applications(tmp_path)
    assert [c.path for c in disc.candidates] == ["backend"]
    # Root must not claim the nested entrypoint as its own.
    assert find_python_web_entry(tmp_path) is None


def test_support_gate_passes_for_nested_fastapi(tmp_path):
    from app.agents.analyzer import analyze_repository

    _write(tmp_path, "requirements.txt", REQ)
    _write(tmp_path, "app/main.py", FASTAPI_BODY)

    profile, _ = analyze_repository(
        deployment_id="dep_nested_fa", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
    )
    assert profile.inferred_stack.app_candidates == ["."]
    assert profile.inferred_stack.language_runtime == "python"
    decision = assess_plan_support(profile)
    assert decision.supported is True
    assert decision.code != "NO_DEPLOYABLE_APP"


def test_detect_profile_name_for_fastapi(tmp_path):
    _write(tmp_path, "requirements.txt", REQ)
    _write(tmp_path, "app/main.py", FASTAPI_BODY)
    assert detect_profile(tmp_path).name == "python"
