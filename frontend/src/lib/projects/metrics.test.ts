import { describe, expect, it } from "vitest";
import type { ExecutionReadiness, RunSummary, ScoresResponse } from "@/lib/api/client";
import { deriveFindings, deriveScorecards, scoreTone } from "@/lib/projects/metrics";

function run(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    deployment_id: "dep_1",
    status: "failed",
    mode: "real",
    is_demo: false,
    repository_url: "https://github.com/example/app",
    intent: null,
    base_revision: null,
    target_revision: null,
    current_stage: "COMPLETE",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:01:00Z",
    duration_seconds: 60,
    risk: null,
    result_kind: "failed",
    error_summary: null,
    ...overrides,
  } as RunSummary;
}

function readiness(overrides: Partial<ExecutionReadiness> = {}): ExecutionReadiness {
  return {
    status: "blocked",
    mode: "auto",
    reason_code: "EXECUTION_NOT_CONFIGURED",
    message: "Execution is not configured. Set MEDHA_EXECUTOR_MODE=simulator and restart.",
    simulated: false,
    requires_operator: true,
    restart_required: true,
    next_actions: ["Set MEDHA_EXECUTOR_MODE=simulator", "Restart the backend"],
    ...overrides,
  };
}

const NO_SUMMARY = null;

function productScore(overrides: Record<string, unknown> = {}) {
  return {
    value: 82,
    version: "scores-v2",
    computed_at: "2026-01-01T00:01:00Z",
    inputs_hash: "abc",
    target_sha: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    evidence: {
      top_finding: "1 high-severity static-analysis finding",
      coverage: { assessed: 2, applicable: 3, ratio: 0.67 },
      checks: [
        {
          id: "static_analysis",
          title: "Static analysis",
          status: "failed",
          severity: "high",
          finding: "1 high-severity static-analysis finding",
          evidence_source: "scanner:semgrep",
          score_impact: 20,
        },
      ],
    },
    ...overrides,
  };
}

function scoresResponse(overrides: Record<string, unknown> = {}): ScoresResponse {
  return {
    deployment_id: "dep_1",
    is_demo: false,
    label: null,
    scores: {
      code_quality: productScore(),
      security: productScore({ value: 78, evidence: { top_finding: "1 high-severity finding", coverage: { assessed: 3, applicable: 4 } } }),
      verification_confidence: productScore({ value: 95, evidence: { top_finding: "1 warning reduced this score", coverage: { assessed: 9, applicable: 9 } } }),
      deployment_readiness: productScore({
        value: null,
        evidence: { reason: "health evidence is unavailable", coverage: { assessed: 3, applicable: 5 } },
      }),
    },
    ...overrides,
  } as ScoresResponse;
}

describe("deriveScorecards", () => {
  it("maps backend-owned scores and evidence to the four cards", () => {
    const cards = deriveScorecards({
      run: run({ status: "completed" }),
      scores: scoresResponse(),
      projectId: "prj_1",
    });
    const byId = Object.fromEntries(cards.map((c) => [c.id, c]));
    expect(cards).toHaveLength(4);
    expect(byId["code-quality"].value).toBe(82);
    expect(byId["code-quality"].evidence).toContain("high-severity");
    expect(byId["code-quality"].status).toBe("critical");
    expect(byId["code-quality"].coverage).toEqual({ assessed: 2, applicable: 3 });
    expect(byId.security.value).toBe(78);
    expect(byId.verification.value).toBe(95);
    expect(byId.readiness.value).toBeNull();
    expect(byId.readiness.status).toBe("not_assessed");
    expect(byId.readiness.evidence).toContain("health evidence is unavailable");
    expect(byId.security.revision).toBe("deadbeef");
    expect(byId["code-quality"].href).toContain("run=dep_1");
    expect(byId.readiness.href).toContain("/runs/dep_1");
  });

  it("never falls back to critic/verification when the score snapshot is missing", () => {
    const cards = deriveScorecards({
      run: run(),
      verification: { passed: true, score: 100, checks: [{ status: "pass" }] },
      critic: { breakdown: { completeness: 100 } },
      scores: null,
      projectId: "prj_1",
    });
    for (const card of cards) {
      expect(card.value).toBeNull();
      expect(card.status).toBe("not_assessed");
      expect(card.evidence.length).toBeGreaterThan(0);
    }
  });

  it("shows each project's own scores without cross-project reuse", () => {
    const first = deriveScorecards({
      run: run({ deployment_id: "dep_1", target_revision: "a".repeat(40) }),
      scores: scoresResponse(),
      projectId: "prj_1",
    });
    const second = deriveScorecards({
      run: run({ deployment_id: "dep_2", target_revision: "b".repeat(40) }),
      scores: {
        ...scoresResponse(),
        deployment_id: "dep_2",
        scores: {
          code_quality: productScore({ value: 31, target_sha: "b".repeat(40) }),
          security: productScore({ value: 12, target_sha: "b".repeat(40) }),
          verification_confidence: productScore({ value: 44, target_sha: "b".repeat(40) }),
          deployment_readiness: productScore({ value: 20, target_sha: "b".repeat(40) }),
        },
      } as ScoresResponse,
      projectId: "prj_2",
    });
    const pick = (cards: ReturnType<typeof deriveScorecards>) =>
      Object.fromEntries(cards.map((c) => [c.id, c.value]));
    expect(pick(first)["code-quality"]).toBe(82);
    expect(pick(second)["code-quality"]).toBe(31);
    expect(pick(second).security).toBe(12);
    expect(first[0].href).toContain("/projects/prj_1/");
  });

  it("marks results from another revision as stale", () => {
    const cards = deriveScorecards({
      run: run({ target_revision: "c".repeat(40) }),
      scores: scoresResponse(),
      projectId: "prj_1",
    });
    const code = cards.find((c) => c.id === "code-quality");
    expect(code?.stale).toBe(true);
    expect(code?.status).toBe("stale");
    expect(code?.statusLabel).toBe("Stale assessment");
  });

  it("labels demo runs on every card", () => {
    const cards = deriveScorecards({
      run: run({ is_demo: true }),
      scores: scoresResponse({ is_demo: true }),
      projectId: "prj_1",
    });
    expect(cards.every((c) => c.isDemo)).toBe(true);
  });
});

