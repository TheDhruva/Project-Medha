"""Phase 2 final regression tests (offline: no network, no Docker daemon)."""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return (out.stdout or "").strip()


@pytest.fixture()
def local_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "t")
    (repo / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "one")
    return repo


# --- source pinning -------------------------------------------------------

def test_resolve_branch_to_immutable_sha(local_repo: Path):
    from app.services.git_service import _FULL_SHA_RE, resolve_ref_to_sha

    sha = resolve_ref_to_sha(str(local_repo), "main")
    assert _FULL_SHA_RE.match(sha)
    head = _git(local_repo, "rev-parse", "HEAD").lower()
    assert sha == head


def test_moved_branch_resolves_differently(local_repo: Path):
    from app.services.git_service import resolve_ref_to_sha

    before = resolve_ref_to_sha(str(local_repo), "main")
    (local_repo / "v2.txt").write_text("v2", encoding="utf-8")
    _git(local_repo, "add", ".")
    _git(local_repo, "commit", "-m", "two")
    after = resolve_ref_to_sha(str(local_repo), "main")
    assert before != after  # approval bound to `before` is now STALE


def test_resolve_rejects_unknown_and_empty(local_repo: Path):
    from app.services.git_service import GitAcquireError, resolve_ref_to_sha

    for bad in ("", "no-such-branch-xyz", "0" * 40):
        with pytest.raises(GitAcquireError):
            resolve_ref_to_sha(str(local_repo), bad)


def test_remote_private_literal_blocked_without_network():
    from app.services.git_service import GitAcquireError, resolve_ref_to_sha

    with pytest.raises(GitAcquireError):
        resolve_ref_to_sha("http://169.254.169.254/o/r.git", "main")


def test_submodule_guards_reject_local_and_nested(tmp_path: Path):
    from app.services.git_service import GitAcquireError, _reject_unsafe_submodules

    evil = tmp_path / "checkout"
    evil.mkdir()
    (evil / ".gitmodules").write_text(
        '[submodule "x"]\n\tpath = x\n\turl = /etc/passwd\n', encoding="utf-8"
    )
    with pytest.raises(GitAcquireError):
        _reject_unsafe_submodules(evil)


# --- GitHub App ------------------------------------------------------------

def _rsa_key() -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


def test_app_jwt_short_lived():
    import jwt

    from app.services.github_app import build_app_jwt

    pem = _rsa_key()
    token = build_app_jwt(app_id="123", private_key_pem=pem, now=1_700_000_000.0)
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["iss"] == "123"
    assert 0 < payload["exp"] - payload["iat"] <= 600


def test_installation_token_via_transport(monkeypatch):
    import app.services.github_app as gh

    monkeypatch.setattr(
        gh.get_settings(), "github_app_id", "123", raising=False,
    )
    settings = gh.get_settings()
    monkeypatch.setattr(settings, "github_app_installation_id", "456", raising=False)
    monkeypatch.setattr(settings, "github_app_private_key", _rsa_key(), raising=False)

    class Fake:
        def mint_installation_token(self, *, app_id, installation_id):
            assert app_id == "123" and installation_id == "456"
            return "tok_abc"

    assert gh.mint_installation_token(transport=Fake()) == "tok_abc"
    env = gh.git_env_with_token("tok_abc")
    assert "tok_abc" in env["GIT_CONFIG_VALUE_0"]
    assert "tok_abc" not in str(gh.redact_token_env(env))


def test_repo_access_requires_contents_permission(monkeypatch):
    import app.services.github_app as gh

    monkeypatch.setattr(
        gh, "_api_request",
        lambda *a, **k: (200, {"permissions": {"contents": "read"}}),
    )
    assert gh.check_repository_access(repository="o/r", token="t")["permissions"]
    monkeypatch.setattr(
        gh, "_api_request", lambda *a, **k: (200, {"permissions": {}}),
    )
    with pytest.raises(gh.GitHubAppError):
        gh.check_repository_access(repository="o/r", token="t")


