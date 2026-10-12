"""GitHub webhook verification/dedup/filtering + approval state machine."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.enums import DeploymentStatus
from app.database.connection import init_db
from app.database.repositories import DeploymentRepository, ProposalRepository
from app.main import create_app
from app.models.deployment import DeploymentRecord, ProposalRecord
from app.core.enums import DeployMode
from app.core.events import utc_now_iso
from app.workflow.planning import _canonical_plan, _plan_hash

SECRET = "whsec_test_only"
FIXTURE_REPO = str(
    (Path(__file__).resolve().parent / "fixtures" / "repos" / "compose_app").resolve()
)


@pytest.fixture()
def webhook_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "test_wh.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SECRET)
    monkeypatch.setenv("MEDHA_WEBHOOK_ALLOWED_REPOS", "octo/demo")
    monkeypatch.setenv("MEDHA_WEBHOOK_BRANCHES", "main")
    get_settings.cache_clear()
    init_db(tmp_path / "test_wh.db")
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()


def _signed(body: dict, *, secret: str = SECRET, delivery: str = "del_1", event: str = "push") -> dict:
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return {
        "content": raw,
        "headers": {
            "x-hub-signature-256": sig,
            "x-github-delivery": delivery,
            "x-github-event": event,
            "content-type": "application/json",
        },
    }


def _push(repo: str = "octo/demo", ref: str = "refs/heads/main", sha: str = "abc1234567890") -> dict:
    return {"repository": {"full_name": repo}, "ref": ref, "after": sha, "before": "0000000"}


def test_missing_secret_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "test_wh2.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "")
    get_settings.cache_clear()
    init_db(tmp_path / "test_wh2.db")
    try:
        with TestClient(create_app()) as client:
            signed = _signed(_push())
            response = client.post("/api/webhooks/github", **signed)
            assert response.status_code == 503
    finally:
        get_settings.cache_clear()


def test_invalid_signature_rejected(webhook_client):
    signed = _signed(_push(), secret="wrong")
    response = webhook_client.post("/api/webhooks/github", **signed)
    assert response.status_code == 401


def test_missing_delivery_id_rejected(webhook_client):
    signed = _signed(_push())
    del signed["headers"]["x-github-delivery"]
    response = webhook_client.post("/api/webhooks/github", **signed)
    assert response.status_code == 400


def test_non_push_ignored(webhook_client):
    signed = _signed({"zen": "hi"}, event="ping")
    response = webhook_client.post("/api/webhooks/github", **signed)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


def test_unwatched_branch_ignored(webhook_client):
    signed = _signed(_push(ref="refs/heads/feature-x"), delivery="del-branch")
    response = webhook_client.post("/api/webhooks/github", **signed)
    assert response.json()["status"] == "ignored"


def test_unlisted_repo_ignored(webhook_client):
    signed = _signed(_push(repo="evil/fork"), delivery="del-repo")
    response = webhook_client.post("/api/webhooks/github", **signed)
    assert response.json()["status"] == "ignored"


def test_push_creates_proposal_and_analysis(webhook_client):
    signed = _signed(_push())
    response = webhook_client.post("/api/webhooks/github", **signed)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "analyzing" and body["proposal_id"].startswith("prp_")
    listed = webhook_client.get("/api/proposals").json()
    assert any(p["proposal_id"] == body["proposal_id"] for p in listed["proposals"])


def test_duplicate_delivery_no_second_run(webhook_client):
    first = webhook_client.post("/api/webhooks/github", **_signed(_push(), delivery="del-dup"))
    assert first.status_code == 202
    second = webhook_client.post("/api/webhooks/github", **_signed(_push(), delivery="del-dup"))
    assert second.json()["status"] == "duplicate"
    listed = webhook_client.get("/api/proposals").json()
    assert len([p for p in listed["proposals"] if p["target_sha"] == "abc1234567890"]) == 1


async def _analyze_ready_proposal() -> tuple[str, str]:
    """Run a real plan-only analysis on the fixture repo; returns (prp, dep)."""
    from app.workflow.planning import PlanningPipeline

    now = utc_now_iso()
    deployment_id = f"dep_{uuid4().hex[:16]}"
    record = DeploymentRecord(
        deployment_id=deployment_id,
        repository_url=FIXTURE_REPO,
        mode=DeployMode.REAL,
        scenario=None,
        target_host="localhost",
        target_port=8080,
        intent="approval e2e",
        base_revision=None,
        target_revision="local-fixture",
        status=DeploymentStatus.STARTED,
        current_stage=None,
        created_at=now,
        updated_at=now,
        is_demo=False,
    )
    DeploymentRepository().create(record)
    proposal = ProposalRecord(
        proposal_id=f"prp_{uuid4().hex[:16]}",
        repository="octo/demo",
        branch="main",
        base_sha=None,
        target_sha="local-fixture",
        deployment_id=deployment_id,
        status="analyzing",
        created_by="webhook:github",
        created_at=now,
        idempotency_key=f"github:{uuid4().hex}",
    )
    ProposalRepository().create(proposal)
    await PlanningPipeline().run(
        deployment_id, plan_only=True, proposal_id=proposal.proposal_id
    )
    settled = ProposalRepository().get(proposal.proposal_id)
    assert settled is not None and settled.status == "ready", settled
    assert settled.plan_hash
    return proposal.proposal_id, deployment_id


def _ready_proposal(client_repo_db=None) -> tuple[str, str]:
    """Fabricate a READY proposal + awaiting deployment (hash-tamper tests)."""
    now = utc_now_iso()
    deployment_id = f"dep_{uuid4().hex[:16]}"
    record = DeploymentRecord(
        deployment_id=deployment_id,
        repository_url=FIXTURE_REPO,
        mode=DeployMode.REAL,
        scenario=None,
        target_host="localhost",
        target_port=8080,
        intent="approval e2e",
        base_revision=None,
        target_revision="abc1234567890",
        status=DeploymentStatus.AWAITING_APPROVAL,
        current_stage="COMPLETE",
        created_at=now,
        updated_at=now,
        is_demo=False,
    )
    canonical = {"deployment_id": deployment_id, "services": ["backend"],
                 "actions": [], "dependencies": {}, "networks": [],
                 "volumes": [], "compose": {}}
    digest = _plan_hash(canonical)
    record.result = {"kind": "plan_awaiting_approval", "plan_hash": digest, "plan": canonical}
    DeploymentRepository().create(record)
    proposal = ProposalRecord(
        proposal_id=f"prp_{uuid4().hex[:16]}",
        repository="octo/demo",
        branch="main",
        base_sha=None,
        target_sha="abc1234567890",
        deployment_id=deployment_id,
        plan_hash=digest,
        plan=canonical,
        status="ready",
        created_by="webhook:github",
        created_at=now,
        idempotency_key=f"github:{uuid4().hex}",
    )
    ProposalRepository().create(proposal)
    return proposal.proposal_id, deployment_id


def _wait_status(client, deployment_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


async def test_approve_executes_verified_plan(webhook_client):
    proposal_id, deployment_id = await _analyze_ready_proposal()
    response = webhook_client.post(f"/api/proposals/{proposal_id}/approve", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "executing" and body["decided_by"] == "local-operator"
    final = _wait_status(webhook_client, deployment_id)
    assert final["status"] == "completed"
    assert final["result"]["title"] == "SUCCESS"
    settled = webhook_client.get(f"/api/proposals/{proposal_id}").json()
    assert settled["status"] == "executed"


async def test_approve_replay_is_idempotent(webhook_client):
    proposal_id, deployment_id = await _analyze_ready_proposal()
    first = webhook_client.post(f"/api/proposals/{proposal_id}/approve", json={})
    assert first.status_code == 200
    second = webhook_client.post(f"/api/proposals/{proposal_id}/approve", json={})
    assert second.status_code == 200
    assert second.json().get("duplicate") is True
    _wait_status(webhook_client, deployment_id)


def test_approve_stale_plan_hash_rejected(webhook_client):
    proposal_id, deployment_id = _ready_proposal()
    proposals_repo = ProposalRepository()
    current = proposals_repo.get(proposal_id)
    assert current is not None
    proposals_repo.update(proposal_id, plan_hash="deadbeef" * 8)
    response = webhook_client.post(f"/api/proposals/{proposal_id}/approve", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_PROPOSAL"
    assert proposals_repo.get(proposal_id) is not None
    assert proposals_repo.get(proposal_id).status == "stale"


def test_reject_blocks_execution(webhook_client):
    proposal_id, _ = _ready_proposal()
    response = webhook_client.post(
        f"/api/proposals/{proposal_id}/reject", json={"reason": "too risky"}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    again = webhook_client.post(f"/api/proposals/{proposal_id}/approve", json={})
    assert again.status_code == 409


def test_owner_can_gate_others_proposal(tmp_path, monkeypatch):
    import app.core.clerk_auth as clerk_auth
    from fastapi import HTTPException

    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "test_appr.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("MEDHA_AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_DOMAIN", "auth.test.local")
    get_settings.cache_clear()

    def fake_verify(token: str, *, client=None):
        mapping = {"token-alice": "user_alice", "token-bob": "user_bob"}
        if token in mapping:
            return {"sub": mapping[token]}
        raise HTTPException(status_code=401, detail={"code": "x", "message": "x", "details": {}})

    monkeypatch.setattr(clerk_auth, "verify_clerk_token", fake_verify)
    init_db(tmp_path / "test_appr.db")
    try:
        with TestClient(create_app()) as client:
            now = utc_now_iso()
            proposal = ProposalRecord(
                proposal_id=f"prp_{uuid4().hex[:16]}",
                repository="octo/demo",
                branch="main",
                target_sha="abc1234567890",
                status="ready",
                created_by="user_alice",
                created_at=now,
                idempotency_key=f"github:{uuid4().hex}",
            )
            ProposalRepository().create(proposal)
            denied = client.post(
                f"/api/proposals/{proposal.proposal_id}/approve",
                json={},
                headers={"Authorization": "Bearer token-bob"},
            )
            # Phase 2: uniform 404 (no existence oracle across owners).
            assert denied.status_code == 404
    finally:
        get_settings.cache_clear()
        clerk_auth.clear_jwks_cache()


def test_ai_status_has_no_secrets(webhook_client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_should_never_appear")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza_should_never_appear")
    get_settings.cache_clear()
    try:
        response = webhook_client.get("/api/ai/status")
        assert response.status_code == 200
        body = response.text
        assert "gsk_should_never_appear" not in body
        assert "AIza_should_never_appear" not in body
        payload = response.json()
        assert "enabled" in payload and "health" in payload
        assert set(payload["health"]["providers"].keys()) == {"groq", "gemini"}
    finally:
        get_settings.cache_clear()
