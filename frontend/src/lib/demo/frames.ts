import {
  BASE_CONSTRAINTS_CLEAN,
  emptyCritic,
  emptyGraph,
  emptyVerification,
  initialAgents,
  initialPipeline,
  setAgents,
  setStages,
  successGraph,
} from "./scenarios";
import type {
  ConstraintView,
  DemoFrame,
  DeploymentSnapshot,
  ScenarioId,
} from "./types";

function baseExplain(
  stage: DeploymentSnapshot["explain"]["currentStage"],
  simple: string,
  technical: string,
  statusLabel: string,
  round: number | null = null,
) {
  return {
    explain: {
      currentStage: stage,
      round,
      statusLabel,
      simpleText: simple,
      technicalText: technical,
    },
  };
}

function t(
  id: string,
  time: string,
  tone: DeploymentSnapshot["trace"][number]["tone"],
  message: string,
  technical?: string,
) {
  return { id, time, tone, message, technical };
}

const PORT_CONFLICT_CONSTRAINTS: ConstraintView[] = [
  {
    id: "c_port_docker",
    type: "PORT_CLAIM",
    priority: "RESOURCE",
    sourceAgent: "Docker Agent",
    service: "backend",
    summary: "Docker Agent requested 8080",
    detail: "Exclusive host port 8080 for backend",
    status: "conflict",
    technical: { payload: { port: 8080, protocol: "tcp", exclusive: true } },
  },
  {
    id: "c_port_nginx",
    type: "PORT_CLAIM",
    priority: "DEPENDENCY",
    sourceAgent: "Nginx Agent",
    service: "nginx",
    summary: "Nginx Agent requested 8080",
    detail: "Edge listener also claimed 8080",
    status: "conflict",
    technical: { payload: { port: 8080, protocol: "tcp", exclusive: true } },
  },
  {
    id: "c_sec_no_priv",
    type: "SECURITY_POLICY",
    priority: "SECURITY",
    sourceAgent: "Security Agent",
    summary: "Disallow privileged containers",
    detail: "privileged=false",
    status: "accepted",
    technical: {
      payload: { rule: "no_privileged", enforcement: "block", severity: "high" },
    },
  },
];

const PORT_RESOLVED: ConstraintView[] = [
  {
    ...PORT_CONFLICT_CONSTRAINTS[0],
    status: "accepted",
  },
  {
    ...PORT_CONFLICT_CONSTRAINTS[1],
    status: "superseded",
    summary: "Nginx remapped to 8081",
    detail: "Alternative port selected after conflict",
    technical: { payload: { port: 8081, protocol: "tcp", exclusive: true } },
  },
  PORT_CONFLICT_CONSTRAINTS[2],
];

const SECURITY_CONFLICT_CONSTRAINTS: ConstraintView[] = [
  {
    id: "c_pref_priv",
    type: "SECURITY_POLICY",
    priority: "PREFERENCE",
    sourceAgent: "Docker Agent",
    service: "backend",
    summary: "Docker preferred privileged mode",
    detail: "privileged=true requested for convenience",
    status: "conflict",
    technical: {
      payload: { rule: "privileged", enforcement: "prefer", severity: "low" },
    },
  },
  {
    id: "c_sec_block_priv",
    type: "SECURITY_POLICY",
    priority: "SECURITY",
    sourceAgent: "Security Agent",
    summary: "Security forbids privileged containers",
    detail: "privileged=false is mandatory",
    status: "conflict",
    technical: {
      payload: { rule: "no_privileged", enforcement: "block", severity: "high" },
    },
  },
];

function earlyFrames(scenario: ScenarioId): DemoFrame[] {
  const pipeline = initialPipeline();
  const agents = initialAgents();

  return [
    {
      delayMs: 700,
      patch: {
        runStatus: "running",
        deploymentId: `dep_demo_${scenario.toLowerCase()}`,
        scenario,
        pipeline: setStages(pipeline, {
          PREFLIGHT: {
            status: "running",
            detail: "Checking host prerequisites",
          },
        }),
        agents: setAgents(agents, {
          preflight: {
            status: "running",
            activity: "Checking Docker socket, disk, and local ports",
            lastEvent: "Preflight started",
          },
        }),
        ...baseExplain(
          "PREFLIGHT",
          "MEDHA is checking whether the host has the prerequisites required for deployment.",
          "agent=preflight · checks=[docker_socket, disk_space, local_target]",
          "Running",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", `scenario=${scenario}`),
          t("e2", "08:41:02", "info", "Preflight started"),
        ],
      },
    },
    {
      delayMs: 800,
      patch: {
        pipeline: setStages(pipeline, {
          PREFLIGHT: {
            status: "success",
            detail: "Host ready",
            durationMs: 820,
          },
          ANALYZE: {
            status: "running",
            detail: "Reading manifests",
          },
        }),
        agents: setAgents(agents, {
          preflight: {
            status: "complete",
            activity: "Local host prerequisites confirmed",
            lastEvent: "Preflight completed",
            durationMs: 820,
          },
          analyzer: {
            status: "running",
            activity: "Inspecting Dockerfile and compose manifests",
            lastEvent: "Analysis started",
          },
        }),
        ...baseExplain(
          "ANALYZE",
          "MEDHA is analyzing repository manifests to infer the application stack.",
          "agent=analyzer · manifests=[Dockerfile, docker-compose.yml, package.json]",
          "Running",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", `scenario=${scenario}`),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:03", "info", "Repository analysis started"),
        ],
      },
    },
    {
      delayMs: 800,
      patch: {
        pipeline: setStages(pipeline, {
          PREFLIGHT: {
            status: "success",
            detail: "Host ready",
            durationMs: 820,
          },
          ANALYZE: {
            status: "success",
            detail: "Stack inferred",
            durationMs: 640,
          },
          PLAN: {
            status: "running",
            detail: "Building task specification",
          },
        }),
        agents: setAgents(agents, {
          preflight: {
            status: "complete",
            activity: "Local host prerequisites confirmed",
            lastEvent: "Preflight completed",
            durationMs: 820,
          },
          analyzer: {
            status: "complete",
            activity: "Inferred node + postgres + nginx stack",
            lastEvent: "Repository analyzed",
            durationMs: 640,
          },
        }),
        ...baseExplain(
          "PLAN",
          "MEDHA is turning the inferred stack into a concrete deployment task.",
          "stage=PLAN · task_spec=draft · services=[network,database,backend,frontend,analytics]",
          "Running",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", `scenario=${scenario}`),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e4", "08:41:05", "info", "Task specification drafted"),
        ],
      },
    },
  ];
}