def test_private_clone_uses_token_env_not_url(local_repo: Path, monkeypatch, tmp_path: Path):
    import app.services.git_service as gs
    import app.services.github_app as gh

    seen: dict = {}

    real_acquire = gs.acquire_repository

    def spy(deployment_id, url, *, ref_sha=None, token_env=None):
        seen["token_env"] = token_env
        seen["url"] = url
        assert token_env and "Bearer" in token_env["GIT_CONFIG_VALUE_0"]
        assert "tok_" not in url  # never embedded in the URL
        return real_acquire(deployment_id, str(local_repo), ref_sha=ref_sha)

    monkeypatch.setattr(gs, "acquire_repository", spy)
    monkeypatch.setattr(gh, "mint_installation_token", lambda **k: "tok_secret")
    monkeypatch.setattr(gh, "check_repository_access", lambda **k: {"ok": True})
    out = gh.clone_private_repository(
        repository_url=str(local_repo), repository="o/r", dest_name="dep_privtest",
    )
    assert out["method"] in {"local_copy", "local_archive"}


# --- build profiles ---------------------------------------------------------

def test_detect_static_python_node(tmp_path: Path):
    from app.execution.profiles import UnsupportedStack, detect_profile

    static = tmp_path / "s"
    static.mkdir()
    (static / "index.html").write_text("x", encoding="utf-8")
    assert detect_profile(static).name == "static"

    py = tmp_path / "p"
    py.mkdir()
    (py / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    (py / "app.py").write_text("app = 1", encoding="utf-8")
    assert detect_profile(py).name == "python"

    node = tmp_path / "n"
    node.mkdir()
    (node / "package.json").write_text('{"scripts": {"start": "node i.js"}}', encoding="utf-8")
    assert detect_profile(node).name == "node"

    empty = tmp_path / "e"
    empty.mkdir()
    with pytest.raises(UnsupportedStack):
        detect_profile(empty)


def test_controlled_dockerfile_ignores_repo_dockerfile(tmp_path: Path):
    from app.execution.profiles import detect_profile, render_dockerfile

    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "package.json").write_text("{}", encoding="utf-8")
    (repo / "Dockerfile").write_text("FROM evil\nRUN rm -rf /\n", encoding="utf-8")
    text = render_dockerfile(detect_profile(repo), checkout=repo)
    assert "evil" not in text and "rm -rf" not in text
    assert "node:22-alpine" in text


# --- real executor fails closed ----------------------------------------------

def test_real_executor_fails_closed_no_daemon(tmp_path: Path, monkeypatch):
    import app.execution.real_executor as rx
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "medha_env", "development", raising=False)
    monkeypatch.setattr(settings, "executor_mode", "real", raising=False)
    monkeypatch.setattr(settings, "docker_execute", True, raising=False)
    monkeypatch.setattr(rx, "runtime_available", lambda: (False, "no daemon"))
    (tmp_path / "index.html").write_text("x", encoding="utf-8")
    result = asyncio.run(
        rx.RealExecutor().deploy(deployment_id="dep_x", checkout=tmp_path)
    )
    assert result.ok is False
    assert result.code == "REAL_BUILDER_UNAVAILABLE"
    assert result.execution_mode == "real"


def test_container_logs_never_fabricates():
    from app.execution import docker_ops

    out = docker_ops.container_logs("medha_no_such_container_xyz", tail=10)
    assert out["available"] is False
    assert out["stdout"] == "" and out["stderr"] == ""


def test_readiness_rejects_non_loopback():
    from app.execution import docker_ops

    out = docker_ops.wait_http_readiness(8080, host="example.com", timeout=1, grace=0)
    assert out["status"] == "failed"


# --- atomic state + rate limit + config ---------------------------------------

def test_terminal_state_not_overwritten(tmp_path: Path):
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord

    db = tmp_path / "t.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id="dep_atomic", repository_url=str(tmp_path),
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, status=DeploymentStatus.CANCELLED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    updated = repo.update_status(
        "dep_atomic", status=DeploymentStatus.COMPLETED, updated_at=utc_now_iso(),
    )
    assert updated is not None and updated.status == DeploymentStatus.CANCELLED


def test_client_ip_ignores_spoofed_xff():
    from app.core.rate_limit import client_ip

    class Req:
        client = type("C", (), {"host": "1.2.3.4"})()
        headers = {"x-forwarded-for": "9.9.9.9"}

    assert client_ip(Req()) == "1.2.3.4"
    assert client_ip(Req(), trusted_proxy="1.2.3.4") == "9.9.9.9"


def test_real_execution_config_validation(monkeypatch):
    from app.core.config import get_settings

    settings = get_settings()
    old = (settings.medha_env, settings.executor_mode, settings.docker_execute)
    settings.medha_env, settings.executor_mode, settings.docker_execute = (
        "production", "real", True,
    )
    try:
        assert settings.hosted_security_error() is not None
        assert settings.real_execution_error() is not None
    finally:
        settings.medha_env, settings.executor_mode, settings.docker_execute = old


