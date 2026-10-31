import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EngineeringMetrics } from "@/components/workspace/EngineeringMetrics";
import type { RunHealth, RunSummary } from "@/lib/api/client";

function mockRun(partial: Partial<RunSummary>): RunSummary {
  return {
    deployment_id: "dep_1",
    status: "completed",
    mode: "real",
    is_demo: false,
    label: null,
    scenario: null,
    repository_url: "https://github.com/example/app",
    intent: null,
    base_revision: null,
    target_revision: "a".repeat(40),
    current_stage: "COMPLETE",
    created_at: "2026-10-20T10:00:00Z",
    updated_at: "2026-10-20T10:01:00Z",
    duration_seconds: 42,
    risk: null,
    result_kind: "success",
    error_summary: null,
    ...partial,
  };
}

describe("EngineeringMetrics", () => {
  it("accurately computes unique assessed commits and open findings breakdown", () => {
    const runs: RunSummary[] = [
      mockRun({ deployment_id: "dep_1", target_revision: "a".repeat(40), status: "completed" }),
      mockRun({ deployment_id: "dep_2", target_revision: "a".repeat(40), status: "completed" }), // duplicate SHA
      mockRun({ deployment_id: "dep_3", target_revision: "b".repeat(40), status: "completed" }),
      mockRun({ deployment_id: "dep_4", target_revision: "c".repeat(40), status: "failed", result_kind: "failed" }),
    ];

    const findings = [
      { id: "f1", tone: "error" as const, title: "Hardcoded secret" },
      { id: "f2", tone: "warning" as const, title: "Outdated package" },
    ];

    const health: RunHealth = {
      deployment_id: "dep_1",
      is_demo: false,
      health_status: "healthy",
      checked_at: "2026-10-20T10:01:00Z",
      source: "probe",
      reason: null,
      execution_mode: "real",
    };

    render(
      <EngineeringMetrics
        runs={runs}
        findings={findings}
        verification={{
          passed: true,
          score: 95,
          total: 5,
          failed: 0,
          passedCount: 5,
          assessed: 5,
          warnings: 0,
          pending: 0,
          summary: "All checks passed",
          blocking: [],
        }}
        health={health}
      />,
    );

    const root = screen.getByTestId("engineering-metrics");

    // 2 unique assessed commits (SHA a and b; c failed)
    expect(within(root).getByText("Commits Assessed")).toBeInTheDocument();
    expect(within(root).getByText("commits")).toBeInTheDocument();
    expect(within(root).getByText("Across 4 runs")).toBeInTheDocument();

    // 2 open findings: 1 critical, 1 warning
    expect(within(root).getByText("Open Findings")).toBeInTheDocument();
    expect(within(root).getByText("1 critical · 1 warning")).toBeInTheDocument();

    // Latest verification passed
    expect(within(root).getByText("Latest Verification")).toBeInTheDocument();
    expect(within(root).getByText("Passed")).toBeInTheDocument();

    // Deployment health
    expect(within(root).getByText("Deployment Health")).toBeInTheDocument();
    expect(within(root).getByText("Healthy")).toBeInTheDocument();
  });

  it("handles empty or not-assessed states without fabricating numbers", () => {
    render(
      <EngineeringMetrics
        runs={[]}
        findings={[]}
        verification={null}
        health={null}
      />,
    );

    const root = screen.getByTestId("engineering-metrics");
    expect(within(root).getByText("No recorded runs")).toBeInTheDocument();
    expect(within(root).getByText("Clean assessment")).toBeInTheDocument();
    expect(within(root).getByText("Not verified")).toBeInTheDocument();
    expect(within(root).getByText("Not deployed")).toBeInTheDocument();
  });
});