function agentPublishFrames(
  scenario: ScenarioId,
  constraints: ConstraintView[],
): DemoFrame[] {
  const pipeline = initialPipeline();
  const agents = initialAgents();
  const doneEarly = {
    PREFLIGHT: {
      status: "success" as const,
      detail: "Host ready",
      durationMs: 820,
    },
    ANALYZE: {
      status: "success" as const,
      detail: "Stack inferred",
      durationMs: 640,
    },
    PLAN: {
      status: "success" as const,
      detail: "Task ready",
      durationMs: 410,
    },
  };

  return [
    {
      delayMs: 900,
      patch: {
        pipeline: setStages(pipeline, {
          ...doneEarly,
          AGENTS: {
            status: "running",
            detail: "Specialists publishing constraints",
          },
        }),
        agents: setAgents(agents, {
          preflight: {
            status: "complete",
            activity: "Local host prerequisites confirmed",
            lastEvent: "Preflight completed",
            durationMs: 820,
          },
          analyzer: {
            status: "complete",
            activity: "Inferred node + postgres + nginx stack",
            lastEvent: "Repository analyzed",
            durationMs: 640,
          },
          docker: {
            status: "running",
            activity: "Generating container configuration",
            lastEvent: "Docker Agent active",
          },
          nginx: {
            status: "running",
            activity: "Generating reverse-proxy configuration",
            lastEvent: "Nginx Agent active",
          },
          security: {
            status: "running",
            activity: "Publishing security policies",
            lastEvent: "Security Agent active",
          },
        }),
        constraints: constraints.map((c) => ({ ...c, status: "proposed" as const })),
        ...baseExplain(
          "AGENTS",
          "Specialist agents are generating configuration and publishing typed infrastructure constraints.",
          "agents=[docker,nginx,security] · constraint_bus=in_process · is_demo=true",
          "Running",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", `scenario=${scenario}`),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e5", "08:41:06", "info", "Docker Agent published constraints"),
          t("e6", "08:41:06", "info", "Nginx Agent published constraints"),
          t("e7", "08:41:06", "info", "Security Agent published constraints"),
        ],
      },
    },
    {
      delayMs: 700,
      patch: {
        pipeline: setStages(pipeline, {
          ...doneEarly,
          AGENTS: {
            status: "success",
            detail: "Constraints published",
            durationMs: 900,
          },
          NEGOTIATE: {
            status: "running",
            detail: "Collecting constraint set",
          },
        }),
        agents: setAgents(agents, {
          preflight: {
            status: "complete",
            activity: "Local host prerequisites confirmed",
            lastEvent: "Preflight completed",
            durationMs: 820,
          },
          analyzer: {
            status: "complete",
            activity: "Inferred node + postgres + nginx stack",
            lastEvent: "Repository analyzed",
            durationMs: 640,
          },
          docker: {
            status: "complete",
            activity: "Generated deployment configuration and published constraints",
            lastEvent: "Constraints published",
            durationMs: 520,
          },
          nginx: {
            status: "complete",
            activity: "Generated proxy configuration and published constraints",
            lastEvent: "Constraints published",
            durationMs: 480,
          },
          security: {
            status: "complete",
            activity: "Published mandatory security policies",
            lastEvent: "Policies published",
            durationMs: 410,
          },
          mediator: {
            status: "running",
            activity: "Collecting and grouping constraints",
            lastEvent: "CNP collect",
          },
        }),
        constraints,
        negotiation: {
          title: "CONSTRAINT NEGOTIATION",
          conflictSummary: "Collecting typed constraints from specialist agents",
          round: 1,
          maxRounds: 3,
          status: "detecting",
          involvedConstraintIds: constraints.map((c) => c.id),
          simpleExplanation:
            "MEDHA is collecting typed constraints before any Docker action runs.",
          technicalNotes: ["phase=COLLECT", "max_rounds=3"],
        },
        ...baseExplain(
          "NEGOTIATE",
          "MEDHA is collecting typed constraints from specialist agents before execution.",
          "cnp.phase=COLLECT · round=1/3",
          "Negotiating",
          1,
        ),
      },
    },
  ];
}