describe("scoreTone", () => {
  it("bands values and treats null as neutral", () => {
    expect(scoreTone(null)).toBe("neutral");
    expect(scoreTone(85)).toBe("success");
    expect(scoreTone(84)).toBe("warning");
    expect(scoreTone(60)).toBe("warning");
    expect(scoreTone(59)).toBe("danger");
  });
});

describe("deriveFindings", () => {
  const base = {
    readiness: null as ExecutionReadiness | null,
    verification: NO_SUMMARY,
    securityFailures: null as number | null,
    conflicts: 0,
    negotiationResolved: true,
    pendingApprovals: 0,
    projectId: "prj_1",
  };

  it("puts execution configuration blocks first with operator guidance", () => {
    const findings = deriveFindings({
      ...base,
      run: run({ error_code: "EXECUTION_NOT_CONFIGURED", error_summary: "not configured" }),
      readiness: readiness(),
      verification: {
        passed: true,
        score: 100,
        total: 5,
        failed: 0,
        passedCount: 5,
        assessed: 5,
        warnings: 0,
        pending: 0,
        summary: "Verification passed. Execution is allowed.",
        blocking: [],
      },
    });
    const first = findings[0];
    expect(first.id).toBe("execution-blocked");
    expect(first.action?.href).toBe("/settings");
    expect(first.note).toContain("backend restart required");
    expect(first.body).toContain("remain valid");
    // Verification passed → no false verification finding.
    expect(findings.some((f) => f.id === "verification-failed")).toBe(false);
  });

  it("flags target-selection failures with a settings action", () => {
    const findings = deriveFindings({
      ...base,
      run: run({ error_code: "MULTIPLE_APPS_REQUIRE_TARGET", error_summary: "pick one" }),
      readiness: null,
    });
    expect(findings[0].id).toBe("target-required");
    expect(findings[0].action?.href).toBe("/projects/prj_1/settings");
  });

  it("flags failed verification gates", () => {
    const findings = deriveFindings({
      ...base,
      run: run({ error_code: "VERIFICATION_FAILED" }),
      readiness: null,
      verification: {
        passed: false,
        score: 40,
        total: 2,
        failed: 1,
        passedCount: 1,
        assessed: 2,
        warnings: 0,
        pending: 0,
        summary: "Verification failed.",
        blocking: ["compose check failed"],
      },
    });
    expect(findings.map((f) => f.id)).toContain("verification-failed");
    const verification = findings.find((f) => f.id === "verification-failed");
    expect(verification?.body).toBe("compose check failed");
  });

  it("returns no findings for a clean run with everything ready", () => {
    const findings = deriveFindings({
      ...base,
      run: run({ status: "completed" }),
      readiness: readiness({ status: "ready", reason_code: "EXECUTOR_SIMULATOR_EXPLICIT", message: "ok" }),
      verification: {
        passed: true,
        score: 100,
        total: 3,
        failed: 0,
        passedCount: 3,
        assessed: 3,
        warnings: 0,
        pending: 0,
        summary: "ok",
        blocking: [],
      },
    });
    expect(findings).toEqual([]);
  });

  it("surfaces security failures and pending approvals as secondary findings", () => {
    const findings = deriveFindings({
      ...base,
      run: run({ status: "completed" }),
      readiness: null,
      securityFailures: 2,
      pendingApprovals: 1,
    });
    const ids = findings.map((f) => f.id);
    expect(ids).toContain("security-failures");
    expect(ids).toContain("pending-approvals");
  });
});
