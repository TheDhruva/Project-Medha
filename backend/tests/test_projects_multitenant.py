"""Project-scoped multi-user repository connections.

Covers ref parsing, owner isolation, duplicate handling, disconnect, and
the rule that a repository URL in a form is configuration — never proof
of access (verify stays honest without network).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.core.clerk_auth as clerk_auth
from app.api.projects import parse_github_repo_ref, validate_branch_name, ProjectRefError
from app.core.config import get_settings
from app.database.connection import init_db
from app.main import create_app


def _env(monkeypatch, tmp_path, name="test_projects.db"):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / name))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    get_settings.cache_clear()


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    init_db(tmp_path / "test_projects.db")
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture()
def clerk_api_client(tmp_path, monkeypatch):
    _env(monkeypatch, tmp_path)
    monkeypatch.setenv("MEDHA_AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_DOMAIN", "auth.test.local")

    def fake_verify(token: str, *, client=None):
        if token == "token-alice":
            return {"sub": "user_alice"}
        if token == "token-bob":
            return {"sub": "user_bob"}
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN",
                                                      "message": "nope", "details": {}})

    monkeypatch.setattr(clerk_auth, "verify_clerk_token", fake_verify)
    init_db(tmp_path / "test_projects_clerk.db")
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()
    clerk_auth.clear_jwks_cache()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _stub_default_branch_detection(monkeypatch):
    """Keep project creation hermetic: no real ls-remote in these tests."""
    from app.services import git_service

    monkeypatch.setattr(git_service, "ls_remote_default_branch", lambda url: None)


# --- ref parsing (pure unit) ----------------------------------------------


def test_parse_owner_name():
    owner, name, repository, canonical = parse_github_repo_ref("octo/Demo")
    assert (owner, name) == ("octo", "Demo")
    assert repository == "octo/demo"
    assert canonical == "https://github.com/octo/Demo.git"


def test_parse_github_url_variants():
    _, _, repository, canonical = parse_github_repo_ref("https://github.com/octo/demo.git")
    assert repository == "octo/demo"
    assert canonical == "https://github.com/octo/demo.git"
    _, _, repository2, _ = parse_github_repo_ref("http://github.com/octo/demo/")
    assert repository2 == "octo/demo"


def test_parse_rejects_non_github_and_garbage():
    for bad in ["", "not a repo!!!", "a/b/c", "https://gitlab.com/octo/demo",
                "https://github.com/onlyowner", "javascript:alert(1)"]:
        with pytest.raises(ProjectRefError):
            parse_github_repo_ref(bad)


def test_branch_validation():
    assert validate_branch_name("main") == "main"
    assert validate_branch_name("release/1.x") == "release/1.x"
    for bad in ["", "../escape", "-dash", "has space", "a" * 121]:
        with pytest.raises(ProjectRefError):
            validate_branch_name(bad)


# --- CRUD + isolation ------------------------------------------------------


def test_create_and_get_project(api_client):
    created = api_client.post(
        "/api/projects",
        json={"name": "Demo", "repository": "octo/demo", "branch": "main"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["repository"] == "octo/demo"
    assert body["canonical_url"] == "https://github.com/octo/demo.git"
    assert body["visibility"] == "unverified"
    assert body["connection_status"] == "pending"
    fetched = api_client.get(f"/api/projects/{body['project_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["project_id"] == body["project_id"]


def test_duplicate_connection_rejected(api_client):
    payload = {"name": "Demo", "repository": "octo/demo"}
    first = api_client.post("/api/projects", json=payload)
    assert first.status_code == 201
    # Idempotent reconnect: same owner + same canonical identity resolves to
    # the existing project instead of inserting a duplicate row.
    again = api_client.post("/api/projects", json=payload)
    assert again.status_code == 200
    assert again.json()["project_id"] == first.json()["project_id"]
    assert api_client.get("/api/projects").json()["total"] == 1
    # URL variations resolve to the same identity.
    for variant in [
        "https://github.com/octo/demo.git",
        "https://github.com/octo/demo/",
        "OCTO/DEMO",
        "git@github.com:octo/demo.git",
    ]:
        resolved = api_client.post("/api/projects", json={"repository": variant})
        assert resolved.status_code == 200, (variant, resolved.text)
        assert resolved.json()["project_id"] == first.json()["project_id"]
    assert api_client.get("/api/projects").json()["total"] == 1


def test_invalid_ref_rejected(api_client):
    response = api_client.post(
        "/api/projects", json={"name": "X", "repository": "https://gitlab.com/a/b"}
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "NON_GITHUB_REPOSITORY"


def test_cross_user_project_isolation(clerk_api_client):
    created = clerk_api_client.post(
        "/api/projects", json={"name": "Alice", "repository": "octo/demo"},
        headers=_auth("token-alice"),
    )
    assert created.status_code == 201
    project_id = created.json()["project_id"]
    # Bob cannot see, read, patch, delete, or run Alice's project.
    assert clerk_api_client.get(f"/api/projects/{project_id}", headers=_auth("token-bob")).status_code == 404
    assert clerk_api_client.patch(
        f"/api/projects/{project_id}", json={"name": "Bob"}, headers=_auth("token-bob")
    ).status_code == 404
    assert clerk_api_client.delete(
        f"/api/projects/{project_id}", headers=_auth("token-bob")
    ).status_code == 404
    assert clerk_api_client.post(
        f"/api/projects/{project_id}/runs", json={}, headers=_auth("token-bob")
    ).status_code == 404
    # Bob's list is empty; Alice's has exactly hers.
    assert clerk_api_client.get("/api/projects", headers=_auth("token-bob")).json()["total"] == 0
    assert clerk_api_client.get("/api/projects", headers=_auth("token-alice")).json()["total"] == 1
    # Same repo may be connected by a different owner (no global lockout).
    other = clerk_api_client.post(
        "/api/projects", json={"name": "Bob", "repository": "octo/demo"},
        headers=_auth("token-bob"),
    )
    assert other.status_code == 201


def test_disconnect_blocks_runs(clerk_api_client, monkeypatch):
    from app.services import git_service

    monkeypatch.setattr(git_service, "ls_remote_sha", lambda url, ref="HEAD": "a" * 40)
    created = clerk_api_client.post(
        "/api/projects", json={"name": "Alice", "repository": "octo/demo"},
        headers=_auth("token-alice"),
    )
    project_id = created.json()["project_id"]
    verified = clerk_api_client.post(
        f"/api/projects/{project_id}/verify", headers=_auth("token-alice")
    )
    assert verified.status_code == 200
    assert verified.json()["reachable"] is True
    assert verified.json()["project"]["connection_status"] == "connected"
    clerk_api_client.post(f"/api/projects/{project_id}/disconnect", headers=_auth("token-alice"))
    run = clerk_api_client.post(
        f"/api/projects/{project_id}/runs", json={}, headers=_auth("token-alice")
    )
    assert run.status_code == 409
    assert run.json()["error"]["code"] == "PROJECT_NOT_CONNECTED"


def test_verify_unreachable_stays_honest(api_client, monkeypatch):
    from app.services import git_service

    monkeypatch.setattr(git_service, "ls_remote_sha", lambda url, ref="HEAD": None)
    created = api_client.post("/api/projects", json={"name": "X", "repository": "octo/nope"})
    project_id = created.json()["project_id"]
    result = api_client.post(f"/api/projects/{project_id}/verify")
    assert result.status_code == 200
    body = result.json()
    assert body["reachable"] is False
    assert body["project"]["connection_status"] == "failed"
    assert "GitHub App" in body["reason"]


def test_delete_removes_mapping(api_client):
    created = api_client.post("/api/projects", json={"name": "X", "repository": "octo/demo"})
    project_id = created.json()["project_id"]
    assert api_client.delete(f"/api/projects/{project_id}").status_code == 200
    assert api_client.get(f"/api/projects/{project_id}").status_code == 404


def test_create_defaults_name_to_repo_and_branch_to_main(api_client):
    created = api_client.post("/api/projects", json={"repository": "octo/Demo"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Demo"
    assert body["branch"] == "main"


def test_create_detects_default_branch(api_client, monkeypatch):
    from app.services import git_service

    monkeypatch.setattr(git_service, "ls_remote_default_branch", lambda url: "develop")
    created = api_client.post("/api/projects", json={"repository": "octo/demo"})
    assert created.status_code == 201, created.text
    assert created.json()["branch"] == "develop"


def test_create_explicit_branch_skips_detection(api_client, monkeypatch):
    from app.services import git_service

    def _boom(url: str):
        raise AssertionError("detection must not run when a branch is given")

    monkeypatch.setattr(git_service, "ls_remote_default_branch", _boom)
    created = api_client.post(
        "/api/projects", json={"name": "X", "repository": "octo/demo", "branch": "release/1.x"}
    )
    assert created.status_code == 201, created.text
    assert created.json()["branch"] == "release/1.x"


def test_delete_blocked_while_run_in_flight(api_client):
    from app.database.repositories import DeploymentRepository
    from app.core.enums import DeployMode, DeploymentStatus
    from app.core.events import utc_now_iso
    from app.models.deployment import DeploymentRecord

    created = api_client.post("/api/projects", json={"name": "X", "repository": "octo/demo"})
    project_id = created.json()["project_id"]
    now = utc_now_iso()
    DeploymentRepository().create(
        DeploymentRecord(
            deployment_id="dep_active_1",
            repository_url="https://github.com/octo/demo.git",
            mode=DeployMode.REAL,
            scenario=None,
            target_host="localhost",
            target_port=8080,
            intent="test",
            base_revision=None,
            target_revision=None,
            status=DeploymentStatus.RUNNING,
            current_stage="ANALYZE",
            owner_sub="local-operator",
            project_id=project_id,
            created_at=now,
            updated_at=now,
            is_demo=False,
        )
    )
    blocked = api_client.delete(f"/api/projects/{project_id}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "ACTIVE_RUNS"
    # Mapping survives; disconnect stays available while blocked.
    assert api_client.get(f"/api/projects/{project_id}").status_code == 200
    assert api_client.post(f"/api/projects/{project_id}/disconnect").status_code == 200
