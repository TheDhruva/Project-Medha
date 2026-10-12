import { describe, expect, it } from "vitest";

import {
  applyBackendEvent,
  buildBackendSnapshot,
  createRunningSnapshot,
  isTerminalDeploymentStatus,
  mapVerificationArtifact,
  reconcileTerminalState,
} from "@/lib/api/eventMapper";
import type {
  BackendSystemEvent,
  DeploymentApiSnapshot,
  RunLogLine,
  VerificationArtifact,
} from "@/lib/api/client";
import type { ChangeIntelAnalysis, DeploymentSnapshot } from "@/lib/demo/types";

function event(overrides: Partial<BackendSystemEvent>): BackendSystemEvent {
  return {
    event_id: "evt_1",
    deployment_id: "dep_abc",
    ts: "2026-01-01T00:00:01+00:00",
    stage: null,
    type: "system.message",
    level: "info",
    message: "event",
    status: null,
    is_demo: true,
    ...overrides,
  };
}

let seq = 0;
function nextEvent(overrides: Partial<BackendSystemEvent>): BackendSystemEvent {
  seq += 1;
  return event({ event_id: `evt_${seq}`, ...overrides });
}

function runningSnapshot(isDemo = true, scenario: "PARTIAL_FAILURE" | null = "PARTIAL_FAILURE") {
  return createRunningSnapshot("dep_abc", scenario, isDemo);
}

describe("applyBackendEvent", () => {
  it("appends every event to the trace", () => {
    const snap = runningSnapshot();
    const out = applyBackendEvent(snap, nextEvent({ type: "system.message", message: "hi" }));
    expect(out.trace).toHaveLength(1);
    expect(out.trace[0].message).toBe("hi");
    expect(out.trace[0].technical).toContain("is_demo=true");
  });

  it("survives unknown event types without changing runStatus", () => {
    const snap = runningSnapshot();
    const out = applyBackendEvent(
      snap,
      nextEvent({ type: "something.else", message: "unknown" }),
    );
    expect(out.runStatus).toBe("running");
    expect(out.trace).toHaveLength(1);
  });

  it("handles malformed/empty data payloads gracefully", () => {
    const snap = runningSnapshot();
    const out = applyBackendEvent(
      snap,
      nextEvent({
        type: "constraint.conflict",
        message: "conflict!",
        data: { bogus: true } as never,
      }),
    );
    expect(out.runStatus).toBe("running");
    expect(out.explain.statusLabel).toBe("Conflict");
    expect(out.explain.simpleText).toBe("conflict!");
  });

  it("marks succeeded on deployment.completed", () => {
    const snap = runningSnapshot();
    const out = applyBackendEvent(
      snap,
      nextEvent({
        type: "deployment.completed",
        status: "completed",
        data: { result: { kind: "success" } },
      }),
    );
    expect(out.runStatus).toBe("succeeded");
    expect(out.explain.statusLabel).toBe("Complete");
    const done = out.pipeline.find((p) => p.id === "COMPLETE");
    expect(done?.status).toBe("success");
  });

  it("marks partial_recovery on deployment.completed with partial status", () => {
    const snap = runningSnapshot();
    const out = applyBackendEvent(
      snap,
      nextEvent({
        type: "deployment.completed",
        status: "partial_recovery",
        data: { result: { kind: "partial_recovery" } },
      }),
    );
    expect(out.runStatus).toBe("partial_recovery");
    const done = out.pipeline.find((p) => p.id === "COMPLETE");
    expect(done?.status).toBe("warning");
  });

  it("marks failed on deployment.failed", () => {
    const snap = runningSnapshot();
    const out = applyBackendEvent(
      snap,
      nextEvent({ type: "deployment.failed", status: "failed", level: "error" }),
    );
    expect(out.runStatus).toBe("failed");
    expect(out.result?.kind).toBe("failed");
    const done = out.pipeline.find((p) => p.id === "COMPLETE");
    expect(done?.status).toBe("failed");
  });

  it("carries live mode through events (is_demo=false)", () => {
    const snap = runningSnapshot(false, null);
    const out = applyBackendEvent(
      snap,
      nextEvent({ type: "stage.started", stage: "ANALYZE", is_demo: false }),
    );
    expect(out.isDemo).toBe(false);
    expect(out.explain.technicalText).toContain("is_demo=false");
  });
});

