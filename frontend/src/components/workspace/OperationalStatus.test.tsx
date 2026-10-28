import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { OperationalStatus } from "@/components/workspace/OperationalStatus";
import type { RunHealth, RunLogLine, RunSummary } from "@/lib/api/client";
import type { NegotiationView, RollbackSummary } from "@/lib/demo/types";
import type { PhaseId } from "@/lib/projects/executionPhases";
import type { PipelineStage, VerificationSummary } from "@/lib/projects/useProjectData";

const IDS = ["preflight", "analyze", "plan", "cnp", "verify", "execute"] as const;
const LABELS: Record<(typeof IDS)[number], string> = {
  preflight: "Preflight",
  analyze: "Analyze",
  plan: "Plan",
  cnp: "Negotiate (CNP)",
  verify: "Verify",
  execute: "Execute",
};

function makeRun(overrides: Partial<RunSummary> = {}): RunSummary {
  return {
    deployment_id: "dep_1",
    status: "completed",
    mode: "real",
    is_demo: false,
    execution_mode: "real",
    label: null,
    scenario: null,
    repository_url: "https://github.com/acme/app",
    intent: null,
    base_revision: null,
    target_revision: null,
    current_stage: "COMPLETE",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:01:00Z",
    duration_seconds: 60,
    risk: null,
    result_kind: "success",
    error_summary: null,
    ...overrides,
  };
}

function makeStages(overrides: Partial<Record<string, Partial<PipelineStage>>> = {}): PipelineStage[] {
  return IDS.map((id) => ({
    id,
    label: LABELS[id],
    state: "done" as const,
    durationMs: 2000,
    ...overrides[id],
  }));
}

function makeLog(
  stage: string | null,
  message: string,
  overrides: Partial<RunLogLine> = {},
): RunLogLine {
  return {
    ts: "2026-01-01T00:00:05Z",
    level: "info",
    source: stage ?? "system",
    message,
    type: "agent.activity",
    stage,
    status: null,
    is_demo: false,
    ...overrides,
  };
}

function summary(overrides: Partial<VerificationSummary> = {}): VerificationSummary {
  return {
    passed: true,
    score: 100,
    total: 3,
    failed: 0,
    passedCount: 3,
    assessed: 3,
    warnings: 0,
    pending: 0,
    summary: null,
    blocking: [],
    ...overrides,
  };
}

function renderStatus(props: {
  run?: RunSummary | null;
  stages?: PipelineStage[];
  logs?: RunLogLine[];
  hydrating?: boolean;
  health?: RunHealth | null;
  verification?: VerificationSummary | null;
  negotiation?: NegotiationView | null;
  rollback?: RollbackSummary | null;
  executionMode?: string | null;
  selectedPhase?: PhaseId | null;
  onClear?: () => void;
  onRetry?: (() => void) | null;
  retrying?: boolean;
} = {}) {
  return render(
    <OperationalStatus
      projectId="prj_1"
      run={props.run === undefined ? makeRun() : props.run}
      stages={props.stages ?? makeStages()}
      logs={props.logs ?? []}
      hydrating={props.hydrating ?? false}
      health={props.health ?? null}
      verification={props.verification === undefined ? summary() : props.verification}
      negotiation={props.negotiation ?? null}
      rollback={props.rollback ?? null}
      executionMode={props.executionMode === undefined ? "real" : props.executionMode}
      selectedPhase={props.selectedPhase ?? null}
      onClear={props.onClear ?? (() => undefined)}
      onRetry={props.onRetry ?? null}
      retrying={props.retrying ?? false}
    />
  );
}

function panel(): HTMLElement {
  return screen.getByRole("region", { name: "Operational status" });
}

