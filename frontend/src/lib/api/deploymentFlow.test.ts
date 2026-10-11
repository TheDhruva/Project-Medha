import { describe, expect, it } from "vitest";
import {
  applyBackendEvent,
  buildBackendSnapshot,
  createRunningSnapshot,
  isTerminalDeploymentStatus,
  reconcileTerminalState,
} from "@/lib/api/eventMapper";
import { createIdleSnapshot } from "@/lib/demo/frames";
import type { BackendSystemEvent } from "@/lib/api/client";

/**
 * Lightweight frontend flow coverage (P1-4): open → start demo → receive
 * events → terminal → rendered result. No e2e framework is configured, so
 * this drives the same pure snapshot machinery the live UI uses.
 */
function makeEvent(partial: Partial<BackendSystemEvent>): BackendSystemEvent {
  return {
    event_id: `e-${Math.random().toString(36).slice(2)}`,
    deployment_id: "dep_flow1",
    ts: new Date().toISOString(),
    stage: "EXECUTE",
    type: "execution.node.completed",
    level: "info",
    message: "backend succeeded",
    status: null,
    is_demo: true,
    ...partial,
  };
}

describe("deployment flow (open → events → terminal → result)", () => {
  it("starts from idle, runs, and reaches a succeeded terminal snapshot", () => {
    let snapshot = createIdleSnapshot();
    expect(snapshot.runStatus).toBe("idle");

    snapshot = createRunningSnapshot("dep_flow1", "PORT_CONFLICT", true);
    expect(snapshot.runStatus).toBe("running");

    snapshot = applyBackendEvent(snapshot, makeEvent({ type: "execution.node.started" }));
    expect(snapshot.runStatus).toBe("running");
    expect(snapshot.trace.length).toBeGreaterThan(0);

    snapshot = applyBackendEvent(
      snapshot,
      makeEvent({ type: "deployment.completed", stage: "COMPLETE" }),
    );
    expect(snapshot.runStatus).toBe("succeeded");
    expect(isTerminalDeploymentStatus("completed")).toBe(true);
  });

  it("reconciles to failed when the stream drops before the terminal event", () => {
    const running = createRunningSnapshot("dep_flow1", "PORT_CONFLICT", true);
    const reconciled = reconcileTerminalState(running, {
      deployment_id: "dep_flow1",
      status: "failed",
      mode: "demo",
      is_demo: true,
      scenario: "PORT_CONFLICT",
      repository_url: "https://github.com/example/app",
      target: { host: "localhost", port: 8080 },
      intent: null,
      current_stage: "COMPLETE",
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
      error_summary: "boom",
      result: {
        kind: "failed",
        title: "FAILED",
        message: "boom",
        durationLabel: "~1s",
        servicesLabel: "0",
        verificationScore: null,
        constraintsResolved: 0,
        rollbackScope: null,
      },
    });
    expect(reconciled.runStatus).toBe("failed");
    expect(reconciled.result?.title).toBe("FAILED");
  });

  it("hydrates a stored completed run with its result intact", () => {
    const snapshot = buildBackendSnapshot({
      api: {
        deployment_id: "dep_flow1",
        status: "completed",
        mode: "demo",
        is_demo: true,
        scenario: "SUCCESSFUL_DEPLOYMENT",
        repository_url: "https://github.com/example/app",
        target: { host: "localhost", port: 8080 },
        intent: null,
        current_stage: "COMPLETE",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        result: {
          kind: "success",
          title: "SUCCESS",
          message: "Deployment completed successfully.",
          durationLabel: "~3s",
          servicesLabel: "5 / 5 healthy",
          verificationScore: 95,
          constraintsResolved: 2,
          rollbackScope: null,
        },
      },
      logs: [],
    });
    expect(snapshot.runStatus).toBe("succeeded");
    expect(snapshot.result?.title).toBe("SUCCESS");
  });
});
