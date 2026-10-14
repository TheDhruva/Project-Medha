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

describe("deriveScorecards", () => {
  const scores = {
    deployment_id: "dep_1",
    is_demo: false,
    label: null,
    scores: {
      security: {
        value: 78,
        version: "scores-v1",
        computed_at: "2026-01-01T00:01:00Z",
        inputs_hash: "abc",
        target_sha: "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
        evidence: { security_failures: 1, critic_security: 65 },
      },
      deployment_readiness: {
        value: null,
        version: "scores-v1",
        computed_at: "2026-01-01T00:01:00Z",
        inputs_hash: "abc",
        target_sha: null,
        evidence: { reason: "no verification evidence" },
      },
    },
  };

  it("maps artifacts to the four scorecards with real values", () => {
    const cards = deriveScorecards({
      run: run({ status: "completed" }),
      verification: {
        passed: true,
        score: 95,
        checks: [
          { status: "pass" },
          { status: "pass" },
          { status: "warning" },
        ],
      },
      critic: {
        breakdown: { completeness: 82 },
        recommendation: "WARN",
        findings: ["one"],
      },
      scores: scores as ScoresResponse,
      projectId: "prj_1",
    });
    const byId = Object.fromEntries(cards.map((c) => [c.id, c]));
    expect(cards).toHaveLength(4);
    expect(byId["code-quality"].value).toBe(82);
    expect(byId["code-quality"].evidence).toContain("WARN");
    expect(byId.verification.value).toBe(95);
    expect(byId.verification.evidence).toBe("2/3 checks passed · 1 warning");
    expect(byId.security.value).toBe(78);
    expect(byId.security.evidence).toContain("1 security failures");
    expect(byId.readiness.value).toBeNull();
    expect(byId.readiness.evidence).toContain("no verification evidence");
    expect(byId.security.revision).toBe("deadbeef");
  });

  it("reports unassessed when artifacts are missing — never 0 or 100", () => {
    const cards = deriveScorecards({
      run: run(),
      verification: null,
      critic: null,
      scores: null,
      projectId: "prj_1",
    });
    for (const card of cards) {
      expect(card.value).toBeNull();
      expect(card.evidence.length).toBeGreaterThan(0);
    }
    const byId = Object.fromEntries(cards.map((c) => [c.id, c]));
    expect(byId.verification.evidence).toContain("No verification artifact");
    expect(byId["code-quality"].evidence).toContain("not assessed");
  });

  it("labels demo runs on every card", () => {
    const cards = deriveScorecards({
      run: run({ is_demo: true }),
      verification: null,
      critic: null,
      scores: null,
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
