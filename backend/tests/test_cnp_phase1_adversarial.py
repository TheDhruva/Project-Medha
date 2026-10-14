"""Phase 1 adversarial CNP regression tests (engine + pipeline paths).

Covers: reversed EXEC_ORDER grouping, malformed input across all types,
eval-declared alternatives, hard-security priority, rejected-proposal
memory, joint infeasibility, round-bound exhaustion, critic gating,
replan re-negotiation, and the persisted negotiation-failure outcome.

Engine tests drive the real `app.cnp.engine`. Pipeline tests drive the
real `PlanningPipeline` through the TestClient; spies only count
delegating calls and never substitute results.
"""

from __future__ import annotations

import time
from pathlib import Path

from app.cnp.engine import (
    _pick_alternative_port,
    apply_decision,
    detect_conflicts,
    resolve_conflict,
    run_cnp,
)
from app.models.domain import (
    Constraint,
    ConstraintStatus,
    ConstraintType,
    Priority,
)
from tests.conftest import _deploy_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "repos"


def _c(
    cid: str,
    ctype: ConstraintType,
    priority: Priority,
    agent: str,
    payload: dict,
    alternatives: list[dict] | None = None,
    status: ConstraintStatus = ConstraintStatus.PROPOSED,
) -> Constraint:
    return Constraint(
        constraint_id=cid,
        type=ctype,
        priority=priority,
        source_agent=agent,
        payload=payload,
        alternatives=alternatives or [],
        status=status,
    )


