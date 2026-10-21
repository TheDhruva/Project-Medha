import { describe, expect, it } from "vitest";

import type { RepositorySummary, RunSummary } from "@/lib/api/client";
import { selectRepositorySummary } from "@/lib/projects/repositorySummary";

function summary(overrides: Partial<RepositorySummary> = {}): RepositorySummary {
  return {
    status: "available",
    text: "A small Node service that exposes a JSON API for tasks.",
    source: "deterministic",
    commit_sha: "a".repeat(40),
    generated_at: "2026-10-01T10:00:00Z",
    technologies: ["node"],
    ...overrides,
  };
}

function run(overrides: Partial<RunSummary> & { deployment_id: string }): RunSummary {
  return {
    status: "completed",
    mode: "real",
    is_demo: false,
    label: null,
    scenario: null,
    repository_url: "https://github.com/example/app",
    intent: null,
    base_revision: null,
    target_revision: "a".repeat(40),
    current_stage: null,
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:05:00Z",
    duration_seconds: 300,
    risk: null,
    result_kind: null,
    error_summary: null,
    ...overrides,
  };
}

describe("selectRepositorySummary", () => {
  it("returns unavailable when no run has a usable summary", () => {
    expect(selectRepositorySummary([])).toEqual({ summary: null, revision: null, stale: false });
    expect(
      selectRepositorySummary([
        run({ deployment_id: "dep_1", repository_summary: summary({ status: "unavailable", text: null }) }),
        run({ deployment_id: "dep_2", repository_summary: summary({ text: "   " }) }),
      ]),
    ).toEqual({ summary: null, revision: null, stale: false });
  });

  it("uses the newest valid summary for the latest revision", () => {
    const selected = selectRepositorySummary([
      run({ deployment_id: "dep_2", repository_summary: summary() }),
      run({ deployment_id: "dep_1", repository_summary: summary({ text: "older" }) }),
    ]);
    expect(selected.summary?.text).toContain("Node service");
    expect(selected.revision).toBe("a".repeat(40));
    expect(selected.stale).toBe(false);
  });

  it("keeps a prior summary while a newer analysis has none", () => {
    const selected = selectRepositorySummary([
      run({ deployment_id: "dep_2", status: "running", target_revision: null, repository_summary: undefined }),
      run({ deployment_id: "dep_1", repository_summary: summary() }),
    ]);
    expect(selected.summary?.text).toContain("Node service");
    expect(selected.stale).toBe(false);
  });

  it("marks a summary from another revision as stale", () => {
    const selected = selectRepositorySummary([
      run({ deployment_id: "dep_2", target_revision: "b".repeat(40), repository_summary: undefined }),
      run({ deployment_id: "dep_1", repository_summary: summary({ source: "ai" }) }),
    ]);
    expect(selected.summary?.source).toBe("ai");
    expect(selected.revision).toBe("a".repeat(40));
    expect(selected.stale).toBe(true);
  });
});
