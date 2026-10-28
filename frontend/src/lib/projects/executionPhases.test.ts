import { describe, expect, it } from "vitest";
import { derivePhaseStates } from "@/lib/projects/executionPhases";
import type { RunSummary } from "@/lib/api/client";
import type { PipelineStage } from "@/lib/projects/useProjectData";

const IDS = ["preflight", "analyze", "plan", "cnp", "verify", "execute"] as const;

function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    deployment_id: "dep_1",
    status: "failed",
    mode: "real",
    is_demo: false,
    execution_mode: "real",
    label: null,
    scenario: null,
    repository_url: "https://github.com/vercel/next.js",
    intent: null,
    base_revision: null,
    target_revision: null,
    current_stage: "COMPLETE",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:01:00Z",
    duration_seconds: null,
    risk: null,
    result_kind: "failed",
    error_summary: null,
    ...overrides,
  } as RunSummary;
}

function makeStages(
  overrides: Partial<Record<string, Partial<PipelineStage>>> = {},
): PipelineStage[] {
  return IDS.map((id) => ({
    id,
    label: id,
    state: "idle" as const,
    ...overrides[id],
  }));
}

describe("derivePhaseStates — authoritative backend snapshot", () => {
  it("prefers the persisted run.phases over inference on a terminal run", () => {
    // Clone failure: Preflight finished, Analyze failed, everything after
    // was never reached. Stages carry no evidence — the snapshot alone
    // must produce the whole picture.
    const run = makeRun({
      status: "failed",
      error_code: "GIT.CHECKOUT_FAILED",
      phases: [
        { id: "preflight", status: "completed" },
        { id: "analyze", status: "failed", reason: "Clone failed: Filename too long" },
        { id: "plan", status: "blocked", reason: "Analyze failed first" },
        { id: "cnp", status: "blocked", reason: "Analyze failed first" },
        { id: "verify", status: "blocked", reason: "Analyze failed first" },
        { id: "execute", status: "blocked", reason: "Analyze failed first" },
      ],
    });

    const states = derivePhaseStates({ run, stages: [], hydrating: false });
    expect(states.preflight).toBe("completed");
    expect(states.analyze).toBe("failed");
    expect(states.plan).toBe("blocked");
    expect(states.cnp).toBe("blocked");
    expect(states.verify).toBe("blocked");
    expect(states.execute).toBe("blocked");
  });

  it("distinguishes skipped (reached-gate) from blocked (never reached)", () => {
    const run = makeRun({
      status: "failed",
      error_code: "NO_DEPLOYABLE_APP",
      phases: [
        { id: "preflight", status: "completed" },
        { id: "analyze", status: "completed" },
        { id: "plan", status: "skipped", reason: "No deployable app" },
        { id: "cnp", status: "skipped", reason: "No deployable app" },
        { id: "verify", status: "skipped", reason: "No deployable app" },
        { id: "execute", status: "skipped", reason: "No deployable app" },
      ],
    });

    const states = derivePhaseStates({ run, stages: [], hydrating: false });
    expect(states.analyze).toBe("completed");
    expect(states.plan).toBe("skipped");
    expect(states.execute).toBe("skipped");
    expect(states.plan).not.toBe("blocked");
  });

  it("ignores a phase snapshot while the run is still live", () => {
    const run = makeRun({
      status: "running",
      phases: [{ id: "preflight", status: "completed" }],
    });
    const states = derivePhaseStates({ run, stages: [], hydrating: false });
    // No stage evidence yet: honest unknown, not a frozen terminal snapshot.
    expect(states.preflight).toBe("unknown");
    expect(states.execute).toBe("unknown");
  });

  it("falls back to stage inference when the snapshot is incomplete", () => {
    const run = makeRun({
      status: "failed",
      phases: [{ id: "preflight", status: "completed" }], // missing the rest
    });
    const states = derivePhaseStates({
      run,
      stages: makeStages({
        preflight: { state: "done" },
        analyze: { state: "blocked", reason: "failure" },
      }),
      hydrating: false,
    });
    expect(states.preflight).toBe("completed");
    expect(states.analyze).toBe("failed");
    // After the failure point, inference says "waiting" — never "done".
    expect(states.plan).toBe("waiting");
    expect(states.plan).not.toBe("completed");
  });
});