function buildSuccessPath(scenario: ScenarioId): DemoFrame[] {
  const pipeline = initialPipeline();
  const agents = initialAgents();
  const earlyDone = {
    PREFLIGHT: { status: "success" as const, detail: "Host ready", durationMs: 820 },
    ANALYZE: { status: "success" as const, detail: "Stack inferred", durationMs: 640 },
    PLAN: { status: "success" as const, detail: "Task ready", durationMs: 410 },
    AGENTS: {
      status: "success" as const,
      detail: "Constraints published",
      durationMs: 900,
    },
    NEGOTIATE: {
      status: "success" as const,
      detail: "No conflicts",
      durationMs: 500,
    },
  };

  return [
    ...earlyFrames(scenario),
    ...agentPublishFrames(scenario, BASE_CONSTRAINTS_CLEAN),
    {
      delayMs: 800,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
        }),
        agents: setAgents(agents, {
          mediator: {
            status: "complete",
            activity: "Constraint set validated — no conflicts",
            lastEvent: "CNP resolved",
            durationMs: 500,
          },
          verifier: {
            status: "running",
            activity: "Running hard verification checks",
            lastEvent: "Verification started",
          },
        }),
        constraints: BASE_CONSTRAINTS_CLEAN,
        negotiation: {
          title: "CONSTRAINT NEGOTIATION",
          conflictSummary: "No conflicting claims detected",
          round: 1,
          maxRounds: 3,
          resolution: "Constraint set accepted as proposed",
          method: "VALIDATE",
          status: "resolved",
          involvedConstraintIds: BASE_CONSTRAINTS_CLEAN.map((c) => c.id),
          simpleExplanation:
            "All specialist constraints were compatible, so MEDHA skipped conflict mediation.",
          technicalNotes: ["conflicts=0", "rounds_used=1", "method=VALIDATE"],
        },
        verification: {
          checks: emptyVerification().checks.map((c) => ({
            ...c,
            status: "pending" as const,
            message: "Running…",
          })),
          passed: null,
          summary: "Verification in progress",
        },
        ...baseExplain(
          "VERIFY",
          "MEDHA is verifying the generated configuration before Docker execution.",
          "agent=verifier · gate=pre_exec",
          "Verifying",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", `scenario=${scenario}`),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e8", "08:41:07", "success", "Constraint set accepted — no conflicts"),
          t("e9", "08:41:08", "info", "Verification started"),
        ],
      },
    },
    {
      delayMs: 900,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          VERIFY: {
            status: "success",
            detail: "Gate passed",
            durationMs: 760,
          },
          EXECUTE: {
            status: "running",
            detail: "Writing CEG nodes",
          },
        }),
        agents: setAgents(agents, {
          mediator: {
            status: "complete",
            activity: "Constraint set validated — no conflicts",
            lastEvent: "CNP resolved",
            durationMs: 500,
          },
          verifier: {
            status: "complete",
            activity: "All hard checks passed",
            lastEvent: "Verification passed",
            durationMs: 760,
          },
          critic: {
            status: "complete",
            activity: "Quality score 94 — recommendation PASS",
            lastEvent: "Critic complete",
            durationMs: 420,
          },
          executor: {
            status: "running",
            activity: "Applying agreed plan on local Docker host (MOCK)",
            lastEvent: "Execution started",
          },
        }),
        verification: {
          checks: [
            { id: "schema", name: "Schema", status: "pass", message: "Configs match schema" },
            { id: "yaml", name: "YAML", status: "pass", message: "YAML parses cleanly" },
            { id: "compose", name: "Compose", status: "pass", message: "Compose graph valid" },
            { id: "security", name: "Security", status: "pass", message: "Security floor intact" },
            {
              id: "constraints",
              name: "Constraints",
              status: "pass",
              message: "Agreed set consistent",
            },
            { id: "health", name: "Health", status: "pass", message: "Health expectations defined" },
          ],
          passed: true,
          summary: "Verification passed. Execution is allowed.",
        },
        critic: {
          score: 94,
          breakdown: {
            security: 96,
            completeness: 93,
            constraints: 100,
            intentAlignment: 90,
          },
          recommendation: "PASS",
          findings: [
            "Security floor preserved after negotiation",
            "Exec order forms a valid DAG",
            "Intent asks for secure deploy — privileged mode remains disabled",
          ],
        },
        graph: {
          nodes: successGraph("all_ok").nodes.map((n) =>
            n.id === "n_network"
              ? { ...n, status: "running" as const }
              : { ...n, status: "pending" as const },
          ),
          edges: successGraph("all_ok").edges,
        },
        ...baseExplain(
          "EXECUTE",
          "MEDHA is executing the agreed plan and recording each action in the causal execution graph.",
          "agent=executor · ceg.write=true · mode=DEMO/MOCK",
          "Executing",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", `scenario=${scenario}`),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e8", "08:41:07", "success", "Constraint set accepted — no conflicts"),
          t("e9", "08:41:08", "success", "Verification passed"),
          t("e10", "08:41:09", "info", "Executor started (DEMO/MOCK)"),
        ],
      },
    },
    {
      delayMs: 1000,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          VERIFY: { status: "success", detail: "Gate passed", durationMs: 760 },
          EXECUTE: { status: "success", detail: "Services running", durationMs: 1800 },
          RECOVER: { status: "skipped", detail: "Not required" },
          COMPLETE: { status: "success", detail: "Deployment finished", durationMs: 120 },
        }),
        agents: setAgents(agents, {
          executor: {
            status: "complete",
            activity: "All CEG nodes succeeded (MOCK)",
            lastEvent: "Execution complete",
            durationMs: 1800,
          },
          rollback: {
            status: "skipped",
            activity: "No failure scope",
            lastEvent: "Rollback not needed",
          },
        }),
        graph: successGraph("all_ok"),
        result: {
          kind: "success",
          title: "SUCCESS",
          message: "Deployment completed successfully.",
          durationLabel: "12.4s",
          servicesLabel: "5 / 5 healthy",
          verificationScore: 94,
          constraintsResolved: 4,
          rollbackScope: null,
        },
        runStatus: "succeeded",
        ...baseExplain(
          "COMPLETE",
          "Deployment finished successfully. Every service in the causal graph reports success.",
          "final_status=succeeded · is_demo=true · rollback=null",
          "Complete",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", `scenario=${scenario}`),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e8", "08:41:07", "success", "Constraint set accepted — no conflicts"),
          t("e9", "08:41:08", "success", "Verification passed"),
          t("e10", "08:41:09", "info", "Executor started (DEMO/MOCK)"),
          t("e11", "08:41:12", "success", "NETWORK node succeeded"),
          t("e12", "08:41:18", "success", "All services healthy"),
          t("e13", "08:41:19", "success", "DEMO deployment succeeded"),
        ],
      },
    },
  ];
}

