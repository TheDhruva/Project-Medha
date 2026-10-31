import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CommitDetailsPanel } from "./CommitDetailsPanel";
import type { CommitDetail, HistoryCommit, RunSummary } from "@/lib/api/client";

function makeCommit(partial: Partial<HistoryCommit>): HistoryCommit {
  return {
    sha: "1234567890abcdef1234567890abcdef12345678",
    parents: ["abcdef1234567890abcdef1234567890abcdef12"],
    author: "Jane Doe <jane@example.com>",
    committed_at: "2026-10-20T10:00:00Z",
    message: "feat(auth): add oauth2 verification\n\nFull details about token verification.",
    branch: "main",
    github_url: "https://github.com/org/repo/commit/1234567",
    summary: "Refactored token checking",
    ...partial,
  };
}

function makeDetail(partial: Partial<CommitDetail>): CommitDetail {
  return {
    sha: "1234567890abcdef1234567890abcdef12345678",
    files: [
      { path: "src/auth/jwt.ts", added: 24, deleted: 5 },
      { path: "package.json", added: 2, deleted: 1 },
    ],
    added: 26,
    deleted: 6,
    truncated: false,
    github_url: "https://github.com/org/repo/commit/1234567",
    summary: "Auth module updated with jsonwebtoken dependency",
    ...partial,
  };
}

function makeRun(partial: Partial<RunSummary>): RunSummary {
  return {
    deployment_id: "dep_abc123456789",
    status: "completed",
    mode: "real",
    is_demo: false,
    label: null,
    scenario: null,
    repository_url: "https://github.com/org/repo",
    intent: null,
    base_revision: null,
    target_revision: "1234567890abcdef1234567890abcdef12345678",
    current_stage: "COMPLETE",
    created_at: "2026-10-20T10:05:00Z",
    updated_at: "2026-10-20T10:06:00Z",
    duration_seconds: 45,
    risk: null,
    result_kind: "success",
    error_summary: null,
    ...partial,
  };
}

describe("CommitDetailsPanel", () => {
  it("renders placeholder state when no commit is selected", () => {
    render(
      <CommitDetailsPanel
        projectId="prj_test"
        commit={null}
        run={null}
        detail={null}
        loading={false}
        error={null}
        onClose={vi.fn()}
        onSelectSha={vi.fn()}
      />,
    );

    expect(screen.getByTestId("commit-details-placeholder")).toBeInTheDocument();
    expect(screen.getByText("Commit Inspector")).toBeInTheDocument();
  });

  it("renders commit metadata, what changed, impact, assessment, files and deployment", () => {
    const commit = makeCommit({});
    const detail = makeDetail({});
    const run = makeRun({});
    const onClose = vi.fn();
    const onSelectSha = vi.fn();

    render(
      <CommitDetailsPanel
        projectId="prj_test"
        commit={commit}
        run={run}
        detail={detail}
        loading={false}
        error={null}
        onClose={onClose}
        onSelectSha={onSelectSha}
      />,
    );

    // Header info
    expect(screen.getByText("1234567")).toBeInTheDocument();
    expect(screen.getByText("feat(auth): add oauth2 verification")).toBeInTheDocument();
    expect(screen.getByText(/Jane Doe/)).toBeInTheDocument();

    // What Changed
    expect(screen.getByText("What Changed?")).toBeInTheDocument();
    expect(screen.getByText("2 changed files")).toBeInTheDocument();
    expect(screen.getByText("+26")).toBeInTheDocument();
    expect(screen.getByText("-6")).toBeInTheDocument();
    expect(screen.getByText("Auth module updated with jsonwebtoken dependency")).toBeInTheDocument();

    // Engineering Impact
    expect(screen.getByText("Engineering Impact")).toBeInTheDocument();
    expect(screen.getByText("Dependencies")).toBeInTheDocument();
    expect(screen.getByText("Security-sensitive")).toBeInTheDocument();

    // MEDHA Assessment
    expect(screen.getByText("MEDHA Assessment")).toBeInTheDocument();
    expect(screen.getByText("Assessment Complete")).toBeInTheDocument();
    expect(screen.getByText("Inspect run →")).toHaveAttribute(
      "href",
      "/projects/prj_test/runs/dep_abc123456789",
    );

    // Files Changed
    expect(screen.getByText("Files Changed (2)")).toBeInTheDocument();
    expect(screen.getByText("src/auth/jwt.ts")).toBeInTheDocument();
    expect(screen.getByText("package.json")).toBeInTheDocument();

    // Deployment
    expect(screen.getByText("Deployment")).toBeInTheDocument();
    expect(screen.getByText(/Deployment recorded for run dep_abc1234567/)).toBeInTheDocument();

    // Clicking parent SHA triggers onSelectSha
    const parentBtn = screen.getByText("abcdef1");
    fireEvent.click(parentBtn);
    expect(onSelectSha).toHaveBeenCalledWith("abcdef1234567890abcdef1234567890abcdef12");

    // Clicking Close calls onClose
    const closeBtn = screen.getByLabelText("Close commit details");
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it("handles unassessed commit gracefully", () => {
    const commit = makeCommit({});
    const detail = makeDetail({});

    render(
      <CommitDetailsPanel
        projectId="prj_test"
        commit={commit}
        run={null}
        detail={detail}
        loading={false}
        error={null}
        onClose={vi.fn()}
        onSelectSha={vi.fn()}
      />,
    );

    expect(screen.getByText("Not assessed yet")).toBeInTheDocument();
    expect(
      screen.getByText(/This commit has not been analyzed by MEDHA/i),
    ).toBeInTheDocument();
    expect(screen.getByText("No deployment attempted for this commit.")).toBeInTheDocument();
  });
});

