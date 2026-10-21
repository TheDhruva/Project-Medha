import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PipelineTimeline } from "@/components/workspace/PipelineTimeline";
import type { RunLogLine, RunSummary } from "@/lib/api/client";
import type { PhaseId } from "@/lib/projects/executionPhases";
import type { PipelineStage } from "@/lib/projects/useProjectData";

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
    status: "running",
    mode: "real",
    is_demo: false,
    execution_mode: "real",
    label: null,
    scenario: null,
    repository_url: "https://github.com/acme/app",
    intent: null,
    base_revision: null,
    target_revision: null,
    current_stage: "PLAN",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:01:00Z",
    duration_seconds: null,
    risk: null,
    result_kind: null,
    error_summary: null,
    ...overrides,
  };
}

function makeStages(overrides: Partial<Record<string, Partial<PipelineStage>>> = {}): PipelineStage[] {
  return IDS.map((id) => ({
    id,
    label: LABELS[id],
    state: "idle" as const,
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

function renderPipeline(props: {
  run?: RunSummary | null;
  stages?: PipelineStage[];
  logs?: RunLogLine[];
  hydrating?: boolean;
  selectedPhase?: PhaseId | null;
  onSelectPhase?: (phase: PhaseId | null) => void;
} = {}) {
  return render(
    <PipelineTimeline
      projectId="prj_1"
      run={props.run === undefined ? makeRun() : props.run}
      stages={props.stages ?? []}
      logs={props.logs ?? []}
      hydrating={props.hydrating ?? false}
      selectedPhase={props.selectedPhase ?? null}
      onSelectPhase={props.onSelectPhase ?? (() => undefined)}
    />,
  );
}

function cards(): HTMLElement[] {
  return within(screen.getByRole("list", { name: "Execution pipeline phases" })).getAllByRole("button");
}

describe("PipelineTimeline", () => {
  it("renders the six phases in execution order with their real descriptions", () => {
    renderPipeline();
    const list = cards();
    expect(list).toHaveLength(6);
    const labels = ["Preflight", "Analyze", "Plan", "Negotiate (CNP)", "Verify", "Execute"];
    const descriptions = [
      "Check environment",
      "Inspect repository",
      "Build deployment plan",
      "Resolve constraints",
      "Validate the plan",
      "Build and deploy app",
    ];
    labels.forEach((label, index) => {
      expect(within(list[index]).getByText(label)).toBeInTheDocument();
      expect(within(list[index]).getByText(descriptions[index])).toBeInTheDocument();
    });
  });

  it("uses a one/two/three-column responsive grid and controlled selection", () => {
    const onSelectPhase = vi.fn();
    const { rerender } = renderPipeline({ onSelectPhase });
    const list = screen.getByRole("list", { name: "Execution pipeline phases" });
    expect(list).toHaveClass("grid-cols-1", "sm:grid-cols-2", "xl:grid-cols-3");
    const first = cards()[0];
    expect(first).toHaveClass("min-w-0");
    expect(first).toHaveAttribute("aria-pressed", "false");
    expect(first).not.toHaveAttribute("aria-controls");
    expect(screen.queryByRole("region", { name: "Preflight details" })).not.toBeInTheDocument();

    first.focus();
    expect(first).toHaveFocus();
    fireEvent.click(first);
    expect(onSelectPhase).toHaveBeenCalledWith("preflight");

    rerender(
      <PipelineTimeline
        projectId="prj_1"
        run={makeRun()}
        stages={[]}
        logs={[]}
        selectedPhase="preflight"
        onSelectPhase={onSelectPhase}
      />,
    );
    expect(cards()[0]).toHaveAttribute("aria-pressed", "true");
    expect(cards()[0]).toHaveAttribute("aria-controls", "operational-status-panel");
    expect(within(cards()[0]).getByText("Selected")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Preflight details" })).not.toBeInTheDocument();
  });

  it("marks completed phases and shows the run's observed total duration", () => {
    const stages = makeStages(
      Object.fromEntries(
        IDS.map((id) => [id, { state: "done" as const, durationMs: 2000 }]),
      ),
    );
    renderPipeline({ run: makeRun({ status: "completed", duration_seconds: 60 }), stages });

    cards().forEach((card) => {
      expect(card).toHaveAttribute("data-state", "completed");
      expect(within(card).getByText("Completed")).toBeInTheDocument();
    });
    expect(screen.getByTestId("pipeline-overall-status")).toHaveTextContent("Completed");
    expect(screen.getByText("Total 1m 00s")).toBeInTheDocument();
  });

  it("shows a running phase, its real activity, and reduced-motion-safe animation", () => {
    renderPipeline({
      run: makeRun({ status: "running", current_stage: "PLAN" }),
      stages: makeStages({
        preflight: { state: "done" },
        plan: { state: "active" },
      }),
      logs: [makeLog("PLAN", "Resolving deployment target from repository layout")],
    });

    const plan = cards()[2];
    expect(plan).toHaveAttribute("data-state", "running");
    expect(plan).toHaveAttribute("aria-current", "step");
    expect(within(plan).getByText("Running")).toBeInTheDocument();
    expect(
      within(plan).getByText("Resolving deployment target from repository layout"),
    ).toBeInTheDocument();
    expect(screen.getByTestId("pipeline-running-indicator")).toHaveClass(
      "motion-safe:animate-spin",
    );
  });

  it("marks the failed phase without duplicating its error message", () => {
    renderPipeline({
      run: makeRun({
        status: "failed",
        current_stage: "VERIFY",
        error_summary: "Health check returned 500.",
      }),
      stages: makeStages({
        preflight: { state: "done" },
        analyze: { state: "done" },
        plan: { state: "done" },
        cnp: { state: "done" },
        verify: { state: "blocked", reason: "failure" },
      }),
      logs: [makeLog("VERIFY", "Health check returned 500.", { level: "error" })],
    });

    const verify = cards()[4];
    expect(verify).toHaveAttribute("data-state", "failed");
    expect(within(verify).getByText("Failed")).toBeInTheDocument();
    expect(screen.queryByText(/Health check returned 500/)).not.toBeInTheDocument();
  });

  it("labels waiting phases as Waiting and config-blocked Execute as Skipped", () => {
    const { unmount } = renderPipeline({
      run: makeRun({ status: "running", current_stage: "ANALYZE" }),
      stages: makeStages({ preflight: { state: "done" }, analyze: { state: "active" } }),
    });
    expect(cards()[2]).toHaveAttribute("data-state", "waiting");
    expect(within(cards()[2]).getByText("Waiting")).toBeInTheDocument();
    expect(screen.queryByText("Pending")).not.toBeInTheDocument();
    unmount();

    renderPipeline({
      run: makeRun({
        status: "failed",
        current_stage: "EXECUTE",
        error_code: "EXECUTION_NOT_CONFIGURED",
        error_summary: "Real execution is not configured.",
      }),
      stages: makeStages({
        preflight: { state: "done" },
        analyze: { state: "done" },
        plan: { state: "done" },
        cnp: { state: "done" },
        verify: { state: "done" },
        execute: { state: "blocked", reason: "config" },
      }),
    });
    const execute = cards()[5];
    expect(execute).toHaveAttribute("data-state", "skipped");
    expect(within(execute).getByText("Skipped")).toBeInTheDocument();
    expect(within(execute).queryByText("Failed")).not.toBeInTheDocument();
  });

  it("keeps missing phase evidence unknown instead of completed, even for a completed run", () => {
    renderPipeline({ run: makeRun({ status: "completed" }), stages: [], logs: [] });

    cards().forEach((card) => {
      expect(card).toHaveAttribute("data-state", "unknown");
      expect(within(card).getByText("Unknown")).toBeInTheDocument();
      expect(within(card).queryByText("Completed")).not.toBeInTheDocument();
    });
  });

  it("does not render health, rollback, or raw logs in the pipeline grid", () => {
    renderPipeline({
      run: makeRun({ status: "partial_recovery" }),
      stages: makeStages({ recover: { state: "done" } }),
      logs: [makeLog("EXECUTE", "docker build failed", { level: "error" })],
    });

    expect(screen.queryByText("Application health")).not.toBeInTheDocument();
    expect(screen.queryByText("Rollback evidence")).not.toBeInTheDocument();
    expect(screen.queryByText("docker build failed")).not.toBeInTheDocument();
  });
});