function buildPortConflict(): DemoFrame[] {
  const pipeline = initialPipeline();
  const agents = initialAgents();
  const earlyDone = {
    PREFLIGHT: { status: "success" as const, detail: "Host ready", durationMs: 820 },
    ANALYZE: { status: "success" as const, detail: "Stack inferred", durationMs: 640 },
    PLAN: { status: "success" as const, detail: "Task ready", durationMs: 410 },
    AGENTS: {
      status: "success" as const,
      detail: "Constraints published",
      durationMs: 900,
    },
  };

  return [
    ...earlyFrames("PORT_CONFLICT"),
    ...agentPublishFrames("PORT_CONFLICT", PORT_CONFLICT_CONSTRAINTS),
    {
      delayMs: 900,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          NEGOTIATE: {
            status: "warning",
            detail: "Conflict detected",
          },
        }),
        constraints: PORT_CONFLICT_CONSTRAINTS,
        negotiation: {
          title: "CONSTRAINT NEGOTIATION",
          conflictSummary: "Docker and Nginx both claimed host port 8080",
          round: 1,
          maxRounds: 3,
          status: "resolving",
          involvedConstraintIds: ["c_port_docker", "c_port_nginx"],
          simpleExplanation:
            "MEDHA detected that two specialist agents requested the same port. It is comparing their constraints before execution.",
          technicalNotes: [
            "conflict_id=cf_port_8080",
            "type=PORT_CLAIM",
            "priorities=RESOURCE vs DEPENDENCY",
          ],
        },
        agents: setAgents(agents, {
          mediator: {
            status: "running",
            activity: "Detecting and resolving port conflict",
            lastEvent: "Conflict detected",
          },
        }),
        ...baseExplain(
          "NEGOTIATE",
          "MEDHA detected that two specialist agents requested the same port. It is comparing their constraints before execution.",
          "cnp.phase=DETECT_CONFLICT · ids=[c_port_docker,c_port_nginx] · round=1/3",
          "Conflict",
          1,
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", "scenario=PORT_CONFLICT"),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t(
            "e5",
            "08:41:06",
            "success",
            "Docker Agent published PORT CLAIM",
            "constraint_id=c_port_docker · port=8080 · priority=RESOURCE",
          ),
          t(
            "e6",
            "08:41:06",
            "success",
            "Nginx Agent published PORT CLAIM",
            "constraint_id=c_port_nginx · port=8080 · priority=DEPENDENCY",
          ),
          t("e7", "08:41:06", "warning", "Conflict detected", "conflict_id=cf_port_8080"),
          t("e8", "08:41:07", "info", "Priority resolution started"),
        ],
      },
    },
    {
      delayMs: 1000,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          NEGOTIATE: {
            status: "success",
            detail: "Port remapped",
            durationMs: 1400,
          },
          VERIFY: { status: "running", detail: "Checking agreed set" },
        }),
        constraints: PORT_RESOLVED,
        negotiation: {
          title: "CONSTRAINT NEGOTIATION",
          conflictSummary: "Port 8080 claimed by Docker and Nginx",
          round: 1,
          maxRounds: 3,
          resolution: "Nginx → 8081",
          method: "PRIORITY + ALTERNATIVE",
          status: "resolved",
          involvedConstraintIds: ["c_port_docker", "c_port_nginx"],
          simpleExplanation:
            "MEDHA found an alternative port that satisfies the deployment requirements.",
          technicalNotes: [
            "winner=c_port_docker (RESOURCE)",
            "loser=c_port_nginx (DEPENDENCY)",
            "alternative.port=8081",
            "rounds_used=1",
          ],
        },
        agents: setAgents(agents, {
          mediator: {
            status: "complete",
            activity: "Resolved port conflict via priority + alternative",
            lastEvent: "Conflict resolved",
            durationMs: 1400,
          },
          verifier: {
            status: "running",
            activity: "Verifying remapped constraint set",
            lastEvent: "Verification started",
          },
        }),
        ...baseExplain(
          "VERIFY",
          "MEDHA found an alternative port that satisfies the deployment requirements. It is verifying the updated plan.",
          "resolution=PRIORITY+ALTERNATIVE · nginx.port=8081 · round=1/3",
          "Verifying",
          1,
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", "scenario=PORT_CONFLICT"),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e5", "08:41:06", "success", "Docker Agent published PORT CLAIM"),
          t("e6", "08:41:06", "success", "Nginx Agent published PORT CLAIM"),
          t("e7", "08:41:06", "warning", "Conflict detected"),
          t("e8", "08:41:07", "info", "Priority resolution started"),
          t(
            "e9",
            "08:41:07",
            "success",
            "Conflict resolved",
            "method=PRIORITY+ALTERNATIVE · nginx→8081",
          ),
          t("e10", "08:41:08", "info", "Verification started"),
        ],
      },
    },
    {
      delayMs: 1100,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          NEGOTIATE: {
            status: "success",
            detail: "Port remapped",
            durationMs: 1400,
          },
          VERIFY: { status: "success", detail: "Gate passed", durationMs: 700 },
          EXECUTE: { status: "success", detail: "Services running", durationMs: 1600 },
          RECOVER: { status: "skipped", detail: "Not required" },
          COMPLETE: { status: "success", detail: "Deployment finished" },
        }),
        constraints: PORT_RESOLVED,
        verification: {
          checks: [
            { id: "schema", name: "Schema", status: "pass", message: "OK" },
            { id: "yaml", name: "YAML", status: "pass", message: "OK" },
            { id: "compose", name: "Compose", status: "pass", message: "OK" },
            { id: "security", name: "Security", status: "pass", message: "OK" },
            {
              id: "constraints",
              name: "Constraints",
              status: "pass",
              message: "Port remap consistent",
            },
            { id: "health", name: "Health", status: "pass", message: "OK" },
          ],
          passed: true,
          summary: "Verification passed after CNP remap.",
        },
        critic: {
          score: 91,
          breakdown: {
            security: 95,
            completeness: 90,
            constraints: 98,
            intentAlignment: 88,
          },
          recommendation: "PASS",
          findings: ["Port conflict resolved without LLM mediation"],
        },
        graph: successGraph("all_ok"),
        agents: setAgents(agents, {
          mediator: {
            status: "complete",
            activity: "Resolved port conflict via priority + alternative",
            lastEvent: "Conflict resolved",
            durationMs: 1400,
          },
          verifier: {
            status: "complete",
            activity: "All hard checks passed",
            lastEvent: "Verification passed",
            durationMs: 700,
          },
          critic: {
            status: "complete",
            activity: "Score 91 — PASS",
            lastEvent: "Critic complete",
          },
          executor: {
            status: "complete",
            activity: "MOCK execution succeeded with remapped ports",
            lastEvent: "Execution complete",
          },
        }),
        result: {
          kind: "success",
          title: "SUCCESS",
          message: "Deployment completed successfully after constraint negotiation.",
          durationLabel: "14.1s",
          servicesLabel: "5 / 5 healthy",
          verificationScore: 91,
          constraintsResolved: 1,
          rollbackScope: null,
        },
        runStatus: "succeeded",
        ...baseExplain(
          "COMPLETE",
          "The port conflict was resolved before execution. Deployment completed successfully.",
          "final_status=succeeded · cnp.conflicts_resolved=1 · method=PRIORITY+ALTERNATIVE",
          "Complete",
          1,
        ),
      },
    },
  ];
}

