"""Focused tests: authoritative port contract (CNP → runtime → publish/probe).

Covers the port-negotiation fix without Docker and without the full suite:
CNP-selected host propagation, internal/host separation (Next.js + python),
genuine-conflict alternative negotiation, plan revalidation enforcement,
pinned-SHA / explicit-mode persistence, and the legacy Next.js path.
"""

from __future__ import annotations

import asyncio
import json

from app.agents.verifier import run_verifier
from app.cnp.engine import apply_decision, run_cnp
from app.execution.ports import (
    app_port_claim,
    negotiate_host_alternative,
    resolve_port_contract,
)
from app.models.domain import (
    ApplicationProfile,
    Constraint,
    ConstraintStatus,
    ConstraintType,
    InferredStack,
    NegotiationResult,
    Priority,
    ServiceHint,
)


def _port_claim(cid, service, source, port, status=ConstraintStatus.PROPOSED):
    return Constraint(
        constraint_id=cid,
        type=ConstraintType.PORT_CLAIM,
        priority=Priority.RESOURCE,
        source_agent=source,
        service=service,
        payload={
            "key": f"host:{port}", "port": port, "protocol": "tcp",
            "exclusive": True,
        },
        alternatives=[{"port": port + 1}, {"port": port + 2}],
        status=status,
    )


def _profile(port=8080) -> ApplicationProfile:
    return ApplicationProfile(
        deployment_id="dep_ports",
        repository_url="https://github.com/example/app",
        workspace_path=".",
        target_host="localhost",
        target_port=port,
        inferred_stack=InferredStack(
            services=[
                ServiceHint(name="network", role="network"),
                ServiceHint(name="backend", role="api", suggested_port=port),
            ],
            language_runtime="node",
            suggested_ports=[port],
            confidence=0.8,
            manifests_examined=["package.json"],
        ),
    )


def _negotiation(constraints) -> NegotiationResult:
    return NegotiationResult(
        deployment_id="dep_ports", status="resolved", rounds_used=1,
        max_rounds=3, final_constraints=constraints,
    )


# --- 1. CNP-selected host propagation ----------------------------------------

def test_app_claim_prefers_docker_over_nginx_edge():
    docker = _port_claim("c_docker", "backend", "Docker Agent", 8080)
    nginx = _port_claim("c_nginx", "nginx", "Nginx Agent", 8080)
    assert app_port_claim([docker, nginx]).constraint_id == "c_docker"
    # Edge-proxy claim alone is never authoritative: falls back to requested.
    assert app_port_claim([nginx]) is None
    assert app_port_claim([]) is None


def test_cnp_alternative_propagates_to_contract():
    result = run_cnp(
        "dep_ports",
        [_port_claim("c_port_docker_1", "backend", "Docker Agent", 8080),
         _port_claim("c_port_nginx_1", "nginx", "Nginx Agent", 8080)],
    )
    assert result.status == "resolved"
    contract = resolve_port_contract(
        _profile(), result.final_constraints, internal_port=8080
    )
    # Docker keeps the requested host port; the edge proxy takes the alternative.
    assert contract.host_port == 8080
    assert contract.internal_port == 8080
    assert contract.app_service == "backend"
    assert contract.mapping == "host 127.0.0.1:8080 → container:8080"
    assert contract.probe_url == "http://127.0.0.1:8080/"


def test_contract_preserves_script_pinned_internal_port(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"start": "node server.js --port 3000"},
        "dependencies": {"express": "^4.19.0"},
    }), encoding="utf-8")
    from app.execution.runtime import detect_runtime

    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.internal_port == 3000  # repository evidence wins
    contract = resolve_port_contract(
        _profile(), [_port_claim("c1", "backend", "Docker Agent", 8080,
                                status=ConstraintStatus.ACCEPTED)],
        internal_port=spec.internal_port,
    )
    assert (contract.internal_port, contract.host_port) == (3000, 8080)


def test_contract_falls_back_to_requested_target_without_claims():
    contract = resolve_port_contract(_profile(8080), [], internal_port=8080)
    assert (contract.host_port, contract.internal_port) == (8080, 8080)
    assert contract.source == "requested-target"


