"""Deterministic step sequences for the five Demo Mode scenarios."""

from __future__ import annotations

from app.core.enums import DeploymentStatus, EventType, ScenarioId, StageId
from app.demo import fixtures as F
from app.demo.models import DemoScenarioDef, DemoStep


def _stage(
    stage: StageId,
    *,
    started: bool,
    message: str,
    simple: str,
    technical: str,
    agents: list[dict] | None = None,
    pipeline: dict | None = None,
    delay: float = 0.3,
    extra: dict | None = None,
) -> DemoStep:
    data: dict = {
        "simple": simple,
        "technical": technical,
        "is_demo": True,
        "label": "DEMO/MOCK",
    }
    if agents is not None:
        data["agents"] = agents
    if pipeline is not None:
        data["pipeline"] = pipeline
    if extra:
        data.update(extra)
    return DemoStep(
        event_type=EventType.STAGE_STARTED.value if started else EventType.STAGE_COMPLETED.value,
        message=message,
        stage=stage,
        status="running" if started else "success",
        delay_after=delay,
        explain_simple=simple,
        explain_technical=technical,
        deployment_status=DeploymentStatus.RUNNING,
        data=data,
    )


def _common_early() -> list[DemoStep]:
    return [
        DemoStep(
            event_type=EventType.DEPLOYMENT_STARTED.value,
            message="DEMO deployment pipeline started.",
            status=DeploymentStatus.RUNNING.value,
            delay_after=0.25,
            explain_simple="MEDHA is starting a deterministic DEMO deployment.",
            explain_technical="workflow=demo · is_demo=true · label=DEMO/MOCK",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "MEDHA is starting a deterministic DEMO deployment.",
                "technical": "workflow=demo · is_demo=true · label=DEMO/MOCK",
                "agents": F.INITIAL_AGENTS,
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.PREFLIGHT,
            started=True,
            message="PREFLIGHT started",
            simple="MEDHA is checking the deployment prerequisites.",
            technical="agent=preflight · checks=[local_target,demo_fixtures] · is_demo=true",
            agents=F.merge_agents(
                {
                    "preflight": {
                        "status": "running",
                        "activity": "Checking DEMO prerequisites",
                        "lastEvent": "Preflight started",
                    }
                }
            ),
            pipeline={"PREFLIGHT": {"status": "running", "detail": "Checking prerequisites"}},
        ),
        _stage(
            StageId.PREFLIGHT,
            started=False,
            message="PREFLIGHT completed",
            simple="Preflight checks completed.",
            technical="agent=preflight · status=success · is_demo=true",
            agents=F.merge_agents(
                {
                    "preflight": {
                        "status": "complete",
                        "activity": "DEMO prerequisites confirmed",
                        "lastEvent": "Preflight completed",
                        "durationMs": 300,
                    }
                }
            ),
            pipeline={"PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"}},
            delay=0.25,
        ),
        _stage(
            StageId.ANALYZE,
            started=True,
            message="ANALYZE started",
            simple="MEDHA is identifying the application's deployment structure.",
            technical="agent=analyzer · source=demo_fixtures · is_demo=true",
            agents=F.merge_agents(
                {
                    "preflight": {
                        "status": "complete",
                        "activity": "DEMO prerequisites confirmed",
                        "lastEvent": "Preflight completed",
                    },
                    "analyzer": {
                        "status": "running",
                        "activity": "Loading fixture stack definition",
                        "lastEvent": "Analysis started",
                    },
                }
            ),
            pipeline={
                "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
                "ANALYZE": {"status": "running", "detail": "Inferring stack"},
            },
        ),
        _stage(
            StageId.ANALYZE,
            started=False,
            message="ANALYZE completed",
            simple="Repository structure identified from DEMO fixtures.",
            technical="inferred_stack=node+postgres+nginx · services=5 · is_demo=true",
            agents=F.merge_agents(
                {
                    "preflight": {
                        "status": "complete",
                        "activity": "DEMO prerequisites confirmed",
                        "lastEvent": "Preflight completed",
                    },
                    "analyzer": {
                        "status": "complete",
                        "activity": "Inferred network/database/backend/frontend/analytics",
                        "lastEvent": "Analysis completed",
                        "durationMs": 280,
                    },
                }
            ),
            pipeline={
                "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
                "ANALYZE": {"status": "success", "detail": "Stack inferred"},
            },
            delay=0.25,
        ),
        _stage(
            StageId.PLAN,
            started=True,
            message="PLAN started",
            simple="MEDHA is drafting a deployment task from the inferred structure.",
            technical="stage=PLAN · task_spec=demo · services=[network,database,backend,frontend,analytics]",
            pipeline={
                "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
                "ANALYZE": {"status": "success", "detail": "Stack inferred"},
                "PLAN": {"status": "running", "detail": "Building task specification"},
            },
        ),
        _stage(
            StageId.PLAN,
            started=False,
            message="PLAN completed",
            simple="Deployment task specification is ready.",
            technical="stage=PLAN · status=success · is_demo=true",
            pipeline={
                "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
                "ANALYZE": {"status": "success", "detail": "Stack inferred"},
                "PLAN": {"status": "success", "detail": "Task ready"},
            },
            delay=0.25,
        ),
    ]