function buildSecurityConflict(): DemoFrame[] {
  const pipeline = initialPipeline();
  const agents = initialAgents();
  const earlyDone = {
    PREFLIGHT: { status: "success" as const, detail: "Host ready", durationMs: 820 },
    ANALYZE: { status: "success" as const, detail: "Stack inferred", durationMs: 640 },
    PLAN: { status: "success" as const, detail: "Task ready", durationMs: 410 },
    AGENTS: {
      status: "success" as const,
      detail: "Constraints published",
      durationMs: 900,
    },
  };

  const resolved: ConstraintView[] = [
    { ...SECURITY_CONFLICT_CONSTRAINTS[0], status: "rejected" },
    { ...SECURITY_CONFLICT_CONSTRAINTS[1], status: "accepted" },
    ...BASE_CONSTRAINTS_CLEAN.filter((c) => c.type === "PORT_CLAIM" || c.type === "EXEC_ORDER"),
  ];

  return [
    ...earlyFrames("SECURITY_CONFLICT"),
    ...agentPublishFrames("SECURITY_CONFLICT", SECURITY_CONFLICT_CONSTRAINTS),
    {
      delayMs: 900,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          NEGOTIATE: { status: "warning", detail: "Security vs preference" },
        }),
        constraints: SECURITY_CONFLICT_CONSTRAINTS,
        negotiation: {
          title: "CONSTRAINT NEGOTIATION",
          conflictSummary: "Privileged preference conflicts with security policy",
          round: 1,
          maxRounds: 3,
          status: "resolving",
          involvedConstraintIds: ["c_pref_priv", "c_sec_block_priv"],
          simpleExplanation:
            "A convenience request conflicts with a security rule. MEDHA is applying priority order before anything runs.",
          technicalNotes: [
            "SECURITY > PREFERENCE",
            "ids=[c_sec_block_priv,c_pref_priv]",
          ],
        },
        ...baseExplain(
          "NEGOTIATE",
          "A specialist asked for a privileged container, but the security policy forbids it. MEDHA is applying priority rules.",
          "cnp.phase=PRIORITY_RESOLUTION · SECURITY>PREFERENCE · round=1/3",
          "Conflict",
          1,
        ),
        agents: setAgents(agents, {
          mediator: {
            status: "running",
            activity: "Resolving security vs preference conflict",
            lastEvent: "Priority resolution",
          },
        }),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", "scenario=SECURITY_CONFLICT"),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e5", "08:41:06", "warning", "Privileged preference published"),
          t("e6", "08:41:06", "success", "Security policy published"),
          t("e7", "08:41:07", "warning", "Security conflict detected"),
          t("e8", "08:41:07", "info", "Priority resolution: SECURITY > PREFERENCE"),
        ],
      },
    },
    {
      delayMs: 1100,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          NEGOTIATE: {
            status: "success",
            detail: "Security wins",
            durationMs: 1100,
          },
          VERIFY: { status: "success", detail: "Gate passed", durationMs: 680 },
          EXECUTE: { status: "success", detail: "Hardened deploy", durationMs: 1500 },
          RECOVER: { status: "skipped", detail: "Not required" },
          COMPLETE: { status: "success", detail: "Deployment finished" },
        }),
        constraints: resolved,
        negotiation: {
          title: "CONSTRAINT NEGOTIATION",
          conflictSummary: "Privileged preference vs no-privileged policy",
          round: 1,
          maxRounds: 3,
          resolution: "Reject privileged preference; keep security policy",
          method: "PRIORITY",
          status: "resolved",
          involvedConstraintIds: ["c_pref_priv", "c_sec_block_priv"],
          simpleExplanation:
            "Security rules outranked the convenience preference. The unsafe option was rejected before execution.",
          technicalNotes: [
            "winner=c_sec_block_priv",
            "loser=c_pref_priv",
            "method=PRIORITY",
            "llm_mediation=false",
          ],
        },
        verification: {
          checks: [
            { id: "schema", name: "Schema", status: "pass", message: "OK" },
            { id: "yaml", name: "YAML", status: "pass", message: "OK" },
            { id: "compose", name: "Compose", status: "pass", message: "OK" },
            {
              id: "security",
              name: "Security",
              status: "pass",
              message: "Privileged mode blocked",
            },
            { id: "constraints", name: "Constraints", status: "pass", message: "Consistent" },
            { id: "health", name: "Health", status: "pass", message: "OK" },
          ],
          passed: true,
          summary: "Security floor preserved.",
        },
        critic: {
          score: 96,
          breakdown: {
            security: 100,
            completeness: 92,
            constraints: 100,
            intentAlignment: 94,
          },
          recommendation: "PASS",
          findings: ["SECURITY priority correctly defeated PREFERENCE"],
        },
        graph: successGraph("all_ok"),
        result: {
          kind: "success",
          title: "SUCCESS",
          message: "Deployment completed with the hardened security choice.",
          durationLabel: "13.2s",
          servicesLabel: "5 / 5 healthy",
          verificationScore: 96,
          constraintsResolved: 1,
          rollbackScope: null,
        },
        runStatus: "succeeded",
        agents: setAgents(agents, {
          mediator: {
            status: "complete",
            activity: "Security policy accepted; privileged preference rejected",
            lastEvent: "Conflict resolved",
          },
          verifier: {
            status: "complete",
            activity: "Security floor verified",
            lastEvent: "Verification passed",
          },
          critic: {
            status: "complete",
            activity: "Score 96 — PASS",
            lastEvent: "Critic complete",
          },
          executor: {
            status: "complete",
            activity: "MOCK hardened execution succeeded",
            lastEvent: "Execution complete",
          },
        }),
        ...baseExplain(
          "COMPLETE",
          "Security policy won. The deployment continued without privileged containers.",
          "method=PRIORITY · winner=c_sec_block_priv · final_status=succeeded",
          "Complete",
          1,
        ),
      },
    },
  ];
}

