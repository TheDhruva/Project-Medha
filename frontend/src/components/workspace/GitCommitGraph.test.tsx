import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { GitCommitGraph } from "./GitCommitGraph";
import * as apiClient from "@/lib/api/client";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    fetchCommitHistory: vi.fn(),
    fetchCommitDetail: vi.fn(),
  };
});

const mockCommits: apiClient.HistoryCommit[] = [
  {
    sha: "1111111111111111111111111111111111111111",
    parents: ["2222222222222222222222222222222222222222"],
    author: "Alice <alice@example.com>",
    committed_at: "2026-10-22T10:00:00Z",
    message: "feat: add secure ingress",
    branch: "main",
    github_url: "https://github.com/org/repo/commit/1111111",
    summary: "Added nginx ingress",
  },
  {
    sha: "2222222222222222222222222222222222222222",
    parents: [],
    author: "Bob <bob@example.com>",
    committed_at: "2026-10-21T10:00:00Z",
    message: "chore: init workspace",
    branch: "main",
    github_url: "https://github.com/org/repo/commit/2222222",
    summary: "Repository setup",
  },
];

describe("GitCommitGraph", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.fetchCommitHistory).mockResolvedValue({
      project_id: "prj_test",
      commits: mockCommits,
      branches: ["main", "feature/auth"],
      partial: false,
      truncated: false,
      shallow: false,
    });
    vi.mocked(apiClient.fetchCommitDetail).mockResolvedValue({
      sha: "1111111111111111111111111111111111111111",
      files: [{ path: "docker-compose.yml", added: 12, deleted: 0 }],
      added: 12,
      deleted: 0,
      truncated: false,
      github_url: "https://github.com/org/repo/commit/1111111",
      summary: "Added ingress service",
    });
  });

  it("renders graph container, header, branch selector, and refresh button", async () => {
    render(
      <GitCommitGraph
        projectId="prj_test"
        defaultBranch="main"
        runs={[]}
      />,
    );

    expect(screen.getByTestId("commit-graph")).toBeInTheDocument();
    expect(screen.getByText("Commit History")).toBeInTheDocument();
    expect(screen.getByText("Ancestry, branching, and assessment graph")).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByLabelText("Select branch")).toBeInTheDocument();
    });

    // Check branch options
    expect(screen.getByRole("option", { name: "main" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "feature/auth" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "All branches" })).toBeInTheDocument();

    // Check commit stats
    expect(screen.getByText(/2 commits rendered/)).toBeInTheDocument();
  });

  it("changes branch when user selects a different branch", async () => {
    render(
      <GitCommitGraph
        projectId="prj_test"
        defaultBranch="main"
        runs={[]}
      />,
    );

    await waitFor(() => {
      expect(screen.getByLabelText("Select branch")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByLabelText("Select branch"), {
      target: { value: "feature/auth" },
    });

    expect(apiClient.fetchCommitHistory).toHaveBeenCalledWith("prj_test", {
      branch: "feature/auth",
      limit: 30,
      refresh: false,
    });
  });
});