describe("change intelligence events", () => {
  const minimalAnalysis: ChangeIntelAnalysis = {
    deployment_id: "dep_abc",
    repository_url: "C:/repo",
    is_demo: false,
    label: null,
    generated_at: "2026-01-01T00:00:00+00:00",
    changeset: {
      base_revision: "base",
      target_revision: "target",
      base_sha: "aaaaaaaa",
      target_sha: "bbbbbbbb",
      source_method: "local",
      is_git: true,
      counts: { modified: 1, added: 0, deleted: 0, renamed: 0 },
      files: [],
      unsupported: [],
    },
    changed_symbols: [],
    graph: { nodes: [], edges: [] },
    traversal: {
      max_depth: 3,
      depth_used: 1,
      direct_targets: [],
      transitive_targets: [],
      cycles_detected: [],
    },
    unresolved: [],
    risk: { level: "low", factors: [] },
    requirements: [],
  };

  it("captures change_intel payload into the snapshot", () => {
    const snap = runningSnapshot();
    const out = applyBackendEvent(
      snap,
      nextEvent({
        type: "system.message",
        data: { change_intel: minimalAnalysis } as never,
      }),
    );
    expect(out.changeIntel).toEqual(minimalAnalysis);
  });

  it("leaves changeIntel null when the event has no payload", () => {
    const snap = runningSnapshot();
    const out = applyBackendEvent(
      snap,
      nextEvent({ type: "system.message", message: "no change intelligence" }),
    );
    expect(out.changeIntel).toBeNull();
  });
});

describe("reconcileTerminalState", () => {
  const apiNotTerminal: DeploymentApiSnapshot = {
    deployment_id: "dep_abc",
    status: "running",
    mode: "demo",
    is_demo: true,
    scenario: "PARTIAL_FAILURE",
    repository_url: "https://github.com/example/medha-sample-app",
    target: { host: "localhost", port: 8080 },
    intent: "Deploy the application securely",
    current_stage: "NEGOTIATE",
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:01+00:00",
  };

  it("leaves a non-terminal snapshot unchanged", () => {
    const snap = runningSnapshot();
    const out = reconcileTerminalState(snap, apiNotTerminal);
    expect(out).toBe(snap);
  });

  it("resolves succeeded when backend says completed", () => {
    const snap = runningSnapshot();
    const out = reconcileTerminalState(snap, {
      ...apiNotTerminal,
      status: "completed",
      current_stage: "COMPLETE",
    });
    expect(out.runStatus).toBe("succeeded");
    expect(out.explain.simpleText).toContain("reconciled");
    expect(out.trace.some((t) => t.id.startsWith("reconcile-"))).toBe(true);
  });

  it("resolves failed when backend says failed", () => {
    const snap = runningSnapshot();
    const out = reconcileTerminalState(snap, { ...apiNotTerminal, status: "failed" });
    expect(out.runStatus).toBe("failed");
    expect(out.trace.at(-1)?.tone).toBe("error");
  });
});

describe("isTerminalDeploymentStatus", () => {
  it("returns true only for terminal statuses", () => {
    expect(isTerminalDeploymentStatus("completed")).toBe(true);
    expect(isTerminalDeploymentStatus("failed")).toBe(true);
    expect(isTerminalDeploymentStatus("partial_recovery")).toBe(true);
    expect(isTerminalDeploymentStatus("cancelled")).toBe(true);
    expect(isTerminalDeploymentStatus("running")).toBe(false);
    expect(isTerminalDeploymentStatus("started")).toBe(false);
    expect(isTerminalDeploymentStatus(null)).toBe(false);
    expect(isTerminalDeploymentStatus(undefined)).toBe(false);
  });
});

// Demonstration that a full demo run through terminal events never leaves the
// UI stuck in "running" (regression guard for SSE lifecycle).
describe("state machine integration", () => {
  it("homogeneous demo run reaches a terminal status", () => {
    let snap: DeploymentSnapshot = runningSnapshot();
    const steps = [
      { type: "deployment.started", status: "running" },
      { type: "stage.started", stage: "PREFLIGHT" },
      { type: "stage.completed", stage: "PREFLIGHT", status: "success" },
      { type: "constraint.published", stage: "AGENTS" },
      { type: "negotiation.started", stage: "NEGOTIATE" },
      { type: "negotiation.resolved", stage: "NEGOTIATE" },
      { type: "verification.passed", stage: "VERIFY" },
      { type: "execution.started", stage: "EXECUTE" },
      { type: "execution.node.completed", stage: "EXECUTE" },
    ] as const;
    for (const s of steps) {
      snap = applyBackendEvent(snap, nextEvent({ ...s }));
    }
    expect(snap.runStatus).toBe("running");
    snap = applyBackendEvent(
      snap,
      nextEvent({ type: "deployment.completed", status: "completed" }),
    );
    expect(snap.runStatus).toBe("succeeded");
  });
});

