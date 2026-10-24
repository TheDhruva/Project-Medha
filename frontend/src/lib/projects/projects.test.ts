import { describe, expect, it } from "vitest";

import type { RunSummary } from "@/lib/api/client";
import {
  canonicalRepoKey,
  conciseRepositorySummary,
  connectionLabel,
  deriveProjects,
  filterProjects,
  filterProjectsByStatus,
  formatActivityCompact,
  projectCardStatus,
  projectHealth,
  projectIdForRepo,
  repoForProjectId,
  shortNameForRepo,
  shortSha,
  sortProjects,
  summarizeRunFailure,
} from "@/lib/projects/projects";
import { derivePipeline, summarizeVerification } from "@/lib/projects/useProjectData";

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
    const quiet = deriveProjects([run({ deployment_id: "dep_1" })]);
    expect(quiet[0]?.attention).toEqual([]);
    // Completed is not healthy: without observed health-check evidence a
    // finished project is idle, never "healthy".
    expect(projectHealth(quiet[0]!)).toBe("idle");

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
    expect(filterProjects(projects, "missing", "all")).toHaveLength(0);
  });

  it("reports running projects as idle-free in-flight state, and search composes with filters", () => {
    const projects = deriveProjects([
      run({ deployment_id: "dep_1", repository_url: "https://github.com/example/atlas", status: "running" }),
      run({ deployment_id: "dep_2", repository_url: "https://github.com/example/bore", status: "failed" }),
    ]);
    expect(projectHealth(projects[0]!)).toBe("running");
    expect(projectHealth(projects[1]!)).toBe("attention");
    // "attention" shows only the failed project; search narrows further.
    expect(filterProjects(projects, "", "attention")).toHaveLength(1);
    expect(filterProjects(projects, "bore", "attention")).toHaveLength(1);
    expect(filterProjects(projects, "atlas", "attention")).toHaveLength(0);
  });
});

describe("deriveProjects canonical identity", () => {
  const project = {
    project_id: "prj_abc123",
    name: "Demo Service",
    provider: "github",
    repo_owner: "octo",
    repo_name: "demo",
    repository: "octo/demo",
    canonical_url: "https://github.com/octo/demo.git",
    branch: "main",
    visibility: "public",
    connection_status: "connected",
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
  };

  it("joins runs to their canonical project id", () => {
    const runs = [
      run({ deployment_id: "dep_1", repository_url: "https://github.com/octo/demo.git", project_id: "prj_abc123" }),
      run({ deployment_id: "dep_2", repository_url: "https://github.com/octo/demo.git", project_id: "prj_abc123", status: "failed", error_summary: "x" }),
    ];
    const summaries = deriveProjects(runs, [project]);
    expect(summaries).toHaveLength(1);
    expect(summaries[0]?.id).toBe("prj_abc123");
    expect(summaries[0]?.projectId).toBe("prj_abc123");
    expect(summaries[0]?.legacy).toBe(false);
    expect(summaries[0]?.name).toBe("Demo Service");
    expect(summaries[0]?.totalRuns).toBe(2);
  });

  it("keeps unclaimed runs as legacy URL groups without ownership", () => {
    const runs = [
      run({ deployment_id: "dep_1", repository_url: "https://github.com/octo/demo.git", project_id: "prj_abc123" }),
      run({ deployment_id: "dep_9", repository_url: "https://github.com/octo/other.git" }),
    ];
    const summaries = deriveProjects(runs, [project]);
    expect(summaries).toHaveLength(2);
    const legacy = summaries.find((p) => p.id !== "prj_abc123");
    expect(legacy?.legacy).toBe(true);
    expect(legacy?.projectId).toBeNull();
  });

  it("lists canonical projects with no runs yet", () => {
    const summaries = deriveProjects([], [project]);
    expect(summaries).toHaveLength(1);
    expect(summaries[0]?.totalRuns).toBe(0);
    expect(summaries[0]?.latest).toBeNull();
  });
});

