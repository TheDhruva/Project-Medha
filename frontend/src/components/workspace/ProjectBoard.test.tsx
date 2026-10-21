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
  };
});

vi.mock("@/components/workspace/DashboardSections", async (importOriginal) => {
  const original =
    (await importOriginal()) as typeof import("@/components/workspace/DashboardSections");
  return {
    ...original,
    DeployHealthCard: () => null,
    EventsCard: () => null,
    FindingsStrip: () => null,
    LatestCommitCard: () => null,
    RepoIntelCard: () => null,
  };
});

import { ProjectBoard } from "@/components/workspace/ProjectBoard";

afterEach(() => {
  projectData.selectedId = "dep_latest_1234567890";
});

describe("ProjectBoard header", () => {
  it("removes the header Settings button and places Deployment details below Run analysis", () => {
    render(<ProjectBoard projectId="prj_test" />);

    const actions = screen.getByTestId("project-actions");
    expect(within(actions).queryByRole("link", { name: /^Settings$/ })).toBeNull();
    expect(within(actions).queryByRole("button", { name: /^Settings$/ })).toBeNull();

    const run = within(actions).getByRole("button", { name: "Run analysis" });
    const details = within(actions).getByRole("button", { name: "Deployment details" });
    expect(
      run.compareDocumentPosition(details) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(details.parentElement?.parentElement).toHaveClass("flex-col");
  });

  it("removes the permanent run selector and metadata strip", () => {
    render(<ProjectBoard projectId="prj_test" />);

    expect(screen.queryByLabelText("Run")).toBeNull();
    expect(screen.queryByText(/Open run/)).toBeNull();
    expect(screen.queryByRole("dialog", { name: "Deployment details" })).toBeNull();
  });

  it("opens deployment details from the compact trigger and keeps project tabs", () => {
    render(<ProjectBoard projectId="prj_test" />);

    expect(screen.getByRole("link", { name: "Runs" })).toHaveAttribute(
      "href",
      "/projects/prj_test/runs",
    );
    expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute(
      "href",
      "/projects/prj_test/settings",
    );

    fireEvent.click(screen.getByRole("button", { name: "Deployment details" }));
    expect(screen.getByRole("dialog", { name: "Deployment details" })).toBeInTheDocument();
  });

  it("clears phase details when the selected run changes", () => {
    const { rerender } = render(<ProjectBoard projectId="prj_test" />);
    const list = screen.getByRole("list", { name: "Execution pipeline phases" });
    fireEvent.click(within(list).getAllByRole("button")[0]);

    expect(screen.getByRole("button", { name: "Back to overview" })).toBeInTheDocument();
    projectData.selectedId = "dep_previous_1234567890";
    rerender(<ProjectBoard projectId="prj_test" />);

    expect(screen.getByText("Execution overview")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back to overview" })).not.toBeInTheDocument();
  });

  it("clears phase details when the project changes", () => {
    const { rerender } = render(<ProjectBoard projectId="prj_test" />);
    const list = screen.getByRole("list", { name: "Execution pipeline phases" });
    fireEvent.click(within(list).getAllByRole("button")[0]);

    expect(screen.getByRole("button", { name: "Back to overview" })).toBeInTheDocument();
    rerender(<ProjectBoard projectId="prj_other" />);

    expect(screen.getByText("Execution overview")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Back to overview" })).not.toBeInTheDocument();
  });
});
