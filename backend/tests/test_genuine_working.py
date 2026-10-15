"""Genuine-working regression: intel, teardown, terminal honesty, idempotency.

Simulator-backed (no Docker required). Live Docker evidence is covered by
test_real_e2e_gated.py when MEDHA_E2E_REAL=1 with a daemon reachable.
"""
from __future__ import annotations

import time
from pathlib import Path

from tests.conftest import _deploy_payload

FIXTURE_REPO = str(
    (Path(__file__).resolve().parent / "fixtures" / "repos" / "compose_app").resolve()
)


def _wait_terminal(client, deployment_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body.get("status") in {
            "completed", "failed", "partial_recovery", "cancelled",
            "awaiting_approval",
        }:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def test_repository_intelligence_builder_shape():
    from app.agents.analyzer import build_repository_intelligence
    from app.models.domain import ApplicationProfile, InferredStack

    profile = ApplicationProfile(
        deployment_id="dep_x",
        repository_url="https://github.com/example/site",
        workspace_path="/tmp/x",
        target_host="localhost",
        target_port=8080,
        inferred_stack=InferredStack(
            language_runtime="node",
            package_managers=["npm"],
            entry_points=["server.js"],
            suggested_ports=[8080],
            manifests_examined=["package.json"],
            confidence=0.8,
        ),
    )
    intel = build_repository_intelligence(
        profile, commit_sha="a" * 40, repository_url=profile.repository_url
    )
    assert intel["schema"] == "repository-intelligence/v1"
    assert intel["commit_sha"] == "a" * 40
    assert intel["proposed_approach"] == "node"
    assert intel["approach_evidence"] == ["package.json with start script"]
    assert intel["runtime_requirements"]["env_names"] == []
    assert intel["confidence"] == 0.8
    assert isinstance(intel["unknowns"], list)


def test_pipeline_persists_and_serves_repository_intelligence(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", repository_url=FIXTURE_REPO),
    )
    assert response.status_code == 202
    deployment_id = response.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)
    assert final["status"] in {"completed", "failed", "partial_recovery"}

    intel_res = client.get(f"/api/deploy/{deployment_id}/repository-intelligence")
    assert intel_res.status_code == 200
    intel = intel_res.json()["repository_intelligence"]
    assert intel["schema"] == "repository-intelligence/v1"
    assert "proposed_approach" in intel
    assert "approach_evidence" in intel
    assert isinstance(intel["unknowns"], list)
    assert isinstance(intel["assumptions"], list)
    # Local fixture checkouts are unpinned by design; remote runs pin a SHA.
    assert intel["commit_sha"] is None or len(intel["commit_sha"]) == 40


def test_repository_intelligence_missing_before_analysis(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", repository_url=FIXTURE_REPO),
    )
    deployment_id = response.json()["deployment_id"]
    # Immediately: analysis has not finished; either 404 (honest) or 200
    # with a recorded artifact — never fabricated content.
    res = client.get(f"/api/deploy/{deployment_id}/repository-intelligence")
    assert res.status_code in {200, 404}
    if res.status_code == 200:
        assert res.json()["repository_intelligence"]["schema"] == (
            "repository-intelligence/v1"
        )
    _wait_terminal(client, deployment_id)


def test_teardown_non_real_run_reports_nothing_to_remove(client):
    response = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", repository_url=FIXTURE_REPO),
    )
    deployment_id = response.json()["deployment_id"]
    _wait_terminal(client, deployment_id)
    res = client.post(f"/api/deploy/{deployment_id}/runtime/teardown")
    assert res.status_code == 200
    body = res.json()
    # Simulator run: no real runtime exists — honest no-op, never an error.
    assert body["torn_down"] is False
    assert body["removed"] == []
    # Idempotent: second call agrees.
    res2 = client.post(f"/api/deploy/{deployment_id}/runtime/teardown")
    assert res2.json() == body


def test_terminal_statuses_are_not_overwritten(tmp_path, monkeypatch):
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord

    db_path = tmp_path / "guard.db"
    init_db(db_path)
    repo = DeploymentRepository(db_path)
    now = utc_now_iso()
    repo.create(
        DeploymentRecord(
            deployment_id="dep_guard",
            repository_url="https://github.com/example/app",
            mode="real",
            scenario=None,
            target_host="localhost",
            target_port=8080,
            intent=None,
            status=DeploymentStatus.PARTIAL_RECOVERY,
            current_stage=None,
            created_at=now,
            updated_at=now,
        )
    )
    kept = repo.update_status(
        "dep_guard", status=DeploymentStatus.FAILED, updated_at=utc_now_iso()
    )
    assert kept is not None
    assert kept.status == DeploymentStatus.PARTIAL_RECOVERY


def test_post_terminal_result_is_not_overwritten(tmp_path):
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord

    db_path = tmp_path / "result_guard.db"
    init_db(db_path)
    repo = DeploymentRepository(db_path)
    now = utc_now_iso()
    repo.create(
        DeploymentRecord(
            deployment_id="dep_rg",
            repository_url="https://github.com/example/app",
            mode="real",
            scenario=None,
            target_host="localhost",
            target_port=8080,
            intent=None,
            status=DeploymentStatus.RUNNING,
            current_stage=None,
            created_at=now,
            updated_at=now,
        )
    )
    repo.save_artifacts("dep_rg", result={"kind": "success"}, updated_at=now)
    repo.update_status(
        "dep_rg", status=DeploymentStatus.COMPLETED, updated_at=utc_now_iso()
    )
    repo.save_artifacts(
        "dep_rg", result={"kind": "failed"}, updated_at=utc_now_iso()
    )
    assert repo.get("dep_rg").result == {"kind": "success"}


def test_static_site_detected_and_supported(tmp_path):
    from app.agents.analyzer import analyze_repository, build_repository_intelligence
    from app.execution.support import assess_plan_support

    root = tmp_path / "site"
    root.mkdir()
    (root / "index.html").write_text("<h1>hello</h1>", encoding="utf-8")
    profile, _ = analyze_repository(
        deployment_id="dep_static",
        repository_url="https://github.com/example/site",
        workspace_path=root,
        target_host="localhost",
        target_port=8080,
    )
    assert "index.html" in profile.inferred_stack.manifests_examined
    assert profile.inferred_stack.confidence >= 0.5
    decision = assess_plan_support(profile)
    assert decision.supported is True
    intel = build_repository_intelligence(profile, commit_sha="b" * 40)
    assert intel["proposed_approach"] == "static"
    assert intel["commit_sha"] == "b" * 40


def test_idempotency_key_prevents_duplicate_runs(client):
    payload = _deploy_payload(mode="real", repository_url=FIXTURE_REPO)
    first = client.post(
        "/api/deploy", json=payload, headers={"Idempotency-Key": "key-123"}
    )
    assert first.status_code == 202
    dep_id = first.json()["deployment_id"]
    second = client.post(
        "/api/deploy", json=payload, headers={"Idempotency-Key": "key-123"}
    )
    assert second.status_code == 200
    assert second.json()["deployment_id"] == dep_id
    assert second.json()["duplicate"] is True
    _wait_terminal(client, dep_id)
