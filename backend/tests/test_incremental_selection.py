"""Incremental check selection from changed paths (acceptance 5 + 6).

A styling change must not trigger backend security agents, an auth-path
change must keep authorization checks in play, and a lockfile change must
trigger dependency analysis. Unknown/truncated changesets and missing or
stale full-scan state always fail safe to a full scan.
"""

from __future__ import annotations

from app.analysis.selection import plan_scan

LAST_FULL = "2026-10-01T00:00:00+00:00"
NOW = "2026-10-02T00:00:00+00:00"  # 1 day later: incremental is allowed


def _plan(paths, **kw):
    kw.setdefault("last_full_scan_at", LAST_FULL)
    kw.setdefault("now", NOW)
    return plan_scan(paths, **kw)


# -- criterion 5: path-based selection --------------------------------------

def test_styling_change_runs_no_external_scanner():
    plan = _plan(["frontend/styles/theme.css", "docs/README.md"])
    assert plan.mode == "incremental"
    assert plan.scanner_names == []
    # builtin policy checks still run; only external scanners are skipped
    assert set(plan.skipped) == {"semgrep", "trivy", "gitleaks"}
    assert plan.authorization_touched is False


def test_lockfile_change_triggers_dependency_scanner():
    plan = _plan(["package-lock.json"])
    assert plan.mode == "incremental"
    assert plan.scanner_names == ["trivy"]
    assert "semgrep" in plan.skipped and "gitleaks" in plan.skipped
    assert plan.authorization_touched is False


def test_shared_auth_helper_keeps_authorization_checks():
    plan = _plan(["app/auth/session.py", "app/middleware/authz.js"])
    assert plan.mode == "incremental"
    assert plan.scanner_names == ["semgrep"]
    assert plan.authorization_touched is True


def test_deploy_config_change_triggers_secret_scan():
    plan = _plan(["Dockerfile", ".github/workflows/ci.yml"])
    assert plan.mode == "incremental"
    assert "gitleaks" in plan.scanner_names
    assert plan.authorization_touched is False


def test_env_file_classified_as_secret():
    plan = _plan(["backend/.env.production"])
    assert plan.mode == "incremental"
    assert plan.scanner_names == ["gitleaks"]


def test_code_change_runs_sast():
    plan = _plan(["src/server.js"])
    assert plan.mode == "incremental"
    assert plan.scanner_names == ["semgrep"]


def test_mixed_changeset_selects_union_of_scanners():
    plan = _plan(["src/app.py", "requirements.txt", "docker-compose.yml"])
    assert plan.mode == "incremental"
    assert plan.scanner_names == ["gitleaks", "semgrep", "trivy"]


# -- criterion 6: fail-safe full scans ---------------------------------------

def test_unknown_changeset_is_full():
    plan = plan_scan(None, last_full_scan_at=LAST_FULL, now=NOW)
    assert plan.full is True


def test_empty_changeset_is_full():
    plan = plan_scan([], last_full_scan_at=LAST_FULL, now=NOW)
    assert plan.full is True


def test_truncated_payload_is_full():
    plan = _plan(["src/app.py"], truncated=True)
    assert plan.full is True
    assert any("truncated" in r for r in plan.reasons)


def test_no_previous_full_scan_is_full():
    plan = plan_scan(["frontend/styles/a.css"], last_full_scan_at=None, now=NOW)
    assert plan.full is True
    assert any("baseline coverage" in r for r in plan.reasons)


def test_periodic_full_rescan_supersedes_incremental():
    plan = _plan(
        ["frontend/styles/a.css"],
        now="2026-10-20T00:00:00+00:00",  # 19 days after last full scan
    )
    assert plan.full is True
    assert any("periodic full rescan" in r for r in plan.reasons)


def test_unreadable_full_scan_timestamp_is_full():
    plan = plan_scan(
        ["src/app.py"], last_full_scan_at="not-a-date", now=NOW
    )
    assert plan.full is True


def test_unclassifiable_paths_fail_full():
    # Paths that classify to nothing (blank entries) → full, not silent skip.
    plan = plan_scan([""], last_full_scan_at=LAST_FULL, now=NOW)
    assert plan.full is True