describe("projectCardStatus / filterProjectsByStatus / sortProjects", () => {
  it("maps completed without implying health, and surfaces no-runs/running", () => {
    const completed = deriveProjects([run({ deployment_id: "dep_1" })]);
    expect(projectCardStatus(completed[0]!)).toBe("completed");
    const running = deriveProjects([
      run({ deployment_id: "dep_1", status: "running" }),
    ]);
    expect(projectCardStatus(running[0]!)).toBe("running");
    const failed = deriveProjects([
      run({ deployment_id: "dep_1", status: "failed", error_summary: "x" }),
    ]);
    expect(projectCardStatus(failed[0]!)).toBe("attention");
    const cancelled = deriveProjects([
      run({ deployment_id: "dep_1", status: "cancelled" }),
    ]);
    // Cancelled never reads as a quiet success.
    expect(projectCardStatus(cancelled[0]!)).toBe("attention");
  });

  it("multi-selects statuses and composes with trimmed case-insensitive search", () => {
    const projects = deriveProjects([
      run({ deployment_id: "dep_1", repository_url: "https://github.com/example/atlas" }),
      run({ deployment_id: "dep_2", repository_url: "https://github.com/example/bore", status: "failed", error_summary: "x" }),
      run({ deployment_id: "dep_3", repository_url: "https://github.com/example/cirrus", status: "running" }),
    ]);
    expect(filterProjectsByStatus(projects, "", [])).toHaveLength(3);
    expect(filterProjectsByStatus(projects, "", ["attention", "running"])).toHaveLength(2);
    expect(filterProjectsByStatus(projects, "  ATLAS ", ["completed"])).toHaveLength(1);
    expect(filterProjectsByStatus(projects, "bore", ["completed"])).toHaveLength(0);
    expect(filterProjectsByStatus(projects, "missing", [])).toHaveLength(0);
  });

  it("sorts deterministically by recent, name, and status", () => {
    const projects = deriveProjects([
      run({ deployment_id: "dep_1", repository_url: "https://github.com/example/beta", updated_at: "2026-10-01T10:00:00Z" }),
      run({ deployment_id: "dep_2", repository_url: "https://github.com/example/alpha", status: "failed", error_summary: "x", updated_at: "2026-10-02T10:00:00Z" }),
    ]);
    expect(sortProjects(projects, "recent")[0]?.repositoryUrl).toContain("alpha");
    expect(sortProjects(projects, "name")[0]?.repositoryUrl).toContain("alpha");
    // Attention sorts before completed regardless of recency.
    expect(sortProjects(projects, "status")[0]?.repositoryUrl).toContain("alpha");
  });
});

describe("deriveProjects demo exclusion", () => {
  it("excludes simulated runs from the Projects experience", () => {
    const summaries = deriveProjects([
      run({ deployment_id: "dep_1", is_demo: true, mode: "demo", label: "DEMO/MOCK" }),
    ]);
    expect(summaries).toHaveLength(0);
  });

  it("reports canonical projects with only demo runs as having no runs", () => {
    const project = {
      project_id: "prj_abc123",
      name: "Demo Service",
      provider: "github",
      repo_owner: "octo",
      repo_name: "demo",
      repository: "octo/demo",
      canonical_url: "https://github.com/octo/demo.git",
      branch: "main",
      visibility: "public",
      connection_status: "connected",
      created_at: "2026-10-01T10:00:00Z",
      updated_at: "2026-10-01T10:00:00Z",
    };
    const summaries = deriveProjects(
      [run({ deployment_id: "dep_1", is_demo: true, mode: "demo", project_id: "prj_abc123" })],
      [project],
    );
    expect(summaries).toHaveLength(1);
    expect(summaries[0]?.totalRuns).toBe(0);
    expect(summaries[0]?.latest).toBeNull();
    expect(summaries[0]?.repoOwner).toBe("octo");
    expect(summaries[0]?.repoName).toBe("demo");
    expect(summaries[0]?.branch).toBe("main");
  });
});

