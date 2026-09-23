"""Phase 10–11 tests: support gate, docker labels, evaluation, concurrency."""

from __future__ import annotations

import pytest

from app.core.deploy_lock import DeployBusyError, real_deploy_status, release_real_deploy, try_acquire_real_deploy
from app.evaluation.baseline import compare_rollback
from app.evaluation.datasets.ceg_cases import load_ceg_cases
from app.evaluation.run_ceg import run_ceg_evaluation
from app.evaluation.run_cnp import run_cnp_evaluation
from app.execution.docker_ops import LABEL_DEPLOYMENT, LABEL_MANAGED, resource_name
from app.execution.support import assess_plan_support
from app.models.domain import ApplicationProfile, InferredStack, ServiceHint


def test_support_requires_manifests_or_confidence():
    profile = ApplicationProfile(
        deployment_id="dep_x",
        repository_url="x",
        workspace_path=".",
        target_host="localhost",
        target_port=8080,
        inferred_stack=InferredStack(confidence=0.1, services=[]),
    )
    decision = assess_plan_support(profile)
    assert decision.supported is False
    assert decision.code == "DEPLOYMENT_UNSUPPORTED"


def test_support_accepts_compose():
    profile = ApplicationProfile(
        deployment_id="dep_x",
        repository_url="x",
        workspace_path=".",
        target_host="localhost",
        target_port=8080,
        inferred_stack=InferredStack(
            has_compose=True,
            confidence=0.7,
            services=[ServiceHint(name="backend", role="api")],
        ),
    )
    assert assess_plan_support(profile).supported is True


def test_resource_naming_and_labels():
    name = resource_name("dep_abcdefghijklmnop", "backend")
    assert name.startswith("medha_")
    assert "backend" in name
    assert LABEL_DEPLOYMENT.startswith("com.medha")
    assert LABEL_MANAGED.startswith("com.medha")


def test_deploy_lock_serializes():
    release_real_deploy()
    try_acquire_real_deploy("dep_a")
    assert real_deploy_status()["busy"] is True
    with pytest.raises(DeployBusyError):
        try_acquire_real_deploy("dep_b")
    release_real_deploy("dep_a")
    assert real_deploy_status()["busy"] is False


def test_deploy_lock_same_id_reacquire():
    release_real_deploy()
    try_acquire_real_deploy("dep_same")
    try_acquire_real_deploy("dep_same")  # idempotent
    assert real_deploy_status()["deployment_id"] == "dep_same"
    release_real_deploy("dep_same")


def test_cnp_evaluation_runner_measured():
    report = run_cnp_evaluation()
    assert report["fabricated"] is False
    assert report["total_cases"] >= 8
    assert report["passed"] + report["failed"] == report["total_cases"]
    assert report["failed"] == 0, report


def test_ceg_evaluation_runner_and_baseline():
    report = run_ceg_evaluation()
    assert report["fabricated"] is False
    assert report["failed"] == 0, report
    case = next(c for c in report["cases"] if c["case_id"] == "ceg_partial_backend")
    assert case["medha_rollback_count"] == 1
    assert case["global_rollback_count"] >= case["medha_rollback_count"]
    assert case["services_saved_vs_global"] >= 1


def test_baseline_comparison_shape():
    case = next(c for c in load_ceg_cases() if c["case_id"] == "ceg_fail_b_preserve_a_d")
    cmp = compare_rollback(case["graph"], case["fail_node"])
    assert cmp["medha"]["rollback_count"] == 1
    assert cmp["baseline"]["strategy"] == "GLOBAL_ROLLBACK"
    assert "n_a" not in cmp["medha"]["rollback_nodes"]
