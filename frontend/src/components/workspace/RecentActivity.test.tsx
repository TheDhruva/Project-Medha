import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecentActivity } from "@/components/workspace/RecentActivity";
import type { RunSummary } from "@/lib/api/client";

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

describe("RecentActivity", () => {
  it("renders meaningful operational events from recorded runs", () => {
    const runs: RunSummary[] = [
      mockRun({
        deployment_id: "dep_success",
        status: "completed",
        result_kind: "success",
        target_revision: "a".repeat(40),
        duration_seconds: 30,
      }),
      mockRun({
        deployment_id: "dep_fail",
        status: "failed",
        result_kind: "failed",
        error_summary: "Build timeout",
        target_revision: "b".repeat(40),
      }),
    ];

    render(<RecentActivity projectId="prj_test" runs={runs} />);

    expect(screen.getByText("Recent Activity")).toBeInTheDocument();
    expect(screen.getByText("View all activity")).toBeInTheDocument();

    // Succeeded run event
    expect(screen.getByText("Deployment completed")).toBeInTheDocument();
    expect(screen.getByText("(commit aaaaaaa · 30s)")).toBeInTheDocument();

    // Failed run event
    expect(screen.getByText("Failed: Build timeout")).toBeInTheDocument();
  });

  it("renders empty state notice when no runs exist", () => {
    render(<RecentActivity projectId="prj_test" runs={[]} />);
    expect(screen.getByText("No operational activity recorded yet.")).toBeInTheDocument();
  });
});

