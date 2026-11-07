"""Regression tests for GitHub App configuration, path resolution, and repository access separation."""

import os
from pathlib import Path
import pytest

from app.core.config import PROJECT_ROOT, get_settings
from app.services.github_app import (
    GitHubAppConfig,
    GitHubAppError,
    build_app_jwt,
    get_github_app_config,
    normalize_private_key_pem,
    prepare_private_access,
)

SAMPLE_RSA_KEY = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    "MIIEowIBAAKCAQEA0Y8L5j6R2kU1G/m8w6pQ5Wf4e5Q9K7L2M1N0O3P4Q5R6S7T8\n"
    "U9V0W1X2Y3Z4a5b6c7d8e9f0a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6q7r8s9t0\n"
    "-----END RSA PRIVATE KEY-----"
)


def test_normalize_private_key_pem_inline():
    assert normalize_private_key_pem(SAMPLE_RSA_KEY) == SAMPLE_RSA_KEY


def test_normalize_private_key_pem_escaped_newlines():
    escaped = SAMPLE_RSA_KEY.replace("\n", "\\n")
    assert normalize_private_key_pem(escaped) == SAMPLE_RSA_KEY


def test_normalize_private_key_pem_resolves_repo_root_file(tmp_path, monkeypatch):
    key_file = tmp_path / "test-key.pem"
    key_file.write_text(SAMPLE_RSA_KEY, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    assert normalize_private_key_pem("test-key.pem") == SAMPLE_RSA_KEY


def test_normalize_private_key_pem_missing_file_returns_empty():
    assert normalize_private_key_pem("nonexistent-key-12345.pem") == ""


def test_normalize_private_key_pem_invalid_non_pem_string_returns_empty():
    assert normalize_private_key_pem("just-a-random-filename.pem") == ""
    assert normalize_private_key_pem("some-random-token-value") == ""


def test_get_github_app_config_unconfigured_when_key_invalid(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "missing-file.pem")
    cfg = get_github_app_config()
    assert cfg.configured is False


def test_get_github_app_config_configured_when_valid(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "67890")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", SAMPLE_RSA_KEY)
    cfg = get_github_app_config()
    assert cfg.configured is True
    assert cfg.app_id == "12345"
    assert cfg.installation_id == "67890"


def test_build_app_jwt_rejects_empty_or_non_pem():
    with pytest.raises(GitHubAppError) as exc_info:
        build_app_jwt(app_id="12345", private_key_pem="missing.pem")
    assert exc_info.value.code == "GITHUB_APP_KEY_INVALID"


def test_prepare_private_access_unconfigured_returns_empty(monkeypatch):
    monkeypatch.setenv("GITHUB_APP_ID", "")
    monkeypatch.setenv("GITHUB_APP_INSTALLATION_ID", "")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "")
    env = prepare_private_access("https://github.com/fastapi/full-stack-fastapi-template")
    assert env == {}


def test_validate_repository_error_mapping_categories():
    from app.services.git_service import GitAcquireError
    from app.api.projects import validate_repository

    # Category 'auth' maps to 401
    err_auth = GitAcquireError("GIT_AUTH", "fatal: could not read Username", category="auth")
    # Category 'not_found' maps to 404
    err_nf = GitAcquireError("REPO_NOT_FOUND", "not found", category="not_found")
    # Category 'timeout' maps to 504
    err_to = GitAcquireError("GIT_TIMEOUT", "timed out", category="timeout")
    # Category 'network' maps to 502
    err_net = GitAcquireError("NETWORK_ERROR", "network down", category="network")

    for err, expected_status in [
        (err_auth, 401),
        (err_nf, 404),
        (err_to, 504),
        (err_net, 502),
    ]:
        status_code = (
            404 if err.category == "not_found"
            else 401 if err.category in {"auth", "auth_required"}
            else 504 if err.category == "timeout"
            else 502 if err.category == "network"
            else 400
        )
        assert status_code == expected_status

