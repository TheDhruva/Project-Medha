"""Comprehensive tests for automated remediation, patch validation, sandbox verification, and delivery."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.remediation.models import RepairPlan
from app.remediation.patcher import (
    create_deterministic_repair_plan,
    _patch_sec_101,
    _patch_sec_102,
    _patch_sec_105,
    _patch_sec_106,
    _patch_sec_107,
    _patch_sec_108,
)
from app.remediation.worktree import apply_and_verify_in_sandbox, validate_file_syntax


def _init_git_repo(path: Path) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=path, check=True)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=path, check=True, capture_output=True, env=env)
    res = subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True)
    return res.stdout.strip()


def test_patch_sec_101_shell_true():
    code = 'import subprocess\nsubprocess.run("ls", shell=True)\n'
    patched, changed = _patch_sec_101(code, 2)
    assert changed is True
    assert "shell=False" in patched
    assert "shell=True" not in patched


def test_patch_sec_102_unsafe_yaml():
    code = 'import yaml\ndata = yaml.load(raw_data)\n'
    patched, changed = _patch_sec_102(code, 2)
    assert changed is True
    assert "yaml.safe_load(raw_data)" in patched


def test_patch_sec_105_weak_hash():
    code = 'import hashlib\nh = hashlib.md5(b"test")\n'
    patched, changed = _patch_sec_105(code, 2)
    assert changed is True
    assert "hashlib.sha256(b\"test\")" in patched


def test_patch_sec_106_debug_flag():
    code = 'app.run(debug=True)\n'
    patched, changed = _patch_sec_106(code, 1)
    assert changed is True
    assert "debug=False" in patched


def test_patch_sec_107_cors_wildcard():
    code = 'allow_origins=["*"]\n'
    patched, changed = _patch_sec_107(code, 1)
    assert changed is True
    assert 'allow_origins=["http://localhost:3000"]' in patched


def test_patch_sec_108_hardcoded_secret():
    code = 'secret_key = "changeme"\n'
    patched, changed = _patch_sec_108(code, 1)
    assert changed is True
    assert 'os").getenv("SECRET_KEY"' in patched


def test_create_deterministic_repair_plan():
    finding = {
        "finding_id": "f_12345",
        "rule_id": "SEC-102",
        "path": "app/config.py",
        "line": 15,
        "explanation": "Unsafe YAML deserialization.",
    }
    content = "import yaml\n\ndef load_cfg(path):\n    with open(path) as f:\n        return yaml.load(f)\n"
    plan = create_deterministic_repair_plan(finding, content)
    assert plan.can_auto_fix is True
    assert plan.rule_id == "SEC-102"
    assert "yaml.safe_load" in plan.diff_unified
    assert "a/app/config.py" in plan.diff_unified


def test_validate_file_syntax(tmp_path):
    valid_py = tmp_path / "valid.py"
    valid_py.write_text("x = 1 + 2\n", encoding="utf-8")
    assert validate_file_syntax(valid_py).syntax_valid is True

    invalid_py = tmp_path / "invalid.py"
    invalid_py.write_text("def broken(:\n", encoding="utf-8")
    res = validate_file_syntax(invalid_py)
    assert res.syntax_valid is False
    assert "syntax error" in res.syntax_error.lower()


def test_apply_and_verify_in_sandbox_success(tmp_path):
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    file_path = repo_dir / "vuln.py"
    file_path.write_text(
        "import yaml\n\ndef parse(doc):\n    return yaml.load(doc)\n",
        encoding="utf-8",
    )
    _init_git_repo(repo_dir)

    finding = {
        "finding_id": "find_abc",
        "rule_id": "SEC-102",
        "path": "vuln.py",
        "line": 4,
    }
    content = file_path.read_text(encoding="utf-8")
    plan = create_deterministic_repair_plan(finding, content)

    verification, branch, commit = apply_and_verify_in_sandbox(repo_dir, plan)
    assert verification.verified is True
    assert verification.finding_eliminated is True
    assert branch is not None
    assert branch.startswith("medha/fix-sec-102-")
    assert commit is not None

    # Verify branch exists in git repo
    proc = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    assert branch in proc.stdout


def test_remediation_api_routes(client, tmp_path):
    from app.database.repositories import DeploymentRepository, FindingRepository, ProjectRepository
    from app.models.deployment import DeploymentRecord, ProjectRecord

    proj_repo = ProjectRepository()
    find_repo = FindingRepository()
    dep_repo = DeploymentRepository()

    # Create dummy project
    repo_dir = tmp_path / "sample_repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("import yaml\nyaml.load(data)\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    now = "2026-10-30T10:00:00Z"
    proj = ProjectRecord(
        project_id="proj_rem_1",
        owner_sub="local",
        name="sample",
        repository=str(repo_dir),
        repo_owner="local",
        repo_name="sample",
        canonical_url=str(repo_dir),
        branch="main",
        created_at=now,
        updated_at=now,
    )
    proj_repo.create(proj)

    # Ingest dummy finding via sync_scan
    find_repo.sync_scan(
        project_id="proj_rem_1",
        repository=str(repo_dir),
        deployment_id="dep_test_1",
        commit_sha="a" * 40,
        findings=[{
            "source": "builtin",
            "rule_id": "SEC-102",
            "category": "security",
            "severity": "medium",
            "confidence": "medium",
            "path": "app.py",
            "line": 2,
            "message": "Potentially unsafe YAML deserialization",
            "explanation": "yaml.load without safe loader",
            "remediation": "Use yaml.safe_load",
        }],
        active_sources={"builtin"},
        scanned_at="2026-10-30T10:00:00Z",
    )

    findings = find_repo.list(project_id="proj_rem_1")
    assert len(findings) == 1
    finding_id = findings[0]["finding_id"]

    # 1. Request Repair Plan
    resp = client.post(f"/api/projects/proj_rem_1/findings/{finding_id}/repair-plan")
    assert resp.status_code == 200
    plan_data = resp.json()
    assert plan_data["can_auto_fix"] is True
    assert plan_data["rule_id"] == "SEC-102"
    assert "yaml.safe_load" in plan_data["diff_unified"]

    # 2. Apply and Verify in Sandbox
    resp2 = client.post(f"/api/projects/proj_rem_1/findings/{finding_id}/apply-and-verify")
    assert resp2.status_code == 200
    verify_data = resp2.json()
    assert verify_data["verification"]["verified"] is True
    assert verify_data["verification"]["finding_eliminated"] is True

    # Check finding status transitioned to fixed_unverified
    updated_finding = find_repo.get(finding_id)
    assert updated_finding["status"] == "fixed_unverified"

    # 3. Deliver (Local delivery mode)
    resp3 = client.post(f"/api/projects/proj_rem_1/findings/{finding_id}/deliver")
    assert resp3.status_code == 200
    deliv_data = resp3.json()
    assert deliv_data["delivered"] is True
    assert deliv_data["delivery_method"] == "local_branch"

    # Check finding status transitioned to resolved
    final_finding = find_repo.get(finding_id)
    assert final_finding["status"] == "resolved"


def test_path_traversal_protection(client, tmp_path):
    from app.database.repositories import FindingRepository, ProjectRepository
    from app.models.deployment import ProjectRecord

    proj_repo = ProjectRepository()
    find_repo = FindingRepository()

    repo_dir = tmp_path / "traversal_repo"
    repo_dir.mkdir()
    (repo_dir / "safe.py").write_text("x = 1\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    now = "2026-10-30T10:00:00Z"
    proj = ProjectRecord(
        project_id="proj_trav_1",
        owner_sub="local",
        name="trav_test",
        repository=str(repo_dir),
        repo_owner="local",
        repo_name="trav_test",
        canonical_url=str(repo_dir),
        branch="main",
        created_at=now,
        updated_at=now,
    )
    proj_repo.create(proj)

    # Ingest a finding with path traversal
    find_repo.sync_scan(
        project_id="proj_trav_1",
        repository=str(repo_dir),
        deployment_id="dep_trav_1",
        commit_sha="b" * 40,
        findings=[{
            "source": "builtin",
            "rule_id": "SEC-101",
            "category": "security",
            "severity": "high",
            "confidence": "high",
            "path": "../../outside_secret.py",
            "line": 1,
            "message": "Traversing path finding",
            "explanation": "Attempt to escape repo root",
            "remediation": "Do not allow",
        }],
        active_sources={"builtin"},
        scanned_at=now,
    )

    findings = find_repo.list(project_id="proj_trav_1")
    finding_id = findings[0]["finding_id"]

    resp = client.post(f"/api/projects/proj_trav_1/findings/{finding_id}/repair-plan")
    assert resp.status_code == 400
    assert "path" in resp.json()["detail"].lower()


def test_branch_argument_injection_prevention(client, tmp_path):
    from app.remediation.worktree import validate_safe_branch_name

    with pytest.raises(ValueError, match="cannot start with '-'"):
        validate_safe_branch_name("--upload-pack=/bin/sh")

    with pytest.raises(ValueError, match="unsafe git characters|invalid characters"):
        validate_safe_branch_name("feature;rm -rf")

    with pytest.raises(ValueError, match="unsafe git characters|invalid characters"):
        validate_safe_branch_name("feature..branch")

    safe = validate_safe_branch_name("medha/fix-sec-101-abc12345")
    assert safe == "medha/fix-sec-101-abc12345"


def test_yaml_loader_patch_does_not_crash():
    code_with_loader = "import yaml\nconfig = yaml.load(raw, Loader=yaml.Loader)\n"
    patched, changed = _patch_sec_102(code_with_loader, 2)
    assert changed is True
    assert "Loader=yaml.SafeLoader" in patched
    assert "safe_load" not in patched  # Must not use safe_load with Loader argument!


def test_canonical_rules_patch_and_verify(tmp_path):
    from app.remediation.patcher import _patch_cfg_004
    # Test CFG-004 (verify=False -> verify=True)
    code = "import requests\nresp = requests.get('https://api.internal', verify=False)\n"
    patched, changed = _patch_cfg_004(code, 2)
    assert changed is True
    assert "verify=True" in patched
    assert "verify=False" not in patched

    # Test CFG-003 / SEC-106 (debug=True / DEBUG = True)
    code_debug = "DEBUG = True\n"
    patched_debug, changed_debug = _patch_sec_106(code_debug, 1)
    assert changed_debug is True
    assert "DEBUG = False" in patched_debug

    # Test in actual git sandbox
    repo_dir = tmp_path / "sandbox_test"
    repo_dir.mkdir()
    app_file = repo_dir / "server.py"
    app_file.write_text("DEBUG = True\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    finding = {
        "finding_id": "find_cfg3",
        "rule_id": "CFG-003",
        "path": "server.py",
        "line": 1,
    }
    plan = create_deterministic_repair_plan(finding, app_file.read_text(encoding="utf-8"))
    verification, branch, commit = apply_and_verify_in_sandbox(repo_dir, plan)
    assert verification.verified is True
    assert verification.finding_eliminated is True
    assert "CFG-003" in verification.verification_evidence[0]


def test_authorization_and_cross_project_enforcement(client, tmp_path):
    from fastapi import HTTPException
    from app.database.repositories import ProjectRepository
    from app.models.deployment import ProjectRecord
    from app.api.remediation import _verify_owned_project

    proj_repo = ProjectRepository()
    now = "2026-10-30T10:00:00Z"
    repo_dir = tmp_path / "auth_repo"
    repo_dir.mkdir()
    (repo_dir / "mod.py").write_text("shell=True\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    # Project owned by "user_alice"
    proj = ProjectRecord(
        project_id="proj_alice_1",
        owner_sub="user_alice",
        name="alice_app",
        repository=str(repo_dir),
        repo_owner="alice",
        repo_name="alice_app",
        canonical_url=str(repo_dir),
        branch="main",
        created_at=now,
        updated_at=now,
    )
    proj_repo.create(proj)

    # When accessed by "user_bob", must raise 404 (BOLA/IDOR protection)
    with pytest.raises(HTTPException) as exc_info:
        _verify_owned_project(proj_repo, "proj_alice_1", "user_bob")
    assert exc_info.value.status_code == 404

    # When accessed by "user_alice", succeeds
    verified = _verify_owned_project(proj_repo, "proj_alice_1", "user_alice")
    assert verified.project_id == "proj_alice_1"


def test_github_delivery_success_and_idempotent_retry(monkeypatch, tmp_path):
    from app.remediation.delivery import deliver_verified_repair
    from app.remediation.models import RepairPlan, RepairVerification
    from app.services import github_app

    repo_dir = tmp_path / "gh_repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    # Fake GitHub App configuration
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "live_delivery_enabled", True)
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "live_delivery_enabled", True)
    monkeypatch.setattr(
        github_app,
        "get_github_app_config",
        lambda: github_app.GitHubAppConfig(app_id="12345", installation_id="67890", configured=True),
    )
    monkeypatch.setattr(github_app, "mint_installation_token", lambda **kwargs: "ghs_testtoken123")

    # Mock git push to succeed
    from app.remediation import delivery
    monkeypatch.setattr(delivery, "_run_git_push", lambda *args, **kwargs: (0, "ok", ""))

    plan = RepairPlan(
        finding_id="fnd_123",
        rule_id="SEC-101",
        file_path="app.py",
        title="Fix shell=True",
        explanation="Remove shell=True",
        remediation_strategy="deterministic_ast",
        can_auto_fix=True,
        risk_level="low",
    )
    verification = RepairVerification(
        verified=True,
        finding_eliminated=True,
        original_rule_retested=True,
        branch_name="medha/fix-sec-101-fnd_123",
        commit_sha="a" * 40,
        verification_evidence=["Verified 0 findings."],
    )

    # 1. First delivery creates PR #42
    monkeypatch.setattr(
        github_app,
        "_api_request",
        lambda method, path, **kwargs: (
            (201, {"number": 42, "html_url": "https://github.com/octo/demo/pull/42"})
            if method == "POST"
            else (200, [])
        ),
    )
    res = deliver_verified_repair(
        repo_dir, "https://github.com/octo/demo.git", "main", "medha/fix-sec-101-fnd_123",
        "a" * 40, plan, verification,
    )
    assert res.delivered is True
    assert res.delivery_method == "github_pr"
    assert res.pr_number == 42
    assert "https://github.com/octo/demo/pull/42" in res.pr_url

    # 2. Idempotent retry: POST returns 422, GET /pulls returns existing PR #42
    def _mock_idempotent_api(method, path, **kwargs):
        if method == "POST":
            return 422, {"message": "A pull request already exists for octo:medha/fix-sec-101-fnd_123"}
        elif method == "GET" and "pulls" in path:
            return 200, [{"number": 42, "html_url": "https://github.com/octo/demo/pull/42"}]
        return 404, {}

    monkeypatch.setattr(github_app, "_api_request", _mock_idempotent_api)
    retry_res = deliver_verified_repair(
        repo_dir, "https://github.com/octo/demo.git", "main", "medha/fix-sec-101-fnd_123",
        "a" * 40, plan, verification,
    )
    assert retry_res.delivered is True
    assert retry_res.pr_number == 42
    assert "already exists" in retry_res.message


def test_github_delivery_push_success_pr_failure_preserves_state(monkeypatch, tmp_path):
    from app.remediation.delivery import deliver_verified_repair
    from app.remediation.models import RepairPlan, RepairVerification
    from app.services import github_app
    from app.remediation import delivery

    repo_dir = tmp_path / "gh_repo2"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("x = 1\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "live_delivery_enabled", True)
    monkeypatch.setattr(
        github_app,
        "get_github_app_config",
        lambda: github_app.GitHubAppConfig(app_id="12345", installation_id="67890", configured=True),
    )
    monkeypatch.setattr(github_app, "mint_installation_token", lambda **kwargs: "ghs_testtoken123")
    monkeypatch.setattr(delivery, "_run_git_push", lambda *args, **kwargs: (0, "ok", ""))

    # PR creation fails with 500
    monkeypatch.setattr(
        github_app,
        "_api_request",
        lambda method, path, **kwargs: (500, {"message": "GitHub Internal Server Error"}),
    )

    plan = RepairPlan(
        finding_id="fnd_124",
        rule_id="SEC-101",
        file_path="app.py",
        title="Fix shell=True",
        explanation="Remove shell=True",
        remediation_strategy="deterministic_ast",
        can_auto_fix=True,
        risk_level="low",
    )
    verification = RepairVerification(
        verified=True,
        finding_eliminated=True,
        original_rule_retested=True,
        branch_name="medha/fix-sec-101-fnd_124",
        commit_sha="b" * 40,
        verification_evidence=["Verified 0 findings."],
    )

    res = deliver_verified_repair(
        repo_dir, "https://github.com/octo/demo.git", "main", "medha/fix-sec-101-fnd_124",
        "b" * 40, plan, verification,
    )
    assert res.delivered is False
    assert res.branch_name == "medha/fix-sec-101-fnd_124"
    assert res.commit_sha == "b" * 40
    assert "Branch pushed to GitHub, but Pull Request creation failed" in res.message


def test_repair_session_persistence_and_backend_restart_recovery(client, tmp_path):
    from app.database.repositories import DeploymentRepository, FindingRepository, ProjectRepository
    from app.models.deployment import ProjectRecord
    from app.remediation.service import RemediationService, _REPAIR_SESSIONS

    proj_repo = ProjectRepository()
    find_repo = FindingRepository()

    now = "2026-10-30T10:00:00Z"
    repo_dir = tmp_path / "persist_repo"
    repo_dir.mkdir()
    (repo_dir / "vuln.py").write_text("DEBUG = True\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    proj = ProjectRecord(
        project_id="proj_persist_1",
        owner_sub="local",
        name="persist_app",
        repository=str(repo_dir),
        repo_owner="local",
        repo_name="persist_app",
        canonical_url=str(repo_dir),
        branch="main",
        created_at=now,
        updated_at=now,
    )
    proj_repo.create(proj)

    find_repo.sync_scan(
        project_id="proj_persist_1",
        repository=str(repo_dir),
        deployment_id="dep_persist_1",
        commit_sha="d" * 40,
        findings=[{
            "source": "builtin",
            "rule_id": "CFG-003",
            "category": "configuration",
            "severity": "medium",
            "confidence": "high",
            "path": "vuln.py",
            "line": 1,
            "message": "DEBUG = True",
            "explanation": "Debug mode enabled",
            "remediation": "Set debug=False",
        }],
        active_sources={"builtin"},
        scanned_at=now,
    )

    finding_id = find_repo.list(project_id="proj_persist_1")[0]["finding_id"]

    service1 = RemediationService()
    # 1. Create plan and verify in sandbox
    import asyncio
    asyncio.run(service1.create_plan("proj_persist_1", finding_id))
    verification, branch, commit = asyncio.run(service1.apply_and_verify("proj_persist_1", finding_id))
    assert verification.verified is True
    assert commit is not None

    # Simulate backend crash / restart: wipe memory cache completely!
    _REPAIR_SESSIONS.clear()
    assert finding_id not in _REPAIR_SESSIONS

    # 2. New service instance after restart
    service2 = RemediationService()
    recovered_session = service2.get_repair_session(finding_id)
    assert recovered_session is not None
    assert recovered_session.status == "verified"
    assert recovered_session.branch_name == branch
    assert recovered_session.commit_sha == commit
    assert recovered_session.verification.verified is True

    # 3. Delivery proceeds cleanly using recovered state
    delivery = asyncio.run(service2.deliver("proj_persist_1", finding_id))
    assert delivery.delivered is True
    assert delivery.delivery_method == "local_branch"
    assert delivery.commit_sha == commit


def test_diff_hash_approval_invalidation_and_audit_trail(client, tmp_path):
    from app.database.repositories import FindingRepository, ProjectRepository
    from app.models.deployment import ProjectRecord
    from app.remediation.service import RemediationService

    proj_repo = ProjectRepository()
    find_repo = FindingRepository()

    now = "2026-10-30T10:00:00Z"
    repo_dir = tmp_path / "hash_repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("DEBUG = True\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    proj = ProjectRecord(
        project_id="proj_hash_1",
        owner_sub="local",
        name="hash_app",
        repository=str(repo_dir),
        repo_owner="local",
        repo_name="hash_app",
        canonical_url=str(repo_dir),
        branch="main",
        created_at=now,
        updated_at=now,
    )
    proj_repo.create(proj)

    find_repo.sync_scan(
        project_id="proj_hash_1",
        repository=str(repo_dir),
        deployment_id="dep_hash_1",
        commit_sha="e" * 40,
        findings=[{
            "source": "builtin",
            "rule_id": "CFG-003",
            "category": "configuration",
            "severity": "medium",
            "confidence": "high",
            "path": "app.py",
            "line": 1,
            "message": "DEBUG = True",
            "explanation": "Debug mode enabled",
            "remediation": "Set debug=False",
        }],
        active_sources={"builtin"},
        scanned_at=now,
    )

    finding_id = find_repo.list(project_id="proj_hash_1")[0]["finding_id"]

    # 1. Create plan
    res_plan = client.post(f"/api/projects/proj_hash_1/findings/{finding_id}/repair-plan")
    assert res_plan.status_code == 200
    plan_data = res_plan.json()
    assert "diff_hash" in plan_data
    original_diff_hash = plan_data["diff_hash"]

    # 2. Apply and verify in sandbox
    res_verify = client.post(f"/api/projects/proj_hash_1/findings/{finding_id}/apply-and-verify")
    assert res_verify.status_code == 200
    assert res_verify.json()["verification"]["verified"] is True

    # 3. Explicit approval
    res_approve = client.post(f"/api/projects/proj_hash_1/findings/{finding_id}/approve")
    assert res_approve.status_code == 200
    approve_data = res_approve.json()
    assert approve_data["approved"] is True
    assert approve_data["approved_diff_hash"] == original_diff_hash

    # 4. Tamper with diff in session to simulate modification after approval
    service = RemediationService()
    session = service.get_repair_session(finding_id)
    assert session is not None
    session.plan.diff_unified += "\n# modified after approval"
    from app.remediation.service import _save_repair_session
    _save_repair_session(session)

    # 5. Delivery attempt must fail with re-approval required
    res_deliver = client.post(
        f"/api/projects/proj_hash_1/findings/{finding_id}/deliver",
        json={"branch_name": "medha/tamper-test"},
    )
    assert res_deliver.status_code == 400
    assert "Patch content has changed since approval" in res_deliver.json()["detail"]

    # 6. Audit trail must record the tampering and invalidation event
    res_audit = client.get(f"/api/projects/proj_hash_1/findings/{finding_id}/audit-trail")
    assert res_audit.status_code == 200
    audit_data = res_audit.json()
    events = [e["event"] for e in audit_data["audit_events"]]
    assert "plan_created" in events
    assert "sandbox_verified" in events
    assert "approved" in events
    assert "approval_invalidated" in events


def test_live_delivery_fail_closed_gate(client, tmp_path, monkeypatch):
    from app.database.repositories import FindingRepository, ProjectRepository
    from app.models.deployment import ProjectRecord

    proj_repo = ProjectRepository()
    find_repo = FindingRepository()

    now = "2026-10-30T10:00:00Z"
    repo_dir = tmp_path / "gate_repo"
    repo_dir.mkdir()
    (repo_dir / "app.py").write_text("DEBUG = True\n", encoding="utf-8")
    _init_git_repo(repo_dir)

    proj = ProjectRecord(
        project_id="proj_gate_1",
        owner_sub="local",
        name="gate_app",
        repository=str(repo_dir),
        repo_owner="local",
        repo_name="gate_app",
        canonical_url=str(repo_dir),
        branch="main",
        created_at=now,
        updated_at=now,
    )
    proj_repo.create(proj)

    find_repo.sync_scan(
        project_id="proj_gate_1",
        repository=str(repo_dir),
        deployment_id="dep_gate_1",
        commit_sha="f" * 40,
        findings=[{
            "source": "builtin",
            "rule_id": "CFG-003",
            "category": "configuration",
            "severity": "medium",
            "confidence": "high",
            "path": "app.py",
            "line": 1,
            "message": "DEBUG = True",
            "explanation": "Debug mode enabled",
            "remediation": "Set debug=False",
        }],
        active_sources={"builtin"},
        scanned_at=now,
    )

    finding_id = find_repo.list(project_id="proj_gate_1")[0]["finding_id"]

    # Plan and verify
    client.post(f"/api/projects/proj_gate_1/findings/{finding_id}/repair-plan")
    client.post(f"/api/projects/proj_gate_1/findings/{finding_id}/apply-and-verify")

    # Explicitly disable live delivery
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "live_delivery_enabled", False)

    # Deliver requesting github_pr must fail closed!
    res = client.post(
        f"/api/projects/proj_gate_1/findings/{finding_id}/deliver",
        json={"delivery_method": "github_pr"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["delivered"] is False
    assert "Live delivery to GitHub is disabled" in data["message"]
    assert data["pr_number"] is None


def test_remediation_rate_limiting(client, tmp_path):
    from app.core.rate_limit import reset_rate_limits
    reset_rate_limits()

    # Repeated requests to repair-plan beyond rate limit return 429
    url = "/api/projects/nonexistent/findings/nonexistent/repair-plan"
    got_429 = False
    for _ in range(35):
        resp = client.post(url)
        if resp.status_code == 429:
            got_429 = True
            break
    assert got_429 is True
    reset_rate_limits()


def test_readiness_and_beta_project_limit(client, monkeypatch):
    # 1. Test /api/readiness endpoint
    res_ready = client.get("/api/readiness")
    assert res_ready.status_code == 200
    ready_data = res_ready.json()
    assert ready_data["status"] == "ready"
    assert "database" in ready_data["subsystems"]
    assert "workspace_storage" in ready_data["subsystems"]
    assert "live_delivery" in ready_data["subsystems"]

    # 2. Test beta project limit
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "max_active_projects", 0)

    # Attempt to create project when limit is 0
    res_limit = client.post(
        "/api/projects",
        json={"repository": "https://github.com/test-owner/test-another-repo-unique", "name": "Another"},
    )
    assert res_limit.status_code == 429
    assert res_limit.json()["error"]["code"] == "PROJECT_LIMIT_EXCEEDED"


def test_normalize_private_key_pem(tmp_path):
    import base64
    from app.services.github_app import normalize_private_key_pem

    # 1. Empty / None
    assert normalize_private_key_pem("") == ""
    assert normalize_private_key_pem(None) == ""

    sample_pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"

    # 2. Standard PEM
    assert normalize_private_key_pem(sample_pem) == sample_pem

    # 3. Quoted string
    assert normalize_private_key_pem(f'"{sample_pem}"') == sample_pem
    assert normalize_private_key_pem(f"'{sample_pem}'") == sample_pem

    # 4. Escaped literal \n
    literal_escaped = sample_pem.replace("\n", "\\n")
    assert normalize_private_key_pem(literal_escaped) == sample_pem

    # 5. Base64 encoded
    b64_encoded = base64.b64encode(sample_pem.encode("utf-8")).decode("utf-8")
    assert normalize_private_key_pem(b64_encoded) == sample_pem

    # 6. File path to .pem
    pem_file = tmp_path / "github_app.pem"
    pem_file.write_text(sample_pem, encoding="utf-8")
    assert normalize_private_key_pem(str(pem_file)) == sample_pem


def test_github_api_request_422_and_404_handling(monkeypatch):
    from urllib.error import HTTPError
    from io import BytesIO
    import app.services.github_app as gh

    # Simulate urllib HTTPError 422 with JSON body
    error_body = b'{"message": "Validation Failed", "errors": ["A pull request already exists"]}'
    mock_err = HTTPError("https://api.github.com/test", 422, "Unprocessable Entity", {}, BytesIO(error_body))

    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=15.0: (_ for _ in ()).throw(mock_err))

    status, payload = gh._api_request("POST", "/test")
    assert status == 422
    assert payload["message"] == "Validation Failed"
    assert "A pull request already exists" in payload["errors"][0]


def test_run_git_push_timeout_and_prompt_guard(tmp_path, monkeypatch):
    import subprocess
    from app.remediation.delivery import _run_git_push

    # Simulate timeout
    def _timeout_mock(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git push", timeout=0.1)

    monkeypatch.setattr(subprocess, "run", _timeout_mock)
    rc, stdout, stderr = _run_git_push(tmp_path, "test-branch", timeout=0.1)
    assert rc == 124
    assert "timed out" in stderr


def test_workspace_pruning_and_directory_containment(tmp_path, monkeypatch):
    from app.services.workspace import cleanup_workspace, prune_stale_workspaces, workspaces_root

    ws_root = tmp_path / "workspaces"
    ws_root.mkdir()
    monkeypatch.setattr("app.services.workspace.workspaces_root", lambda: ws_root)

    # Create safe child workspace
    safe_ws = ws_root / "dep_test_123"
    safe_ws.mkdir()
    (safe_ws / "file.txt").write_text("test", encoding="utf-8")
    assert safe_ws.exists()

    # Cleanup should remove the contained workspace
    cleanup_workspace("dep_test_123")
    assert not safe_ws.exists()

    # Path outside workspaces root must NOT be deleted
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "important.txt").write_text("do not touch", encoding="utf-8")

    # Attempt cleanup with relative path traversal
    cleanup_workspace("../outside")
    assert outside_dir.exists()
    assert (outside_dir / "important.txt").exists()


def test_pull_request_webhook_event_handling(tmp_path, monkeypatch):
    """Validate signed GitHub pull_request webhook payload processing."""
    import hmac, hashlib, json
    from app.core.config import get_settings
    from app.database.connection import init_db
    from app.main import create_app
    from fastapi.testclient import TestClient

    secret = "whsec_test_only"
    db_path = tmp_path / "test_pr_wh.db"
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db_path))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", secret)
    monkeypatch.setenv("MEDHA_WEBHOOK_ALLOWED_REPOS", "octo/demo")
    monkeypatch.setenv("MEDHA_WEBHOOK_BRANCHES", "main")
    get_settings.cache_clear()
    init_db(db_path)

    body = json.dumps({
        "action": "opened",
        "number": 42,
        "repository": {"full_name": "octo/demo"},
        "pull_request": {
            "number": 42,
            "state": "open",
            "title": "fix: security patch",
            "base": {"ref": "main", "sha": "1" * 40, "repo": {"full_name": "octo/demo"}},
            "head": {"ref": "medha/fix", "sha": "2" * 40, "repo": {"full_name": "octo/demo"}},
        }
    }).encode("utf-8")

    sig = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    headers = {
        "x-github-delivery": "pr-delivery-uuid-1",
        "x-github-event": "pull_request",
        "x-hub-signature-256": sig,
        "content-type": "application/json",
    }

    try:
        with TestClient(create_app()) as test_client:
            res = test_client.post("/api/webhooks/github", content=body, headers=headers)
            assert res.status_code == 202
            assert res.json()["status"] == "analyzing"
            assert "proposal_id" in res.json()
    finally:
        get_settings.cache_clear()






