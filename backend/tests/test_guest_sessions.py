"""Guest sessions: issuance, server-side verification, isolation, cleanup.

Covers the contract the UI depends on: a guest gets the same core API as an
authenticated user, ownership is enforced server-side, sessions expire, and
cleanup is idempotent and observable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.core.clerk_auth as clerk_auth
from app.core.config import get_settings
from app.core.guest_sessions import cleanup_expired_guest_sessions, guest_subject
from app.core.rate_limit import reset_rate_limits
from app.database.connection import get_connection, init_db
from app.database.repositories import GuestSessionRepository
from app.main import create_app
from tests.conftest import _deploy_payload


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    with get_connection(get_settings().database_path) as conn:
        return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _create(client: TestClient) -> dict:
    response = client.post("/api/guest-session")
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(autouse=True)
def _reset_limits():
    reset_rate_limits()
    yield
    reset_rate_limits()


# --- issuance ---------------------------------------------------------------


def test_create_returns_token_subject_and_expiry(client):
    body = _create(client)
    assert body["token"].startswith("medha_guest_")
    assert body["subject"] == guest_subject(body["session_id"])
    assert body["mode"] == "guest"
    assert body["expires_at"].endswith("Z")


def test_raw_token_is_never_stored(client):
    body = _create(client)
    rows = _rows("SELECT * FROM guest_sessions")
    assert len(rows) == 1
    row = rows[0]
    assert row["token_hash"] != body["token"]
    assert body["token"] not in row["token_hash"]
    # The whole row must not contain the raw token anywhere.
    assert all(body["token"] not in str(value) for value in row.values())


def test_token_is_returned_in_the_body_not_a_url(client):
    response = client.post("/api/guest-session")
    assert response.status_code == 201
    assert "?" not in response.text or "token=" not in response.text


def test_create_is_rate_limited_per_ip(client):
    for _ in range(10):
        assert client.post("/api/guest-session").status_code == 201
    assert client.post("/api/guest-session").status_code == 429


# --- verification -----------------------------------------------------------


def test_guest_token_validates_server_side(client):
    body = _create(client)
    response = client.get("/api/guest-session", headers=_bearer(body["token"]))
    assert response.status_code == 200
    assert response.json()["subject"] == body["subject"]


def test_unknown_guest_token_rejected(client):
    response = client.get(
        "/api/guest-session", headers=_bearer("medha_guest_not-a-real-token")
    )
    assert response.status_code == 401


def test_non_guest_token_rejected_by_guest_endpoint(client):
    response = client.get("/api/guest-session", headers=_bearer("some-clerk-jwt"))
    assert response.status_code == 401


def test_missing_token_rejected_by_guest_endpoint(client):
    assert client.get("/api/guest-session").status_code == 401


def test_get_session_is_read_only(client):
    body = _create(client)
    before = _rows("SELECT * FROM guest_sessions")[0]
    client.get("/api/guest-session", headers=_bearer(body["token"]))
    after = _rows("SELECT * FROM guest_sessions")[0]
    assert before["status"] == after["status"] == "active"
    assert after["cleanup_attempts"] == 0


# --- off-mode regression ----------------------------------------------------


def test_off_mode_without_token_still_local_operator(client):
    response = client.get("/api/deploys")
    assert response.status_code == 200


def test_off_mode_guest_subject_replaces_local_operator(client):
    body = _create(client)
    response = client.get("/api/deploy/nonexistent", headers=_bearer(body["token"]))
    # Ownership scoping is active for a guest even in off mode (404, not 500).
    assert response.status_code == 404


# --- isolation --------------------------------------------------------------


def test_two_guests_cannot_see_each_others_runs(client):
    alice = _create(client)
    bob = _create(client)
    assert alice["subject"] != bob["subject"]

    created = client.post(
        "/api/deploy", json=_deploy_payload(), headers=_bearer(alice["token"])
    )
    assert created.status_code == 202
    deployment_id = created.json()["deployment_id"]

    assert (
        client.get(f"/api/deploy/{deployment_id}", headers=_bearer(alice["token"])).status_code
        == 200
    )
    assert (
        client.get(f"/api/deploy/{deployment_id}", headers=_bearer(bob["token"])).status_code
        == 404
    )
    listed = client.get("/api/deploys", headers=_bearer(bob["token"])).json()
    assert all(run["deployment_id"] != deployment_id for run in listed["runs"])


def test_guest_cannot_read_an_authenticated_users_run(client, monkeypatch):
    """Guest isolation is enforced against Clerk subjects too."""
    from app.core.deploy_lock import release_real_deploy

    monkeypatch.setenv("MEDHA_AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_DOMAIN", "auth.test.local")
    get_settings.cache_clear()
    clerk_auth.clear_jwks_cache()

    def fake_verify(token, *, client=None):
        return {"sub": "user_alice"}

    monkeypatch.setattr(clerk_auth, "verify_clerk_token", fake_verify)
    guest = _create(client)
    created = client.post(
        "/api/deploy",
        json=_deploy_payload(),
        headers=_bearer("token-alice"),
    )
    assert created.status_code == 202
    deployment_id = created.json()["deployment_id"]
    assert (
        client.get(f"/api/deploy/{deployment_id}", headers=_bearer(guest["token"])).status_code
        == 404
    )
    # ...and the reverse: the authenticated user cannot read the guest's run.
    # (V1 allows one real deployment at a time — release the lock between.)
    release_real_deploy()
    guest_run = client.post(
        "/api/deploy", json=_deploy_payload(), headers=_bearer(guest["token"])
    )
    assert guest_run.status_code == 202
    assert (
        client.get(
            f"/api/deploy/{guest_run.json()['deployment_id']}",
            headers=_bearer("token-alice"),
        ).status_code
        == 404
    )


def test_authenticated_flow_unaffected_by_guest_sessions(client, monkeypatch):
    monkeypatch.setenv("MEDHA_AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_DOMAIN", "auth.test.local")
    get_settings.cache_clear()
    clerk_auth.clear_jwks_cache()
    monkeypatch.setattr(
        clerk_auth, "verify_clerk_token", lambda token, *, client=None: {"sub": "user_alice"}
    )
    _create(client)
    assert client.get("/api/deploys", headers=_bearer("token-alice")).status_code == 200
    assert client.get("/api/deploys").status_code == 401


# --- expiry and cleanup -----------------------------------------------------


def _expire(session_id: str) -> None:
    with get_connection(get_settings().database_path) as conn:
        conn.execute(
            "UPDATE guest_sessions SET expires_at = '2000-01-01T00:00:00Z' WHERE session_id = ?",
            (session_id,),
        )
        conn.commit()


def test_expired_session_is_refused_and_queued(client):
    body = _create(client)
    _expire(body["session_id"])
    assert client.get("/api/guest-session", headers=_bearer(body["token"])).status_code == 401
    assert _rows("SELECT status FROM guest_sessions")[0]["status"] == "expired"


def test_cleanup_purges_guest_data(client):
    from app.core.deploy_lock import release_real_deploy

    guest = _create(client)
    created = client.post(
        "/api/deploy", json=_deploy_payload(), headers=_bearer(guest["token"])
    )
    assert created.status_code == 202
    deployment_id = created.json()["deployment_id"]

    # Another guest's data in the same database must survive.
    release_real_deploy()
    other = _create(client)
    other_run = client.post(
        "/api/deploy", json=_deploy_payload(), headers=_bearer(other["token"])
    )
    assert other_run.status_code == 202
    other_deployment_id = other_run.json()["deployment_id"]

    _expire(guest["session_id"])
    summary = cleanup_expired_guest_sessions()
    assert summary["due"] == 1
    assert summary["cleaned"] == 1
    assert summary["failed"] == 0
    assert summary["purged_rows"] >= 1

    assert _rows("SELECT * FROM deployments WHERE deployment_id = ?", (deployment_id,)) == []
    # The other guest's row survives: cleanup is owner-scoped, never global.
    assert (
        len(_rows("SELECT * FROM deployments WHERE deployment_id = ?", (other_deployment_id,)))
        == 1
    )
    assert (
        _rows("SELECT * FROM guest_sessions WHERE session_id = ?", (guest["session_id"],))[0][
            "status"
        ]
        == "cleaned"
    )


def test_cleanup_is_idempotent(client):
    guest = _create(client)
    client.post("/api/deploy", json=_deploy_payload(), headers=_bearer(guest["token"]))
    _expire(guest["session_id"])

    first = cleanup_expired_guest_sessions()
    second = cleanup_expired_guest_sessions()
    assert first["cleaned"] == 1
    assert second["due"] == 0
    assert second["cleaned"] == 0
    assert second["purged_rows"] == 0


def test_cleanup_records_failure_and_retries(client):
    guest = _create(client)
    _expire(guest["session_id"])

    repo = GuestSessionRepository(get_settings().database_path)
    # The reaper queues the session before attempting cleanup.
    repo.mark_expired(guest["session_id"], at="2026-01-01T00:00:00Z")
    repo.record_cleanup_failure(guest["session_id"], at="2026-01-01T00:00:00Z", error="boom")
    row = _rows("SELECT * FROM guest_sessions")[0]
    assert row["cleanup_attempts"] == 1
    assert row["status"] == "expired"  # still retryable
    assert row["cleanup_error"] == "boom"

    # Exhausted budget: the session parks in `failed` instead of looping.
    for _ in range(4):
        repo.record_cleanup_failure(guest["session_id"], at="2026-01-01T00:00:00Z", error="boom")
    row = _rows("SELECT * FROM guest_sessions")[0]
    assert row["cleanup_attempts"] == 5
    assert row["status"] == "failed"
    assert cleanup_expired_guest_sessions()["due"] == 0


def test_ending_a_session_purges_data_immediately(client):
    guest = _create(client)
    run = client.post("/api/deploy", json=_deploy_payload(), headers=_bearer(guest["token"]))
    deployment_id = run.json()["deployment_id"]

    response = client.delete("/api/guest-session", headers=_bearer(guest["token"]))
    assert response.status_code == 200
    body = response.json()
    assert body["ended"] is True
    assert body["already_ended"] is False
    assert body["purged"].get("deployments") == 1
    assert _rows("SELECT * FROM deployments WHERE deployment_id = ?", (deployment_id,)) == []
    # The token no longer authorizes anything.
    assert client.get("/api/guest-session", headers=_bearer(guest["token"])).status_code == 401


def test_ending_twice_is_idempotent(client):
    guest = _create(client)
    first = client.delete("/api/guest-session", headers=_bearer(guest["token"]))
    second = client.delete("/api/guest-session", headers=_bearer(guest["token"]))
    assert first.status_code == second.status_code == 200
    assert second.json()["already_ended"] is True


def test_ending_without_a_token_is_not_an_error(client):
    assert client.delete("/api/guest-session").json() == {
        "ended": True,
        "already_ended": True,
        "purged": {},
    }


# --- expiry driven by configuration ----------------------------------------


def test_zero_ttl_issues_an_already_expired_session(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "ttl.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_GUEST_SESSION_TTL_HOURS", "0")
    monkeypatch.setenv("MEDHA_GUEST_CLEANUP_INTERVAL_SECONDS", "0")
    get_settings.cache_clear()
    init_db(tmp_path / "ttl.db")
    with TestClient(create_app()) as client:
        body = _create(client)
        assert client.get("/api/guest-session", headers=_bearer(body["token"])).status_code == 401
        assert cleanup_expired_guest_sessions()["cleaned"] == 1
    get_settings.cache_clear()


def test_sessions_do_not_leak_between_databases(tmp_path, monkeypatch):
    """A token minted in one database is meaningless in another."""
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "a.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    get_settings.cache_clear()
    init_db(tmp_path / "a.db")
    with TestClient(create_app()) as client:
        token = _create(client)["token"]
    get_settings.cache_clear()

    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "b.db"))
    get_settings.cache_clear()
    init_db(tmp_path / "b.db")
    with TestClient(create_app()) as client:
        assert client.get("/api/guest-session", headers=_bearer(token)).status_code == 401
    get_settings.cache_clear()


def test_session_id_is_unforgeable(client):
    guest = _create(client)
    forged = f"medha_guest_{uuid4().hex}"
    assert client.get("/api/guest-session", headers=_bearer(forged)).status_code == 401
    assert guest["subject"] not in forged