function buildVerificationFailure(): DemoFrame[] {
  const pipeline = initialPipeline();
  const agents = initialAgents();
  const earlyDone = {
    PREFLIGHT: { status: "success" as const, detail: "Host ready", durationMs: 820 },
    ANALYZE: { status: "success" as const, detail: "Stack inferred", durationMs: 640 },
    PLAN: { status: "success" as const, detail: "Task ready", durationMs: 410 },
    AGENTS: {
      status: "success" as const,
      detail: "Constraints published",
      durationMs: 900,
    },
    NEGOTIATE: {
      status: "success" as const,
      detail: "Constraints agreed",
      durationMs: 500,
    },
  };

  return [
    ...earlyFrames("VERIFICATION_FAILURE"),
    ...agentPublishFrames("VERIFICATION_FAILURE", BASE_CONSTRAINTS_CLEAN),
    {
      delayMs: 800,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          VERIFY: { status: "running", detail: "Hard checks running" },
        }),
        negotiation: {
          title: "CONSTRAINT NEGOTIATION",
          conflictSummary: "No conflicting claims detected",
          round: 1,
          maxRounds: 3,
          resolution: "Constraint set accepted",
          method: "VALIDATE",
          status: "resolved",
          involvedConstraintIds: BASE_CONSTRAINTS_CLEAN.map((c) => c.id),
          simpleExplanation: "Constraints agreed. Verification is the next gate.",
          technicalNotes: ["conflicts=0"],
        },
        verification: {
          checks: emptyVerification().checks.map((c) => ({
            ...c,
            status: "pending" as const,
            message: "Running…",
          })),
          passed: null,
          summary: "Verification in progress",
        },
        agents: setAgents(agents, {
          mediator: {
            status: "complete",
            activity: "Constraint set accepted",
            lastEvent: "CNP resolved",
          },
          verifier: {
            status: "running",
            activity: "Evaluating compose and health expectations",
            lastEvent: "Verification started",
          },
        }),
        ...baseExplain(
          "VERIFY",
          "MEDHA is verifying the generated configuration before Docker execution.",
          "agent=verifier · gate=pre_exec",
          "Verifying",
        ),
      },
    },
    {
      delayMs: 1000,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          VERIFY: { status: "failed", detail: "Health check missing", durationMs: 900 },
          EXECUTE: { status: "skipped", detail: "Blocked by gate" },
          RECOVER: { status: "skipped", detail: "Nothing executed" },
          COMPLETE: { status: "failed", detail: "Stopped before execution" },
        }),
        verification: {
          checks: [
            { id: "schema", name: "Schema", status: "pass", message: "OK" },
            { id: "yaml", name: "YAML", status: "pass", message: "OK" },
            {
              id: "compose",
              name: "Compose",
              status: "warning",
              message: "Service backend missing healthcheck block",
            },
            { id: "security", name: "Security", status: "pass", message: "OK" },
            { id: "constraints", name: "Constraints", status: "pass", message: "OK" },
            {
              id: "health",
              name: "Health",
              status: "fail",
              message: "No health expectation for backend",
            },
          ],
          passed: false,
          summary: "Verification failed. Execution is blocked.",
        },
        critic: {
          score: 58,
          breakdown: {
            security: 88,
            completeness: 42,
            constraints: 90,
            intentAlignment: 55,
          },
          recommendation: "BLOCK",
          findings: [
            "Backend has no health expectation — rollback would be unsafe to automate",
            "Completeness below deployment floor",
          ],
        },
        graph: emptyGraph(),
        agents: setAgents(agents, {
          verifier: {
            status: "failed",
            activity: "Health expectation check failed",
            lastEvent: "Verification failed",
            durationMs: 900,
          },
          critic: {
            status: "complete",
            activity: "Score 58 — BLOCK",
            lastEvent: "Critic blocked execution",
          },
          executor: {
            status: "skipped",
            activity: "Did not run — gate blocked",
            lastEvent: "Skipped",
          },
        }),
        result: {
          kind: "failed",
          title: "FAILED",
          message: "Deployment stopped before execution.",
          durationLabel: "8.6s",
          servicesLabel: "0 / 0 started",
          verificationScore: 58,
          constraintsResolved: 0,
          rollbackScope: null,
        },
        runStatus: "failed",
        ...baseExplain(
          "COMPLETE",
          "Verification failed on missing health expectations. MEDHA stopped before any Docker changes.",
          "verification.passed=false · critic.verdict=BLOCK · executor=skipped",
          "Failed",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", "scenario=VERIFICATION_FAILURE"),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e8", "08:41:07", "success", "Constraints agreed"),
          t("e9", "08:41:08", "error", "Verification failed — health expectation missing"),
          t("e10", "08:41:08", "error", "Critic recommendation: BLOCK"),
          t("e11", "08:41:09", "neutral", "Executor skipped — nothing to roll back"),
        ],
      },
    },
  ];
}