def test_production_rejects_docker_execute_flag():
    from app.core.config import Settings

    prod = {
        "MEDHA_ENV": "production",
        "MEDHA_AUTH_MODE": "clerk",
        "CLERK_DOMAIN": "x.clerk.accounts.dev",
        "MEDHA_API_TOKEN": "t",
        "MEDHA_DATABASE_URL": "postgresql://u:p@h:5432/db",
        "MEDHA_EXECUTOR_MODE": "disabled",
    }
    assert Settings(**{**prod, "MEDHA_DOCKER_EXECUTE": "false"}).hosted_security_error() is None
    err = Settings(**{**prod, "MEDHA_DOCKER_EXECUTE": "true"}).hosted_security_error()
    assert err is not None and "MEDHA_DOCKER_EXECUTE" in err


def test_cross_tenant_owned_record_blocked(monkeypatch):
    import asyncio

    import app.api.deploy as deploy_api

    class Rec:
        owner_sub = "user-a"
        project_id = None

    monkeypatch.setattr(deploy_api.repo, "get", lambda did: Rec())
    assert asyncio.run(deploy_api._owned_record("dep_x", "user-b")) is None
    assert asyncio.run(deploy_api._owned_record("dep_x", "user-a")) is not None


def test_build_verb_still_rejected_at_gateway():
    import pytest as _pytest

    from app.execution import docker_ops

    assert "build" not in docker_ops.ALLOWED_VERBS
    with _pytest.raises(docker_ops.DockerOpsError) as exc:
        docker_ops._run(["build", "."], check=False)
    assert exc.value.code == "VERB_REJECTED"


def test_plan_hash_binds_resolved_sha_not_moving_ref():
    from app.workflow.planning import _canonical_plan, _plan_hash

    class _FakePlan:
        deployment_id = "dep_test"

        def model_dump(self, mode="json"):
            return {"services": [], "actions": [], "dependencies": {}}

    base = _canonical_plan(_FakePlan(), repository_url="https://github.com/o/r.git",
                           target_sha="a" * 40)
    moved = _canonical_plan(_FakePlan(), repository_url="https://github.com/o/r.git",
                            target_sha="b" * 40)
    assert _plan_hash(base) != _plan_hash(moved)


