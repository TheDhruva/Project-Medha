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

describe("workspace demo layer", () => {
  it("covers all ten required demo scenarios exactly once", () => {
    const keys = SEED_PROJECTS.map((p) => p.scenarioKey).sort();
    expect(keys).toEqual([
      "empty-evaluations", "empty-workspace", "failed-scoped-recovery",
      "interrupted-run", "populated-multi-run", "proposal-blocked",
      "proposal-ready", "simulated-success", "superseded-proposal",
      "verification-failure",
    ].sort());
    // every run belongs to a known project
    const ids = new Set(SEED_PROJECTS.map((p) => p.id));
    for (const run of SEED_RUNS) {
      expect(ids.has(run.projectId)).toBe(true);
      expect(run.summary.length).toBeGreaterThan(10);
    }
  });

  it("never mixes projects: proposals reference existing projects", () => {
    const ids = new Set(SEED_PROJECTS.map((p) => p.id));
    for (const p of SEED_PROPOSALS) {
      expect(ids.has(p.projectId)).toBe(true);
    }
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

  it("evaluation fixtures stay honest: empty vs populated", () => {
    expect(evalFor("proj-evalempty").status).toBe("empty");
    const metro = evalFor("proj-metro");
    expect(metro.status).toBe("complete");
    expect(metro.results.length).toBeGreaterThanOrEqual(2);
    expect(metro.note).toMatch(/same|comparable|definitions/i);
  });
});
