import { describe, expect, it } from "vitest";

import {
  applyBackendEvent,
  createRunningSnapshot,
  isTerminalDeploymentStatus,
  reconcileTerminalState,
} from "@/lib/api/eventMapper";
import { getDecision } from "@/lib/run/decision";
import type { BackendSystemEvent } from "@/lib/api/client";

function readyEvent(): BackendSystemEvent {
  return {
    event_id: "evt_ready",
    deployment_id: "dep_abc",
    ts: "2026-01-01T00:00:01+00:00",
    stage: "COMPLETE",
    type: "proposal.ready",
    level: "info",
    message: "Plan ready — waiting for human approval.",
    status: "awaiting_approval",
    is_demo: false,
    data: {
      plan_hash: "abc123",
      result: {
        kind: "plan_awaiting_approval",
        title: "AWAITING APPROVAL",
        message: "Verified plan ready.",
      },
    },
  };
}

describe("approval-gated states", () => {
  it("maps proposal.ready to awaiting_approval with an honest label", () => {
    const out = applyBackendEvent(
      createRunningSnapshot("dep_abc", null, false),
      readyEvent(),
    );
    expect(out.runStatus).toBe("awaiting_approval");
    expect(out.explain.statusLabel).toBe("Waiting for approval");
    expect(out.result?.kind).toBe("plan_awaiting_approval");
  });

  it("treats awaiting_approval as terminal for reconcile/stream purposes", () => {
    expect(isTerminalDeploymentStatus("awaiting_approval")).toBe(true);
    expect(isTerminalDeploymentStatus("running")).toBe(false);
  });

  it("reconciles an awaiting record from REST without fabricating a result", () => {
    const snap = createRunningSnapshot("dep_abc", null, false);
    const out = reconcileTerminalState(snap, {
      deployment_id: "dep_abc",
      status: "awaiting_approval",
      mode: "real",
      is_demo: false,
      scenario: null,
      repository_url: "https://github.com/octo/demo.git",
      target: { host: "localhost", port: 8080 },
      intent: null,
      current_stage: "COMPLETE",
      created_at: "2026-01-01T00:00:00+00:00",
      updated_at: "2026-01-01T00:00:02+00:00",
      result: null,
    });
    expect(out.runStatus).toBe("awaiting_approval");
    expect(out.explain.statusLabel).toBe("Waiting for approval");
  });

  it("offers a review-proposal decision while awaiting approval", () => {
    const snap = applyBackendEvent(
      createRunningSnapshot("dep_abc", null, false),
      readyEvent(),
    );
    const decision = getDecision(snap);
    expect(decision.kind).toBe("awaiting");
    expect(decision.title).toBe("Waiting for approval");
    expect(decision.cta).toBe("Review proposal");
  });
});