# --- 2. Internal/host separation (Next.js + python) --------------------------

NEXT_PKG = {
    "name": "site",
    "packageManager": "pnpm@10.12.4",
    "scripts": {"build": "next build", "start": "next start"},
    "dependencies": {"next": "16.2.12", "react": "19.2.4"},
}


def test_nextjs_host_rebind_keeps_internal_port_env(tmp_path):
    from app.execution.profiles import render_dockerfile
    from app.execution.runtime import detect_runtime, with_host_port

    (tmp_path / "package.json").write_text(json.dumps(NEXT_PKG), encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080)
    rebound = with_host_port(spec, 8081)
    assert (rebound.internal_port, rebound.host_port) == (8080, 8081)
    # The generated container still listens on the internal port/interface…
    assert rebound.env_defaults == {"PORT": "8080", "HOSTNAME": "0.0.0.0"}
    profile = rebound.to_build_profile()
    text = render_dockerfile(profile, checkout=tmp_path)
    assert "ENV PORT=8080" in text and "ENV HOSTNAME=0.0.0.0" in text
    assert "EXPOSE 8080" in text
    # …while only the publish side moves.
    assert profile.port == 8080


def test_python_host_rebind_rewrites_server_port(tmp_path):
    from app.execution.runtime import detect_runtime, with_host_port

    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("app = 1", encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.start.command[-1] == "8080"
    rebound = with_host_port(spec, 8083)
    assert (rebound.internal_port, rebound.host_port) == (8080, 8083)
    assert rebound.start.command[-1] == "8080"
    assert rebound.start.command[rebound.start.command.index("--port") + 1] == "8080"


# --- 3. Genuine conflicts + alternative negotiation --------------------------

def test_negotiate_host_alternative_skips_busy_and_used():
    constraints = [
        _port_claim("c_app", "backend", "Docker Agent", 8080,
                    status=ConstraintStatus.ACCEPTED),
        _port_claim("c_edge", "nginx", "Nginx Agent", 8081,
                    status=ConstraintStatus.SUPERSEDED),
    ]
    busy = {8081, 8082}  # 8081 held by the edge claim, 8082 by the host
    decision = negotiate_host_alternative(
        constraints, 8080, is_available=lambda p: p not in busy,
    )
    assert decision is not None
    assert decision.method == "alternative"
    assert decision.updates[0]["new_value"] == 8083
    apply_decision(constraints, decision)
    by_id = {c.constraint_id: c for c in constraints}
    assert by_id["c_app"].payload["port"] == 8083
    assert by_id["c_app"].payload["key"] == "host:8083"
    contract = resolve_port_contract(_profile(), constraints, internal_port=8080)
    assert (contract.host_port, contract.internal_port) == (8083, 8080)


def test_negotiate_host_alternative_exhausted_returns_none():
    constraints = [_port_claim("c_app", "backend", "Docker Agent", 8080,
                               status=ConstraintStatus.ACCEPTED)]
    assert negotiate_host_alternative(
        constraints, 8080, is_available=lambda p: False, max_candidates=3,
    ) is None
    assert negotiate_host_alternative([], 8080, is_available=lambda p: True) is None


# --- 4. Plan revalidation + verifier/critic enforcement -----------------------

def _fragments(service="backend", ports=None):
    return {
        "docker": {"compose_fragment": {"services": {
            service: {"image": "medha/backend:local",
                      "ports": ports or ["8080:8080"]}}}},
        "env_present": {},
    }


def test_verifier_rejects_unresolved_duplicate_host_ports():
    constraints = [
        _port_claim("c_a", "backend", "Docker Agent", 8080,
                    status=ConstraintStatus.ACCEPTED),
        _port_claim("c_b", "nginx", "Nginx Agent", 8080,
                    status=ConstraintStatus.ACCEPTED),
    ]
    result = run_verifier(
        deployment_id="dep_ports", profile=_profile(), constraints=constraints,
        negotiation=_negotiation(constraints), config_fragments=_fragments(),
    )
    assert result.passed is False
    assert any(c.rule == "PORT-001" for c in result.checks)


def test_verifier_accepts_remapped_ports_after_cnp_decision():
    constraints = [
        _port_claim("c_port_docker_1", "backend", "Docker Agent", 8080),
        _port_claim("c_port_nginx_1", "nginx", "Nginx Agent", 8080),
    ]
    negotiated = run_cnp("dep_ports", constraints)
    assert negotiated.status == "resolved"
    result = run_verifier(
        deployment_id="dep_ports", profile=_profile(),
        constraints=negotiated.final_constraints, negotiation=negotiated,
        config_fragments=_fragments(),
    )
    assert result.passed is True
    assert any(c.id == "ports" and c.status.value == "pass" for c in result.checks)


def test_compose_fragment_syncs_to_contracted_mapping():
    from app.workflow.planning import _sync_compose_ports

    contract = resolve_port_contract(
        _profile(),
        [_port_claim("c_app", "backend", "Docker Agent", 8083,
                     status=ConstraintStatus.SUPERSEDED)],
        internal_port=3000,
    )
    synced = _sync_compose_ports(_fragments(), contract)
    svc = synced["docker"]["compose_fragment"]["services"]["backend"]
    assert svc["ports"] == ["8083:3000"]
    # Unknown app service: fragment left untouched, never fabricated.
    from app.execution.ports import PortContract

    missing = PortContract(internal_port=3000, host_port=8083,
                           app_service="missing", source="x")
    assert _sync_compose_ports(_fragments(), missing) == _fragments()


# --- 4b. Pipeline host renegotiation + gate revalidation -----------------------

def _pipeline_repo(tmp_path, deployment_id="dep_ports_e2e"):
    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import DeploymentRepository
    from app.models.deployment import DeploymentRecord

    db = tmp_path / "ports.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    repo.create(DeploymentRecord(
        deployment_id=deployment_id,
        repository_url="https://github.com/example/app",
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, status=DeploymentStatus.RUNNING, current_stage=None,
        created_at=now, updated_at=now, is_demo=False,
    ))
    return repo