describe("deriveProjects card summary", () => {
  it("uses the recorded repository summary and drops missing-evidence fallback text", () => {
    const summaryRun = run({
      deployment_id: "dep_1",
      repository_summary: {
        status: "available",
        text: "A task tracker for small teams built with Next.js and FastAPI.",
        source: "ai",
        commit_sha: null,
        generated_at: "2026-10-01T10:00:00Z",
        technologies: ["Next.js", "FastAPI"],
      },
    });
    const withSummary = deriveProjects([summaryRun]);
    expect(withSummary[0]?.summary).toBe(
      "A task tracker for small teams built with Next.js and FastAPI.",
    );

    const fallback = deriveProjects([
      run({
        deployment_id: "dep_2",
        repository_summary: {
          status: "available",
          text: "Python repository with 1 detected application; no README description was available.",
          source: "deterministic",
          commit_sha: null,
          generated_at: "2026-10-01T10:00:00Z",
          technologies: ["Python"],
        },
      }),
    ]);
    expect(fallback[0]?.summary).toBeNull();
  });

  it("bounds summaries to a single short sentence", () => {
    const long = `${"word ".repeat(20)}end. Second sentence.`;
    expect(conciseRepositorySummary(long)?.split(" ").length).toBe(14);
    expect(conciseRepositorySummary("First sentence. Second sentence.")).toBe(
      "First sentence.",
    );
    expect(conciseRepositorySummary("")).toBeNull();
  });
});

describe("formatActivityCompact", () => {
  const now = new Date(2026, 9, 22, 12, 0);

  it("formats today, yesterday, and older activity in local time", () => {
    expect(
      formatActivityCompact(new Date(2026, 9, 22, 10, 35).toISOString(), now),
    ).toMatch(/^10:35\s?AM$/i);
    expect(
      formatActivityCompact(new Date(2026, 9, 21, 16, 30).toISOString(), now),
    ).toBe("Yesterday");
    expect(
      formatActivityCompact(new Date(2026, 9, 15, 11, 49).toISOString(), now),
    ).toBe("Oct 15");
  });

  it("includes the year only when it differs from the current year", () => {
    expect(
      formatActivityCompact(new Date(2025, 9, 15, 11, 49).toISOString(), now),
    ).toBe("Oct 15, 2025");
  });

  it("returns null instead of inventing a timestamp", () => {
    expect(formatActivityCompact(null, now)).toBeNull();
    expect(formatActivityCompact("not-a-date", now)).toBeNull();
  });
});

describe("canonicalRepoKey", () => {
  it("normalizes equivalent GitHub URL variants", () => {
    const keys = new Set(
      [
        "octo/demo",
        "https://github.com/octo/demo",
        "https://github.com/octo/demo.git",
        "https://github.com/octo/demo/",
        "https://github.com/OCTO/DEMO",
        "https://github.com/octo/demo/tree/main",
      ].map((u) => canonicalRepoKey(u)),
    );
    expect(keys).toEqual(new Set(["octo/demo"]));
  });

  it("rejects lookalike hosts and garbage", () => {
    expect(canonicalRepoKey("https://evilgithub.com/octo/demo")).toBeNull();
    expect(canonicalRepoKey("https://github.com.evil.com/octo/demo")).toBeNull();
    expect(canonicalRepoKey("C:/src/local")).toBeNull();
  });
});

describe("deriveProjects duplicate collapse", () => {
  const project = {
    project_id: "prj_abc123",
    name: "Demo Service",
    provider: "github",
    repo_owner: "octo",
    repo_name: "demo",
    repository: "octo/demo",
    canonical_url: "https://github.com/octo/demo.git",
    branch: "main",
    visibility: "public",
    connection_status: "connected",
    created_at: "2026-10-01T10:00:00Z",
    updated_at: "2026-10-01T10:00:00Z",
  };

  it("merges legacy URL-variant runs into the canonical card", () => {
    const summaries = deriveProjects(
      [
        run({ deployment_id: "dep_1", repository_url: "https://github.com/octo/demo" }),
        run({ deployment_id: "dep_2", repository_url: "https://github.com/OCTO/demo.git" }),
      ],
      [project],
    );
    expect(summaries).toHaveLength(1);
    expect(summaries[0]?.id).toBe("prj_abc123");
    expect(summaries[0]?.totalRuns).toBe(2);
  });

  it("groups legacy variants without a project into one card", () => {
    const summaries = deriveProjects([
      run({ deployment_id: "dep_1", repository_url: "https://github.com/octo/demo" }),
      run({ deployment_id: "dep_2", repository_url: "https://github.com/octo/demo.git" }),
    ]);
    expect(summaries).toHaveLength(1);
    expect(summaries[0]?.legacy).toBe(true);
  });
});

