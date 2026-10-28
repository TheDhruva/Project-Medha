"""Phase 2 security + integrity regression tests (no network, no Docker)."""
from __future__ import annotations

import app.api.webhooks as webhooks
from app.core.rate_limit import check_rate_limit, reset_rate_limits
from app.ai.redact import REDACTED, redact_mapping, redact_text
from app.core.repo_url import RepositoryUrlError, ensure_approved_github_host, resolve_and_recheck
from app.execution.policy import PolicyViolation, check_real_execution_policy
from app.execution.real_executor import RealExecutor
from app.models.deployment import ProposalRecord
from app.workflow.planning import _canonical_plan, _plan_hash


class _FakePlan:
    deployment_id = "dep_test"

    def model_dump(self, mode: str = "json"):  # noqa: ANN001, ANN202
        return {"services": [{"name": "web"}], "actions": [], "dependencies": {}, "networks": [], "volumes": [], "compose": {}}


def test_rate_limit_blocks_over_budget():
    reset_rate_limits()
    key = "test-rate-limit-key"
    for _ in range(60):
        assert check_rate_limit(key, limit_per_minute=60)
    assert not check_rate_limit(key, limit_per_minute=60)
    reset_rate_limits()


def test_redact_strips_tokens_and_url_creds():
    assert redact_text("https://user:pass@github.com/o/r.git") == f"https://{REDACTED}@github.com/o/r.git"
    assert REDACTED in redact_text("token ghp_abcdef1234567890 leaked")
    cleaned = redact_mapping({"api_token": "secret", "note": "https://a:b@x.com/y"})
    assert cleaned["api_token"] == REDACTED
    assert f"{REDACTED}@" in cleaned["note"]


def test_redact_matches_prefixed_secret_variable_names():
    # A leading \b sits between two word chars in db_password/user_token and
    # used to skip them entirely; the value must still be redacted.
    for line in ("db_password=synthpass1234", "user_token: synthtok99",
                 "APP_SECRET = 'synthsecret'"):
        out = redact_text(line)
        assert REDACTED in out, f"{line!r} was not redacted"
        assert "synthpass1234" not in out
        assert "synthtok99" not in out
        assert "synthsecret" not in out


def test_redact_strips_google_api_keys():
    key = "AIza" + "Sy" + "D" + "-" + "a" * 30   # realistic AIza… shape
    assert redact_text(f"key={key}") == f"key={REDACTED}"
    assert key not in redact_text(f"found {key} in config")


def test_repo_url_blocks_metadata_and_private():
    for bad in ("https://169.254.169.254/latest", "https://metadata.google.internal/x", "https://user:pw@github.com/o/r.git"):
        try:
            from app.core.repo_url import validate_repository_url
            validate_repository_url(bad)
        except RepositoryUrlError:
            continue
        raise AssertionError(f"should block {bad}")


def test_resolve_and_recheck_blocks_private():
    try:
        resolve_and_recheck("localhost")
    except RepositoryUrlError:
        pass  # localhost allowed only by name check path; pinned loopback must block
    try:
        resolve_and_recheck("169.254.169.254")
        raise AssertionError("metadata IP must be blocked")
    except RepositoryUrlError:
        pass


def test_github_host_allowlist():
    assert ensure_approved_github_host("https://github.com/o/r.git") == "github.com"
    try:
        ensure_approved_github_host("https://evil.example.com/o/r.git")
        raise AssertionError("unapproved host must be blocked")
    except RepositoryUrlError:
        pass


def test_plan_hash_binds_repo_and_sha():
    a = _canonical_plan(_FakePlan(), repository_url="https://github.com/o/r.git", target_sha="a" * 40)
    b = _canonical_plan(_FakePlan(), repository_url="https://github.com/o/r.git", target_sha="b" * 40)
    c = _canonical_plan(_FakePlan(), repository_url="https://github.com/o/other.git", target_sha="a" * 40)
    assert _plan_hash(a) != _plan_hash(b)
    assert _plan_hash(a) != _plan_hash(c)


def test_real_executor_fails_closed(monkeypatch):
    import asyncio

    async def _run():
        try:
            await RealExecutor().execute(dockerfile_text="FROM busybox:1.36")
        except PolicyViolation as exc:
            return exc.code
        return "NO_ERROR"

    code = asyncio.run(_run())
    assert code in ("REAL_EXECUTION_NOT_ENABLED", "REAL_EXECUTION_DISABLED_HOSTED", "REAL_BUILDER_UNAVAILABLE")


def test_policy_rejects_privileged_builds(monkeypatch):
    from app.core.config import get_settings
    settings = get_settings()
    old_env, old_mode, old_exec = settings.medha_env, settings.executor_mode, settings.docker_execute
    settings.medha_env, settings.executor_mode, settings.docker_execute = "development", "real", True
    try:
        try:
            check_real_execution_policy(dockerfile_text="FROM x\nADD secrets /etc\n")
            raise AssertionError("ADD must be rejected")
        except PolicyViolation as exc:
            assert exc.code == "POLICY_VIOLATION"
    finally:
        settings.medha_env, settings.executor_mode, settings.docker_execute = old_env, old_mode, old_exec


def test_legacy_proposal_not_visible_cross_user():
    proposal = ProposalRecord(
        proposal_id="prop_x",
        repository="o/r",
        branch="main",
        target_sha="a" * 40,
        created_by="webhook:github",
        created_at="2026-01-01T00:00:00Z",
        idempotency_key="idem-x",
    )
    assert webhooks._may_view(proposal, "user-a") is False
    assert webhooks._may_decide(proposal, "user-a") is False
    assert webhooks._may_view(proposal, "local-operator") is True
