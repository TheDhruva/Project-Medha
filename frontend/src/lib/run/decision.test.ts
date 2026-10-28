import { describe, expect, it } from "vitest";
import { getDecision, getJourney } from "@/lib/run/decision";
import { createIdleSnapshot } from "@/lib/demo/frames";
import { initialPipeline, setStages } from "@/lib/demo/scenarios";
import type { DeploymentSnapshot } from "@/lib/demo/types";

function base(overrides: Partial<DeploymentSnapshot> = {}): DeploymentSnapshot {
  return { ...createIdleSnapshot(), ...overrides };
}

describe("getDecision", () => {
  it("approves a succeeded run and shows a real score", () => {
    const d = getDecision(
      base({
        runStatus: "succeeded",
        verification: { checks: [], passed: true, summary: "ok" },
        critic: {
          score: 92,
          breakdown: { security: 90, completeness: 90, constraints: 95, intentAlignment: 90 },
          recommendation: "PASS",
          findings: ["good"],
        },
        result: {
          kind: "success",
          title: "SUCCESS",
          message: "done",
          durationLabel: "7.2s",
          servicesLabel: "5 / 5",
          verificationScore: 92,
          constraintsResolved: 1,
          rollbackScope: null,
        },
      }),
    );
    expect(d.kind).toBe("approved");
    expect(d.title).toBe("Deployment approved");
    expect(d.score).toBe(92);
  });

  it("never shows a zero score as evaluated", () => {
    const d = getDecision(
      base({
        runStatus: "succeeded",
        critic: {
          score: 0,
          breakdown: { security: 0, completeness: 0, constraints: 0, intentAlignment: 0 },
          recommendation: "PASS",
          findings: [],
        },
        result: {
          kind: "success",
          title: "SUCCESS",
          message: "done",
          durationLabel: "—",
          servicesLabel: "see graph",
          verificationScore: null,
          constraintsResolved: 0,
          rollbackScope: null,
        },
      }),
    );
    expect(d.score).toBeNull();
  });

  it("blocks a failed run with the backend message", () => {
    const d = getDecision(
      base({
        runStatus: "failed",
        verification: {
          checks: [{ id: "health", name: "Health", status: "fail", message: "missing" }],
          passed: false,
          summary: "Verification failed.",
        },
        result: {
          kind: "failed",
          title: "FAILED",
          message: "A blocking security constraint remains unresolved.",
          durationLabel: "—",
          servicesLabel: "n/a",
          verificationScore: null,
          constraintsResolved: 0,
          rollbackScope: null,
        },
      }),
    );
    expect(d.kind).toBe("blocked");
    expect(d.body).toContain("blocking security constraint");
  });

  it("labels post-execution failures without any assessment score", () => {
    // Regression: a critic 100/100 beside "Deployment blocked" read as a
    // perfect deployment score on a failed run.
    const d = getDecision(
      base({
        runStatus: "failed",
        critic: {
          score: 100,
          breakdown: { security: 100, completeness: 100, constraints: 100, intentAlignment: 100 },
          recommendation: "PASS",
          findings: ["clean"],
        },
        graph: {
          nodes: [
            {
              id: "n1",
              service: "app",
              action: "start",
              status: "failed",
              timestamp: "t",
              dependencies: [],
              position: { x: 0, y: 0 },
            },
          ],
          edges: [],
        },
        result: {
          kind: "failed",
          title: "READINESS_FAILED",
          message: "Application did not become ready: connection refused",
          durationLabel: "real",
          servicesLabel: "0 / 1 healthy",
          verificationScore: 100,
          constraintsResolved: 0,
          rollbackScope: null,
        },
      }),
    );
    expect(d.kind).toBe("blocked");
    expect(d.title).toBe("Deployment failed");
    expect(d.body).toContain("connection refused");
    expect(d.score).toBeNull();
  });

  it("labels pre-execution failures as blocked", () => {
    const d = getDecision(
      base({
        runStatus: "failed",
        verification: {
          checks: [{ id: "v", name: "Gate", status: "fail", message: "nope" }],
          passed: false,
          summary: "Verification failed.",
        },
        result: {
          kind: "failed",
          title: "FAILED",
          message: "Verification gate failed.",
          durationLabel: "planning",
          servicesLabel: "n/a",
          verificationScore: null,
          constraintsResolved: 0,
          rollbackScope: null,
        },
      }),
    );
    expect(d.title).toBe("Deployment blocked");
    expect(d.score).toBeNull();
  });

  it("names a clone failure as a repository checkout failure, not a deployment block", () => {
    const d = getDecision(
      base({
        runStatus: "failed",
        result: {
          kind: "failed",
          title: "FAILED",
          message: "fatal: cannot create directory at 'test/…': Filename too long",
          durationLabel: "84s",
          servicesLabel: "n/a",
          verificationScore: null,
          constraintsResolved: 0,
          rollbackScope: null,
          code: "GIT.CHECKOUT_FAILED",
          failure: {
            code: "GIT.CHECKOUT_FAILED",
            category: "filesystem",
            operation: "clone",
            exit_code: 128,
          },
        },
      }),
    );
    expect(d.title).toBe("Repository checkout failed");
    expect(d.kind).toBe("blocked");
    expect(d.score).toBeNull();
    expect(d.body).toContain("Filename too long");
    expect(d.body).not.toContain("deployment decision");
  });

  it("marks partial recovery runs as recovered", () => {
    const d = getDecision(
      base({
        runStatus: "partial_recovery",
        rollback: {
          headline: "SCOPED ROLLBACK COMPLETE",
          preserved: 3,
          failed: 1,
          rolledBack: 1,
          details: [],
          scopeNodeIds: ["n_backend"],
          simpleExplanation: "Only the failed branch was rolled back.",
        },
      }),
    );
    expect(d.kind).toBe("recovered");
    expect(d.body).toContain("failed branch");
  });
});

describe("getJourney", () => {
  it("marks every step done for a completed run", () => {
    const snap = base({
      runStatus: "succeeded",
      pipeline: setStages(initialPipeline(), {
        ANALYZE: { status: "success", detail: "done" },
        PLAN: { status: "success", detail: "done" },
        NEGOTIATE: { status: "success", detail: "done" },
        VERIFY: { status: "success", detail: "done" },
        EXECUTE: { status: "success", detail: "done" },
      }),
      negotiation: {
        title: "CNP",
        conflictSummary: "ok",
        round: 1,
        maxRounds: 3,
        status: "resolved",
        involvedConstraintIds: [],
        simpleExplanation: "ok",
      },
      verification: { checks: [], passed: true, summary: "ok" },
      graph: {
        nodes: [
          {
            id: "n1",
            service: "api",
            action: "start",
            status: "success",
            timestamp: "t",
            dependencies: [],
            position: { x: 0, y: 0 },
          },
        ],
        edges: [],
      },
    });
    const steps = getJourney(snap);
    expect(steps).toHaveLength(6);
    expect(steps.every((s) => s.done)).toBe(true);
  });

  it("leaves future steps pending while running", () => {
    const snap = base({ runStatus: "running" });
    const steps = getJourney(snap);
    expect(steps[0].done).toBe(false);
    expect(steps.filter((s) => s.active)).toHaveLength(1);
  });
});