def test_local_unpinned_ref_falls_back_with_warning(tmp_path):
    """Local symbolic refs keep legacy behavior; remotes fail closed."""
    import asyncio as _asyncio

    from app.core.enums import DeployMode, DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord
    from app.workflow.planning import PlanningPipeline

    db = tmp_path / "t.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("local", encoding="utf-8")
    repo.create(DeploymentRecord(
        deployment_id="dep_unpinned", repository_url=str(src),
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=None, target_revision="symbolic-ref",
        status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    _asyncio.run(
        PlanningPipeline(repo=repo).run("dep_unpinned", plan_only=True)
    )
    record = repo.get("dep_unpinned")
    assert record is not None
    texts = [e.message for e in repo.list_events("dep_unpinned")]
    assert any("without commit binding" in t for t in texts)


# --- GitHub App private-access wiring -----------------------------------------

def _configure_app(monkeypatch):
    import app.services.github_app as gh

    settings = gh.get_settings()
    monkeypatch.setattr(settings, "github_app_id", "123", raising=False)
    monkeypatch.setattr(settings, "github_app_installation_id", "456", raising=False)
    monkeypatch.setattr(settings, "github_app_private_key", _rsa_key(), raising=False)
    return gh


def test_parse_github_repo():
    import app.services.github_app as gh

    assert gh.parse_github_repo("https://github.com/octo/demo.git") == "octo/demo"
    assert gh.parse_github_repo("https://github.com/octo/demo") == "octo/demo"
    assert gh.parse_github_repo("git@github.com:octo/demo.git") is None  # ssh never authed
    assert gh.parse_github_repo("/tmp/local") is None
    assert gh.parse_github_repo("https://evil.example.com/octo/demo.git") is None
    assert gh.parse_github_repo("https://user:pw@github.com/octo/demo.git") is None
    assert gh.parse_github_repo("https://github.com/onlyowner") is None


def test_prepare_private_access_anonymous_paths(monkeypatch):
    import app.services.github_app as gh

    _configure_app(monkeypatch)
    assert gh.prepare_private_access("/tmp/local") == {}
    assert gh.prepare_private_access("git@github.com:octo/demo.git") == {}


def test_prepare_private_access_unconfigured_returns_empty(monkeypatch):
    import app.services.github_app as gh

    settings = gh.get_settings()
    monkeypatch.setattr(settings, "github_app_id", "", raising=False)
    monkeypatch.setattr(settings, "github_app_installation_id", "", raising=False)
    monkeypatch.setattr(settings, "github_app_private_key", "", raising=False)
    assert gh.prepare_private_access("https://github.com/octo/demo.git") == {}


def test_prepare_private_access_mints_and_scopes(monkeypatch):
    import app.services.github_app as gh

    _configure_app(monkeypatch)
    seen: dict = {}

    class FakeTransport:
        def mint_installation_token(self, *, app_id, installation_id):
            assert (app_id, installation_id) == ("123", "456")
            return "tok_test_secret"

    def fake_check(*, repository, token, timeout=15.0):
        seen["repository"] = repository
        seen["token"] = token
        return {"permissions": {"contents": "read"}}

    monkeypatch.setattr(gh, "check_repository_access", fake_check)
    env = gh.prepare_private_access(
        "https://github.com/octo/demo.git", transport=FakeTransport()
    )
    assert seen == {"repository": "octo/demo", "token": "tok_test_secret"}
    assert env["GIT_CONFIG_VALUE_0"] == "Authorization: Bearer tok_test_secret"
    assert "tok_test_secret" not in str(gh.redact_token_env(env))


def test_prepare_private_access_denied_fails_closed(monkeypatch):
    import app.services.github_app as gh

    _configure_app(monkeypatch)

    class FakeTransport:
        def mint_installation_token(self, *, app_id, installation_id):
            return "tok_test_secret"

    def denied(*, repository, token, timeout=15.0):
        raise gh.GitHubAppError("GITHUB_INSUFFICIENT_PERMISSIONS", "no access")

    monkeypatch.setattr(gh, "check_repository_access", denied)
    with pytest.raises(gh.GitHubAppError) as exc:
        gh.prepare_private_access(
            "https://github.com/octo/demo.git", transport=FakeTransport()
        )
    assert exc.value.code == "GITHUB_INSUFFICIENT_PERMISSIONS"
    assert "tok_test_secret" not in str(exc.value.message)


def _pipeline_db(tmp_path):
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository

    db = tmp_path / "t.db"
    init_db(db)
    return DeploymentRepository(db_path=db)


def test_pipeline_wires_app_token_to_acquire(tmp_path, monkeypatch):
    """Private GitHub URL: token minted, scoped, passed to acquire; never leaked."""
    import asyncio as _asyncio
    import json as _json

    import app.services.github_app as gh
    import app.workflow.planning as planning
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.models.deployment import DeploymentRecord, ProposalRecord
    from app.database.repositories import ProposalRepository
    from app.services.git_service import RepoAcquisition
    from app.workflow.planning import PlanningPipeline

    _configure_app(monkeypatch)
    monkeypatch.setattr(gh, "mint_installation_token", lambda **k: "tok_test_secret")
    seen: dict = {}

    def fake_check(*, repository, token, timeout=15.0):
        seen["repository"] = repository
        assert token == "tok_test_secret"
        return {"full_name": repository, "private": True,
                "permissions": {"contents": "read"}}

    monkeypatch.setattr(gh, "check_repository_access", fake_check)

    sha = "a" * 40
    fixture = Path("tests/fixtures/repos/compose_app").resolve()

    def fake_acquire(deployment_id, url, *, ref_sha=None, token_env=None):
        seen["url"] = url
        seen["token_env"] = dict(token_env or {})
        seen["ref_sha"] = ref_sha
        assert "tok_test_secret" not in url
        return RepoAcquisition(
            path=fixture, method="local_archive", cleaned_url=url, checked_sha=sha,
        )

    monkeypatch.setattr(planning, "acquire_repository", fake_acquire)

    repo = _pipeline_db(tmp_path)
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id="dep_priv", repository_url="https://github.com/octo/demo.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=None, target_revision=sha,
        status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    proposals = ProposalRepository(db_path=repo.db_path)
    proposal = ProposalRecord(
        proposal_id="prp_priv", repository="octo/demo", branch="main",
        base_sha=None, target_sha=sha, deployment_id="dep_priv",
        status="analyzing", created_by="webhook:github", created_at=now,
        idempotency_key="github:priv-1",
    )
    proposals.create(proposal)

    _asyncio.run(PlanningPipeline(repo=repo).run(
        "dep_priv", plan_only=True, proposal_id="prp_priv",
    ))

    assert seen["repository"] == "octo/demo"
    assert seen["url"] == "https://github.com/octo/demo.git"
    assert seen["ref_sha"] == sha
    assert seen["token_env"].get("GIT_CONFIG_VALUE_0") == \
        "Authorization: Bearer tok_test_secret"
    settled = proposals.get("prp_priv")
    assert settled is not None and settled.status == "ready", settled
    # Token must appear nowhere in persisted events, records, or proposals.
    for event in repo.list_events("dep_priv"):
        assert "tok_test_secret" not in _json.dumps(event.to_sse_payload())
    stored = repo.get("dep_priv")
    assert stored is not None
    assert "tok_test_secret" not in _json.dumps(stored.to_api())
    assert "tok_test_secret" not in _json.dumps(proposals.get("prp_priv").to_api())


def test_pipeline_private_access_failure_fails_closed(tmp_path, monkeypatch):
    import asyncio as _asyncio

    import app.services.github_app as gh
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.models.deployment import DeploymentRecord
    from app.workflow.planning import PlanningPipeline

    _configure_app(monkeypatch)
    monkeypatch.setattr(gh, "mint_installation_token", lambda **k: "tok_test_secret")

    def revoked(*, repository, token, timeout=15.0):
        raise gh.GitHubAppError("GITHUB_INSUFFICIENT_PERMISSIONS", "removed")

    monkeypatch.setattr(gh, "check_repository_access", revoked)

    repo = _pipeline_db(tmp_path)
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id="dep_privdeny",
        repository_url="https://github.com/octo/demo.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=None, target_revision="b" * 40,
        status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    _asyncio.run(PlanningPipeline(repo=repo).run("dep_privdeny"))
    stored = repo.get("dep_privdeny")
    assert stored is not None
    assert stored.status == DeploymentStatus.FAILED
    assert stored.error_summary
    assert "tok_test_secret" not in (stored.error_summary or "")
    assert "GITHUB_INSUFFICIENT_PERMISSIONS" in (stored.explain_technical or "")


def test_pipeline_mismatched_checkout_head_fails_closed(tmp_path, monkeypatch):
    """A shallow checkout whose HEAD != approved SHA must fail, never deploy."""
    import asyncio as _asyncio
    import shutil as _shutil
    import subprocess as _sp

    import app.workflow.planning as planning
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.models.deployment import DeploymentRecord
    from app.services.git_service import RepoAcquisition
    from app.workflow.planning import PlanningPipeline

    src = Path("tests/fixtures/repos/compose_app").resolve()
    work = tmp_path / "work"
    _shutil.copytree(src, work)
    _sp.run(["git", "init", "-q"], cwd=work, check=True)
    _sp.run(["git", "config", "user.email", "t@t"], cwd=work, check=True)
    _sp.run(["git", "config", "user.name", "t"], cwd=work, check=True)
    _sp.run(["git", "add", "-A"], cwd=work, check=True)
    _sp.run(["git", "commit", "-qm", "one"], cwd=work, check=True)
    head = _sp.run(
        ["git", "rev-parse", "HEAD"], cwd=work, check=True,
        capture_output=True, text=True,
    ).stdout.strip().lower()

    approved = "b" * 40  # approved SHA differs from the real checkout HEAD
    assert head != approved

    def fake_acquire(deployment_id, url, *, ref_sha=None, token_env=None):
        return RepoAcquisition(
            path=work, method="shallow_clone", cleaned_url=url, checked_sha=approved,
        )

    monkeypatch.setattr(planning, "acquire_repository", fake_acquire)

    repo = _pipeline_db(tmp_path)
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id="dep_mismatch",
        repository_url="https://github.com/octo/demo.git",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=None, target_revision=approved,
        status=DeploymentStatus.STARTED, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    _asyncio.run(PlanningPipeline(repo=repo).run("dep_mismatch"))
    stored = repo.get("dep_mismatch")
    assert stored is not None
    assert stored.status == DeploymentStatus.FAILED
    assert "SHA_MISMATCH" in (stored.explain_technical or "")
