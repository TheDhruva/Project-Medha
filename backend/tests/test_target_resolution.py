"""Focused tests: deployment-target resolution contract (multi-app fix).

Covers the target-resolution rules: manifest-backed detection (supporting
directories are not applications), deterministic explicit/saved selection,
root (".") handling, stale-target diagnostics, unsupported repos, target
persistence (save/clear/round-trip), and run creation carrying the target.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.database.connection import init_db
from app.main import create_app


def _env(monkeypatch, tmp_path, name="test_targets.db"):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / name))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    get_settings.cache_clear()


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    init_db(tmp_path / "test_targets.db")
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _stub_default_branch_detection(monkeypatch):
    from app.services import git_service

    monkeypatch.setattr(git_service, "ls_remote_default_branch", lambda url: None)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _multi_app(root: Path) -> None:
    _write(root / "frontend" / "package.json",
           '{"dependencies": {"next": "15.0.0"}, "scripts": {"start": "next start"}}')
    _write(root / "backend" / "requirements.txt", "fastapi\nuvicorn\n")
    _write(root / "backend" / "app.py", "app = 1")


# --- resolution rules ------------------------------------------------------


def test_single_app_selected_automatically(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    _write(tmp_path / "package.json", '{"scripts": {"start": "node server.js"}}')
    profile, _ = analyze_repository(
        deployment_id="dep_one", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
    )
    assert profile.inferred_stack.app_candidates == ["."]
    assert assess_plan_support(profile).supported is True


def test_multiple_apps_block_without_silent_pick(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    _multi_app(tmp_path)
    profile, _ = analyze_repository(
        deployment_id="dep_m", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
    )
    assert profile.inferred_stack.selected_target is None
    decision = assess_plan_support(profile)
    assert (decision.supported, decision.code) == (False, "MULTIPLE_APPS_REQUIRE_TARGET")
    assert [c["path"] for c in decision.details["candidates"]] == ["backend", "frontend"]
    assert decision.details["candidates"][0]["technologies"]
    assert decision.details["candidates"][0]["evidence"]


def test_valid_explicit_target_reaches_support_gate(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    _multi_app(tmp_path)
    _write(tmp_path / "backend" / "Dockerfile", "FROM python:3.12-slim\nEXPOSE 8080\n")
    profile, _ = analyze_repository(
        deployment_id="dep_m", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
        deploy_target="backend",
    )
    assert profile.inferred_stack.selected_target == "backend"
    assert profile.inferred_stack.language_runtime == "python"
    assert assess_plan_support(profile, selected_target="backend").supported is True


def test_stale_target_rejected_with_checkout_candidates(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.workflow.planning import stale_target_selection

    _multi_app(tmp_path)
    with pytest.raises(ValueError, match="INVALID_DEPLOYMENT_TARGET"):
        analyze_repository(
            deployment_id="dep_m", repository_url=str(tmp_path),
            workspace_path=tmp_path, target_host="localhost", target_port=8080,
            deploy_target="nope",
        )
    # The blocked run still offers the valid options from the pinned checkout.
    selection = stale_target_selection(tmp_path, "nope", "prj_x")
    assert [c["path"] for c in selection["candidates"]] == ["backend", "frontend"]
    assert selection["supported_targets"] == ["backend", "frontend"]
    assert selection["selected_target"] == "nope"
    assert selection["project_id"] == "prj_x"
    assert selection["next_actions"] == ["select_target", "reanalyze"]
    # Discovery never raises for unreadable checkouts: empty, not a crash.
    assert stale_target_selection(tmp_path / "missing", "nope", None)["candidates"] == []


def test_explicit_root_target_selects_detected_root_app(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    _write(tmp_path / "package.json", '{"scripts": {"start": "node server.js"}}')
    _write(tmp_path / "backend" / "requirements.txt", "fastapi\n")
    _write(tmp_path / "backend" / "app.py", "app = 1")
    profile, _ = analyze_repository(
        deployment_id="dep_r", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
    )
    assert sorted(profile.inferred_stack.app_candidates) == [".", "backend"]
    # No silent pick of the root when nothing was requested.
    assert assess_plan_support(profile).code == "MULTIPLE_APPS_REQUIRE_TARGET"
    # An explicit "." selects the detected root application.
    scoped, _ = analyze_repository(
        deployment_id="dep_r", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
        deploy_target=".",
    )
    assert scoped.inferred_stack.selected_target == "."
    assert scoped.inferred_stack.language_runtime == "node"
    assert assess_plan_support(scoped, selected_target=".").supported is True


def test_dot_is_unset_when_root_is_not_an_application(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    _multi_app(tmp_path)
    profile, _ = analyze_repository(
        deployment_id="dep_m", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
        deploy_target=".",
    )
    assert profile.inferred_stack.selected_target is None
    assert assess_plan_support(profile).code == "MULTIPLE_APPS_REQUIRE_TARGET"


def test_supporting_directories_are_not_applications(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    _write(tmp_path / "package.json", '{"scripts": {"start": "node server.js"}}')
    _write(tmp_path / "docs" / "README.md", "docs")
    _write(tmp_path / "scripts" / "requirements.txt", "requests\n")  # no entrypoint
    _write(tmp_path / "tooling" / "package.json", '{"name": "tooling"}')  # bare manifest
    _write(tmp_path / "node_modules" / "dep" / "package.json",
           '{"scripts": {"start": "x"}}')
    profile, _ = analyze_repository(
        deployment_id="dep_s", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
    )
    assert profile.inferred_stack.app_candidates == ["."]
    assert assess_plan_support(profile).supported is True


def test_runtime_detection_agrees_with_discovery(tmp_path):
    from app.core.app_discovery import _inspect_dir
    from app.execution.runtime import _is_app_dir

    bare = tmp_path / "tooling"
    bare.mkdir()
    (bare / "package.json").write_text('{"name": "tooling"}', encoding="utf-8")
    assert _inspect_dir(bare, "tooling") is None
    assert _is_app_dir(bare) is False

    pylib = tmp_path / "scripts"
    pylib.mkdir()
    (pylib / "requirements.txt").write_text("requests\n", encoding="utf-8")
    assert _is_app_dir(pylib) is False  # manifest without entrypoint

    app = tmp_path / "backend"
    app.mkdir()
    (app / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (app / "app.py").write_text("app = 1", encoding="utf-8")
    assert _is_app_dir(app) is True

    node = tmp_path / "frontend"
    node.mkdir()
    (node / "package.json").write_text(
        '{"scripts": {"start": "node i.js"}}', encoding="utf-8")
    assert _is_app_dir(node) is True


def test_unsupported_application_is_not_a_target_block(tmp_path):
    from app.agents.analyzer import analyze_repository
    from app.execution.support import assess_plan_support

    (tmp_path / "README.md").write_text("nothing deployable", encoding="utf-8")
    profile, _ = analyze_repository(
        deployment_id="dep_u", repository_url=str(tmp_path),
        workspace_path=tmp_path, target_host="localhost", target_port=8080,
    )
    decision = assess_plan_support(profile)
    assert (decision.supported, decision.code) == (False, "DEPLOYMENT_UNSUPPORTED")


# --- persistence -----------------------------------------------------------


def test_deploy_target_save_clear_and_round_trip(api_client):
    created = api_client.post("/api/projects", json={"repository": "octo/demo"})
    assert created.status_code == 201
    pid = created.json()["project_id"]

    patched = api_client.patch(f"/api/projects/{pid}", json={"deploy_target": "backend"})
    assert patched.status_code == 200, patched.text
    assert patched.json()["deploy_target"] == "backend"
    assert api_client.get(f"/api/projects/{pid}").json()["deploy_target"] == "backend"

    cleared = api_client.patch(f"/api/projects/{pid}", json={"deploy_target": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["deploy_target"] is None

    root = api_client.patch(f"/api/projects/{pid}", json={"deploy_target": "."})
    assert root.status_code == 200, root.text
    assert root.json()["deploy_target"] == "."

    bad = api_client.patch(f"/api/projects/{pid}", json={"deploy_target": "../escape"})
    assert bad.status_code == 400


def test_project_run_carries_explicit_target_and_reports_effective(api_client, monkeypatch):
    import app.workflow.planning as planning_mod
    from app.core.deploy_lock import release_real_deploy
    from app.database.repositories import ProjectRepository

    monkeypatch.setattr(planning_mod, "schedule_planning_pipeline", lambda *a, **k: None)
    created = api_client.post("/api/projects", json={"repository": "octo/demo"})
    pid = created.json()["project_id"]
    ProjectRepository().update(pid, connection_status="connected", updated_at="x")

    run = api_client.post(f"/api/projects/{pid}/runs", json={"deployment_target": "backend"})
    assert run.status_code == 202, run.text
    body = run.json()
    assert body["deploy_target"] == "backend"
    # Explicit run targets persist to the project: retries reuse them.
    assert ProjectRepository().get(pid).deploy_target == "backend"
    # The mocked pipeline never runs, so release the V1 single-deploy lock
    # before the retry (production releases it when the pipeline settles).
    release_real_deploy(body["deployment_id"])

    # Blank means "no explicit target": the saved value is left untouched.
    again = api_client.post(f"/api/projects/{pid}/runs", json={"deployment_target": "  "})
    assert again.status_code == 202, again.text
    assert again.json()["deploy_target"] == "backend"