describe("OperationalStatus", () => {
  it("shows a compact execution, application, and verification overview by default", () => {
    renderStatus({ run: makeRun({ status: "completed" }), verification: summary() });

    expect(within(panel()).getByText("Execution overview")).toBeInTheDocument();
    expect(within(panel()).getByText("All six phases completed.")).toBeInTheDocument();
    expect(within(panel()).getByText("Unknown")).toBeInTheDocument();
    expect(within(panel()).getByText(/No health probe was recorded/)).toBeInTheDocument();
    expect(within(panel()).getByText("Passed 3 of 3 assessed checks")).toBeInTheDocument();
    expect(within(panel()).getByRole("link", { name: "Verification details →" })).toHaveAttribute(
      "href",
      "/projects/prj_1/verification?run=dep_1",
    );
    expect(screen.queryByRole("region", { name: "Verify details" })).not.toBeInTheDocument();
  });

  it("does not treat a completed pipeline as a healthy application", () => {
    renderStatus({ run: makeRun({ status: "completed" }), health: null });

    const region = panel();
    expect(within(region).getByText("Unknown")).toBeInTheDocument();
    expect(within(region).getByText(/does not confirm a healthy application/)).toBeInTheDocument();
    expect(within(region).queryByText("Healthy")).not.toBeInTheDocument();
  });

  it("never reports Analyze failed when no failure-stage evidence exists", () => {
    renderStatus({
      run: makeRun({
        status: "failed",
        current_stage: "COMPLETE",
        result_kind: "failed",
        error_summary: null,
      }),
      stages: [],
      verification: null,
    });

    const region = panel();
    const text = region.textContent ?? "";
    expect(text).toContain("This run stopped before the failing stage was recorded");
    expect(text).toContain("dep_1"); // run reference is shown
    expect(text).not.toContain("Failed at Analyze");
    expect(text).not.toContain("Failed —");
    // No identifiable failed phase → the link goes straight to the
    // diagnosis section under its own label.
    expect(within(region).getByRole("link", { name: "View failure details →" })).toHaveAttribute(
      "href",
      "/projects/prj_1/runs/dep_1#diagnosis",
    );
  });

  it("shows no fabricated verification metrics when verification never ran", () => {
    renderStatus({
      run: makeRun({ status: "failed", result_kind: "failed", error_summary: "boom" }),
      stages: [],
      verification: null,
    });

    const region = panel();
    expect(within(region).getByText("No verification artifact was recorded.")).toBeInTheDocument();
    expect(within(region).queryByText(/Passed \d+ of \d+/)).toBeNull();
    expect(within(region).queryByText("100")).toBeNull();
  });

  it("reports a deployment-blocked run as analysis completed, phases not reached", () => {
    renderStatus({
      run: makeRun({
        status: "failed",
        result_kind: "failed",
        error_code: "NO_DEPLOYABLE_APP",
        error_summary:
          "Analysis completed, but this repository does not contain a deployable web application.",
      }),
      stages: makeStages({
        plan: { state: "idle" },
        cnp: { state: "idle" },
        verify: { state: "idle" },
        execute: { state: "idle" },
      }),
      verification: null,
    });

    const region = panel();
    expect(
      within(region).getByText(/Analysis completed\. This repository has no deployable web application/),
    ).toBeInTheDocument();
    // Technical codes stay behind the expandable technical-details section.
    expect(within(region).getByText("code: NO_DEPLOYABLE_APP")).toBeInTheDocument();
    expect(within(region).getByText("run: dep_1")).toBeInTheDocument();
    expect(within(region).queryByText(/Failed at/)).not.toBeInTheDocument();
  });

  it("reports real verification passed, failed, warning, and pending counts", () => {
    renderStatus({
      verification: summary({
        passed: false,
        total: 5,
        passedCount: 2,
        assessed: 4,
        failed: 1,
        warnings: 1,
        pending: 1,
      }),
    });

    const region = panel();
    expect(within(region).getByText("Passed 2 of 4 assessed checks · 1 failed · 1 warning · 1 pending")).toBeInTheDocument();
    expect(within(region).getByText("1 failed check")).toBeInTheDocument();
  });

  it("shows observed application health and its reason", () => {
    renderStatus({
      health: {
        deployment_id: "dep_1",
        is_demo: false,
        health_status: "unhealthy",
        checked_at: "2026-01-01T00:02:00Z",
        source: "live-probe",
        reason: "Container 'app' is not running.",
        execution_mode: "real",
      },
    });

    const region = panel();
    expect(within(region).getByText("Unhealthy")).toBeInTheDocument();
    expect(within(region).getByText("Container 'app' is not running.")).toBeInTheDocument();
    expect(within(region).getByRole("link", { name: "Health details →" })).toHaveAttribute(
      "href",
      "#deployment-health",
    );
  });

  it("returns to overview without carrying phase details", () => {
    const onClear = vi.fn();
    renderStatus({ selectedPhase: "verify", onClear });

    expect(screen.getByRole("region", { name: "Verify details" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Back to overview" }));
    expect(onClear).toHaveBeenCalledOnce();
  });

  it("shows Preflight's observed activity instead of a fabricated result", () => {
    renderStatus({
      selectedPhase: "preflight",
      logs: [makeLog("PREFLIGHT", "Docker daemon check passed")],
      stages: makeStages({ preflight: { state: "done" } }),
    });

    const details = screen.getByRole("region", { name: "Preflight details" });
    expect(within(details).getByText("Docker daemon check passed")).toBeInTheDocument();
    expect(within(details).getByText("Completed")).toBeInTheDocument();
  });

  it("shows Analyze's detected stack from the repository summary", () => {
    renderStatus({
      run: makeRun({
        repository_summary: {
          status: "available",
          text: "A Next.js application with API routes.",
          source: "ai",
          commit_sha: null,
          generated_at: null,
          technologies: ["Next.js", "TypeScript"],
        },
      }),
      selectedPhase: "analyze",
    });

    const details = screen.getByRole("region", { name: "Analyze details" });
    expect(within(details).getByText(/Detected Next.js, TypeScript/)).toBeInTheDocument();
    expect(within(details).getByText(/A Next.js application/)).toBeInTheDocument();
  });

  it("shows Plan's observed activity and warns when no detail was recorded", () => {
    const { unmount } = renderStatus({
      selectedPhase: "plan",
      logs: [makeLog("PLAN", "Deployment target resolved to web service")],
    });
    expect(
      within(screen.getByRole("region", { name: "Plan details" })).getByText(
        "Deployment target resolved to web service",
      ),
    ).toBeInTheDocument();
    unmount();

    renderStatus({ selectedPhase: "plan", logs: [] });
    expect(
      within(screen.getByRole("region", { name: "Plan details" })).getByText(
        "Plan completed; no additional detail was recorded.",
      ),
    ).toBeInTheDocument();
  });

  it("shows CNP resolution and links to constraints", () => {
    const negotiation: NegotiationView = {
      title: "Port conflict",
      conflictSummary: "Both services requested port 8080.",
      round: 2,
      maxRounds: 3,
      resolution: "Moved API to 8081.",
      method: "priority-weighted",
      status: "resolved",
      simpleExplanation: "The higher-priority service kept the port.",
    };
    renderStatus({ selectedPhase: "cnp", negotiation });

    const details = screen.getByRole("region", { name: "Negotiate (CNP) details" });
    expect(within(details).getByText(/Constraints resolved via priority-weighted/)).toBeInTheDocument();
    expect(within(details).getByText(/Moved API to 8081/)).toBeInTheDocument();
    expect(within(details).getByRole("link", { name: /Review constraints/ })).toHaveAttribute(
      "href",
      "/projects/prj_1/constraints",
    );
  });

  it("shows verification counts and the run-scoped details link", () => {
    renderStatus({
      selectedPhase: "verify",
      verification: summary({ total: 4, passedCount: 3, failed: 1, assessed: 4 }),
    });

    const details = screen.getByRole("region", { name: "Verify details" });
    expect(within(details).getByText("Passed 3 of 4 assessed checks · 1 failed")).toBeInTheDocument();
    expect(within(details).getByRole("link", { name: /Open verification details/ })).toHaveAttribute(
      "href",
      "/projects/prj_1/verification?run=dep_1",
    );
  });

  it("shows Execute's real failure cause and the diagnosis link", () => {
    renderStatus({
      run: makeRun({
        status: "failed",
        current_stage: "EXECUTE",
        result_kind: "failed",
        error_summary: "docker build failed: missing package.json",
      }),
      stages: makeStages({
        execute: { state: "blocked", reason: "failure" },
      }),
      selectedPhase: "execute",
    });

    const details = screen.getByRole("region", { name: "Execute details" });
    expect(within(details).getByText("Failed")).toBeInTheDocument();
    expect(within(details).getByText("docker build failed: missing package.json")).toBeInTheDocument();
    expect(within(details).getByRole("link", { name: /Open failure diagnosis/ })).toHaveAttribute(
      "href",
      "/projects/prj_1/runs/dep_1#diagnosis",
    );
  });

  it("shows a config-skipped Execute as skipped and links to Settings", () => {
    renderStatus({
      run: makeRun({
        status: "failed",
        current_stage: "EXECUTE",
        error_code: "EXECUTION_NOT_CONFIGURED",
        error_summary: "Real execution is not configured.",
      }),
      stages: makeStages({ execute: { state: "blocked", reason: "config" } }),
      selectedPhase: "execute",
    });

    const details = screen.getByRole("region", { name: "Execute details" });
    expect(within(details).getByText("Skipped")).toBeInTheDocument();
    expect(within(details).getByText(/Execution was not attempted/)).toBeInTheDocument();
    expect(within(details).getByRole("link", { name: /Configure execution/ })).toHaveAttribute(
      "href",
      "/projects/prj_1/settings",
    );
  });

  it("labels a failed phase without fabricating a cause", () => {
    renderStatus({
      run: makeRun({ status: "failed", error_summary: null }),
      stages: makeStages({ verify: { state: "blocked", reason: "failure" } }),
      selectedPhase: "verify",
    });

    const details = screen.getByRole("region", { name: "Verify details" });
    expect(
      within(details).getByText("The backend recorded this phase as failed; no error summary was stored."),
    ).toBeInTheDocument();
  });

  it("keeps missing phase evidence unknown and explains why", () => {
    renderStatus({
      run: makeRun({ status: "completed" }),
      stages: [],
      selectedPhase: "execute",
      logs: [],
    });

    const details = screen.getByRole("region", { name: "Execute details" });
    expect(within(details).getByText("Unknown")).toBeInTheDocument();
    expect(within(details).getByText("No phase data was recorded for this run.")).toBeInTheDocument();
  });

  it("shows recovery activity only when evidence exists", () => {
    const { unmount } = renderStatus();
    expect(within(panel()).queryByText("Recovery")).not.toBeInTheDocument();
    unmount();

    const rollback: RollbackSummary = {
      headline: "Rolled back the API only; worker stayed healthy.",
      preserved: 2,
      failed: 1,
      rolledBack: 1,
      details: [],
      scopeNodeIds: ["api"],
      simpleExplanation: "Dependent service was restored.",
    };
    renderStatus({ run: makeRun({ status: "partial_recovery" }), rollback });

    const region = panel();
    expect(within(region).getByText("Recovery")).toBeInTheDocument();
    expect(within(region).getByText("1 rolled back · 2 preserved")).toBeInTheDocument();
    expect(within(region).getByText("Rolled back the API only; worker stayed healthy.")).toBeInTheDocument();
    expect(within(region).getByRole("link", { name: "Rollback evidence →" })).toHaveAttribute(
      "href",
      "/projects/prj_1/graphs",
    );
  });

  it("shows a concise root cause and failure link without raw phase logs", () => {
    renderStatus({
      run: makeRun({ status: "failed", error_summary: "unique root cause" }),
      stages: makeStages({ verify: { state: "blocked", reason: "failure" } }),
      logs: [
        makeLog("VERIFY", "unique root cause", { level: "error" }),
        makeLog("VERIFY", "line-by-line raw verification output"),
      ],
    });

    const region = panel();
    expect(within(region).getByText("Failed at Verify — unique root cause")).toBeInTheDocument();
    expect(
      within(region).getByRole("link", { name: "Open verification details →" }),
    ).toHaveAttribute("href", "/projects/prj_1/verification?run=dep_1");
    expect(within(region).queryByText("line-by-line raw verification output")).not.toBeInTheDocument();
  });

  it("shows structured checkout diagnostics and a retry action on a failed run", () => {
    const onRetry = vi.fn();
    renderStatus({
      run: makeRun({
        status: "failed",
        current_stage: "COMPLETE",
        result_kind: "failed",
        error_code: "GIT.CHECKOUT_FAILED",
        error_summary: "fatal: cannot create directory at 'test/…': Filename too long",
        failure: {
          code: "GIT.CHECKOUT_FAILED",
          category: "filesystem",
          operation: "clone",
          exit_code: 128,
          duration_seconds: 84,
          failed_stage: "ANALYZE",
          stderr_tail: "fatal: cannot create directory at 'test/…': Filename too long",
        },
      }),
      stages: makeStages({
        preflight: { state: "done" },
        analyze: { state: "blocked", reason: "failure" },
      }),
      verification: null,
      onRetry,
    });

    const region = panel();
    // A failed phase exists (Analyze), so the link opens that run's details.
    expect(within(region).getByRole("link", { name: "Open run details →" })).toHaveAttribute(
      "href",
      "/projects/prj_1/runs/dep_1",
    );
    expect(within(region).getByText("code: GIT.CHECKOUT_FAILED")).toBeInTheDocument();
    expect(within(region).getByText("operation: clone")).toBeInTheDocument();
    expect(within(region).getByText("category: filesystem")).toBeInTheDocument();
    expect(within(region).getByText("exit code: 128")).toBeInTheDocument();

    const retry = within(region).getByTestId("retry-run-button");
    expect(retry).toBeEnabled();
    fireEvent.click(retry);
    expect(onRetry).toHaveBeenCalledOnce();
  });

  it("disables retry while a retry attempt is already starting", () => {
    renderStatus({
      run: makeRun({ status: "failed", result_kind: "failed", error_summary: "boom" }),
      stages: [],
      verification: null,
      onRetry: vi.fn(),
      retrying: true,
    });
    const retry = within(panel()).getByTestId("retry-run-button");
    expect(retry).toBeDisabled();
    expect(retry).toHaveTextContent("Starting retry…");
  });

  it("explains phases the backend marked blocked as not reached, with the reason", () => {
    renderStatus({
      run: makeRun({
        status: "failed",
        error_code: "GIT.CHECKOUT_FAILED",
        error_summary: "Clone failed",
        phases: [
          { id: "preflight", status: "completed" },
          { id: "analyze", status: "failed", reason: "Clone failed" },
          { id: "plan", status: "blocked", reason: "Analyze failed first" },
          { id: "cnp", status: "blocked", reason: "Analyze failed first" },
          { id: "verify", status: "blocked", reason: "Analyze failed first" },
          { id: "execute", status: "blocked", reason: "Analyze failed first" },
        ],
      }),
      stages: [],
      verification: null,
      selectedPhase: "plan",
    });

    const details = screen.getByRole("region", { name: "Plan details" });
    expect(within(details).getByText("Blocked")).toBeInTheDocument();
    expect(within(details).getByText("Not reached — Analyze failed first")).toBeInTheDocument();
    expect(within(details).queryByText("Failed")).not.toBeInTheDocument();
  });
});