def _gate_inputs(tmp_path):
    import types

    from app.agents.critic import run_critic
    from app.agents.verifier import run_verifier

    (tmp_path / "package.json").write_text(json.dumps({
        "scripts": {"start": "node server.js"},
    }), encoding="utf-8")
    negotiated = run_cnp(
        "dep_ports_e2e",
        [_port_claim("c_port_docker_1", "backend", "Docker Agent", 8080),
         _port_claim("c_port_nginx_1", "nginx", "Nginx Agent", 8080)],
    )
    assert negotiated.status == "resolved"
    constraints = list(negotiated.final_constraints)
    fragments = _fragments()
    verification = run_verifier(
        deployment_id="dep_ports_e2e", profile=_profile(),
        constraints=constraints, negotiation=negotiated,
        config_fragments=fragments,
    )
    assert verification.passed
    critic = run_critic(
        deployment_id="dep_ports_e2e", profile=_profile(),
        constraints=constraints, negotiation=negotiated,
        verification=verification, config_fragments=fragments,
    )
    acquisition = types.SimpleNamespace(path=tmp_path, method="shallow_clone")
    return constraints, negotiated, fragments, verification, critic, acquisition


def test_pipeline_renegotiates_blocked_host_port_then_revalidates(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.execution import docker_ops
    from app.models.execution import CriticRecommendation
    from app.workflow.planning import PlanningPipeline

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(
        docker_ops, "is_port_available", lambda port: int(port) != 8080)

    repo = _pipeline_repo(tmp_path)
    constraints, negotiated, fragments, verification, critic, acquisition = (
        _gate_inputs(tmp_path))
    pipeline = PlanningPipeline(repo=repo)
    out = asyncio.run(pipeline._ensure_host_port(
        deployment_id="dep_ports_e2e", profile=_profile(),
        constraints=constraints, negotiation=negotiated,
        config_fragments=fragments, verification=verification, critic=critic,
        replan_count=0, change_requirements=None, change_risk=None,
        acquisition=acquisition, delay=0.0,
        ui_constraints=[c.to_ui() for c in constraints],
        ui_negotiation=negotiated.to_ui(),
    ))
    assert out["ok"] is True
    contract = out["contract"]
    # 8081 is held by the negotiated edge-proxy claim, so the supported
    # alternative is 8082; the container-internal port never moves.
    assert (contract.host_port, contract.internal_port) == (8082, 8080)
    assert contract.renegotiated is True
    # Gate revalidation ran on the remapped set — never bypassed.
    assert out["verification"].passed is True
    assert out["critic"].recommendation != CriticRecommendation.ESCALATE
    by_id = {c.constraint_id: c for c in out["constraints"]}
    assert by_id["c_port_docker_1"].payload["port"] == 8082
    assert by_id["c_port_docker_1"].payload["key"] == "host:8082"
    svc = out["config_fragments"]["docker"]["compose_fragment"]["services"]["backend"]
    assert svc["ports"] == ["8082:8080"]
    assert out["ui_negotiation"]["host_renegotiation"]["method"] == "alternative"
    stored = repo.get("dep_ports_e2e")
    assert stored.verification is not None and stored.critic is not None
    get_settings.cache_clear()


def test_pipeline_fails_precisely_when_no_host_alternative(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.execution import docker_ops
    from app.workflow.planning import PlanningPipeline

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(docker_ops, "is_port_available", lambda port: False)

    repo = _pipeline_repo(tmp_path, deployment_id="dep_ports_e2e")
    constraints, negotiated, fragments, verification, critic, acquisition = (
        _gate_inputs(tmp_path))
    pipeline = PlanningPipeline(repo=repo)
    out = asyncio.run(pipeline._ensure_host_port(
        deployment_id="dep_ports_e2e", profile=_profile(),
        constraints=constraints, negotiation=negotiated,
        config_fragments=fragments, verification=verification, critic=critic,
        replan_count=0, change_requirements=None, change_risk=None,
        acquisition=acquisition, delay=0.0,
        ui_constraints=[c.to_ui() for c in constraints],
        ui_negotiation=negotiated.to_ui(),
    ))
    assert out["ok"] is False
    assert out["code"] == "PORT_UNAVAILABLE"
    assert out["conflicting_resource"] == "host:127.0.0.1:8080"
    assert out["contract"]["internal_port"] == 8080
    # The blocked plan is untouched: still the negotiated 8080 claim.
    assert out["constraints"][0].payload["port"] == 8080
    get_settings.cache_clear()


def test_pipeline_skips_availability_claim_when_real_not_selected(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.execution import docker_ops
    from app.workflow.planning import PlanningPipeline

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "simulator")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "false")
    get_settings.cache_clear()
    calls: list = []
    monkeypatch.setattr(
        docker_ops, "is_port_available",
        lambda port: calls.append(port) or False)

    repo = _pipeline_repo(tmp_path, deployment_id="dep_ports_e2e")
    constraints, negotiated, fragments, verification, critic, acquisition = (
        _gate_inputs(tmp_path))
    pipeline = PlanningPipeline(repo=repo)
    out = asyncio.run(pipeline._ensure_host_port(
        deployment_id="dep_ports_e2e", profile=_profile(),
        constraints=constraints, negotiation=negotiated,
        config_fragments=fragments, verification=verification, critic=critic,
        replan_count=0, change_requirements=None, change_risk=None,
        acquisition=acquisition,
        delay=0.0,
        ui_constraints=[c.to_ui() for c in constraints],
        ui_negotiation=negotiated.to_ui(),
    ))
    assert out["ok"] is True
    assert calls == []  # the simulator binds nothing: no host claim made
    assert out["contract"].host_port == 8080
    get_settings.cache_clear()


# --- 5. Pinned SHA + explicit mode persistence --------------------------------

def test_selected_execution_mode_never_guesses(monkeypatch):
    from app.core.config import get_settings
    from app.workflow.planning import _selected_execution_mode

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    assert _selected_execution_mode(get_settings()) == "real"

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "simulator")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "false")
    get_settings.cache_clear()
    assert _selected_execution_mode(get_settings()) == "simulator"

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "auto")
    get_settings.cache_clear()
    assert _selected_execution_mode(get_settings()) == "unconfigured"
    get_settings.cache_clear()