describe("shortSha / connectionLabel", () => {
  it("shortens only full 40-hex SHAs", () => {
    expect(shortSha("a".repeat(40))).toBe("aaaaaaa");
    expect(shortSha("abc123")).toBeNull();
    expect(shortSha(null)).toBeNull();
    expect(shortSha("")).toBeNull();
  });

  it("distinguishes connection states without implying run health", () => {
    expect(connectionLabel("connected")).toContain("Connected");
    expect(connectionLabel("pending")).toContain("pending");
    expect(connectionLabel("failed")).toContain("failed");
    expect(connectionLabel("disconnected")).toContain("Disconnected");
    expect(connectionLabel(null)).toBe("No runs yet");
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

  it("blocks the execute gate (not upstream) when execution was never configured", () => {
    const stages = derivePipeline(
      ["PREFLIGHT", "ANALYZE", "PLAN", "AGENTS", "NEGOTIATE", "VERIFY"].map((stage) => ({
        ts: "2026-01-01T00:00:00Z",
        level: "info",
        source: "system",
        message: `${stage} completed`,
        type: "stage.completed",
        stage,
        status: "success",
        is_demo: false,
      })),
      "COMPLETE",
      "failed",
      "EXECUTION_NOT_CONFIGURED",
    );
    const byId = Object.fromEntries(stages.map((s) => [s.id, s.state]));
    // Upstream stages stay done — only the unconfigured execute gate blocks.
    expect(byId.preflight).toBe("done");
    expect(byId.analyze).toBe("done");
    expect(byId.plan).toBe("done");
    expect(byId.cnp).toBe("done");
    expect(byId.verify).toBe("done");
    expect(byId.execute).toBe("blocked");
    expect(byId.recover).toBe("idle");
    const execute = stages.find((s) => s.id === "execute");
    expect(execute?.reason).toBe("config");
  });

  it("reports observed stage durations from started/completed pairs", () => {
    const stages = derivePipeline(
      [
        {
          ts: "2026-01-01T00:00:00.000Z",
          level: "info",
          source: "system",
          message: "PREFLIGHT started",
          type: "stage.started",
          stage: "PREFLIGHT",
          status: "running",
          is_demo: false,
        },
        {
          ts: "2026-01-01T00:00:05.000Z",
          level: "info",
          source: "system",
          message: "PREFLIGHT completed",
          type: "stage.completed",
          stage: "PREFLIGHT",
          status: "success",
          is_demo: false,
        },
      ],
      "ANALYZE",
      "running",
    );
    const byId = Object.fromEntries(stages.map((s) => [s.id, s]));
    expect(byId.preflight.durationMs).toBe(5000);
    expect(byId.preflight.state).toBe("done");
    expect(byId.analyze.state).toBe("active");
    expect(byId.execute.durationMs == null).toBe(true);
  });
});

describe("summarizeRunFailure", () => {
  it("prefixes the backend code in plain language", () => {
    expect(
      summarizeRunFailure({ error_code: "BUILD_FAILED", error_summary: "missing AUTH_KEY" }),
    ).toBe("Build failed: missing AUTH_KEY");
  });

  it("uses the first meaningful line and strips ANSI", () => {
    expect(
      summarizeRunFailure({
        error_code: null,
        error_summary: "\u001b[31mREADINESS_FAILED: probe timed out\u001b[0m\ndetails...",
      }),
    ).toBe("Application did not become ready: probe timed out");
  });

  it("never invents a cause when none was recorded", () => {
    expect(summarizeRunFailure({ error_code: "BUILD_TIMEOUT", error_summary: null })).toBe(
      "Build timed out.",
    );
    expect(summarizeRunFailure({ error_code: null, error_summary: null })).toBe(
      "No error summary was recorded.",
    );
  });

  it("does not duplicate an already-explicit summary", () => {
    expect(
      summarizeRunFailure({ error_code: "BUILD_FAILED", error_summary: "Build failed at Dockerfile line 4" }),
    ).toBe("Build failed at Dockerfile line 4");
  });
});