describe("buildBackendSnapshot (run detail hydration)", () => {
  const api: DeploymentApiSnapshot = {
    deployment_id: "dep_hydrated",
    status: "completed",
    mode: "demo",
    is_demo: true,
    scenario: "PARTIAL_FAILURE",
    repository_url: "https://github.com/example/medha-sample-app",
    target: { host: "localhost", port: 8080 },
    intent: "Deploy the application securely",
    current_stage: "COMPLETE",
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:05+00:00",
  };

  const logs: RunLogLine[] = [
    {
      ts: "2026-01-01T00:00:01+00:00",
      level: "info",
      source: "preflight",
      message: "Preflight ok",
      type: "stage.completed",
      stage: "PREFLIGHT",
      status: "success",
      is_demo: true,
    },
    {
      ts: "2026-01-01T00:00:05+00:00",
      level: "info",
      source: "executor",
      message: "Deployment completed",
      type: "deployment.completed",
      stage: "COMPLETE",
      status: "completed",
      is_demo: true,
    },
  ];

  it("hydrates a completed run into a terminal, honest snapshot", () => {
    const snap = buildBackendSnapshot({ api, logs });
    expect(snap.runStatus).toBe("succeeded");
    expect(snap.deploymentId).toBe("dep_hydrated");
    expect(snap.isDemo).toBe(true);
    expect(snap.explain.statusLabel).toBe("Complete");
    expect(snap.explain.currentStage).toBe("COMPLETE");
    expect(snap.result?.kind).toBe("success");
    const complete = snap.pipeline.find((p) => p.id === "COMPLETE");
    expect(complete?.status).toBe("success");
    expect(snap.trace).toHaveLength(2);
    expect(snap.trace[0].message).toBe("Preflight ok");
  });

  it("never fabricates missing artifacts", () => {
    const snap = buildBackendSnapshot({ api });
    expect(snap.constraints).toEqual([]);
    expect(snap.negotiation).toBeNull();
    expect(snap.verification).toBeNull();
    expect(snap.critic).toBeNull();
    expect(snap.rollback).toBeNull();
    expect(snap.changeIntel).toBeNull();
    expect(snap.graph.nodes).toHaveLength(0);
    expect(snap.graph.edges).toHaveLength(0);
  });

  it("maps a failed run through the honest result fallback", () => {
    const snap = buildBackendSnapshot({ api: { ...api, status: "failed" } });
    expect(snap.runStatus).toBe("failed");
    expect(snap.result?.kind).toBe("failed");
    expect(snap.explain.statusLabel).toBe("Failed");
    const complete = snap.pipeline.find((p) => p.id === "COMPLETE");
    expect(complete?.status).toBe("failed");
  });

  it("carries injected backend artifacts through", () => {
    const snap = buildBackendSnapshot({
      api,
      constraints: [
        {
          id: "c1",
          type: "SECURITY_POLICY",
          priority: "SECURITY",
          sourceAgent: "Security Agent",
          summary: "No exposed secrets",
          detail: "Rejected because a secret literal was detected",
          status: "accepted",
        },
      ],
      negotiation: {
        title: "Secret exposure conflict",
        conflictSummary: "Security vs preflight on env exposure",
        round: 2,
        maxRounds: 3,
        status: "resolved",
        involvedConstraintIds: ["c1", "c2"],
        simpleExplanation: "granted security constraint",
      },
      changeIntel: {
        deployment_id: "dep_hydrated",
        repository_url: "C:/repo",
        is_demo: true,
        label: "DEMO/MOCK",
        generated_at: "2026-01-01T00:00:00+00:00",
        changeset: {
          base_revision: "base",
          target_revision: "target",
          base_sha: "a",
          target_sha: "b",
          source_method: "local",
          is_git: true,
          counts: { modified: 1, added: 0, deleted: 0, renamed: 0 },
          files: [],
          unsupported: [],
        },
        changed_symbols: [],
        graph: { nodes: [], edges: [] },
        traversal: {
          max_depth: 3,
          depth_used: 0,
          direct_targets: [],
          transitive_targets: [],
          cycles_detected: [],
        },
        unresolved: [],
        risk: { level: "low", factors: [] },
        requirements: [],
      },
      rollback: {
        headline: "Scoped rollback",
        preserved: 2,
        failed: 1,
        rolledBack: 1,
        details: [{ service: "svc-b", status: "failed", note: "rolled back" }],
        scopeNodeIds: ["svc-b"],
        simpleExplanation: "rolled back svc-b only",
      },
    });
    expect(snap.constraints).toHaveLength(1);
    expect(snap.negotiation?.round).toBe(2);
    expect(snap.changeIntel?.repository_url).toBe("C:/repo");
    expect(snap.graph).toBeDefined();
    expect(snap.rollback?.headline).toBe("Scoped rollback");
    expect(snap.constraints[0].sourceAgent).toBe("Security Agent");
  });

  it("keeps running runs as running with retrieve messaging", () => {
    const snap = buildBackendSnapshot({
      api: { ...api, status: "running", current_stage: "ANALYZE" },
    });
    expect(snap.runStatus).toBe("running");
    expect(snap.explain.currentStage).toBe("ANALYZE");
    expect(snap.explain.simpleText).toContain("Retrieving run state");
    // Phase 2: running deployments have no result yet — never fake SUCCESS.
    expect(snap.result).toBeNull();
  });
});

