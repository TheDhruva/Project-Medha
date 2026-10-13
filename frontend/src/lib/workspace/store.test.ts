import { describe, expect, it } from "vitest";
import { isProposalApprovable } from "./store";
import { SEED_PROJECTS, SEED_PROPOSALS, SEED_RUNS, evalFor } from "./seed";
import { BOARD_PANELS, DEFAULT_BOARD_LAYOUT, type ChangeProposal } from "./types";

function proposal(over: Partial<ChangeProposal>): ChangeProposal {
  return {
    id: "p1", projectId: "proj-x", title: "t", sourceRevision: "abc1234",
    previousRevision: null, state: "ready", stale: false, supersededBy: null,
    summary: "s", files: [], affected: [], constraints: [], plan: [],
    verification: { state: "pass", passed: 1, failed: 0, warnings: 0, skipped: 0, notRun: 0, findings: [] },
    risks: [], assumptions: [], openQuestions: [], target: "localhost:8080", mode: "simulator", history: [],
    ...over,
  };
}

describe("workspace (no seeded fixtures)", () => {
  it("starts empty: no fabricated projects, proposals, or runs", () => {
    expect(SEED_PROJECTS).toEqual([]);
    expect(SEED_PROPOSALS).toEqual([]);
    expect(SEED_RUNS).toEqual([]);
  });

  it("evaluation fixture reports empty honestly", () => {
    expect(evalFor("proj-evalempty").status).toBe("empty");
  });

  it("blocks approval for stale/superseded proposals with an explanation", () => {
    const stale = proposal({ stale: true, state: "outdated", supersededBy: "prop-new", sourceRevision: "old123" });
    const gate = isProposalApprovable(stale);
    expect(gate.ok).toBe(false);
    expect(gate.reason).toMatch(/Superseded/);
    expect(gate.reason).toMatch(/re-analysis/i);
  });

  it("blocks approval while verification fails or constraints are unresolved", () => {
    expect(isProposalApprovable(proposal({ state: "blocked" })).ok).toBe(false);
    expect(isProposalApprovable(proposal({ state: "ready" })).ok).toBe(true);
    expect(isProposalApprovable(proposal({ state: "approved" })).ok).toBe(false);
  });

  it("default board layout exposes every panel exactly once", () => {
    expect(DEFAULT_BOARD_LAYOUT.order).toHaveLength(BOARD_PANELS.length);
    expect(new Set(DEFAULT_BOARD_LAYOUT.order).size).toBe(BOARD_PANELS.length);
    for (const p of BOARD_PANELS) {
      expect(DEFAULT_BOARD_LAYOUT.visible[p.id]).toBe(true);
    }
  });
});
