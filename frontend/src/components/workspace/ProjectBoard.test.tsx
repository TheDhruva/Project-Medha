import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { projectData } = vi.hoisted(() => ({
  projectData: {
    projectId: "prj_test",
    project: {
      project_id: "prj_test",
      name: "Example App",
      provider: "github",
      repo_owner: "example",
      repo_name: "app",
      repository: "https://github.com/example/app",
      canonical_url: "https://github.com/example/app",
      branch: "main",
      visibility: "public",
      connection_status: "connected",
      created_at: "2026-10-20T09:00:00Z",
      updated_at: "2026-10-20T09:00:00Z",
    },
    repo: "https://github.com/example/app",
    name: "Example App",
    runs: [
      {
        deployment_id: "dep_latest_1234567890",
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
      },
      {
        deployment_id: "dep_previous_1234567890",
        status: "failed",
        mode: "real",
        is_demo: false,
        label: null,
        scenario: null,
        repository_url: "https://github.com/example/app",
        intent: null,
        base_revision: null,
        target_revision: "b".repeat(40),
        current_stage: "EXECUTE",
        created_at: "2026-10-19T10:00:00Z",
        updated_at: "2026-10-19T10:01:00Z",
        duration_seconds: 12,
        risk: null,
        result_kind: "failed",
        error_summary: "Execution failed",
      },
    ],
    loading: false,
    error: null,
    backendReachable: true,
    latest: null,
    selectedId: "dep_latest_1234567890",
    selectRun: vi.fn(),
    hydration: {
      logs: [],
      agents: null,
      executionMode: "real",
      constraints: [],
      negotiation: null,
      verification: null,
      critic: null,
      graph: { nodes: [], edges: [] },
      rollback: null,
      changeImpact: null,
      changeImpactLabel: null,
      changeImpactIsDemo: false,
      health: null,
      runtimeLogs: null,
    },
    hydrating: false,
    proposals: [],
    proposalsLoading: false,
    refresh: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/projects/useProjectData", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/projects/useProjectData");
  return { ...original, useProjectData: () => ({ ...projectData, latest: projectData.runs[0] }) };
});

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/api/client");
  return {
    ...original,
    fetchScores: vi.fn(() => new Promise(() => undefined)),
    fetchConfigStatus: vi.fn(() => new Promise(() => undefined)),
    fetchAssessmentSummary: vi.fn(() => new Promise(() => undefined)),
    fetchCommitHistory: vi.fn(() =>
      Promise.resolve({
        project_id: "prj_test",
        commits: [
          {
            sha: "a".repeat(40),
            parents: [],
            author: "Author",
            committed_at: "2026-10-20T10:00:00Z",
            message: "Add feature",
            branch: "main",
            github_url: null,
          },
        ],
        branches: ["main"],
        partial: false,
        truncated: false,
        shallow: false,
      }),
    ),
    fetchCommitDetail: vi.fn(() =>
      Promise.resolve({
        sha: "a".repeat(40),
        files: [],
        added: 0,
        deleted: 0,
        truncated: false,
        github_url: null,
        summary: "No diff",
      }),
    ),
  };
});

import { ProjectBoard } from "@/components/workspace/ProjectBoard";

afterEach(() => {
  projectData.selectedId = "dep_latest_1234567890";
});

describe("ProjectBoard header", () => {
  it("renders the project title, repository identity and branch without redundant summary", () => {
    render(<ProjectBoard projectId="prj_test" />);

    expect(screen.getByRole("heading", { level: 1, name: "Example App" })).toBeInTheDocument();
    expect(screen.getByText("example/app")).toBeInTheDocument();
    expect(screen.getAllByText("main").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/stale summary/i)).toBeNull();
  });

  it("renders deployment status and analysis status independently", () => {
    render(<ProjectBoard projectId="prj_test" />);

    const deployStatus = screen.getByTestId("deployment-status");
    expect(within(deployStatus).getByText(/deployment completed/i)).toBeInTheDocument();

    const analysisStatus = screen.getByTestId("analysis-status");
    expect(within(analysisStatus).getByText(/analysis complete/i)).toBeInTheDocument();
  });

  it("provides Run analysis and Deployment details actions in the header", () => {
    render(<ProjectBoard projectId="prj_test" />);

    const actions = screen.getByTestId("project-actions");
    expect(within(actions).getByRole("button", { name: "Run analysis" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Deployment details" })).toBeInTheDocument();

    // Opens deployment details popover on click
    fireEvent.click(within(actions).getByRole("button", { name: "Deployment details" }));
    expect(screen.getByRole("dialog", { name: "Deployment details" })).toBeInTheDocument();
  });
});

describe("ProjectBoard Phase 3 redesigned overview", () => {
  it("renders the full 5-level overview hierarchy and removes obsolete panels", async () => {
    render(<ProjectBoard projectId="prj_test" />);

    // 1. Four semicircular engineering scorecards
    expect(screen.getByLabelText("Run scorecards")).toBeInTheDocument();
    expect(screen.getByText("Code Quality")).toBeInTheDocument();
    expect(screen.getByText("Security Posture")).toBeInTheDocument();
    expect(screen.getByText("Verification")).toBeInTheDocument();
    expect(screen.getByText("Deployment Readiness")).toBeInTheDocument();

    // 2. Compact engineering metrics
    expect(screen.getByTestId("engineering-metrics")).toBeInTheDocument();
    expect(screen.getByText("Commits Assessed")).toBeInTheDocument();
    expect(screen.getByText("Open Findings")).toBeInTheDocument();
    expect(screen.getByText("Latest Verification")).toBeInTheDocument();
    expect(screen.getByText("Deployment Health")).toBeInTheDocument();

    // 3. Interactive Git commit graph
    expect(screen.getByTestId("commit-graph")).toBeInTheDocument();
    expect(screen.getByText("Commit History")).toBeInTheDocument();

    // 4. Recent activity is completely removed from the overview
    expect(screen.queryByTestId("recent-activity")).toBeNull();
    expect(screen.queryByText("Recent Activity")).toBeNull();

    // Obsolete overview panels remain completely removed:
    expect(screen.queryByText("Most important findings")).toBeNull();
    expect(screen.queryByText("Recent runs")).toBeNull();
    expect(screen.queryByText("Technical details")).toBeNull();
    expect(screen.queryByRole("list", { name: "Run Timeline phases" })).toBeNull();
  });
});
