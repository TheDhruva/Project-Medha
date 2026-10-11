"""Clerk backend verification + ownership enforcement.

Real RS256 verification is tested with a generated keypair (no network);
API enforcement uses a stubbed verifier to isolate the authorization layer.
"""

from __future__ import annotations

import time
from uuid import uuid4

import jwt as pyjwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app.core.clerk_auth as clerk_auth
from app.core.config import get_settings
from app.database.connection import init_db
from app.main import create_app
from tests.conftest import _deploy_payload


def _rsa_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    public_numbers = key.public_key().public_numbers()
    import base64

    def b64url(num: int) -> str:
        raw = num.to_bytes((num.bit_length() + 7) // 8, "big")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    jwk = {
        "kty": "RSA",
        "kid": "test-key-1",
        "use": "sig",
        "alg": "RS256",
        "n": b64url(public_numbers.n),
        "e": b64url(public_numbers.e),
    }
    return private_pem, jwk


@pytest.fixture()
def rsa_ctx():
    private_pem, jwk = _rsa_keypair()
    return {"private": private_pem, "jwks": {"keys": [jwk]}}


def _sign(rsa_ctx, *, sub="user_alice", issuer="https://auth.test.local", exp_skew=600, kid="test-key-1"):
    now = int(time.time())
    return pyjwt.encode(
        {"sub": sub, "iss": issuer, "iat": now, "exp": now + exp_skew},
        rsa_ctx["private"],
        algorithm="RS256",
        headers={"kid": kid},
    )


def _clerk_env(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "test_clerk.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("MEDHA_AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_DOMAIN", "auth.test.local")
    get_settings.cache_clear()
    clerk_auth.clear_jwks_cache()


def test_verify_valid_token(rsa_ctx, tmp_path, monkeypatch):
    _clerk_env(monkeypatch, tmp_path)
    monkeypatch.setattr(clerk_auth, "_fetch_jwks", lambda client=None: rsa_ctx["jwks"])
    claims = clerk_auth.verify_clerk_token(_sign(rsa_ctx))
    assert claims["sub"] == "user_alice"


def test_verify_expired_token_rejected(rsa_ctx, tmp_path, monkeypatch):
    _clerk_env(monkeypatch, tmp_path)
    monkeypatch.setattr(clerk_auth, "_fetch_jwks", lambda client=None: rsa_ctx["jwks"])
    with pytest.raises(HTTPException) as exc_info:
        clerk_auth.verify_clerk_token(_sign(rsa_ctx, exp_skew=-10))
    assert exc_info.value.status_code == 401


def test_verify_wrong_issuer_rejected(rsa_ctx, tmp_path, monkeypatch):
    _clerk_env(monkeypatch, tmp_path)
    monkeypatch.setattr(clerk_auth, "_fetch_jwks", lambda client=None: rsa_ctx["jwks"])
    with pytest.raises(HTTPException) as exc_info:
        clerk_auth.verify_clerk_token(_sign(rsa_ctx, issuer="https://evil.example"))
    assert exc_info.value.status_code == 401


def test_verify_unknown_kid_rejected(rsa_ctx, tmp_path, monkeypatch):
    _clerk_env(monkeypatch, tmp_path)
    monkeypatch.setattr(clerk_auth, "_fetch_jwks", lambda client=None: rsa_ctx["jwks"])
    with pytest.raises(HTTPException) as exc_info:
        clerk_auth.verify_clerk_token(_sign(rsa_ctx, kid="unknown"))
    assert exc_info.value.status_code == 401


def test_verify_unconfigured_fails_closed(tmp_path, monkeypatch):
    _clerk_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CLERK_DOMAIN", "")
    monkeypatch.setenv("CLERK_JWKS_URL", "")
    get_settings.cache_clear()
    with pytest.raises(HTTPException) as exc_info:
        clerk_auth.verify_clerk_token("anything")
    assert exc_info.value.status_code == 503


@pytest.fixture()
def clerk_client(tmp_path, monkeypatch):
    _clerk_env(monkeypatch, tmp_path)

    def fake_verify(token: str, *, client=None):
        if token == "token-alice":
            return {"sub": "user_alice"}
        if token == "token-bob":
            return {"sub": "user_bob"}
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_TOKEN", "message": "nope", "details": {}},
        )

    monkeypatch.setattr(clerk_auth, "verify_clerk_token", fake_verify)
    db_path = tmp_path / "test_clerk.db"
    init_db(db_path)
    with TestClient(create_app()) as client:
        yield client
    get_settings.cache_clear()
    clerk_auth.clear_jwks_cache()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_unauthenticated_rejected_in_clerk_mode(clerk_client):
    response = clerk_client.get("/api/deploys")
    assert response.status_code == 401


def test_invalid_token_rejected(clerk_client):
    response = clerk_client.get("/api/deploys", headers=_auth("garbage"))
    assert response.status_code == 401


def test_valid_token_accepted(clerk_client):
    response = clerk_client.get("/api/deploys", headers=_auth("token-alice"))
    assert response.status_code == 200


def test_cross_user_run_access_rejected(clerk_client):
    created = clerk_client.post(
        "/api/deploy", json=_deploy_payload(), headers=_auth("token-alice")
    )
    assert created.status_code == 202
    deployment_id = created.json()["deployment_id"]
    # Owner can read.
    assert clerk_client.get(f"/api/deploy/{deployment_id}", headers=_auth("token-alice")).status_code == 200
    # Another user gets 404 (no existence oracle).
    denied = clerk_client.get(f"/api/deploy/{deployment_id}", headers=_auth("token-bob"))
    assert denied.status_code == 404
    # Bob's list does not contain Alice's run.
    listed = clerk_client.get("/api/deploys", headers=_auth("token-bob")).json()
    assert all(r["deployment_id"] != deployment_id for r in listed["runs"])
    # Events/logs also scoped.
    assert clerk_client.get(f"/api/deploy/{deployment_id}/events", headers=_auth("token-bob")).status_code == 404
    assert clerk_client.get(f"/api/deploy/{deployment_id}/logs", headers=_auth("token-bob")).status_code == 404


def test_user_id_from_body_not_trusted(clerk_client):
    created = clerk_client.post(
        "/api/deploy", json=_deploy_payload(), headers=_auth("token-alice")
    )
    deployment_id = created.json()["deployment_id"]
    record = clerk_client.get(f"/api/deploy/{deployment_id}", headers=_auth("token-alice")).json()
    assert record["owner_sub"] == "user_alice"


def test_missing_production_auth_config_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(tmp_path / "test_prod.db"))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("MEDHA_CORS_ORIGINS", "http://localhost:3000")
    monkeypatch.setenv("MEDHA_WORKFLOW_STEP_DELAY_SECONDS", "0")
    monkeypatch.setenv("MEDHA_ENV", "production")
    monkeypatch.setenv("MEDHA_AUTH_MODE", "clerk")
    monkeypatch.setenv("CLERK_DOMAIN", "")
    monkeypatch.setenv("CLERK_JWKS_URL", "")
    get_settings.cache_clear()
    init_db(tmp_path / "test_prod.db")
    try:
        with TestClient(create_app()) as client:
            response = client.get("/api/deploys", headers=_auth("token-alice"))
            assert response.status_code == 503
    finally:
        get_settings.cache_clear()
        clerk_auth.clear_jwks_cache()


def test_off_mode_legacy_behavior_unaffected(client):
    response = client.post("/api/deploy", json=_deploy_payload())
    assert response.status_code == 202
    deployment_id = response.json()["deployment_id"]
    assert client.get(f"/api/deploy/{deployment_id}").status_code == 200
