import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommitTimeline } from "@/components/workspace/CommitTimeline";
import * as client from "@/lib/api/client";

const mockCommits: client.HistoryCommit[] = [
  {
    sha: "a".repeat(40),
    parents: ["b".repeat(40)],
    author: "Ada Lovelace",
    committed_at: "2026-10-20T10:00:00Z",
    message: "Fix dependency vulnerability\n\nUpgrade express to 4.21.2",
    branch: "main",
    github_url: "https://github.com/example/app/commit/aaaaaaaa",
  },
  {
    sha: "b".repeat(40),
    parents: [],
    author: "Alan Turing",
    committed_at: "2026-10-19T10:00:00Z",
    message: "Initial commit",
    branch: "main",
    github_url: "https://github.com/example/app/commit/bbbbbbbb",
  },
];

const mockDetail: client.CommitDetail = {
  sha: "a".repeat(40),
  files: [
    { path: "package.json", added: 2, deleted: 2 },
    { path: "src/server.ts", added: 10, deleted: 1 },
  ],
  added: 12,
  deleted: 3,
  truncated: false,
  github_url: "https://github.com/example/app/commit/aaaaaaaa",
  summary: "Fix dependency vulnerability — +12/-3 across 2 file(s)",
};

const mockRuns: client.RunSummary[] = [
  {
    deployment_id: "dep_run_1",
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
];

describe("CommitTimeline", () => {
  it("renders commits and distinguishes assessed from unassessed commits", async () => {
    vi.spyOn(client, "fetchCommitHistory").mockResolvedValueOnce({
      project_id: "prj_test",
      commits: mockCommits,
      branches: ["main", "feature/auth"],
      partial: false,
      truncated: false,
      shallow: false,
    });

    render(
      <CommitTimeline
        projectId="prj_test"
        defaultBranch="main"
        runs={mockRuns}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Fix dependency vulnerability")).toBeInTheDocument();
      expect(screen.getByText("Initial commit")).toBeInTheDocument();
    });

    // Commit A is assessed (matches target_revision in mockRuns)
    expect(screen.getByText("Assessed")).toBeInTheDocument();

    // Commit B is unassessed
    expect(screen.getByText("Not assessed")).toBeInTheDocument();

    // Authors and SHAs
    expect(screen.getByText("Ada Lovelace")).toBeInTheDocument();
    expect(screen.getByText("Alan Turing")).toBeInTheDocument();
    expect(screen.getByText("aaaaaaa")).toBeInTheDocument();
    expect(screen.getByText("bbbbbbb")).toBeInTheDocument();
  });

  it("expands inline commit details on click", async () => {
    vi.spyOn(client, "fetchCommitHistory").mockResolvedValueOnce({
      project_id: "prj_test",
      commits: mockCommits,
      branches: ["main"],
      partial: false,
      truncated: false,
      shallow: false,
    });

    vi.spyOn(client, "fetchCommitDetail").mockResolvedValueOnce(mockDetail);

    render(
      <CommitTimeline
        projectId="prj_test"
        defaultBranch="main"
        runs={mockRuns}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Fix dependency vulnerability")).toBeInTheDocument();
    });

    // Click first commit to expand
    fireEvent.click(screen.getByLabelText(/^Commit aaaaaaa:/));

    await waitFor(() => {
      expect(screen.getByTestId("commit-detail-aaaaaaa")).toBeInTheDocument();
    });

    // What Changed section
    expect(screen.getByText("What Changed?")).toBeInTheDocument();
    expect(screen.getByText(/Upgrade express to 4.21.2/)).toBeInTheDocument();
    expect(screen.getByText(/2 changed files/)).toBeInTheDocument();
    expect(screen.getByText("+12")).toBeInTheDocument();
    expect(screen.getByText("-3")).toBeInTheDocument();

    // Impact section (identified Dependencies from package.json)
    expect(screen.getByText("Engineering Impact")).toBeInTheDocument();
    expect(screen.getByText("Dependencies")).toBeInTheDocument();

    // Files Changed section
    expect(screen.getByText("Files Changed (2)")).toBeInTheDocument();
    expect(screen.getByText("package.json")).toBeInTheDocument();
    expect(screen.getByText("src/server.ts")).toBeInTheDocument();

    // Assessment section
    expect(screen.getByText("MEDHA Assessment")).toBeInTheDocument();
    expect(screen.getByText("Assessment Complete")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Inspect run evidence/ })).toBeInTheDocument();
  });

  it("switches branches via the branch selector", async () => {
    const fetchSpy = vi.spyOn(client, "fetchCommitHistory").mockResolvedValue({
      project_id: "prj_test",
      commits: mockCommits,
      branches: ["main", "feature/auth"],
      partial: false,
      truncated: false,
      shallow: false,
    });

    render(
      <CommitTimeline
        projectId="prj_test"
        defaultBranch="main"
        runs={mockRuns}
      />,
    );

    await waitFor(() => {
      expect(screen.getByRole("combobox", { name: "Select branch" })).toBeInTheDocument();
    });

    fireEvent.change(screen.getByRole("combobox", { name: "Select branch" }), {
      target: { value: "feature/auth" },
    });

    expect(fetchSpy).toHaveBeenCalledWith("prj_test", expect.objectContaining({
      branch: "feature/auth",
    }));
  });
});

