import { describe, expect, it } from "vitest";

import type { AgentSnapshotRow } from "@/lib/api/client";
import {
  agentsFromSnapshot,
  resolveAgents,
  type RunHydration,
} from "@/lib/projects/useProjectData";

function row(partial: Partial<AgentSnapshotRow> & { id: string }): AgentSnapshotRow {
  return {
    name: partial.id,
    status: "idle",
    activity: "Waiting",
    lastEvent: "—",
    durationMs: null,
    startedAt: null,
    finishedAt: null,
    deps: [],
    ...partial,
  };
}

function hydrationWith(agents: RunHydration["agents"]): RunHydration {
  return {
    logs: [],
    agents,
    executionMode: null,
    constraints: [],
    negotiation: null,
    verification: null,
    critic: null,
    graph: { nodes: [], edges: [] },
    rollback: null,
    changeImpact: null,
    changeImpactLabel: null,
    changeImpactIsDemo: false,
    health: null,
    runtimeLogs: null,
  };
}

describe("backend agent snapshot mapping", () => {
  it("maps backend statuses to display states without inventing progress", () => {
    const states = agentsFromSnapshot([
      row({ id: "preflight", status: "complete", activity: "Done", durationMs: 12.5 }),
      row({ id: "analyzer", status: "running", activity: "Analyzing" }),
      row({ id: "docker", status: "failed", activity: "Failed", error: "boom" }),
      row({ id: "nginx", status: "timed_out", activity: "Timed out" }),
      row({ id: "security", status: "cancelled", activity: "Cancelled" }),
      row({ id: "mediator", status: "skipped", activity: "Skipped" }),
      row({ id: "verifier", status: "bogus", activity: "??" }),
    ]);
    expect(states.map((s) => s.state)).toEqual([
      "done",
      "active",
      "blocked",
      "blocked",
      "idle",
      "idle",
      "idle",
    ]);
    expect(states[0].detail).toContain("0.0s");
    expect(states[2].detail).toContain("boom");
    expect(states[0].label).toBe("Preflight");
  });

  it("prefers the backend snapshot and falls back to logs only when absent", () => {
    const snapshot = [row({ id: "preflight", status: "complete", activity: "Done" })];
    const fromBackend = resolveAgents(hydrationWith(snapshot), null, "running");
    expect(fromBackend.source).toBe("backend");
    expect(fromBackend.agents).toHaveLength(1);
    expect(fromBackend.agents[0].state).toBe("done");

    const fromLogs = resolveAgents(hydrationWith(null), null, "failed");
    expect(fromLogs.source).toBe("logs");
    // Fallback never claims unobserved stages as done.
    expect(fromLogs.agents.every((a) => a.state !== "done")).toBe(true);
  });
});