def _wait_terminal(client, deployment_id: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body["status"] in {"completed", "failed", "partial_recovery", "cancelled"}:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


# --- 1. Reversed EXEC_ORDER constraints ---------------------------------------

def test_reversed_exec_order_grouped_as_conflict():
    constraints = [
        _c("o_fwd", ConstraintType.EXEC_ORDER, Priority.DEPENDENCY,
           "Docker Agent", {"before": "database", "after": "backend"}),
        _c("o_rev", ConstraintType.EXEC_ORDER, Priority.DEPENDENCY,
           "Nginx Agent", {"before": "backend", "after": "database"}),
    ]
    # Direction-independent grouping: both share one conflict.
    assert constraints[0].resource_key() == constraints[1].resource_key()
    conflicts = detect_conflicts(constraints)
    assert len(conflicts) == 1
    assert set(conflicts[0].constraint_ids) == {"o_fwd", "o_rev"}
    result = run_cnp("dep_exec_rev", constraints)
    assert result.status == "resolved"
    by_id = {c.constraint_id: c for c in result.final_constraints}
    statuses = {by_id["o_fwd"].status, by_id["o_rev"].status}
    assert statuses == {ConstraintStatus.ACCEPTED, ConstraintStatus.REJECTED}


def test_chained_exec_order_not_grouped():
    constraints = [
        _c("o1", ConstraintType.EXEC_ORDER, Priority.DEPENDENCY,
           "Docker Agent", {"before": "database", "after": "backend"}),
        _c("o2", ConstraintType.EXEC_ORDER, Priority.DEPENDENCY,
           "Docker Agent", {"before": "backend", "after": "frontend"}),
    ]
    assert constraints[0].resource_key() != constraints[1].resource_key()
    assert detect_conflicts(constraints) == []
    result = run_cnp("dep_exec_chain", constraints)
    assert result.status == "resolved"
    assert result.conflicts == []


# --- 2. Malformed constraints across every supported type ----------------------

def test_malformed_constraints_dropped_across_types():
    bad = [
        _c("bad_port", ConstraintType.PORT_CLAIM, Priority.RESOURCE,
           "Docker Agent", {"key": "host:x"}),  # missing port
        _c("bad_env", ConstraintType.ENV_VAR, Priority.RESOURCE,
           "Docker Agent", {"value": "v"}),  # missing key
        _c("bad_vol", ConstraintType.VOLUME_MOUNT, Priority.RESOURCE,
           "Docker Agent", {"host_path": "/data"}),  # missing container
        _c("bad_net", ConstraintType.NETWORK_POLICY, Priority.DEPENDENCY,
           "Nginx Agent", {"isolation": "bridge"}),  # no rule/network
        _c("bad_sec", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Security Agent", {"enforcement": "block"}),  # missing rule
        _c("bad_ord", ConstraintType.EXEC_ORDER, Priority.DEPENDENCY,
           "Docker Agent", {"before": "a"}),  # missing after
    ]
    good = _c("good_port", ConstraintType.PORT_CLAIM, Priority.RESOURCE,
              "Docker Agent", {"port": 8080, "exclusive": True})
    result = run_cnp("dep_malformed", [*bad, good])
    assert result.status == "resolved"
    assert set(result.dropped_constraint_ids) == {c.constraint_id for c in bad}
    assert [c.constraint_id for c in result.final_constraints] == ["good_port"]


def test_all_malformed_constraints_invalid_not_resolved():
    bad = [
        _c("bad_port", ConstraintType.PORT_CLAIM, Priority.RESOURCE,
           "Docker Agent", {"key": "host:x"}),
        _c("bad_env", ConstraintType.ENV_VAR, Priority.RESOURCE,
           "Docker Agent", {"value": "v"}),
    ]
    result = run_cnp("dep_all_bad", bad)
    assert result.status == "invalid"
    assert result.rounds_used == 0
    assert set(result.dropped_constraint_ids) == {"bad_port", "bad_env"}
    assert result.final_constraints == []


# --- 3. Alternatives preserved from evaluation declarations --------------------

def test_eval_declared_alternatives_reach_engine():
    from app.evaluation.datasets.cnp_cases import constraints_from_case, load_cnp_cases

    case = next(c for c in load_cnp_cases() if c["case_id"] == "cnp_port_01")
    constraints = constraints_from_case(case)
    by_id = {c.constraint_id: c for c in constraints}
    # Payload-nested ints become top-level {"port": n} alternatives.
    assert by_id["d1"].alternatives == [{"port": 8081}]
    assert by_id["n1"].alternatives == [{"port": 8082}]
    assert "alternatives" not in by_id["d1"].payload
    result = run_cnp("dep_eval_alt", constraints)
    assert result.status == "resolved"
    decision = next(d for d in result.decisions if d.method == "alternative")
    # Keeper is lexicographically first (d1); n1 remaps via its DECLARED
    # alternative 8082, not the base+delta fallback (8081 is also free, so a
    # fallback would have picked 8081).
    update = next(u for u in decision.updates if u["constraint_id"] == "n1")
    assert update["new_value"] == 8082


# --- 4. Conflicting hard security constraints -----------------------------------

def test_hard_security_priority_wins_over_preference():
    constraints = [
        _c("c_pref", ConstraintType.NETWORK_POLICY, Priority.PREFERENCE,
           "Docker Agent", {"rule": "external_access", "mode": "unrestricted"}),
        _c("c_sec", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Security Agent", {"rule": "external_access", "mode": "restricted"}),
    ]
    result = run_cnp("dep_sec_priority", constraints)
    assert result.status == "resolved"
    assert any(d.method == "priority" for d in result.decisions)
    by_id = {c.constraint_id: c for c in result.final_constraints}
    assert by_id["c_sec"].status == ConstraintStatus.ACCEPTED
    assert by_id["c_pref"].status == ConstraintStatus.REJECTED


def test_contradictory_hard_security_detected_not_silently_accepted():
    # Same rule, contradictory enforcement: must conflict, never both ACCEPTED.
    constraints = [
        _c("s_block", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Security Agent", {"rule": "no_privileged", "enforcement": "block"}),
        _c("s_allow", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Rogue Agent", {"rule": "no_privileged", "enforcement": "allow"}),
    ]
    conflicts = detect_conflicts(constraints)
    assert len(conflicts) == 1
    result = run_cnp("dep_sec_deadlock", constraints)
    # No deterministic compromise may drop a hard constraint.
    assert result.status == "exhausted"
    assert any(d.method == "infeasible" for d in result.decisions)


# --- 5. Repeated rejected proposals ---------------------------------------------

def test_rejected_ports_never_reproposed():
    keeper = _c("c_keep", ConstraintType.PORT_CLAIM, Priority.RESOURCE,
               "Docker Agent", {"port": 8080, "exclusive": True})
    rejected = _c("c_old", ConstraintType.PORT_CLAIM, Priority.RESOURCE,
                 "Nginx Agent", {"port": 8081, "exclusive": True},
                 status=ConstraintStatus.REJECTED)
    other = _c("c_other", ConstraintType.PORT_CLAIM, Priority.RESOURCE,
               "Nginx Agent", {"port": 8080, "exclusive": True},
               alternatives=[{"port": 8081}])
    # Declared 8081 is a previously rejected proposal: skipped.
    assert _pick_alternative_port(other, 8080, [keeper, rejected, other]) == 8082
    result = run_cnp("dep_reject_mem", [keeper, rejected, other])
    assert result.status == "resolved"
    by_id = {c.constraint_id: c for c in result.final_constraints}
    assert by_id["c_other"].payload["port"] == 8082


# --- 6. Jointly infeasible decisions ----------------------------------------------

def test_jointly_infeasible_security_modes_exhausted():
    constraints = [
        _c("s1", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Security Agent", {"rule": "external_access", "mode": "restricted"}),
        _c("s2", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Docker Agent", {"rule": "external_access", "mode": "unrestricted"}),
    ]
    result = run_cnp("dep_infeasible", constraints)
    assert result.status == "exhausted"
    assert result.status != "resolved"
    # Infeasible decisions change nothing: both claims stay conflicted,
    # neither is arbitrarily accepted.
    by_id = {c.constraint_id: c for c in result.final_constraints}
    assert by_id["s1"].status == ConstraintStatus.CONFLICT
    assert by_id["s2"].status == ConstraintStatus.CONFLICT


# --- 7. Exhaustion at the configured negotiation limit --------------------------

def test_exhaustion_bounded_by_max_rounds():
    from app.cnp.engine import MAX_ROUNDS

    constraints = [
        _c("s1", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Security Agent", {"rule": "external_access", "mode": "restricted"}),
        _c("s2", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Docker Agent", {"rule": "external_access", "mode": "unrestricted"}),
    ]
    full = run_cnp("dep_exhaust", constraints)
    assert full.status == "exhausted"
    assert 1 <= full.rounds_used <= MAX_ROUNDS
    single = run_cnp("dep_exhaust1", constraints, max_rounds=1)
    assert single.status == "exhausted"
    assert single.rounds_used == 1


def test_cnp_deterministic_for_equivalent_inputs():
    def make():
        return [
            _c("c_port_a", ConstraintType.PORT_CLAIM, Priority.RESOURCE,
               "Docker Agent", {"key": "host:8080", "port": 8080, "exclusive": True},
               alternatives=[{"port": 8081}]),
            _c("c_port_b", ConstraintType.PORT_CLAIM, Priority.RESOURCE,
               "Nginx Agent", {"key": "host:8080", "port": 8080, "exclusive": True},
               alternatives=[{"port": 8081}]),
        ]

    def signature(result):
        return (
            result.status,
            result.rounds_used,
            [(d.method, sorted(d.winner_ids), sorted(d.loser_ids), d.updates)
             for d in result.decisions],
            sorted((c.constraint_id, c.status.value, str(sorted(c.payload.items())))
                   for c in result.final_constraints),
        )

    assert signature(run_cnp("dep_det", make())) == signature(run_cnp("dep_det", make()))


def test_infeasible_apply_is_noop():
    constraints = [
        _c("s1", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Security Agent", {"rule": "external_access", "mode": "restricted"}),
        _c("s2", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
           "Docker Agent", {"rule": "external_access", "mode": "unrestricted"}),
    ]
    conflicts = detect_conflicts(constraints)
    assert len(conflicts) == 1
    decision = resolve_conflict(constraints, conflicts[0])
    assert decision.method == "infeasible"
    before = [(c.constraint_id, c.status) for c in constraints]
    apply_decision(constraints, decision)
    assert [(c.constraint_id, c.status) for c in constraints] == before


# --- 8. Critic rejection preventing executor invocation -------------------------

def test_critic_escalate_blocks_executor_invocation(client, monkeypatch):
    import app.workflow.planning as planning
    from app.execution.executor import SimulatorExecutor

    repo = str((FIXTURES / "compose_app").resolve())
    calls = {"execute": 0}
    real_execute = SimulatorExecutor.execute

    def counting_execute(self, *args, **kwargs):
        calls["execute"] += 1
        return real_execute(self, *args, **kwargs)

    monkeypatch.setattr(SimulatorExecutor, "execute", counting_execute)
    # Simulate an unfixable defect: replan patches change nothing, so the
    # missing-env failure persists through every bounded round.
    monkeypatch.setattr(
        planning,
        "_apply_replan_fixes",
        lambda fragments, _v, _c=None: (
            fragments,
            {"applied": [], "rejected": [], "plan_changed": False},
        ),
    )

    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo,
                             intent="force verification failure, missing env"),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "failed"
    assert calls["execute"] == 0
    verification = client.get(
        f"/api/deploy/{final['deployment_id']}/verification").json()
    # Backend verdict stays ESCALATE (gate_recommendation); the UI label maps
    # it to BLOCK per the documented contract (VERIFICATION_SPEC).
    assert verification["critic"]["gate_recommendation"] == "ESCALATE"
    assert verification["critic"]["recommendation"] == "BLOCK"


# --- 9. Replanning causing CNP to run again ---------------------------------------

def test_replan_reruns_cnp_before_reverification(client):
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
    lines = client.get(f"/api/deploy/{deployment_id}/logs",
                       params={"limit": 2000}).json()["lines"]
    negotiate_starts = [ln for ln in lines if ln["type"] == "negotiation.started"]
    assert len(negotiate_starts) >= 2
    assert any("CNP re-run after replan" in ln["message"] for ln in negotiate_starts)


# --- 10. Complete negotiation failure path -----------------------------------------

def test_negotiation_failure_persists_honest_failed_outcome(client, monkeypatch):
    import app.workflow.planning as planning
    from app.models.domain import ConstraintType, Priority

    real_security = planning.run_security_agent

    def rogue_security(profile):
        result = real_security(profile)
        # A second hard SECURITY claim contradicting the agent's own policy:
        # same rule, incompatible mode. No deterministic compromise exists.
        result.constraints.append(
            _c("c_rogue_access", ConstraintType.SECURITY_POLICY, Priority.SECURITY,
               "Docker Agent", {"rule": "external_access", "mode": "unrestricted"})
        )
        result.summary += " + rogue hard claim"
        return result

    monkeypatch.setattr(planning, "run_security_agent", rogue_security)
    repo = str((FIXTURES / "compose_app").resolve())
    resp = client.post(
        "/api/deploy",
        json=_deploy_payload(mode="real", scenario=None, repository_url=repo),
    )
    assert resp.status_code == 202
    final = _wait_terminal(client, resp.json()["deployment_id"])
    assert final["status"] == "failed"
    assert final["result"]["kind"] == "failed"
    assert final["result"]["title"] == "PLAN_FAILED"
    assert "CNP" in (final.get("error_summary") or "")
    constraints = client.get(f"/api/deploy/{final['deployment_id']}/constraints").json()
    assert constraints["negotiation"]["status"] == "exhausted"
    health = client.get(f"/api/deploy/{final['deployment_id']}/health").json()
    assert health["health_status"] != "healthy"