describe("mapVerificationArtifact", () => {
  it("maps a stored verification + critic artifact", () => {
    const artifact: VerificationArtifact = {
      verification: {
        passed: true,
        summary: "All checks passed",
        checks: [
          {
            id: "chk1",
            name: "Secret scan",
            status: "pass",
            message: "no secrets",
            rule: "no-secrets",
            category: "security",
          },
        ],
      },
      critic: {
        score: 88,
        recommendation: "APPROVE",
        breakdown: { security: 90, completeness: 80, constraints: 95, intentAlignment: 86 },
        findings: ["none"],
      },
    };
    const { verification, critic } = mapVerificationArtifact(artifact);
    expect(verification?.checks).toHaveLength(1);
    expect(verification?.checks[0].status).toBe("pass");
    expect(verification?.passed).toBe(true);
    expect(critic?.score).toBe(88);
    expect(critic?.recommendation).toBe("APPROVE");
  });

  it("returns null views for null or unrecognised artifacts", () => {
    expect(mapVerificationArtifact(null)).toEqual({ verification: null, critic: null });
    const v = mapVerificationArtifact({ verification: null, critic: null });
    expect(v.verification).toBeNull();
    expect(v.critic).toBeNull();
  });

  it("tolerates malformed checks and missing critic fields", () => {
    const { verification, critic } = mapVerificationArtifact({
      verification: { checks: [{ status: "pending" }] as never, passed: false },
      critic: { score: "72" } as never,
    });
    expect(verification?.checks[0].name).toBe("");
    expect(verification?.passed).toBe(false);
    expect(critic?.score).toBe(72);
    expect(critic?.recommendation).toBe("WARN");
  });
});

describe("execution mode and runtime logs hydration", () => {
  const baseApi: DeploymentApiSnapshot = {
    deployment_id: "dep_mode",
    status: "completed",
    mode: "real",
    is_demo: false,
    scenario: null,
    repository_url: "https://github.com/example/app",
    target: { host: "localhost", port: 8080 },
    intent: null,
    current_stage: "COMPLETE",
    created_at: "2026-01-01T00:00:00+00:00",
    updated_at: "2026-01-01T00:00:05+00:00",
  };

  it("carries explicit real mode and container logs through", () => {
    const snap = buildBackendSnapshot({
      api: baseApi,
      executionMode: "real",
      runtimeLogs: { available: true, container: "medha_x", stdout: "ok", stderr: "" },
    });
    expect(snap.executionMode).toBe("real");
    expect(snap.runtimeLogs?.stdout).toBe("ok");
  });

  it("falls back honestly when the backend sends no mode", () => {
    const demo = buildBackendSnapshot({ api: { ...baseApi, is_demo: true } });
    expect(demo.executionMode).toBe("demo");
    expect(demo.runtimeLogs).toBeNull();
    const sim = buildBackendSnapshot({ api: baseApi });
    expect(sim.executionMode).toBe("simulator");
  });

  it("never upgrades an unknown mode to real", () => {
    const snap = buildBackendSnapshot({ api: baseApi, executionMode: "quantum" });
    expect(snap.executionMode).toBe("simulator");
  });

  it("reads the mode from the stored result when /logs omits it", () => {
    const snap = buildBackendSnapshot({
      api: { ...baseApi, result: { execution_mode: "controlled_test" } },
    });
    expect(snap.executionMode).toBe("controlled_test");
  });
});