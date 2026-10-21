import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RepositorySummaryBlock } from "@/components/workspace/RepositorySummaryBlock";
import type { RepositorySummary } from "@/lib/api/client";

const summary: RepositorySummary = {
  status: "available",
  text: "A small Node service that exposes a JSON API for tasks.",
  source: "deterministic",
  commit_sha: "a".repeat(40),
  generated_at: "2026-10-01T10:00:00Z",
  technologies: ["node", "python-fastapi"],
};

function renderBlock(overrides: Partial<Parameters<typeof RepositorySummaryBlock>[0]> = {}) {
  return render(
    <RepositorySummaryBlock
      summary={null}
      revision={null}
      stale={false}
      loading={false}
      analyzing={false}
      {...overrides}
    />,
  );
}

describe("RepositorySummaryBlock", () => {
  it("shows a loading placeholder while the project loads", () => {
    renderBlock({ loading: true });
    expect(screen.getByRole("status")).toHaveTextContent("Reading repository summary");
  });

  it("shows an explicit unavailable state", () => {
    renderBlock();
    expect(screen.getByText("Summary unavailable for this revision.")).toBeInTheDocument();
  });

  it("renders the summary text and reliable stack labels", () => {
    renderBlock({ summary, revision: summary.commit_sha });
    expect(screen.getByText(summary.text!)).toBeInTheDocument();
    expect(screen.getByText(/node · python-fastapi/)).toBeInTheDocument();
    expect(screen.queryByText(/AI-assisted/)).not.toBeInTheDocument();
  });

  it("shows the AI indicator only for an AI-assisted summary", () => {
    renderBlock({ summary: { ...summary, source: "ai" }, revision: summary.commit_sha });
    expect(screen.getByText(/AI-assisted/)).toBeInTheDocument();
  });

  it("labels a summary from an earlier revision", () => {
    renderBlock({
      summary: { ...summary, status: "stale", commit_sha: "a".repeat(40) },
      revision: "a".repeat(40),
      stale: true,
    });
    expect(screen.getByText(/Earlier revision aaaaaaa/)).toBeInTheDocument();
  });
});