def test_terminal_provenance_carries_sha_mode_and_contract():
    from app.workflow.planning import _terminal_provenance

    payload = _terminal_provenance(
        resolved_sha="a" * 40, requested_ref="main",
        repository_url="https://github.com/o/r", selected_mode="real",
        port_contract={"host_port": 8081, "internal_port": 8080},
    )
    assert payload["target_sha"] == "a" * 40
    assert payload["execution_mode"] == "real"
    assert payload["port_contract"]["host_port"] == 8081
    assert payload["requested_ref"] == "main"


# --- 6. Docker mapping / readiness consistency (mocked daemon) ------------------

def test_real_executor_split_host_container_mapping(tmp_path, monkeypatch):
    from app.execution import docker_ops
    from app.execution.real_executor import RealExecutor
    from app.core.config import get_settings

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "node server.js"}}), encoding="utf-8")

    captured: dict = {}

    def fake_start(**kwargs):
        captured.update(kwargs)
        return "medha_c1_app"

    internal, host = 8080, 8081
    monkeypatch.setattr(docker_ops, "docker_cli_available", lambda: True)
    monkeypatch.setattr(docker_ops, "docker_daemon_running", lambda: True)
    monkeypatch.setattr(docker_ops, "build_image", lambda **k: "sha256:abc")
    monkeypatch.setattr(docker_ops, "create_network", lambda deployment_id: "medha_net")
    monkeypatch.setattr(docker_ops, "start_container", fake_start)
    monkeypatch.setattr(docker_ops, "container_state", lambda name, **k: {
        "available": True, "running": True, "exit_code": 0, "oom_killed": False,
        "ports": {f"{internal}/tcp": [{"host_ip": "127.0.0.1",
                                       "host_port": str(host)}]},
    })
    seen_port: dict = {}
    import urllib.request as _url

    def fake_wait(port, **kwargs):
        seen_port["port"] = port
        return {"status": "ready", "http_status": 200, "attempts": 1,
                "probe_url": f"http://127.0.0.1:{port}/"}
    monkeypatch.setattr(docker_ops, "wait_http_readiness", fake_wait)
    monkeypatch.setattr(
        docker_ops, "container_logs",
        lambda name, **k: {"available": True, "stdout": "", "stderr": ""},
    )

    outcome = asyncio.run(RealExecutor().deploy(
        deployment_id="dep_split", checkout=tmp_path, target_port=internal,
        host_port=host, internal_port=internal, readiness_timeout=5,
        build_timeout=60,
    ))
    try:
        assert outcome.ok, f"{outcome.code}: {outcome.message[:300]}"
        assert captured["publish_port"] == host
        assert captured["container_port"] == internal
        assert captured["env"]["PORT"] == str(internal)
        assert seen_port["port"] == host
        assert outcome.port == host
        assert outcome.readiness["host_port"] == host
        assert outcome.readiness["container_port"] == internal
        assert outcome.readiness["mapping"] == (
            f"host 127.0.0.1:{host} → container:{internal}"
        )
        assert outcome.runtime_spec["host_port"] == host
        assert outcome.runtime_spec["internal_port"] == internal
    finally:
        asyncio.run(RealExecutor().cleanup(
            deployment_id="dep_split", container=outcome.container,
            image=outcome.image))


def test_nextjs_legacy_single_port_path_unchanged(tmp_path):
    """The existing successful Next.js path: no split, PORT env governs."""
    from app.execution.profiles import render_dockerfile
    from app.execution.runtime import detect_runtime

    (tmp_path / "package.json").write_text(json.dumps(NEXT_PKG), encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080, commit_sha="b" * 40)
    assert spec.profile == "nextjs"
    assert (spec.internal_port, spec.host_port) == (8080, 8080)
    assert spec.env_defaults == {"PORT": "8080", "HOSTNAME": "0.0.0.0"}
    assert spec.start.command == ["pnpm", "start"]
    text = render_dockerfile(spec.to_build_profile(), checkout=tmp_path)
    assert "ENV PORT=8080" in text and "RUN pnpm run build" in text
