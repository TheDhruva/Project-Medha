import type {
  AgentActivity,
  CegGraph,
  PipelineStage,
  StageId,
} from "./types";

// Live initializers for the real deployment flow (used by eventMapper and
// DeploymentContext). The deterministic demo catalog, playback constants,
// and scripted graphs were removed: SCENARIOS was [] and framesForScenario
// always returned [], so nothing in product routes consumed them.

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

export function setStages(
  pipeline: PipelineStage[],
  updates: Partial<Record<StageId, Partial<PipelineStage>>>,
): PipelineStage[] {
  return pipeline.map((stage) => {
    const patch = updates[stage.id];
    return patch ? { ...stage, ...patch } : stage;
  });
}
