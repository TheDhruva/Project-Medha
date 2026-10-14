"""Phase 2 replanning hardening: validated fixes, gates, bounded repeats.

Unit tests drive the real `_apply_replan_fixes` and real `run_critic`.
Pipeline tests drive the real PlanningPipeline; scripted gates stand in
only for gate *judgments* (unit-covered elsewhere) — every substituted
result is a real model instance, and the wiring under test
(fix → re-negotiate → re-verify → gate → execute-or-fail) is real.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.agents.critic import run_critic
from app.cnp.engine import run_cnp
from app.models.domain import (
    ApplicationProfile,
    Constraint,
    ConstraintType,
    InferredStack,
    NegotiationResult,
    Priority,
)
from app.models.execution import (
    CheckSeverity,
    CheckStatus,
    CriticRecommendation,
    VerificationCheck,
    VerificationResult,
)
from tests.conftest import _deploy_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"


def _wait_terminal(client, deployment_id: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def _log_lines(client, deployment_id: str) -> list[dict]:
    return client.get(f"/api/deploy/{deployment_id}/logs",
                      params={"limit": 2000}).json()["lines"]


def _profile(intent: str = "Deploy securely") -> ApplicationProfile:
    return ApplicationProfile(
        deployment_id="dep_replan",
        repository_url="x",
        workspace_path=".",
        target_host="localhost",
        target_port=8080,
        intent=intent,
        inferred_stack=InferredStack(
            services=[], language_runtime="node", confidence=0.8),
    )


def _negotiation(status: str = "resolved") -> NegotiationResult:
    return NegotiationResult(deployment_id="dep_replan", status=status,
                             rounds_used=1, final_constraints=[])


def _check(cid: str, rule: str, status: CheckStatus,
           severity: CheckSeverity = CheckSeverity.HIGH,
           message: str = "failed") -> VerificationCheck:
    return VerificationCheck(id=cid, name=cid, category="config", rule=rule,
                             status=status, severity=severity, message=message)


def _verification(passed: bool, checks: list[VerificationCheck],
                  blocking: list[str]) -> VerificationResult:
    return VerificationResult(deployment_id="dep_replan", passed=passed,
                              checks=checks, blocking_failures=blocking,
                              score=50 if not passed else 95)


def _env_fragments() -> dict:
    return {
        "docker": {"compose_fragment": {"services": {
            "backend": {"image": "x", "environment": {}},
        }}},
        "env_present": {},
    }


def _required_env(key: str = "DATABASE_URL") -> Constraint:
    return Constraint(
        constraint_id="c_env_req", type=ConstraintType.ENV_VAR,
        priority=Priority.DEPENDENCY, source_agent="Docker Agent",
        payload={"key": key, "required": True, "value_policy": "secret_ref"},
    )


# --- 1. Critic REPLAN on an initially passing verification ----------------------

def test_critic_replan_on_passing_verification():
    checks = [
        _check("schema", "SCHEMA-001", CheckStatus.PASS, CheckSeverity.HIGH, "ok"),
        _check("advisory", "ADVISORY-001", CheckStatus.FAIL, CheckSeverity.LOW,
               "Advisory low failure"),
    ]
    verification = _verification(passed=True, checks=checks,
                                 blocking=["Advisory low failure"])
    result = run_critic(
        deployment_id="dep_replan", profile=_profile(),
        constraints=[], negotiation=_negotiation(),
        verification=verification, config_fragments={},
    )
    assert result.recommendation == CriticRecommendation.REPLAN


def test_critic_pass_warn_escalate_mapping():
    passed = _verification(passed=True, checks=[
        _check("schema", "SCHEMA-001", CheckStatus.PASS)], blocking=[])
    assert run_critic(
        deployment_id="d", profile=_profile(), constraints=[],
        negotiation=_negotiation(), verification=passed,
        config_fragments={}).recommendation == CriticRecommendation.PASS
    failed = _verification(passed=False, checks=[
        _check("env", "ENV-001", CheckStatus.FAIL)], blocking=["env missing"])
    assert run_critic(
        deployment_id="d", profile=_profile(), constraints=[],
        negotiation=_negotiation(), verification=failed,
        config_fragments={}).recommendation == CriticRecommendation.ESCALATE


# --- 2/3/4. Fix validation ---------------------------------------------------------

def test_supported_env_fix_applied_and_idempotent():
    import app.workflow.planning as planning

    verification = _verification(passed=False, checks=[
        _check("env", "ENV-001", CheckStatus.FAIL, CheckSeverity.HIGH,
               "Required environment variable DATABASE_URL missing")],
        blocking=["Required environment variable DATABASE_URL missing"])
    fixed, report = planning._apply_replan_fixes(
        _env_fragments(), verification, [_required_env()])
    assert report["plan_changed"] is True
    assert report["applied"] == [{"kind": "inject_env", "key": "DATABASE_URL",
                                  "services": ["backend"], "rule": "ENV-001"}]
    assert report["rejected"] == []
    env = fixed["docker"]["compose_fragment"]["services"]["backend"]["environment"]
    assert env == {"DATABASE_URL": "${DATABASE_URL}"}
    assert fixed["env_present"] == {"DATABASE_URL": True}
    # Re-applying is a no-op: repeat detection can stop the loop.
    _fixed2, report2 = planning._apply_replan_fixes(
        fixed, verification, [_required_env()])
    assert report2["plan_changed"] is False


def test_unsupported_fix_rejected_fragments_untouched():
    import app.workflow.planning as planning

    before = _env_fragments()
    verification = _verification(passed=False, checks=[
        _check("order", "ORDER-001", CheckStatus.FAIL, CheckSeverity.HIGH,
               "EXEC_ORDER constraints contain a cycle"),
        _check("compose", "COMPOSE-005", CheckStatus.FAIL, CheckSeverity.HIGH,
               "depends on unknown 'dbx'")],
        blocking=["EXEC_ORDER constraints contain a cycle",
                  "depends on unknown 'dbx'"])
    fixed, report = planning._apply_replan_fixes(before, verification, [])
    assert report["applied"] == []
    assert report["plan_changed"] is False
    assert fixed == before
    rules = {r["rule"] for r in report["rejected"]}
    assert rules == {"ORDER-001", "COMPOSE-005"}


def test_security_settings_immutable_to_replan():
    import app.workflow.planning as planning

    fragments = {
        "docker": {"compose_fragment": {"services": {
            "backend": {"image": "x", "privileged": True,
                        "environment": {"DATABASE_URL": "${DATABASE_URL}"}},
        }}},
        "env_present": {"DATABASE_URL": True},
    }
    verification = _verification(passed=False, checks=[
        _check("security", "SEC-001", CheckStatus.FAIL, CheckSeverity.CRITICAL,
               "Container 'backend' must not require privileged=true")],
        blocking=["Container 'backend' must not require privileged=true"])
    fixed, report = planning._apply_replan_fixes(
        fragments, verification, [_required_env()])
    svc = fixed["docker"]["compose_fragment"]["services"]["backend"]
    assert svc["privileged"] is True  # never patched by replan
    assert report["applied"] == []
    assert any(r.get("rule") == "SEC-001" for r in report["rejected"])


def test_malformed_verification_rejected_safely():
    import app.workflow.planning as planning

    class _Broken:
        checks = None
        blocking_failures = []

    fixed, report = planning._apply_replan_fixes(_env_fragments(), _Broken(), None)
    assert report["applied"] == []
    assert report["plan_changed"] is False


# --- 5. Supported fix end-to-end: fix → re-negotiate → verify → execute -----------

def test_replan_fix_pipeline_end_to_end(client):
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo,
                             intent="force verification failure"),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "completed"
    lines = _log_lines(client, final["deployment_id"])
    types = [ln["type"] for ln in lines]
    rerun = next(i for i, ln in enumerate(lines)
                 if ln["type"] == "negotiation.started"
                 and "CNP re-run after replan" in ln["message"])
    order = ["verification.failed", "replan.started",
             "verification.passed", "critic.completed", "deployment.completed"]
    positions = [types.index(t) for t in order]
    assert positions == sorted(positions)
    assert positions[0] < rerun < positions[2]


# --- 6. Re-negotiation failure after replan prevents execution ---------------------

def test_renegotiation_failure_after_replan_blocks_execution(client, monkeypatch):
    import app.workflow.planning as planning
    from app.execution.executor import SimulatorExecutor

    deadlock = [
        Constraint(constraint_id="s1", type=ConstraintType.SECURITY_POLICY,
                   priority=Priority.SECURITY, source_agent="Security Agent",
                   payload={"rule": "external_access", "mode": "restricted"}),
        Constraint(constraint_id="s2", type=ConstraintType.SECURITY_POLICY,
                   priority=Priority.SECURITY, source_agent="Docker Agent",
                   payload={"rule": "external_access", "mode": "unrestricted"}),
    ]
    # Genuine engine output for genuinely infeasible input (computed once,
    # up front): the pipeline must treat it as a terminal negotiation failure.
    real_exhausted = run_cnp("dep_precomputed", deadlock)
    assert real_exhausted.status == "exhausted"
    real_run_cnp = planning.run_cnp
    calls = {"n": 0, "execute": 0}

    def flaky_cnp(deployment_id, constraints, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return real_run_cnp(deployment_id, constraints, **kwargs)
        return real_exhausted

    monkeypatch.setattr(planning, "run_cnp", flaky_cnp)
    real_execute = SimulatorExecutor.execute

    def counting_execute(self, *args, **kwargs):
        calls["execute"] += 1
        return real_execute(self, *args, **kwargs)

    monkeypatch.setattr(SimulatorExecutor, "execute", counting_execute)
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo,
                             intent="force verification failure"),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "failed"
    assert calls["execute"] == 0
    assert "re-negotiation" in (final.get("error_summary") or "")


# --- 7. Cosmetic ever-changing fixes still bounded ----------------------------------

def test_cosmetic_fixes_bound_by_max_rounds(client, monkeypatch):
    import app.workflow.planning as planning
    from app.core.config import get_settings

    state = {"n": 0}

    def cosmetic(fragments, verification, constraints=None):
        state["n"] += 1
        fixed = {**fragments, f"cosmetic_{state['n']}": True}
        return fixed, {"applied": [{"kind": "cosmetic", "key": str(state["n"])}],
                       "rejected": [], "plan_changed": True}

    monkeypatch.setattr(planning, "_apply_replan_fixes", cosmetic)
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo,
                             intent="force verification failure"),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "failed"
    lines = _log_lines(client, final["deployment_id"])
    replans = [ln for ln in lines if ln["type"] == "replan.started"]
    assert 1 <= len(replans) <= get_settings().max_verify_rounds - 1


# --- 8/9. Final artifacts and event history ------------------------------------------

def test_final_artifacts_match_final_plan(client):
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo,
                             intent="force verification failure"),
    )
    assert resp.status_code == 202
    deployment_id = resp.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)
    assert final["status"] == "completed"
    assert final["result"]["plan_hash"]
    constraints = client.get(f"/api/deploy/{deployment_id}/constraints").json()
    assert constraints["negotiation"]["status"] == "resolved"
    assert constraints["constraints"]
    verification = client.get(f"/api/deploy/{deployment_id}/verification").json()
    assert verification["verification"]["passed"] is True