def _agents_publish(constraints: list[dict], scenario_note: str) -> list[DemoStep]:
    return [
        _stage(
            StageId.AGENTS,
            started=True,
            message="AGENTS started",
            simple="Specialist agents are preparing deployment requirements.",
            technical=f"agents=[docker,nginx,security] · {scenario_note} · is_demo=true",
            agents=F.merge_agents(
                {
                    "preflight": {
                        "status": "complete",
                        "activity": "DEMO prerequisites confirmed",
                        "lastEvent": "Preflight completed",
                    },
                    "analyzer": {
                        "status": "complete",
                        "activity": "Fixture stack ready",
                        "lastEvent": "Analysis completed",
                    },
                    "docker": {
                        "status": "running",
                        "activity": "Publishing container constraints",
                        "lastEvent": "Docker Agent active",
                    },
                    "nginx": {
                        "status": "running",
                        "activity": "Publishing proxy constraints",
                        "lastEvent": "Nginx Agent active",
                    },
                    "security": {
                        "status": "running",
                        "activity": "Publishing security policies",
                        "lastEvent": "Security Agent active",
                    },
                }
            ),
            pipeline={
                "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
                "ANALYZE": {"status": "success", "detail": "Stack inferred"},
                "PLAN": {"status": "success", "detail": "Task ready"},
                "AGENTS": {"status": "running", "detail": "Publishing constraints"},
            },
            extra={"constraints": [{**c, "status": "proposed"} for c in constraints]},
            delay=0.35,
        ),
        DemoStep(
            event_type=EventType.CONSTRAINT_PUBLISHED.value,
            message="Specialist agents published typed constraints.",
            stage=StageId.AGENTS,
            status="running",
            delay_after=0.3,
            explain_simple="Specialist agents published typed infrastructure constraints.",
            explain_technical="event=constraint.published · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "Specialist agents published typed infrastructure constraints.",
                "technical": "event=constraint.published · is_demo=true",
                "constraints": [{**c, "status": "proposed"} for c in constraints],
                "agents": F.merge_agents(
                    {
                        "docker": {
                            "status": "complete",
                            "activity": "Published Docker constraints",
                            "lastEvent": "Constraints published",
                            "durationMs": 220,
                        },
                        "nginx": {
                            "status": "complete",
                            "activity": "Published Nginx constraints",
                            "lastEvent": "Constraints published",
                            "durationMs": 200,
                        },
                        "security": {
                            "status": "complete",
                            "activity": "Published security policies",
                            "lastEvent": "Policies published",
                            "durationMs": 180,
                        },
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.AGENTS,
            started=False,
            message="AGENTS completed",
            simple="Specialist agents finished publishing requirements.",
            technical="stage=AGENTS · status=success · is_demo=true",
            agents=F.merge_agents(
                {
                    "docker": {
                        "status": "complete",
                        "activity": "Published Docker constraints",
                        "lastEvent": "Constraints published",
                    },
                    "nginx": {
                        "status": "complete",
                        "activity": "Published Nginx constraints",
                        "lastEvent": "Constraints published",
                    },
                    "security": {
                        "status": "complete",
                        "activity": "Published security policies",
                        "lastEvent": "Policies published",
                    },
                    "mediator": {
                        "status": "running",
                        "activity": "Collecting constraint set",
                        "lastEvent": "CNP collect",
                    },
                }
            ),
            pipeline={
                "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
                "ANALYZE": {"status": "success", "detail": "Stack inferred"},
                "PLAN": {"status": "success", "detail": "Task ready"},
                "AGENTS": {"status": "success", "detail": "Constraints published"},
            },
            extra={"constraints": [{**c, "status": "proposed"} for c in constraints]},
            delay=0.25,
        ),
    ]


def _verify_execute_success(
    *,
    constraints: list[dict],
    negotiation: dict,
    critic_score: int,
    result: dict,
    constraints_resolved: int,
    pipeline_early: dict,
) -> list[DemoStep]:
    early = {
        **pipeline_early,
        "NEGOTIATE": {"status": "success", "detail": negotiation.get("resolution") or "Agreed"},
    }
    return [
        _stage(
            StageId.VERIFY,
            started=True,
            message="VERIFY started",
            simple="MEDHA is checking the generated configuration before execution.",
            technical="agent=verifier · gate=pre_exec · is_demo=true",
            agents=F.merge_agents(
                {
                    "mediator": {
                        "status": "complete",
                        "activity": negotiation.get("resolution") or "Constraints agreed",
                        "lastEvent": "CNP resolved",
                    },
                    "verifier": {
                        "status": "running",
                        "activity": "Running hard verification checks",
                        "lastEvent": "Verification started",
                    },
                }
            ),
            pipeline={**early, "VERIFY": {"status": "running", "detail": "Hard checks running"}},
            extra={
                "constraints": constraints,
                "negotiation": negotiation,
                "verification": {
                    "checks": [
                        {**c, "status": "pending", "message": "Running…"}
                        for c in F.VERIFICATION_CHECKS_PASS
                    ],
                    "passed": None,
                    "summary": "Verification in progress",
                    "is_demo": True,
                },
            },
        ),
        DemoStep(
            event_type=EventType.VERIFICATION_PASSED.value,
            message="Verification passed.",
            stage=StageId.VERIFY,
            status="success",
            delay_after=0.3,
            explain_simple="Configuration checks passed. Execution is allowed.",
            explain_technical="verification.passed=true · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "Configuration checks passed. Execution is allowed.",
                "technical": "verification.passed=true · is_demo=true",
                "verification": {
                    "checks": F.VERIFICATION_CHECKS_PASS,
                    "passed": True,
                    "summary": "Verification passed. Execution is allowed.",
                    "is_demo": True,
                },
                "critic": {
                    "score": critic_score,
                    "breakdown": {
                        "security": min(100, critic_score + 2),
                        "completeness": max(0, critic_score - 2),
                        "constraints": 100,
                        "intentAlignment": max(0, critic_score - 4),
                    },
                    "recommendation": "PASS",
                    "findings": ["Demo configuration meets hard gates"],
                    "is_demo": True,
                },
                "agents": F.merge_agents(
                    {
                        "verifier": {
                            "status": "complete",
                            "activity": "All hard checks passed",
                            "lastEvent": "Verification passed",
                            "durationMs": 320,
                        },
                        "critic": {
                            "status": "complete",
                            "activity": f"Quality score {critic_score} — PASS",
                            "lastEvent": "Critic complete",
                            "durationMs": 200,
                        },
                    }
                ),
                "pipeline": {
                    **early,
                    "VERIFY": {"status": "success", "detail": "Gate passed"},
                },
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.VERIFY,
            started=False,
            message="VERIFY completed",
            simple="Verification gate passed.",
            technical="stage=VERIFY · status=success · is_demo=true",
            pipeline={**early, "VERIFY": {"status": "success", "detail": "Gate passed"}},
            delay=0.2,
        ),
        _stage(
            StageId.EXECUTE,
            started=True,
            message="EXECUTE started",
            simple="MEDHA is applying the agreed DEMO plan and recording causal execution nodes.",
            technical="agent=executor · mode=DEMO/MOCK · ceg.write=true",
            agents=F.merge_agents(
                {
                    "executor": {
                        "status": "running",
                        "activity": "Applying DEMO plan (MOCK)",
                        "lastEvent": "Execution started",
                    }
                }
            ),
            pipeline={
                **early,
                "VERIFY": {"status": "success", "detail": "Gate passed"},
                "EXECUTE": {"status": "running", "detail": "Starting services (DEMO)"},
            },
            extra={
                "graph": F.graph_execution_progress(network="running"),
                "constraints": constraints,
                "negotiation": negotiation,
            },
        ),
        DemoStep(
            event_type=EventType.EXECUTION_SERVICE_STATUS.value,
            message="All DEMO services succeeded.",
            stage=StageId.EXECUTE,
            status="success",
            delay_after=0.35,
            explain_simple="All services reported success in the DEMO causal graph.",
            technical="ceg.nodes=all_success · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "All services reported success in the DEMO causal graph.",
                "technical": "ceg.nodes=all_success · is_demo=true",
                "graph": F.graph_all_success(),
                "agents": F.merge_agents(
                    {
                        "executor": {
                            "status": "complete",
                            "activity": "All CEG nodes succeeded (MOCK)",
                            "lastEvent": "Execution complete",
                            "durationMs": 900,
                        },
                        "rollback": {
                            "status": "skipped",
                            "activity": "No failure scope",
                            "lastEvent": "Rollback not needed",
                        },
                    }
                ),
                "pipeline": {
                    **early,
                    "VERIFY": {"status": "success", "detail": "Gate passed"},
                    "EXECUTE": {"status": "success", "detail": "Services running"},
                    "RECOVER": {"status": "skipped", "detail": "Not required"},
                },
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.EXECUTE,
            started=False,
            message="EXECUTE completed",
            simple="DEMO execution finished successfully.",
            technical="stage=EXECUTE · status=success · is_demo=true",
            pipeline={
                **early,
                "VERIFY": {"status": "success", "detail": "Gate passed"},
                "EXECUTE": {"status": "success", "detail": "Services running"},
                "RECOVER": {"status": "skipped", "detail": "Not required"},
            },
            delay=0.2,
        ),
        DemoStep(
            event_type=EventType.DEPLOYMENT_COMPLETED.value,
            message="Deployment completed successfully.",
            stage=StageId.COMPLETE,
            status=DeploymentStatus.COMPLETED.value,
            delay_after=0.0,
            explain_simple="Deployment completed successfully.",
            explain_technical=(
                f"final_status=succeeded · constraints_resolved={constraints_resolved} "
                "· is_demo=true · label=DEMO/MOCK"
            ),
            deployment_status=DeploymentStatus.COMPLETED,
            data={
                "simple": "Deployment completed successfully.",
                "technical": (
                    f"final_status=succeeded · constraints_resolved={constraints_resolved} "
                    "· is_demo=true · label=DEMO/MOCK"
                ),
                "result": result,
                "constraints": constraints,
                "negotiation": negotiation,
                "verification": {
                    "checks": F.VERIFICATION_CHECKS_PASS,
                    "passed": True,
                    "summary": "Verification passed.",
                    "is_demo": True,
                },
                "critic": {
                    "score": critic_score,
                    "breakdown": {
                        "security": min(100, critic_score + 2),
                        "completeness": max(0, critic_score - 2),
                        "constraints": 100,
                        "intentAlignment": max(0, critic_score - 4),
                    },
                    "recommendation": "PASS",
                    "findings": ["Demo configuration meets hard gates"],
                    "is_demo": True,
                },
                "graph": F.graph_all_success(),
                "rollback": None,
                "pipeline": {
                    **early,
                    "VERIFY": {"status": "success", "detail": "Gate passed"},
                    "EXECUTE": {"status": "success", "detail": "Services running"},
                    "RECOVER": {"status": "skipped", "detail": "Not required"},
                    "COMPLETE": {"status": "success", "detail": "Deployment finished"},
                },
                "label": "DEMO/MOCK",
            },
        ),
    ]


def build_successful_deployment() -> DemoScenarioDef:
    constraints = [{**c} for c in F.CLEAN_CONSTRAINTS]
    negotiation = {
        "title": "CONSTRAINT NEGOTIATION",
        "conflictSummary": "No conflicting claims detected",
        "round": 1,
        "maxRounds": F.MAX_CNP_ROUNDS,
        "resolution": "Constraint set accepted as proposed",
        "method": "VALIDATE",
        "status": "resolved",
        "rounds_used": 1,
        "max_rounds": F.MAX_CNP_ROUNDS,
        "involvedConstraintIds": [c["id"] for c in constraints],
        "simpleExplanation": (
            "All specialist constraints were compatible, so MEDHA skipped conflict mediation."
        ),
        "technicalNotes": ["conflicts=0", "rounds_used=1", "method=VALIDATE", "is_demo=true"],
        "is_demo": True,
    }
    pipeline_early = {
        "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
        "ANALYZE": {"status": "success", "detail": "Stack inferred"},
        "PLAN": {"status": "success", "detail": "Task ready"},
        "AGENTS": {"status": "success", "detail": "Constraints published"},
    }
    steps = [
        *_common_early(),
        *_agents_publish(constraints, "scenario=SUCCESSFUL_DEPLOYMENT"),
        DemoStep(
            event_type=EventType.NEGOTIATION_STARTED.value,
            message="Negotiation started — collecting constraints.",
            stage=StageId.NEGOTIATE,
            status="running",
            delay_after=0.3,
            explain_simple="MEDHA is collecting typed constraints before execution.",
            explain_technical="cnp.phase=COLLECT · round=1/3 · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "MEDHA is collecting typed constraints before execution.",
                "technical": "cnp.phase=COLLECT · round=1/3 · is_demo=true",
                "constraints": constraints,
                "negotiation": {**negotiation, "status": "detecting", "resolution": None, "method": None},
                "pipeline": {
                    **pipeline_early,
                    "NEGOTIATE": {"status": "running", "detail": "Collecting constraints"},
                },
                "agents": F.merge_agents(
                    {
                        "mediator": {
                            "status": "running",
                            "activity": "Collecting and validating constraints",
                            "lastEvent": "CNP collect",
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.NEGOTIATION_RESOLVED.value,
            message="No conflicts — constraint set accepted.",
            stage=StageId.NEGOTIATE,
            status="success",
            delay_after=0.3,
            explain_simple="No constraint conflicts were detected.",
            explain_technical="cnp.status=resolved · conflicts=0 · method=VALIDATE · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "No constraint conflicts were detected.",
                "technical": "cnp.status=resolved · conflicts=0 · method=VALIDATE · is_demo=true",
                "constraints": constraints,
                "negotiation": negotiation,
                "pipeline": {
                    **pipeline_early,
                    "NEGOTIATE": {"status": "success", "detail": "No conflicts"},
                },
                "agents": F.merge_agents(
                    {
                        "mediator": {
                            "status": "complete",
                            "activity": "Constraint set validated — no conflicts",
                            "lastEvent": "CNP resolved",
                            "durationMs": 280,
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.NEGOTIATE,
            started=False,
            message="NEGOTIATE completed",
            simple="Negotiation completed with no conflicts.",
            technical="stage=NEGOTIATE · status=success · is_demo=true",
            pipeline={
                **pipeline_early,
                "NEGOTIATE": {"status": "success", "detail": "No conflicts"},
            },
            delay=0.2,
        ),
        *_verify_execute_success(
            constraints=constraints,
            negotiation=negotiation,
            critic_score=94,
            result=F.success_result(
                message="Deployment completed successfully.",
                verification_score=94,
                constraints_resolved=0,
            ),
            constraints_resolved=0,
            pipeline_early=pipeline_early,
        ),
    ]
    return DemoScenarioDef(
        id=ScenarioId.SUCCESSFUL_DEPLOYMENT,
        name="Successful Deployment",
        description="Happy path through analysis, CNP, verify, and execute.",
        expected_final_status=DeploymentStatus.COMPLETED,
        steps=steps,
    )


def build_port_conflict() -> DemoScenarioDef:
    proposed = F.PORT_CONFLICT_PROPOSED
    conflicted = F.port_conflict_constraints()
    resolved = F.port_resolved_constraints()
    negotiation_detecting = {
        "title": "CONSTRAINT NEGOTIATION",
        "conflictSummary": "Docker and Nginx both claimed host port 8080",
        "round": 1,
        "maxRounds": F.MAX_CNP_ROUNDS,
        "status": "resolving",
        "rounds_used": 1,
        "max_rounds": F.MAX_CNP_ROUNDS,
        "involvedConstraintIds": ["c_port_docker", "c_port_nginx"],
        "simpleExplanation": (
            "Two deployment components requested the same port. MEDHA detected the conflict "
            "before execution and is selecting an available alternative."
        ),
        "technicalNotes": [
            "conflict_id=cf_port_8080",
            "type=PORT_CLAIM",
            "key=host:8080",
            "priority=RESOURCE vs RESOURCE",
            "round=1/3",
        ],
        "is_demo": True,
    }
    negotiation_resolved = {
        **negotiation_detecting,
        "status": "resolved",
        "resolution": "8081 selected for Nginx",
        "method": "ALTERNATIVE",
        "simpleExplanation": (
            "Two deployment components requested the same port. MEDHA detected the conflict "
            "before execution and selected an available alternative."
        ),
        "technicalNotes": [
            "conflict_id=cf_port_8080",
            "method=ALTERNATIVE",
            "old_value=8080",
            "new_value=8081",
            "winner=c_port_docker",
            "loser=c_port_nginx",
            "rounds_used=1",
        ],
    }
    pipeline_early = {
        "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
        "ANALYZE": {"status": "success", "detail": "Stack inferred"},
        "PLAN": {"status": "success", "detail": "Task ready"},
        "AGENTS": {"status": "success", "detail": "Constraints published"},
    }
    steps = [
        *_common_early(),
        *_agents_publish(proposed, "scenario=PORT_CONFLICT"),
        DemoStep(
            event_type=EventType.NEGOTIATION_STARTED.value,
            message="Negotiation round 1 started.",
            stage=StageId.NEGOTIATE,
            status="running",
            delay_after=0.3,
            explain_simple="MEDHA is comparing published constraints before execution.",
            explain_technical="cnp.phase=DETECT_CONFLICT · round=1/3 · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "MEDHA is comparing published constraints before execution.",
                "technical": "cnp.phase=DETECT_CONFLICT · round=1/3 · is_demo=true",
                "constraints": conflicted,
                "negotiation": {**negotiation_detecting, "status": "detecting"},
                "pipeline": {
                    **pipeline_early,
                    "NEGOTIATE": {"status": "running", "detail": "Detecting conflicts"},
                },
                "agents": F.merge_agents(
                    {
                        "mediator": {
                            "status": "running",
                            "activity": "Detecting port conflicts",
                            "lastEvent": "CNP detect",
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.CONSTRAINT_CONFLICT.value,
            message="CONSTRAINT CONFLICT: PORT CLAIM host:8080",
            stage=StageId.NEGOTIATE,
            status="warning",
            level="warning",
            delay_after=0.4,
            explain_simple=(
                "Two deployment components requested the same port. MEDHA detected the conflict "
                "before execution."
            ),
            explain_technical=(
                "conflict_id=cf_port_8080 · type=PORT_CLAIM · key=host:8080 · "
                "c_port_docker=8080 · c_port_nginx=8080 · priority=RESOURCE · round=1"
            ),
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": (
                    "Two deployment components requested the same port. MEDHA detected the "
                    "conflict before execution."
                ),
                "technical": (
                    "conflict_id=cf_port_8080 · type=PORT_CLAIM · key=host:8080 · "
                    "c_port_docker=8080 · c_port_nginx=8080 · priority=RESOURCE · round=1"
                ),
                "constraints": conflicted,
                "negotiation": negotiation_detecting,
                "conflict": {
                    "conflict_id": "cf_port_8080",
                    "type": "PORT_CLAIM",
                    "key": "host:8080",
                    "constraint_ids": ["c_port_docker", "c_port_nginx"],
                    "values": {"c_port_docker": 8080, "c_port_nginx": 8080},
                    "priorities": {"c_port_docker": "RESOURCE", "c_port_nginx": "RESOURCE"},
                    "round": 1,
                },
                "pipeline": {
                    **pipeline_early,
                    "NEGOTIATE": {"status": "warning", "detail": "Conflict detected"},
                },
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.NEGOTIATION_RESOLVED.value,
            message="Conflict resolved: Nginx remapped to 8081.",
            stage=StageId.NEGOTIATE,
            status="success",
            delay_after=0.35,
            explain_simple=(
                "MEDHA selected an alternative that satisfies the deployment requirements."
            ),
            explain_technical=(
                "method=ALTERNATIVE · old_value=8080 · new_value=8081 · "
                "target=c_port_nginx · round=1 · is_demo=true"
            ),
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": (
                    "MEDHA selected an alternative that satisfies the deployment requirements."
                ),
                "technical": (
                    "method=ALTERNATIVE · old_value=8080 · new_value=8081 · "
                    "target=c_port_nginx · round=1 · is_demo=true"
                ),
                "constraints": resolved,
                "negotiation": negotiation_resolved,
                "resolution": {
                    "method": "ALTERNATIVE",
                    "old_value": 8080,
                    "new_value": 8081,
                    "constraint_id": "c_port_nginx",
                    "round": 1,
                },
                "pipeline": {
                    **pipeline_early,
                    "NEGOTIATE": {"status": "success", "detail": "Port remapped"},
                },
                "agents": F.merge_agents(
                    {
                        "mediator": {
                            "status": "complete",
                            "activity": "Resolved port conflict via alternative",
                            "lastEvent": "Conflict resolved",
                            "durationMs": 420,
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.NEGOTIATE,
            started=False,
            message="NEGOTIATE completed",
            simple="Negotiation succeeded after alternative selection.",
            technical="stage=NEGOTIATE · status=success · method=ALTERNATIVE · is_demo=true",
            pipeline={
                **pipeline_early,
                "NEGOTIATE": {"status": "success", "detail": "Port remapped"},
            },
            delay=0.2,
        ),
        *_verify_execute_success(
            constraints=resolved,
            negotiation=negotiation_resolved,
            critic_score=91,
            result=F.success_result(
                message="Deployment completed successfully after constraint negotiation.",
                verification_score=91,
                constraints_resolved=1,
                duration_label="~14s",
            ),
            constraints_resolved=1,
            pipeline_early=pipeline_early,
        ),
    ]
    return DemoScenarioDef(
        id=ScenarioId.PORT_CONFLICT,
        name="Port Conflict",
        description="Same-priority PORT_CLAIM conflict resolved via alternative port.",
        expected_final_status=DeploymentStatus.COMPLETED,
        steps=steps,
    )


def build_security_conflict() -> DemoScenarioDef:
    proposed = F.SECURITY_CONFLICT_PROPOSED
    conflicted = F.security_conflict_constraints()
    resolved = F.security_resolved_constraints()
    negotiation_detecting = {
        "title": "CONSTRAINT NEGOTIATION",
        "conflictSummary": "Unrestricted access preference conflicts with security policy",
        "round": 1,
        "maxRounds": F.MAX_CNP_ROUNDS,
        "status": "resolving",
        "rounds_used": 1,
        "max_rounds": F.MAX_CNP_ROUNDS,
        "involvedConstraintIds": ["c_net_open", "c_sec_restricted"],
        "simpleExplanation": (
            "MEDHA detected a security conflict and is applying priority order before execution."
        ),
        "technicalNotes": [
            "SECURITY > PREFERENCE",
            "ids=[c_sec_restricted,c_net_open]",
            "round=1/3",
        ],
        "is_demo": True,
    }
    negotiation_resolved = {
        **negotiation_detecting,
        "status": "resolved",
        "resolution": "Restricted access enforced; unsafe preference rejected",
        "method": "PRIORITY",
        "simpleExplanation": (
            "MEDHA detected a security conflict and kept the safer policy because security "
            "constraints have higher priority."
        ),
        "technicalNotes": [
            "method=PRIORITY",
            "winner=c_sec_restricted (SECURITY)",
            "loser=c_net_open (PREFERENCE)",
            "rounds_used=1",
        ],
    }
    pipeline_early = {
        "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
        "ANALYZE": {"status": "success", "detail": "Stack inferred"},
        "PLAN": {"status": "success", "detail": "Task ready"},
        "AGENTS": {"status": "success", "detail": "Constraints published"},
    }
    steps = [
        *_common_early(),
        *_agents_publish(proposed, "scenario=SECURITY_CONFLICT"),
        DemoStep(
            event_type=EventType.NEGOTIATION_STARTED.value,
            message="Negotiation round 1 started.",
            stage=StageId.NEGOTIATE,
            status="running",
            delay_after=0.3,
            explain_simple="MEDHA is evaluating security and preference constraints.",
            explain_technical="cnp.phase=PRIORITY_RESOLUTION · round=1/3 · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "MEDHA is evaluating security and preference constraints.",
                "technical": "cnp.phase=PRIORITY_RESOLUTION · round=1/3 · is_demo=true",
                "constraints": conflicted,
                "negotiation": {**negotiation_detecting, "status": "detecting"},
                "pipeline": {
                    **pipeline_early,
                    "NEGOTIATE": {"status": "running", "detail": "Comparing priorities"},
                },
                "agents": F.merge_agents(
                    {
                        "mediator": {
                            "status": "running",
                            "activity": "Comparing SECURITY vs PREFERENCE",
                            "lastEvent": "Priority evaluation",
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.CONSTRAINT_CONFLICT.value,
            message="SECURITY CONFLICT detected.",
            stage=StageId.NEGOTIATE,
            status="warning",
            level="warning",
            delay_after=0.4,
            explain_simple=(
                "A lower-priority request conflicts with a security policy. MEDHA is applying "
                "priority rules."
            ),
            explain_technical=(
                "conflict_id=cf_sec_access · SECURITY>PREFERENCE · "
                "c_sec_restricted vs c_net_open · round=1"
            ),
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": (
                    "A lower-priority request conflicts with a security policy. MEDHA is applying "
                    "priority rules."
                ),
                "technical": (
                    "conflict_id=cf_sec_access · SECURITY>PREFERENCE · "
                    "c_sec_restricted vs c_net_open · round=1"
                ),
                "constraints": conflicted,
                "negotiation": negotiation_detecting,
                "conflict": {
                    "conflict_id": "cf_sec_access",
                    "type": "SECURITY_POLICY",
                    "constraint_ids": ["c_net_open", "c_sec_restricted"],
                    "priorities": {
                        "c_net_open": "PREFERENCE",
                        "c_sec_restricted": "SECURITY",
                    },
                    "round": 1,
                },
                "pipeline": {
                    **pipeline_early,
                    "NEGOTIATE": {"status": "warning", "detail": "Security vs preference"},
                },
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.NEGOTIATION_RESOLVED.value,
            message="Security policy wins; unsafe preference rejected.",
            stage=StageId.NEGOTIATE,
            status="success",
            delay_after=0.35,
            explain_simple=(
                "MEDHA rejected the lower-priority unsafe request and preserved the security policy."
            ),
            explain_technical=(
                "method=PRIORITY · winner=c_sec_restricted · loser=c_net_open · "
                "resolution=restricted · is_demo=true"
            ),
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": (
                    "MEDHA rejected the lower-priority unsafe request and preserved the "
                    "security policy."
                ),
                "technical": (
                    "method=PRIORITY · winner=c_sec_restricted · loser=c_net_open · "
                    "resolution=restricted · is_demo=true"
                ),
                "constraints": resolved,
                "negotiation": negotiation_resolved,
                "resolution": {
                    "method": "PRIORITY",
                    "winner_ids": ["c_sec_restricted"],
                    "loser_ids": ["c_net_open"],
                    "new_value": "restricted",
                    "old_value": "unrestricted",
                    "round": 1,
                },
                "pipeline": {
                    **pipeline_early,
                    "NEGOTIATE": {"status": "success", "detail": "Security wins"},
                },
                "agents": F.merge_agents(
                    {
                        "mediator": {
                            "status": "complete",
                            "activity": "Security policy accepted; unsafe preference rejected",
                            "lastEvent": "Conflict resolved",
                            "durationMs": 400,
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.NEGOTIATE,
            started=False,
            message="NEGOTIATE completed",
            simple="Negotiation completed with security policy enforced.",
            technical="stage=NEGOTIATE · method=PRIORITY · is_demo=true",
            pipeline={
                **pipeline_early,
                "NEGOTIATE": {"status": "success", "detail": "Security wins"},
            },
            delay=0.2,
        ),
        *_verify_execute_success(
            constraints=resolved,
            negotiation=negotiation_resolved,
            critic_score=96,
            result=F.success_result(
                message="Deployment completed with the hardened security choice.",
                verification_score=96,
                constraints_resolved=1,
                duration_label="~13s",
            ),
            constraints_resolved=1,
            pipeline_early=pipeline_early,
        ),
    ]
    return DemoScenarioDef(
        id=ScenarioId.SECURITY_CONFLICT,
        name="Security Conflict",
        description="SECURITY priority defeats PREFERENCE; safer policy kept.",
        expected_final_status=DeploymentStatus.COMPLETED,
        steps=steps,
    )


def build_verification_failure() -> DemoScenarioDef:
    constraints = [{**c} for c in F.CLEAN_CONSTRAINTS]
    negotiation = {
        "title": "CONSTRAINT NEGOTIATION",
        "conflictSummary": "No conflicting claims detected",
        "round": 1,
        "maxRounds": F.MAX_CNP_ROUNDS,
        "resolution": "Constraint set accepted",
        "method": "VALIDATE",
        "status": "resolved",
        "rounds_used": 1,
        "max_rounds": F.MAX_CNP_ROUNDS,
        "involvedConstraintIds": [c["id"] for c in constraints],
        "simpleExplanation": "Constraints agreed. Verification is the next gate.",
        "technicalNotes": ["conflicts=0", "is_demo=true"],
        "is_demo": True,
    }
    pipeline_early = {
        "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
        "ANALYZE": {"status": "success", "detail": "Stack inferred"},
        "PLAN": {"status": "success", "detail": "Task ready"},
        "AGENTS": {"status": "success", "detail": "Constraints published"},
        "NEGOTIATE": {"status": "success", "detail": "Constraints agreed"},
    }
    result = F.success_result(
        message=(
            "MEDHA found a configuration problem before execution and replanned within the "
            "allowed retry limit. Deployment completed successfully."
        ),
        verification_score=90,
        constraints_resolved=0,
        duration_label="~15s",
    )
    steps = [
        *_common_early(),
        *_agents_publish(constraints, "scenario=VERIFICATION_FAILURE"),
        DemoStep(
            event_type=EventType.NEGOTIATION_RESOLVED.value,
            message="Constraints agreed — no conflicts.",
            stage=StageId.NEGOTIATE,
            status="success",
            delay_after=0.25,
            explain_simple="Constraints agreed. Verification is next.",
            explain_technical="cnp.status=resolved · conflicts=0 · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "Constraints agreed. Verification is next.",
                "technical": "cnp.status=resolved · conflicts=0 · is_demo=true",
                "constraints": constraints,
                "negotiation": negotiation,
                "pipeline": pipeline_early,
                "agents": F.merge_agents(
                    {
                        "mediator": {
                            "status": "complete",
                            "activity": "Constraint set accepted",
                            "lastEvent": "CNP resolved",
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.VERIFY,
            started=True,
            message="VERIFY started",
            simple="MEDHA is checking the generated configuration before execution.",
            technical="agent=verifier · attempt=1 · is_demo=true",
            agents=F.merge_agents(
                {
                    "verifier": {
                        "status": "running",
                        "activity": "Evaluating required environment variables",
                        "lastEvent": "Verification started",
                    }
                }
            ),
            pipeline={**pipeline_early, "VERIFY": {"status": "running", "detail": "Hard checks"}},
            extra={
                "constraints": constraints,
                "negotiation": negotiation,
                "verification": {
                    "checks": [
                        {**c, "status": "pending", "message": "Running…"}
                        for c in F.VERIFICATION_CHECKS_FAIL_ENV
                    ],
                    "passed": None,
                    "summary": "Verification in progress",
                    "replan_count": 0,
                    "is_demo": True,
                },
            },
        ),
        DemoStep(
            event_type=EventType.VERIFICATION_FAILED.value,
            message="Verification FAILED: required environment variable missing.",
            stage=StageId.VERIFY,
            status="failed",
            level="error",
            delay_after=0.4,
            explain_simple=(
                "MEDHA found a configuration problem and is attempting one bounded replan."
            ),
            explain_technical=(
                "verification.passed=false · rule=required_env_var · missing=DATABASE_URL · "
                "replan_count=0 · max_replan=1 · is_demo=true"
            ),
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": (
                    "MEDHA found a configuration problem and is attempting one bounded replan."
                ),
                "technical": (
                    "verification.passed=false · rule=required_env_var · missing=DATABASE_URL · "
                    "replan_count=0 · max_replan=1 · is_demo=true"
                ),
                "verification": {
                    "checks": F.VERIFICATION_CHECKS_FAIL_ENV,
                    "passed": False,
                    "summary": "Verification failed. Required environment variable missing.",
                    "blocking_failures": ["Required environment variable DATABASE_URL missing"],
                    "replan_count": 0,
                    "is_demo": True,
                },
                "pipeline": {
                    **pipeline_early,
                    "VERIFY": {"status": "failed", "detail": "Missing DATABASE_URL"},
                },
                "agents": F.merge_agents(
                    {
                        "verifier": {
                            "status": "failed",
                            "activity": "Required env var DATABASE_URL missing",
                            "lastEvent": "Verification failed",
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.REPLAN_STARTED.value,
            message="REPLAN ROUND 1 — correcting configuration.",
            stage=StageId.VERIFY,
            status="running",
            delay_after=0.4,
            explain_simple=(
                "MEDHA found a configuration problem before execution and is replanning within "
                "the allowed retry limit."
            ),
            explain_technical=(
                "replan.round=1 · max_replan=1 · fix=inject_DATABASE_URL · is_demo=true"
            ),
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": (
                    "MEDHA found a configuration problem before execution and is replanning "
                    "within the allowed retry limit."
                ),
                "technical": (
                    "replan.round=1 · max_replan=1 · fix=inject_DATABASE_URL · is_demo=true"
                ),
                "replan": {
                    "round": 1,
                    "max_rounds": F.MAX_REPLAN_ROUNDS,
                    "reason": "missing_required_env",
                    "correction": "Add DATABASE_URL to DEMO configuration fixture",
                },
                "pipeline": {
                    **pipeline_early,
                    "VERIFY": {"status": "warning", "detail": "Replan round 1"},
                },
                "agents": F.merge_agents(
                    {
                        "verifier": {
                            "status": "running",
                            "activity": "Applying corrected DEMO configuration",
                            "lastEvent": "Replan started",
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.VERIFICATION_PASSED.value,
            message="Verification PASSED after replan.",
            stage=StageId.VERIFY,
            status="success",
            delay_after=0.35,
            explain_simple="Corrected configuration passed verification.",
            explain_technical=(
                "verification.passed=true · replan_count=1 · corrected=true · is_demo=true"
            ),
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "Corrected configuration passed verification.",
                "technical": (
                    "verification.passed=true · replan_count=1 · corrected=true · is_demo=true"
                ),
                "verification": {
                    "checks": F.VERIFICATION_CHECKS_PASS,
                    "passed": True,
                    "summary": "Verification passed after bounded replan.",
                    "replan_count": 1,
                    "corrected": True,
                    "is_demo": True,
                },
                "critic": {
                    "score": 90,
                    "breakdown": {
                        "security": 92,
                        "completeness": 88,
                        "constraints": 100,
                        "intentAlignment": 86,
                    },
                    "recommendation": "PASS",
                    "findings": ["Bounded replan corrected missing DATABASE_URL"],
                    "is_demo": True,
                },
                "pipeline": {
                    **pipeline_early,
                    "VERIFY": {"status": "success", "detail": "Passed after replan"},
                },
                "agents": F.merge_agents(
                    {
                        "verifier": {
                            "status": "complete",
                            "activity": "Verification passed after replan",
                            "lastEvent": "Verification passed",
                            "durationMs": 500,
                        },
                        "critic": {
                            "status": "complete",
                            "activity": "Score 90 — PASS",
                            "lastEvent": "Critic complete",
                        },
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.VERIFY,
            started=False,
            message="VERIFY completed",
            simple="Verification gate passed after replan.",
            technical="stage=VERIFY · status=success · replan_count=1 · is_demo=true",
            pipeline={
                **pipeline_early,
                "VERIFY": {"status": "success", "detail": "Passed after replan"},
            },
            delay=0.2,
        ),
    ]
    # Reuse execute+complete tail from the success helper (skip VERIFY* steps).
    execute_tail = _verify_execute_success(
        constraints=constraints,
        negotiation=negotiation,
        critic_score=90,
        result=result,
        constraints_resolved=0,
        pipeline_early=pipeline_early,
    )
    # Indices: 0 VERIFY started, 1 passed, 2 VERIFY completed, 3+ EXECUTE…
    execute_tail = execute_tail[3:]
    # Keep replan metadata on the terminal verification snapshot.
    terminal = execute_tail[-1]
    terminal.data["verification"] = {
        "checks": F.VERIFICATION_CHECKS_PASS,
        "passed": True,
        "summary": "Verification passed after bounded replan.",
        "replan_count": 1,
        "corrected": True,
        "is_demo": True,
    }
    steps.extend(execute_tail)
    return DemoScenarioDef(
        id=ScenarioId.VERIFICATION_FAILURE,
        name="Verification Failure",
        description="Hard gate fails once, bounded replan, then success.",
        expected_final_status=DeploymentStatus.COMPLETED,
        steps=steps,
    )


def build_partial_failure() -> DemoScenarioDef:
    constraints = [{**c} for c in F.CLEAN_CONSTRAINTS]
    negotiation = {
        "title": "CONSTRAINT NEGOTIATION",
        "conflictSummary": "No conflicting claims detected",
        "round": 1,
        "maxRounds": F.MAX_CNP_ROUNDS,
        "resolution": "Constraint set accepted",
        "method": "VALIDATE",
        "status": "resolved",
        "rounds_used": 1,
        "max_rounds": F.MAX_CNP_ROUNDS,
        "involvedConstraintIds": [c["id"] for c in constraints],
        "simpleExplanation": "Constraints agreed. Execution records the causal graph.",
        "technicalNotes": ["conflicts=0", "is_demo=true"],
        "is_demo": True,
    }
    pipeline_early = {
        "PREFLIGHT": {"status": "success", "detail": "Host ready (DEMO)"},
        "ANALYZE": {"status": "success", "detail": "Stack inferred"},
        "PLAN": {"status": "success", "detail": "Task ready"},
        "AGENTS": {"status": "success", "detail": "Constraints published"},
        "NEGOTIATE": {"status": "success", "detail": "No conflicts"},
        "VERIFY": {"status": "success", "detail": "Gate passed"},
    }
    rollback = F.rollback_scope_partial()
    result = F.partial_result()
    steps = [
        *_common_early(),
        *_agents_publish(constraints, "scenario=PARTIAL_FAILURE"),
        DemoStep(
            event_type=EventType.NEGOTIATION_RESOLVED.value,
            message="Constraints agreed — no conflicts.",
            stage=StageId.NEGOTIATE,
            status="success",
            delay_after=0.25,
            explain_simple="No conflicts. Proceeding to verification.",
            explain_technical="cnp.status=resolved · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "No conflicts. Proceeding to verification.",
                "technical": "cnp.status=resolved · is_demo=true",
                "constraints": constraints,
                "negotiation": negotiation,
                "pipeline": {
                    **{k: pipeline_early[k] for k in ("PREFLIGHT", "ANALYZE", "PLAN", "AGENTS")},
                    "NEGOTIATE": {"status": "success", "detail": "No conflicts"},
                },
                "agents": F.merge_agents(
                    {
                        "mediator": {
                            "status": "complete",
                            "activity": "No conflicts",
                            "lastEvent": "CNP resolved",
                        }
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.VERIFICATION_PASSED.value,
            message="Verification passed.",
            stage=StageId.VERIFY,
            status="success",
            delay_after=0.3,
            explain_simple="MEDHA is checking the generated configuration before execution.",
            explain_technical="verification.passed=true · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "Configuration checks passed. Execution is allowed.",
                "technical": "verification.passed=true · is_demo=true",
                "verification": {
                    "checks": F.VERIFICATION_CHECKS_PASS,
                    "passed": True,
                    "summary": "Verification passed.",
                    "is_demo": True,
                },
                "critic": {
                    "score": 93,
                    "breakdown": {
                        "security": 95,
                        "completeness": 92,
                        "constraints": 100,
                        "intentAlignment": 89,
                    },
                    "recommendation": "PASS",
                    "findings": ["Plan approved for DEMO execution"],
                    "is_demo": True,
                },
                "pipeline": pipeline_early,
                "agents": F.merge_agents(
                    {
                        "verifier": {
                            "status": "complete",
                            "activity": "Gate passed",
                            "lastEvent": "Verification passed",
                        },
                        "critic": {
                            "status": "complete",
                            "activity": "Score 93 — PASS",
                            "lastEvent": "Critic complete",
                        },
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.EXECUTE,
            started=True,
            message="EXECUTE started",
            simple="MEDHA is starting services and recording causal dependencies.",
            technical="agent=executor · mode=DEMO/MOCK · ceg.write=true",
            agents=F.merge_agents(
                {
                    "executor": {
                        "status": "running",
                        "activity": "Starting network/database/analytics (MOCK)",
                        "lastEvent": "Execution started",
                    }
                }
            ),
            pipeline={
                **pipeline_early,
                "EXECUTE": {"status": "running", "detail": "Starting services"},
            },
            extra={
                "graph": F.graph_execution_progress(network="running"),
                "constraints": constraints,
                "negotiation": negotiation,
            },
        ),
        DemoStep(
            event_type=EventType.EXECUTION_SERVICE_STATUS.value,
            message="Network, database, and analytics succeeded.",
            stage=StageId.EXECUTE,
            status="running",
            delay_after=0.35,
            explain_simple="Independent and upstream services started successfully.",
            explain_technical="services=[network,database,analytics]=success · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "Independent and upstream services started successfully.",
                "technical": "services=[network,database,analytics]=success · is_demo=true",
                "graph": F.graph_execution_progress(
                    network="success",
                    database="success",
                    analytics="success",
                    backend="running",
                    frontend="pending",
                ),
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.EXECUTION_FAILED.value,
            message="Backend failed during DEMO execution.",
            stage=StageId.EXECUTE,
            status="failed",
            level="error",
            delay_after=0.4,
            explain_simple=(
                "Backend failed. MEDHA is tracing the dependency graph to determine which "
                "services are affected."
            ),
            explain_technical=(
                "failed_node=n_backend · service=backend · dependents=[n_frontend] · is_demo=true"
            ),
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": (
                    "Backend failed. MEDHA is tracing the dependency graph to determine which "
                    "services are affected."
                ),
                "technical": (
                    "failed_node=n_backend · service=backend · dependents=[n_frontend] · is_demo=true"
                ),
                "graph": F.graph_execution_progress(
                    network="success",
                    database="success",
                    analytics="success",
                    backend="failed",
                    frontend="running",
                ),
                "selected_node_id": "n_backend",
                "pipeline": {
                    **pipeline_early,
                    "EXECUTE": {"status": "failed", "detail": "Backend health failed"},
                    "RECOVER": {"status": "running", "detail": "Tracing causal graph"},
                },
                "agents": F.merge_agents(
                    {
                        "executor": {
                            "status": "failed",
                            "activity": "Backend health check failed (MOCK)",
                            "lastEvent": "Node n_backend failed",
                        },
                        "rollback": {
                            "status": "running",
                            "activity": "Computing dependency-aware rollback scope",
                            "lastEvent": "CEG traversal started",
                        },
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.RECOVER,
            started=True,
            message="RECOVER started",
            simple="MEDHA is rolling back only the affected dependency branch.",
            technical=(
                "rollback.failed_node=n_backend · scope=[n_frontend] · "
                "preserved=[n_network,n_database,n_analytics] · is_demo=true"
            ),
            agents=F.merge_agents(
                {
                    "rollback": {
                        "status": "running",
                        "activity": "Rolling back frontend only",
                        "lastEvent": "Scoped rollback started",
                    }
                }
            ),
            pipeline={
                **pipeline_early,
                "EXECUTE": {"status": "failed", "detail": "Backend health failed"},
                "RECOVER": {"status": "running", "detail": "Scoped rollback"},
            },
            extra={"selected_node_id": "n_backend"},
            delay=0.35,
        ),
        DemoStep(
            event_type=EventType.ROLLBACK_STARTED.value,
            message="Scoped rollback started.",
            stage=StageId.RECOVER,
            status="running",
            delay_after=0.3,
            explain_simple="MEDHA is rolling back only the affected dependency branch.",
            explain_technical="rollback.scope=[n_frontend] · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "MEDHA is rolling back only the affected dependency branch.",
                "technical": "rollback.scope=[n_frontend] · is_demo=true",
                "rollback": rollback,
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.ROLLBACK_NODE.value,
            message="Frontend rolled back.",
            stage=StageId.RECOVER,
            status="running",
            delay_after=0.3,
            explain_simple="Frontend depended on Backend and was rolled back.",
            explain_technical="rollback.node=n_frontend · status=rolled_back · is_demo=true",
            deployment_status=DeploymentStatus.RUNNING,
            data={
                "simple": "Frontend depended on Backend and was rolled back.",
                "technical": "rollback.node=n_frontend · status=rolled_back · is_demo=true",
                "graph": F.graph_partial_final(),
                "selected_node_id": "n_backend",
                "label": "DEMO/MOCK",
            },
        ),
        DemoStep(
            event_type=EventType.ROLLBACK_COMPLETED.value,
            message="SCOPED ROLLBACK COMPLETE",
            stage=StageId.RECOVER,
            status="success",
            delay_after=0.3,
            explain_simple=(
                "Backend failed. MEDHA traced the dependency graph and rolled back only the "
                "affected Frontend branch. Independent services were preserved."
            ),
            explain_technical=(
                "failed_node=backend · dependent=frontend · "
                "preserved=[network,database,analytics] · rollback_scope=[frontend] · is_demo=true"
            ),
            deployment_status=DeploymentStatus.PARTIAL_RECOVERY,
            data={
                "simple": (
                    "Backend failed. MEDHA traced the dependency graph and rolled back only the "
                    "affected Frontend branch. Independent services were preserved."
                ),
                "technical": (
                    "failed_node=backend · dependent=frontend · "
                    "preserved=[network,database,analytics] · rollback_scope=[frontend] · is_demo=true"
                ),
                "graph": F.graph_partial_final(),
                "rollback": rollback,
                "selected_node_id": "n_backend",
                "pipeline": {
                    **pipeline_early,
                    "EXECUTE": {"status": "failed", "detail": "Backend health failed"},
                    "RECOVER": {"status": "success", "detail": "Scoped rollback complete"},
                },
                "agents": F.merge_agents(
                    {
                        "executor": {
                            "status": "failed",
                            "activity": "Backend failed during MOCK execution",
                            "lastEvent": "Node n_backend failed",
                        },
                        "rollback": {
                            "status": "complete",
                            "activity": "Rolled back frontend; preserved analytics",
                            "lastEvent": "Scoped rollback complete",
                            "durationMs": 600,
                        },
                    }
                ),
                "label": "DEMO/MOCK",
            },
        ),
        _stage(
            StageId.RECOVER,
            started=False,
            message="RECOVER completed",
            simple="Scoped rollback finished.",
            technical="stage=RECOVER · status=success · is_demo=true",
            pipeline={
                **pipeline_early,
                "EXECUTE": {"status": "failed", "detail": "Backend health failed"},
                "RECOVER": {"status": "success", "detail": "Scoped rollback complete"},
            },
            delay=0.2,
        ),
        DemoStep(
            event_type=EventType.DEPLOYMENT_COMPLETED.value,
            message="DEMO deployment finished with partial failure and scoped recovery.",
            stage=StageId.COMPLETE,
            status=DeploymentStatus.PARTIAL_RECOVERY.value,
            delay_after=0.0,
            explain_simple=(
                "Scoped rollback finished. Analytics stayed up because it did not depend on "
                "the failed backend."
            ),
            explain_technical=(
                "final_status=partial_recovery · failed=[backend] · rolled_back=[frontend] · "
                "preserved=[network,database,analytics] · is_demo=true · label=DEMO/MOCK"
            ),
            deployment_status=DeploymentStatus.PARTIAL_RECOVERY,
            data={
                "simple": (
                    "Scoped rollback finished. Analytics stayed up because it did not depend "
                    "on the failed backend."
                ),
                "technical": (
                    "final_status=partial_recovery · failed=[backend] · rolled_back=[frontend] · "
                    "preserved=[network,database,analytics] · is_demo=true · label=DEMO/MOCK"
                ),
                "result": result,
                "constraints": constraints,
                "negotiation": negotiation,
                "verification": {
                    "checks": F.VERIFICATION_CHECKS_PASS,
                    "passed": True,
                    "summary": "Verification passed.",
                    "is_demo": True,
                },
                "graph": F.graph_partial_final(),
                "rollback": rollback,
                "selected_node_id": "n_backend",
                "pipeline": {
                    **pipeline_early,
                    "EXECUTE": {"status": "failed", "detail": "Backend health failed"},
                    "RECOVER": {"status": "success", "detail": "Scoped rollback complete"},
                    "COMPLETE": {"status": "warning", "detail": "Partial recovery"},
                },
                "label": "DEMO/MOCK",
            },
        ),
    ]
    return DemoScenarioDef(
        id=ScenarioId.PARTIAL_FAILURE,
        name="Partial Failure",
        description="Backend fails; frontend rolled back; independent services preserved.",
        expected_final_status=DeploymentStatus.PARTIAL_RECOVERY,
        steps=steps,
    )


SCENARIO_BUILDERS = {
    ScenarioId.SUCCESSFUL_DEPLOYMENT: build_successful_deployment,
    ScenarioId.PORT_CONFLICT: build_port_conflict,
    ScenarioId.SECURITY_CONFLICT: build_security_conflict,
    ScenarioId.VERIFICATION_FAILURE: build_verification_failure,
    ScenarioId.PARTIAL_FAILURE: build_partial_failure,
}


def get_scenario(scenario_id: ScenarioId) -> DemoScenarioDef:
    builder = SCENARIO_BUILDERS.get(scenario_id)
    if builder is None:
        raise KeyError(f"Unknown scenario: {scenario_id}")
    return builder()


def list_scenarios() -> list[dict]:
    return [
        {
            "id": sid.value,
            "name": builder().name,
            "description": builder().description,
            "expected_final_status": builder().expected_final_status.value,
        }
        for sid, builder in SCENARIO_BUILDERS.items()
    ]
