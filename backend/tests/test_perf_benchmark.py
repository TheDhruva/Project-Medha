"""Repeatable simulator-level benchmarks for deterministic stages.

Measures specialists + CNP + verifier/critic over synthetic small/medium/
larger profiles. No Docker, no network, no LLM: numbers reflect pure
in-process orchestration cost on the test host. This module asserts only
correctness (negotiation resolves, gates complete); latencies are reported
via stdout for before/after comparison, never asserted against brittle
millisecond thresholds.
"""

from __future__ import annotations

import time

import pytest

from app.agents.critic import run_critic
from app.agents.docker_agent import run_docker_agent
from app.agents.nginx_agent import run_nginx_agent
from app.agents.security_agent import run_security_agent
from app.agents.verifier import run_verifier
from app.cnp.engine import run_cnp
from app.models.domain import (
    ApplicationProfile,
    InferredStack,
    ServiceHint,
)
from app.workflow.stages import StageTracker


def _profile(n_services: int) -> ApplicationProfile:
    services = [
        ServiceHint(
            name=f"svc_{i}",
            role="api" if i == 0 else "worker",
            evidence_paths=["package.json"],
            suggested_port=3000 + i,
        )
        for i in range(n_services)
    ]
    return ApplicationProfile(
        deployment_id=f"dep_bench_{n_services}",
        repository_url="bench://synthetic",
        workspace_path=".",
        target_host="localhost",
        target_port=8080,
        inferred_stack=InferredStack(
            services=services,
            language_runtime="node",
            has_dockerfile=True,
            has_compose=n_services > 1,
            suggested_ports=[3000 + i for i in range(n_services)],
            confidence=0.8,
            manifests_examined=["package.json"],
        ),
    )


def _config_fragments(n_services: int) -> dict:
    return {
        "docker": {
            "compose_fragment": {
                "services": {
                    f"svc_{i}": {
                        "image": f"bench/svc_{i}:latest",
                        "ports": [f"{3000 + i}:{3000 + i}"],
                        "environment": {},
                    }
                    for i in range(n_services)
                }
            }
        },
        "nginx": {"servers": []},
        "security": {"policies": ["tls-required"]},
        "env_present": {},
    }


@pytest.mark.parametrize("n_services", [1, 4, 12])
def test_benchmark_deterministic_stages(n_services: int):
    profile = _profile(n_services)
    deployment_id = profile.deployment_id
    tracker = StageTracker()
    marks: dict[str, float] = {}

    t0 = time.perf_counter()
    tracker.start("docker", "benchmark")
    docker_res = run_docker_agent(profile)
    tracker.finish("docker", "complete")
    marks["specialists_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    nginx_res = run_nginx_agent(profile)
    security_res = run_security_agent(profile)
    marks["specialists_ms"] = (time.perf_counter() - t0) * 1000.0 + marks["specialists_ms"]

    constraints = [
        *docker_res.constraints,
        *nginx_res.constraints,
        *security_res.constraints,
    ]

    t0 = time.perf_counter()
    tracker.start("mediator", "benchmark")
    negotiation = run_cnp(deployment_id, constraints, is_demo=False)
    tracker.finish("mediator", "complete")
    marks["cnp_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    tracker.start("verifier", "benchmark")
    verification = run_verifier(
        deployment_id=deployment_id,
        profile=profile,
        constraints=list(negotiation.final_constraints),
        negotiation=negotiation,
        config_fragments=_config_fragments(n_services),
    )
    tracker.finish("verifier", "complete")
    marks["verify_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    tracker.start("critic", "benchmark")
    critic = run_critic(
        deployment_id=deployment_id,
        profile=profile,
        constraints=list(negotiation.final_constraints),
        negotiation=negotiation,
        verification=verification,
        config_fragments=_config_fragments(n_services),
    )
    tracker.finish("critic", "complete")
    marks["critic_ms"] = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    rows = tracker.snapshot()
    marks["snapshot_ms"] = (time.perf_counter() - t0) * 1000.0

    assert negotiation.status == "resolved"
    assert len(rows) == 10
    assert all(row["durationMs"] is not None for row in rows
               if row["id"] in {"docker", "mediator", "verifier", "critic"})

    total_ms = sum(marks.values())
    print(
        f"\nBENCH services={n_services} "
        + " ".join(f"{k}={v:.1f}" for k, v in sorted(marks.items()))
        + f" total_ms={total_ms:.1f} constraints={len(constraints)} "
        f"decisions={len(negotiation.decisions)} rounds={negotiation.rounds_used} "
        f"verify_passed={verification.passed} critic={critic.recommendation.value}"
    )
