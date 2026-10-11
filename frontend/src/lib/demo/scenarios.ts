import type {
  AgentActivity,
  CegGraph,
  ConstraintView,
  CriticView,
  PipelineStage,
  ScenarioId,
  ScenarioMeta,
  StageId,
  VerificationView,
} from "./types";

export const SCENARIOS: ScenarioMeta[] = [
  {
    id: "SUCCESSFUL_DEPLOYMENT",
    name: "Successful Deployment",
    description:
      "A clean path from analysis through negotiation, verification, and execution.",
    expectedBehavior:
      "All stages succeed. Constraints agree without conflict. The causal graph shows every service healthy.",
  },
  {
    id: "PORT_CONFLICT",
    name: "Port Conflict",
    description:
      "Two specialist agents claim the same host port before anything is started.",
    expectedBehavior:
      "CNP detects the conflict, resolves it within bounded rounds, remaps Nginx to an alternative port, then continues.",
  },
  {
    id: "SECURITY_CONFLICT",
    name: "Security Conflict",
    description:
      "A preference for unrestricted access conflicts with a security policy.",
    expectedBehavior:
      "SECURITY priority wins over PREFERENCE. The unsafe request is rejected; deployment continues with the hardened choice.",
  },
  {
    id: "VERIFICATION_FAILURE",
    name: "Verification Failure",
    description:
      "Generated configuration fails a hard verification gate, then MEDHA performs one bounded replan.",
    expectedBehavior:
      "Verification fails once (missing env), replan round 1 corrects the fixture, verification passes, then execution succeeds.",
  },
  {
    id: "PARTIAL_FAILURE",
    name: "Partial Failure",
    description:
      "Backend fails after dependent services have started.",
    expectedBehavior:
      "MEDHA identifies the affected branch and preserves independent successful services via scoped rollback.",
  },
];

export const STAGE_ORDER: StageId[] = [
  "PREFLIGHT",
  "ANALYZE",
  "PLAN",
  "AGENTS",
  "NEGOTIATE",
  "VERIFY",
  "EXECUTE",
  "RECOVER",
  "COMPLETE",
];

export function initialPipeline(): PipelineStage[] {
  return STAGE_ORDER.map((id) => ({
    id,
    label: id,
    status: "pending",
    detail: "Waiting",
  }));
}

export function initialAgents(): AgentActivity[] {
  return [
    {
      id: "preflight",
      name: "Preflight",
      status: "idle",
      activity: "Waiting for deployment start",
      lastEvent: "—",
    },
    {
      id: "analyzer",
      name: "Code Analyzer",
      status: "idle",
      activity: "Waiting for repository analysis",
      lastEvent: "—",
    },
    {
      id: "docker",
      name: "Docker",
      status: "idle",
      activity: "Waiting to publish constraints",
      lastEvent: "—",
    },
    {
      id: "nginx",
      name: "Nginx",
      status: "idle",
      activity: "Waiting to publish constraints",
      lastEvent: "—",
    },
    {
      id: "security",
      name: "Security",
      status: "idle",
      activity: "Waiting to publish policies",
      lastEvent: "—",
    },
    {
      id: "mediator",
      name: "Mediator",
      status: "idle",
      activity: "Waiting for constraint set",
      lastEvent: "—",
    },
    {
      id: "verifier",
      name: "Verifier",
      status: "idle",
      activity: "Waiting for agreed plan",
      lastEvent: "—",
    },
    {
      id: "critic",
      name: "Critic",
      status: "idle",
      activity: "Waiting for verification context",
      lastEvent: "—",
    },
    {
      id: "executor",
      name: "Executor",
      status: "idle",
      activity: "Waiting for gate pass",
      lastEvent: "—",
    },
    {
      id: "rollback",
      name: "Rollback",
      status: "idle",
      activity: "Standing by for failure scope",
      lastEvent: "—",
    },
  ];
}

export function emptyGraph(): CegGraph {
  return { nodes: [], edges: [] };
}

export function emptyVerification(): VerificationView {
  return {
    checks: [
      { id: "schema", name: "Schema", status: "pending", message: "Not run" },
      { id: "yaml", name: "YAML", status: "pending", message: "Not run" },
      { id: "compose", name: "Compose", status: "pending", message: "Not run" },
      {
        id: "security",
        name: "Security",
        status: "pending",
        message: "Not run",
      },
      {
        id: "constraints",
        name: "Constraints",
        status: "pending",
        message: "Not run",
      },
      { id: "health", name: "Health", status: "pending", message: "Not run" },
    ],
    passed: null,
    summary: "Verification has not started.",
  };
}

export function emptyCritic(): CriticView {
  return {
    score: 0,
    breakdown: {
      security: 0,
      completeness: 0,
      constraints: 0,
      intentAlignment: 0,
    },
    recommendation: "PASS",
    findings: [],
  };
}

export function scenarioById(id: ScenarioId): ScenarioMeta {
  return SCENARIOS.find((s) => s.id === id) ?? SCENARIOS[0];
}

export function setStages(
  pipeline: PipelineStage[],
  updates: Partial<Record<StageId, Partial<PipelineStage>>>,
): PipelineStage[] {
  return pipeline.map((stage) => {
    const patch = updates[stage.id];
    return patch ? { ...stage, ...patch } : stage;
  });
}

