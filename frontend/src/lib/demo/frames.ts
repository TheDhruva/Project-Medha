import { emptyGraph, initialAgents, initialPipeline } from "./scenarios";
import type { DeploymentSnapshot } from "./types";

// Live-only helper: the deterministic demo playback frames were removed
// (framesForScenario always returned []). Only the idle snapshot used by the
// real deployment flow (DeploymentContext + eventMapper tests) remains.
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
    durationSeconds: null,
  };
}
