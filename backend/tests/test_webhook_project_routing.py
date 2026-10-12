"""Webhook ↔ project routing: mapping, isolation, substitution resistance."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

import app.core.clerk_auth as clerk_auth
from app.core.config import get_settings
from app.core.events import utc_now_iso
from app.database.connection import init_db
from app.database.repositories import ProjectRepository, ProposalRepository
from app.main import create_app
from app.models.deployment import ProposalRecord

SECRET = "whsec_test_only"


@pytest.fixture()
def routed_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "test_routing.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("MEDHA_WEBHOOK_ALLOWED_REPOS", "octo/demo,octo/other")
    monkeypatch.setenv("MEDHA_WEBHOOK_BRANCHES", "main")
    get_settings.cache_clear()
    init_db(tmp_path / "test_routing.db")
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def _signed(body: dict, *, delivery: str = "del_1") -> dict:
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    return {
        "content": raw,
        "headers": {
            "x-hub-signature-256": sig,
            "x-github-delivery": delivery,
            "x-github-event": "push",
            "content-type": "application/json",
        },
    }


def _push(repo="octo/demo", sha="a" * 40, ref="refs/heads/main", before="b" * 40):
    return {
        "repository": {"full_name": repo},
        "ref": ref,
        "after": sha,
        "before": before,
        "commits": [
            {"id": sha, "message": "fix things",
             "added": ["app.py"], "removed": [], "modified": ["README.md"]},
        ],
    }


def _connect(client, repo="octo/demo", branch="main", name="P"):
    created = client.post(
        "/api/projects", json={"name": name, "repository": repo, "branch": branch}
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["project_id"]
    ProjectRepository().update(
        project_id, connection_status="connected", visibility="public",
        updated_at=utc_now_iso(),
    )
    return project_id


def test_mapped_push_creates_project_bound_proposal(routed_client):
    project_id = _connect(routed_client)
    response = routed_client.post("/api/webhooks/github", **_signed(_push()))
    assert response.status_code == 202, response.text
    body = response.json()
    proposal = ProposalRepository().get(body["proposal_id"])
    assert proposal is not None
    assert proposal.project_id == project_id
    assert proposal.push is not None
    assert proposal.push["target_sha"] == "a" * 40
    assert len(proposal.push["files"]) == 2


def test_unknown_repo_rejected_once_projects_exist(routed_client):
    _connect(routed_client, repo="octo/demo")
    response = routed_client.post(
        "/api/webhooks/github", **_signed(_push(repo="octo/other"), delivery="del-x")
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ignored", "reason": "no connected project"}


def test_disconnected_project_stops_routing(routed_client):
    project_id = _connect(routed_client)
    ProjectRepository().update(
        project_id, connection_status="disconnected", updated_at=utc_now_iso()
    )
    response = routed_client.post(
        "/api/webhooks/github", **_signed(_push(), delivery="del-disc")
    )
    assert response.json() == {"status": "ignored", "reason": "no connected project"}


def test_branch_mismatch_does_not_route(routed_client):
    _connect(routed_client, branch="main")
    response = routed_client.post(
        "/api/webhooks/github",
        **_signed(_push(ref="refs/heads/release"), delivery="del-branch"),
    )
    # Unwatched branch is ignored before project routing is even consulted.
    assert response.json()["reason"] == "branch not watched"


def test_deleted_branch_push_ignored(routed_client):
    _connect(routed_client)
    body = _push()
    body["after"] = "0" * 40
    response = routed_client.post(
        "/api/webhooks/github", **_signed(body, delivery="del-gone")
    )
    assert response.json() == {"status": "ignored", "reason": "branch deleted"}


def test_supersede_scoped_to_project(routed_client):
    proposals = ProposalRepository()
    now = utc_now_iso()

    def _row(pid, project):
        return ProposalRecord(
            proposal_id=pid, repository="octo/demo", branch="main",
            base_sha=None, target_sha="a" * 40, deployment_id=None,
            status="ready", created_by="webhook:github", created_at=now,
            project_id=project, idempotency_key=f"test:{pid}",
        )

    proposals.create(_row("prp_a_old", "prj_A"))
    proposals.create(_row("prp_b", "prj_B"))
    proposals.supersede_older(
        repository="octo/demo", branch="main",
        except_proposal_id="prp_a_new", project_id="prj_A",
    )
    assert proposals.get("prp_a_old").status == "superseded"
    assert proposals.get("prp_b").status == "ready"


def test_cross_owner_approve_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "test_xowner.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("MEDHA_WEBHOOK_ALLOWED_REPOS", "octo/demo")
    monkeypatch.setenv("MEDHA_WEBHOOK_BRANCHES", "main")
    monkeypatch.setenv("MEDHA_AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_DOMAIN", "auth.test.local")

    def fake_verify(token: str, *, client=None):
        mapping = {"token-alice": "user_alice", "token-bob": "user_bob"}
        if token in mapping:
            return {"sub": mapping[token]}
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail={"code": "X", "message": "x", "details": {}})

    monkeypatch.setattr(clerk_auth, "verify_clerk_token", fake_verify)
    get_settings.cache_clear()
    init_db(tmp_path / "test_xowner.db")
    try:
        with TestClient(create_app()) as client:
            created = client.post(
                "/api/projects", json={"name": "A", "repository": "octo/demo"},
                headers={"Authorization": "Bearer token-alice"},
            )
            assert created.status_code == 201
            project_id = created.json()["project_id"]
            now = utc_now_iso()
            ProposalRepository().create(
                ProposalRecord(
                    proposal_id="prp_alice", repository="octo/demo", branch="main",
                    base_sha=None, target_sha="a" * 40, deployment_id=None,
                    status="analyzing", created_by="webhook:github",
                    created_at=now, project_id=project_id,
                    idempotency_key="test:prp_alice",
                )
            )
            # Bob can neither view nor decide Alice's project proposal (uniform
            # 404 avoids leaking resource existence across owners).
            assert client.get(
                "/api/proposals/prp_alice", headers={"Authorization": "Bearer token-bob"}
            ).status_code == 404
            denied = client.post(
                "/api/proposals/prp_alice/approve", json={},
                headers={"Authorization": "Bearer token-bob"},
            )
            assert denied.status_code == 404
            assert client.get(
                "/api/proposals", headers={"Authorization": "Bearer token-bob"}
            ).json()["total"] == 0
    finally:
        get_settings.cache_clear()
        clerk_auth.clear_jwks_cache()
