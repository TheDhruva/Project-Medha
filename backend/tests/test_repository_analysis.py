"""Comprehensive repository analysis & failure-resilient orchestration.

Acceptance coverage: analysis runs across all discovered applications without
requiring a deployment-target choice; deployment stays blocked until an
explicit target is chosen; the analysis report remains available while a
deployment is blocked; an unavailable scanner is never "clean"; one failing
task does not cancel independent tasks.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from app.analysis import tasks as analysis_tasks
from app.analysis.inventory import build_repository_inventory
from tests.conftest import _deploy_payload


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _multi_app(root: Path) -> None:
    # Root package.json AND frontend/package.json — the screenshot scenario.
    _write(root / "package.json", '{"name": "root", "scripts": {"start": "node index.js"}}')
    _write(root / "index.js", "console.log('root')")
    _write(root / "frontend" / "package.json",
           '{"dependencies": {"next": "15.0.0"}, "scripts": {"start": "next start"}}')
    _write(root / "frontend" / "index.js", "console.log('web')")
    _write(root / "backend" / "requirements.txt", "fastapi\nuvicorn\n")
    _write(root / "backend" / "app.py", "app = 1")


# --- isolated task runner ---------------------------------------------------


def test_run_isolated_success_and_failure_isolated():
    ok = analysis_tasks.run_isolated(
        "ok", lambda: analysis_tasks.TaskResult(task="ok", status=analysis_tasks.SUCCEEDED)
    )
    assert ok.status == analysis_tasks.SUCCEEDED

    def boom():
        raise RuntimeError("recoverable")

    failed = analysis_tasks.run_isolated("boom", boom)
    assert failed.status == analysis_tasks.FAILED
    assert "recoverable" in (failed.error or "")
    # The runner itself does not raise: independent tasks keep running.


def test_run_isolated_timeout_is_recorded():
    def slow():
        time.sleep(3)
        return analysis_tasks.TaskResult(task="slow", status=analysis_tasks.SUCCEEDED)

    res = analysis_tasks.run_isolated("slow", slow, timeout_s=0.1)
    assert res.status == analysis_tasks.TIMED_OUT


def test_run_isolated_retries_are_bounded(monkeypatch):
    calls = {"n": 0}

    def always_fail():
        calls["n"] += 1
        raise OSError("transient")

    res = analysis_tasks.run_isolated("flaky", always_fail, retries=10, max_retries=2)
    assert res.status == analysis_tasks.FAILED
    assert calls["n"] == 3  # never an unbounded retry storm
    assert res.attempts == 3


def test_dedupe_findings_collapses_duplicates():
    f = {
        "source": "scanner:semgrep", "rule_id": "r", "path": "a.py",
        "line": 1, "message": "m",
    }
    assert analysis_tasks.dedupe_findings([f, dict(f), f]) == [f]


# --- comprehensive inventory ------------------------------------------------


def test_inventory_covers_all_discovered_applications(tmp_path):
    _multi_app(tmp_path)
    report = build_repository_inventory(tmp_path, commit_sha="a" * 40)
    assert report["schema"] == "repository-analysis/v1"
    paths = sorted(a["path"] for a in report["applications"])
    assert "frontend" in paths and "backend" in paths
    langs = {l["language"] for l in report["languages"]}
    assert {"python", "javascript"} <= langs
    # Every sub-task declares a status, evidence and (where relevant) coverage.
    assert report["tasks"]
    for t in report["tasks"]:
        assert t["status"]
        assert "duration_ms" in t


def test_missing_scanner_is_unavailable_not_clean(tmp_path, monkeypatch):
    from app.security import scanners

    monkeypatch.setattr(scanners.shutil, "which", lambda exe: None)
    report = build_repository_inventory(tmp_path, scanner_names=["gitleaks"])
    sec = next(t for t in report["tasks"] if t["task"] == "security:gitleaks")
    assert sec["status"] == analysis_tasks.UNAVAILABLE
    assert report["findings"] == []
    # An unavailable scan is a coverage gap, never a clean bill of health.
    assert any("security:gitleaks" in g for g in report["coverage"]["gaps"])


def test_scanner_findings_do_not_stop_other_scanners(tmp_path, monkeypatch):
    from app.security import scanners

    monkeypatch.setattr(scanners.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    payload = '[{"RuleID":"x","Description":"d","File":"a","StartLine":1}]'

    def fake_run(argv, **kwargs):
        name = Path(argv[0]).name
        if name == "gitleaks":
            return scanners.subprocess.CompletedProcess(argv, 1, payload, "")
        if name == "semgrep":
            raise scanners.subprocess.TimeoutExpired(cmd=argv, timeout=1)
        return scanners.subprocess.CompletedProcess(argv, 0, "[]", "")

    monkeypatch.setattr(scanners.subprocess, "run", fake_run)
    report = build_repository_inventory(
        tmp_path, scanner_names=["gitleaks", "semgrep", "trivy"]
    )
    by_task = {t["task"]: t for t in report["tasks"]}
    assert by_task["security:gitleaks"]["status"] == analysis_tasks.COMPLETED_WITH_FINDINGS
    assert by_task["security:semgrep"]["status"] == analysis_tasks.FAILED
    assert by_task["security:trivy"]["status"] == analysis_tasks.SUCCEEDED
    # Findings from the successful scanner survive the sibling's failure.
    assert report["finding_count"] == 1


def test_inventory_carries_the_bound_commit_sha(tmp_path):
    _multi_app(tmp_path)
    sha = "b" * 40
    report = build_repository_inventory(tmp_path, commit_sha=sha)
    assert report["commit_sha"] == sha


# --- end-to-end: analysis completes, deployment blocked ---------------------


def _wait_terminal(client, deployment_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body.get("status") in {
            "completed", "failed", "partial_recovery", "cancelled", "awaiting_approval",
        }:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def test_multi_app_analysis_succeeds_deployment_blocked(client, tmp_path):
    repo = tmp_path / "monorepo"
    _multi_app(repo)

    resp = client.post("/api/deploy", json=_deploy_payload(repository_url=str(repo)))
    assert resp.status_code == 202, resp.text
    deployment_id = resp.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)

    # Deployment blocked on an explicit target choice — not a repository error.
    assert final["status"] == "failed"
    result = final["result"]
    assert result["code"] == "MULTIPLE_APPS_REQUIRE_TARGET"
    # Analysis completed and its report is available despite the block.
    assert result["analysis_status"] in {"completed", "partial"}
    assert result["deployment_status"] == "blocked"
    assert result["deployment"]["status"] == "blocked"
    analysis = result["repository_analysis"]
    assert analysis["analysis_status"] in {"completed", "partial"}
    paths = sorted(a["path"] for a in analysis["applications"])
    assert "frontend" in paths and "backend" in paths
    # Candidates for the picker carry evidence; nothing was silently chosen.
    cands = result["target_selection"]["candidates"]
    cand_paths = {c["path"] for c in cands}
    assert {"frontend", "backend"} <= cand_paths
    assert all(c.get("evidence") for c in cands)

    # The report is served independently of the blocked deployment.
    intel = client.get(f"/api/deploy/{deployment_id}/repository-intelligence").json()
    assert isinstance(intel.get("repository_analysis"), dict)
    assert intel["repository_analysis"]["applications"]


def test_invalid_repository_intake_never_false_success(client, tmp_path):
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(repository_url=str(tmp_path / "does-not-exist")),
    )
    assert resp.status_code == 202, resp.text
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "failed"
    result = final["result"]
    # No fabricated successful analysis when intake itself failed.
    assert result.get("analysis_status") != "completed"
    analysis = result.get("repository_analysis")
    assert analysis is None or analysis.get("analysis_status") != "completed"
    health = client.get(f"/api/deploy/{final['deployment_id']}/health").json()
    assert health["health_status"] != "healthy"


def test_simulator_result_is_not_live(client):
    from pathlib import Path

    repo = str(
        (Path(__file__).resolve().parent / "fixtures" / "repos" / "node_api").resolve()
    )
    resp = client.post("/api/deploy", json=_deploy_payload(repository_url=repo))
    assert resp.status_code == 202, resp.text
    final = _wait_terminal(client, resp.json()["deployment_id"])
    result = final["result"]
    # Explicit simulator success must never be labelled real execution.
    assert result.get("execution_mode") != "real"
    health = client.get(f"/api/deploy/{final['deployment_id']}/health").json()
    assert health["health_status"] != "healthy"


def test_unsupported_repo_keeps_analysis_report(client, tmp_path):
    repo = tmp_path / "emptysvc"
    _write(repo / "README.md", "nothing deployable here")

    resp = client.post("/api/deploy", json=_deploy_payload(repository_url=str(repo)))
    assert resp.status_code == 202, resp.text
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["result"]["code"] == "DEPLOYMENT_UNSUPPORTED"
    # The (possibly empty) analysis report is still persisted, never discarded.
    assert "repository_analysis" in final["result"]
    assert final["result"]["repository_analysis"]["schema"] == "repository-analysis/v1"