function buildPartialFailure(): DemoFrame[] {
  const pipeline = initialPipeline();
  const agents = initialAgents();
  const earlyDone = {
    PREFLIGHT: { status: "success" as const, detail: "Host ready", durationMs: 820 },
    ANALYZE: { status: "success" as const, detail: "Stack inferred", durationMs: 640 },
    PLAN: { status: "success" as const, detail: "Task ready", durationMs: 410 },
    AGENTS: {
      status: "success" as const,
      detail: "Constraints published",
      durationMs: 900,
    },
    NEGOTIATE: {
      status: "success" as const,
      detail: "No conflicts",
      durationMs: 500,
    },
    VERIFY: { status: "success" as const, detail: "Gate passed", durationMs: 700 },
  };

  const runningGraph = {
    nodes: successGraph("all_ok").nodes.map((n) => {
      if (n.id === "n_network" || n.id === "n_database" || n.id === "n_analytics") {
        return { ...n, status: "success" as const };
      }
      if (n.id === "n_backend") return { ...n, status: "running" as const };
      return { ...n, status: "pending" as const };
    }),
    edges: successGraph("all_ok").edges,
  };

  const failedGraph = {
    nodes: successGraph("partial").nodes.map((n) => {
      if (n.id === "n_frontend") return { ...n, status: "running" as const };
      return n.id === "n_backend" ? { ...n, status: "failed" as const } : n;
    }),
    edges: successGraph("partial").edges,
  };

  return [
    ...earlyFrames("PARTIAL_FAILURE"),
    ...agentPublishFrames("PARTIAL_FAILURE", BASE_CONSTRAINTS_CLEAN),
    {
      delayMs: 800,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          EXECUTE: { status: "running", detail: "Starting services" },
        }),
        constraints: BASE_CONSTRAINTS_CLEAN,
        negotiation: {
          title: "CONSTRAINT NEGOTIATION",
          conflictSummary: "No conflicting claims detected",
          round: 1,
          maxRounds: 3,
          resolution: "Constraint set accepted",
          method: "VALIDATE",
          status: "resolved",
          involvedConstraintIds: BASE_CONSTRAINTS_CLEAN.map((c) => c.id),
          simpleExplanation: "Constraints agreed. Execution is recording the causal graph.",
          technicalNotes: ["conflicts=0"],
        },
        verification: {
          checks: [
            { id: "schema", name: "Schema", status: "pass", message: "OK" },
            { id: "yaml", name: "YAML", status: "pass", message: "OK" },
            { id: "compose", name: "Compose", status: "pass", message: "OK" },
            { id: "security", name: "Security", status: "pass", message: "OK" },
            { id: "constraints", name: "Constraints", status: "pass", message: "OK" },
            { id: "health", name: "Health", status: "pass", message: "OK" },
          ],
          passed: true,
          summary: "Verification passed.",
        },
        critic: {
          score: 93,
          breakdown: {
            security: 95,
            completeness: 92,
            constraints: 100,
            intentAlignment: 89,
          },
          recommendation: "PASS",
          findings: ["Plan approved for local Docker execution"],
        },
        graph: runningGraph,
        agents: setAgents(agents, {
          mediator: {
            status: "complete",
            activity: "No conflicts",
            lastEvent: "CNP resolved",
          },
          verifier: {
            status: "complete",
            activity: "Gate passed",
            lastEvent: "Verification passed",
          },
          critic: {
            status: "complete",
            activity: "Score 93 — PASS",
            lastEvent: "Critic complete",
          },
          executor: {
            status: "running",
            activity: "Starting backend after database (MOCK)",
            lastEvent: "CEG node n_backend running",
          },
        }),
        ...baseExplain(
          "EXECUTE",
          "MEDHA is starting services and recording causal dependencies in the execution graph.",
          "ceg.nodes=[network,database,analytics,backend…] · mode=DEMO/MOCK",
          "Executing",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", "scenario=PARTIAL_FAILURE"),
          t("e2", "08:41:02", "success", "Preflight completed"),
          t("e3", "08:41:04", "success", "Repository analyzed"),
          t("e8", "08:41:07", "success", "Constraints agreed"),
          t("e9", "08:41:08", "success", "Verification passed"),
          t("e10", "08:41:12", "success", "NETWORK succeeded"),
          t("e11", "08:41:14", "success", "DATABASE succeeded"),
          t("e12", "08:41:14", "success", "ANALYTICS succeeded"),
          t("e13", "08:41:16", "info", "BACKEND starting"),
        ],
      },
    },
    {
      delayMs: 1000,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          EXECUTE: { status: "failed", detail: "Backend health failed" },
          RECOVER: { status: "running", detail: "Tracing causal graph" },
        }),
        graph: failedGraph,
        selectedNodeId: "n_backend",
        agents: setAgents(agents, {
          executor: {
            status: "failed",
            activity: "Backend health check failed (MOCK)",
            lastEvent: "Node n_backend failed",
          },
          rollback: {
            status: "running",
            activity: "Computing dependency-aware rollback scope",
            lastEvent: "CEG traversal started",
          },
        }),
        ...baseExplain(
          "RECOVER",
          "Backend failed. MEDHA is tracing the causal graph to determine which services are actually affected.",
          "failed_node=n_backend · dependents=[n_frontend] · independent=[n_analytics]",
          "Recovering",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", "scenario=PARTIAL_FAILURE"),
          t("e10", "08:41:12", "success", "NETWORK succeeded"),
          t("e11", "08:41:14", "success", "DATABASE succeeded"),
          t("e12", "08:41:14", "success", "ANALYTICS succeeded"),
          t("e13", "08:41:16", "error", "BACKEND failed — health check failed"),
          t("e14", "08:41:17", "warning", "FRONTEND depends on BACKEND"),
          t("e15", "08:41:17", "info", "CEG analysis started for scoped rollback"),
        ],
      },
    },
    {
      delayMs: 1200,
      patch: {
        pipeline: setStages(pipeline, {
          ...earlyDone,
          EXECUTE: { status: "failed", detail: "Backend health failed", durationMs: 2100 },
          RECOVER: {
            status: "success",
            detail: "Scoped rollback complete",
            durationMs: 1100,
          },
          COMPLETE: { status: "warning", detail: "Partial recovery" },
        }),
        graph: successGraph("partial"),
        selectedNodeId: "n_backend",
        rollback: {
          headline: "SCOPED ROLLBACK COMPLETE",
          preserved: 3,
          failed: 1,
          rolledBack: 1,
          details: [
            { service: "NETWORK", status: "preserved", note: "Independent of failure branch" },
            { service: "DATABASE", status: "preserved", note: "Upstream success retained" },
            {
              service: "BACKEND",
              status: "failed",
              note: "Health check failed after start",
            },
            {
              service: "FRONTEND",
              status: "rolled_back",
              note: "Dependent on backend — reversed",
            },
            {
              service: "ANALYTICS",
              status: "preserved",
              note: "Causally independent branch kept running",
            },
          ],
          scopeNodeIds: ["n_frontend", "n_backend"],
          simpleExplanation:
            "Only the failed service and its dependents were rolled back. Independent successes stayed up.",
        },
        agents: setAgents(agents, {
          executor: {
            status: "failed",
            activity: "Backend failed during MOCK execution",
            lastEvent: "Node n_backend failed",
          },
          rollback: {
            status: "complete",
            activity: "Rolled back frontend; preserved analytics",
            lastEvent: "Scoped rollback complete",
            durationMs: 1100,
          },
        }),
        result: {
          kind: "partial_recovery",
          title: "PARTIAL RECOVERY",
          message:
            "Deployment encountered a failure and recovered the affected branch.",
          durationLabel: "16.8s",
          servicesLabel: "3 preserved · 1 failed · 1 rolled back",
          verificationScore: 93,
          constraintsResolved: 0,
          rollbackScope: "n_frontend ← n_backend",
        },
        runStatus: "partial_recovery",
        ...baseExplain(
          "COMPLETE",
          "Scoped rollback finished. Analytics stayed up because it did not depend on the failed backend.",
          "rollback.scope=[n_frontend,n_backend] · preserved=[n_network,n_database,n_analytics]",
          "Recovered",
        ),
        trace: [
          t("e1", "08:41:01", "info", "DEMO deployment started", "scenario=PARTIAL_FAILURE"),
          t("e13", "08:41:16", "error", "BACKEND failed — health check failed"),
          t("e14", "08:41:17", "warning", "FRONTEND marked for rollback"),
          t("e15", "08:41:17", "info", "ANALYTICS preserved — independent branch"),
          t("e16", "08:41:18", "success", "FRONTEND rolled back"),
          t("e17", "08:41:19", "success", "Scoped rollback complete (DEMO)"),
        ],
      },
    },
  ];
}

export function framesForScenario(scenario: ScenarioId): DemoFrame[] {
  void scenario;
  return [];
}

export function createIdleSnapshot(): DeploymentSnapshot {
  return {
    deploymentId: null,
    isDemo: false,
    executionMode: null,
    runtimeLogs: null,
    scenario: null,
    runStatus: "idle",
    explain: {
      currentStage: null,
      round: null,
      statusLabel: "Idle",
      simpleText:
        "Connect a repository and start a real analysis. No demo data is shown.",
      technicalText:
        "runStatus=idle · mode=real · backend=SSE · data_source=none",
    },
    pipeline: initialPipeline(),
    agents: initialAgents(),
    constraints: [],
    negotiation: null,
    verification: null,
    critic: null,
    graph: emptyGraph(),
    selectedNodeId: null,
    rollback: null,
    result: null,
    trace: [],
    frameIndex: -1,
    totalFrames: 0,
    changeIntel: null,
  };
}
