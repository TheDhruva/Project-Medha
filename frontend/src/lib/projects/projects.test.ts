import { describe, expect, it } from "vitest";

import type { RunSummary } from "@/lib/api/client";
import {
  deriveProjects,
  filterProjects,
  projectHealth,
  projectIdForRepo,
  repoForProjectId,
  shortNameForRepo,
} from "@/lib/projects/projects";
import { derivePipeline, summarizeVerification } from "@/lib/projects/useProjectData";

function run(overrides: Partial<RunSummary> & { deployment_id: string }): RunSummary {
  return {
    status: "completed",
    mode: "demo",
    is_demo: true,
    label: "DEMO/MOCK",
    scenario: "PORT_CONFLICT",
    repository_url: "https://github.com/example/app",
    intent: null,
    base_revision: null,
    target_revision: null,
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

describe("project identity", () => {
  it("round-trips repository URLs through project ids", () => {
    const repo = "https://github.com/example/my-app";
    expect(repoForProjectId(projectIdForRepo(repo))).toBe(repo);
  });

  it("rejects malformed project ids", () => {
    expect(repoForProjectId("%E0%A4%A")).toBeNull();
  });

  it("derives short names from URLs and paths", () => {
    expect(shortNameForRepo("https://github.com/example/my-app.git")).toBe("my-app");
    expect(shortNameForRepo("C:/src/sample-app")).toBe("sample-app");
  });
});

describe("deriveProjects", () => {
  it("groups runs by exact repository URL", () => {
    const runs = [
      run({ deployment_id: "dep_1", repository_url: "https://github.com/example/a" }),
      run({ deployment_id: "dep_2", repository_url: "https://github.com/example/a", status: "failed", error_summary: "boom" }),
      run({ deployment_id: "dep_3", repository_url: "https://github.com/example/b" }),
    ];
    const projects = deriveProjects(runs);
    expect(projects).toHaveLength(2);
    const a = projects.find((p) => p.repositoryUrl === "https://github.com/example/a");
    expect(a?.totalRuns).toBe(2);
    expect(a?.failedRuns).toBe(1);
  });

  it("flags attention only from real backend state", () => {
    const healthy = deriveProjects([run({ deployment_id: "dep_1" })]);
    expect(healthy[0]?.attention).toEqual([]);
    expect(projectHealth(healthy[0]!)).toBe("healthy");

    const failed = deriveProjects([
      run({ deployment_id: "dep_1", status: "failed", error_summary: "gate failed" }),
    ]);
    expect(failed[0]?.attention.length).toBeGreaterThan(0);
    expect(projectHealth(failed[0]!)).toBe("attention");

    const awaiting = deriveProjects([
      run({ deployment_id: "dep_1", status: "awaiting_approval" }),
    ]);
    expect(projectHealth(awaiting[0]!)).toBe("attention");
  });

  it("filters by query and health without inventing projects", () => {
    const projects = deriveProjects([
      run({ deployment_id: "dep_1", repository_url: "https://github.com/example/atlas" }),
      run({ deployment_id: "dep_2", repository_url: "https://github.com/example/bore", status: "failed" }),
    ]);
    expect(filterProjects(projects, "atlas", "all")).toHaveLength(1);
    expect(filterProjects(projects, "", "attention")).toHaveLength(1);
    expect(filterProjects(projects, "", "healthy")).toHaveLength(1);
    expect(filterProjects(projects, "missing", "all")).toHaveLength(0);
  });
});

describe("summarizeVerification", () => {
  it("returns null when no artifact exists", () => {
    expect(summarizeVerification(null)).toBeNull();
  });

  it("reads the backend to_ui shape", () => {
    const summary = summarizeVerification({
      passed: false,
      score: 40,
      checks: [
        { id: "a", name: "A", status: "pass", message: "ok" },
        { id: "b", name: "B", status: "fail", message: "bad" },
      ],
      blocking_failures: ["B failed"],
      summary: "Verification failed. Execution is blocked.",
    });
    expect(summary?.passed).toBe(false);
    expect(summary?.total).toBe(2);
    expect(summary?.failed).toBe(1);
    expect(summary?.blocking).toEqual(["B failed"]);
  });
});

describe("derivePipeline", () => {
  it("marks backend NEGOTIATE as the CNP step", () => {
    const stages = derivePipeline(
      [
        { ts: "t", level: "info", source: "system", message: "PREFLIGHT completed", type: "stage.completed", stage: "PREFLIGHT", status: "success", is_demo: true },
        { ts: "t", level: "info", source: "system", message: "Conflict resolved", type: "negotiation.resolved", stage: "NEGOTIATE", status: "success", is_demo: true },
      ],
      "VERIFY",
      "running",
    );
    const byId = Object.fromEntries(stages.map((s) => [s.id, s.state]));
    expect(byId.preflight).toBe("done");
    expect(byId.cnp).toBe("done");
    expect(byId.verify).toBe("active");
    expect(byId.execute).toBe("idle");
  });

  it("marks the reported current stage blocked on failure", () => {
    const stages = derivePipeline([], "VERIFY", "failed");
    const byId = Object.fromEntries(stages.map((s) => [s.id, s.state]));
    // current_stage comes from the backend record, so it is evidence.
    expect(byId.verify).toBe("blocked");
    expect(byId.execute).toBe("idle");
  });
});