export function setAgents(
  agents: AgentActivity[],
  updates: Partial<Record<AgentActivity["id"], Partial<AgentActivity>>>,
): AgentActivity[] {
  return agents.map((agent) => {
    const patch = updates[agent.id];
    return patch ? { ...agent, ...patch } : agent;
  });
}

export const BASE_CONSTRAINTS_CLEAN: ConstraintView[] = [
  {
    id: "c_port_backend",
    type: "PORT_CLAIM",
    priority: "RESOURCE",
    sourceAgent: "Docker Agent",
    service: "backend",
    summary: "Backend claims host port 8080",
    detail: "Exclusive publish of container port 8080 → host 8080",
    status: "accepted",
    technical: { payload: { port: 8080, protocol: "tcp", exclusive: true } },
  },
  {
    id: "c_port_proxy",
    type: "PORT_CLAIM",
    priority: "DEPENDENCY",
    sourceAgent: "Nginx Agent",
    service: "nginx",
    summary: "Nginx publishes edge port 80",
    detail: "Reverse proxy listens on host port 80",
    status: "accepted",
    technical: { payload: { port: 80, protocol: "tcp", exclusive: true } },
  },
  {
    id: "c_sec_no_priv",
    type: "SECURITY_POLICY",
    priority: "SECURITY",
    sourceAgent: "Security Agent",
    summary: "Disallow privileged containers",
    detail: "privileged=false required for all services",
    status: "accepted",
    technical: {
      payload: { rule: "no_privileged", enforcement: "block", severity: "high" },
    },
  },
  {
    id: "c_order_db_be",
    type: "EXEC_ORDER",
    priority: "DEPENDENCY",
    sourceAgent: "Docker Agent",
    summary: "Database before backend",
    detail: "backend starts only after database is healthy",
    status: "accepted",
    technical: { payload: { before: "database", after: "backend" } },
  },
];

export function successGraph(variant: "all_ok" | "partial"): CegGraph {
  if (variant === "all_ok") {
    return {
      nodes: [
        {
          id: "n_network",
          service: "NETWORK",
          action: "create_network",
          status: "success",
          timestamp: "08:41:12",
          dependencies: [],
          position: { x: 280, y: 0 },
        },
        {
          id: "n_database",
          service: "DATABASE",
          action: "start_container",
          status: "success",
          timestamp: "08:41:14",
          dependencies: ["n_network"],
          position: { x: 80, y: 120 },
        },
        {
          id: "n_analytics",
          service: "ANALYTICS",
          action: "start_container",
          status: "success",
          timestamp: "08:41:14",
          dependencies: ["n_network"],
          position: { x: 480, y: 120 },
        },
        {
          id: "n_backend",
          service: "BACKEND",
          action: "start_container",
          status: "success",
          timestamp: "08:41:16",
          dependencies: ["n_database"],
          position: { x: 80, y: 250 },
        },
        {
          id: "n_frontend",
          service: "FRONTEND",
          action: "start_container",
          status: "success",
          timestamp: "08:41:18",
          dependencies: ["n_backend"],
          position: { x: 80, y: 380 },
        },
      ],
      edges: [
        { id: "e1", source: "n_network", target: "n_database" },
        { id: "e2", source: "n_network", target: "n_analytics" },
        { id: "e3", source: "n_database", target: "n_backend" },
        { id: "e4", source: "n_backend", target: "n_frontend" },
      ],
    };
  }

  return {
    nodes: [
      {
        id: "n_network",
        service: "NETWORK",
        action: "create_network",
        status: "preserved",
        timestamp: "08:41:12",
        dependencies: [],
        preserved: true,
        position: { x: 280, y: 0 },
      },
      {
        id: "n_database",
        service: "DATABASE",
        action: "start_container",
        status: "preserved",
        timestamp: "08:41:14",
        dependencies: ["n_network"],
        preserved: true,
        position: { x: 80, y: 120 },
      },
      {
        id: "n_analytics",
        service: "ANALYTICS",
        action: "start_container",
        status: "preserved",
        timestamp: "08:41:14",
        dependencies: ["n_network"],
        preserved: true,
        reason: "Causally independent of backend failure",
        position: { x: 480, y: 120 },
      },
      {
        id: "n_backend",
        service: "BACKEND",
        action: "start_container",
        status: "failed",
        timestamp: "08:41:16",
        dependencies: ["n_database"],
        reason: "Health check failed after start",
        dependents: ["n_frontend"],
        rollbackRequired: true,
        position: { x: 80, y: 250 },
      },
      {
        id: "n_frontend",
        service: "FRONTEND",
        action: "start_container",
        status: "rolled_back",
        timestamp: "08:41:19",
        dependencies: ["n_backend"],
        reason: "Dependent on failed backend",
        rollbackRequired: true,
        position: { x: 80, y: 380 },
      },
    ],
    edges: [
      { id: "e1", source: "n_network", target: "n_database" },
      { id: "e2", source: "n_network", target: "n_analytics" },
      { id: "e3", source: "n_database", target: "n_backend" },
      { id: "e4", source: "n_backend", target: "n_frontend" },
    ],
  };
}
