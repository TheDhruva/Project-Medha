import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DeploymentDetailsPopover } from "@/components/workspace/DeploymentDetailsPopover";
import type { RunHealth, RunSummary } from "@/lib/api/client";

function run(partial: Partial<RunSummary> & { deployment_id: string }): RunSummary {
  return {
    status: "completed",
    mode: "real",
    is_demo: false,
    execution_mode: "real",
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
    ...partial,
  };
}

function health(runId: string, status: string): RunHealth {
  return {
    deployment_id: runId,
    is_demo: false,
    health_status: status,
    checked_at: "2026-10-20T10:01:00Z",
    source: "probe",
    reason: null,
    execution_mode: "real",
  };
}

function Harness({
  runs,
  healths = {},
  blockers = 0,
  loading = false,
  error = null,
  hydrating = false,
}: {
  runs: RunSummary[];
  healths?: Record<string, RunHealth>;
  blockers?: number;
  loading?: boolean;
  error?: string | null;
  hydrating?: boolean;
}) {
  const [selectedId, setSelectedId] = useState(runs[0]?.deployment_id ?? null);
  const selected = runs.find((r) => r.deployment_id === selectedId) ?? runs[0] ?? null;
  const selectedIndex = selected
    ? runs.findIndex((r) => r.deployment_id === selected.deployment_id)
    : -1;
  return (
    <DeploymentDetailsPopover
      projectId="prj_test"
      runs={runs}
      selectedRun={selected}
      selectedIndex={selectedIndex}
      health={selected ? healths[selected.deployment_id] ?? null : null}
      hydrating={hydrating}
      blockers={blockers}
      loading={loading}
      error={error}
      executionMode="real"
      starting={false}
      canStartRun
      onSelectRun={setSelectedId}
      onRetry={vi.fn()}
      onStartRun={vi.fn()}
    />
  );
}

const latest = run({ deployment_id: "dep_latest_1234567890" });
const previous = run({
  deployment_id: "dep_previous_1234567890",
  status: "failed",
  created_at: "2026-10-19T10:00:00Z",
  updated_at: "2026-10-19T10:01:00Z",
});

function open() {
  fireEvent.click(screen.getByRole("button", { name: "Deployment details" }));
  return screen.getByRole("dialog", { name: "Deployment details" });
}

describe("DeploymentDetailsPopover", () => {
  it("opens and closes on outside click and Escape", () => {
    render(<Harness runs={[latest]} />);
    const trigger = screen.getByRole("button", { name: "Deployment details" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");

    open();
    expect(trigger).toHaveAttribute("aria-expanded", "true");

    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).toBeNull();

    open();
    fireEvent.keyDown(document, { key: "Escape" });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(trigger).toHaveFocus();
  });

  it("selects historical runs and updates statuses and links for that run", () => {
    render(
      <Harness
        runs={[latest, previous]}
        healths={{
          [latest.deployment_id]: health(latest.deployment_id, "healthy"),
          [previous.deployment_id]: health(previous.deployment_id, "unhealthy"),
        }}
      />,
    );
    const dialog = open();

    expect(within(dialog).getByText("Latest deployment")).toBeInTheDocument();
    expect(within(dialog).getByText("Pipeline completed")).toBeInTheDocument();
    expect(within(dialog).getByText("Deployment healthy")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Run details" })).toHaveAttribute(
      "href",
      `/projects/prj_test/runs/${latest.deployment_id}`,
    );

    fireEvent.change(within(dialog).getByLabelText("Selected deployment"), {
      target: { value: previous.deployment_id },
    });

    expect(within(dialog).getByText("Previous deployment")).toBeInTheDocument();
    expect(within(dialog).getByText("Pipeline failed")).toBeInTheDocument();
    expect(within(dialog).getByText("Deployment unhealthy")).toBeInTheDocument();
    expect(within(dialog).getByRole("link", { name: "Run details" })).toHaveAttribute(
      "href",
      `/projects/prj_test/runs/${previous.deployment_id}`,
    );
    expect(within(dialog).getByRole("link", { name: "Verification" })).toHaveAttribute(
      "href",
      `/projects/prj_test/verification?run=${previous.deployment_id}`,
    );
    expect(within(dialog).getByRole("link", { name: "Run history" })).toHaveAttribute(
      "href",
      "/projects/prj_test/runs",
    );
  });

  it("keeps pipeline completion independent from deployment health", () => {
    render(
      <Harness
        runs={[latest]}
        healths={{ [latest.deployment_id]: health(latest.deployment_id, "unhealthy") }}
      />,
    );
    const dialog = open();
    expect(within(dialog).getByText("Pipeline completed")).toBeInTheDocument();
    expect(within(dialog).getByText("Deployment unhealthy")).toBeInTheDocument();
  });

  it("never substitutes healthy when health is unknown", () => {
    render(<Harness runs={[latest]} />);
    const dialog = open();
    expect(within(dialog).getByText("Pipeline completed")).toBeInTheDocument();
    expect(within(dialog).getByText("Health status unavailable")).toBeInTheDocument();
    expect(within(dialog).queryByText("Deployment healthy")).toBeNull();
  });

  it("links the real blocker count to findings and omits a dead link at zero", () => {
    const { unmount } = render(<Harness runs={[latest]} blockers={2} />);
    let dialog = open();
    expect(within(dialog).getByRole("link", { name: "2 blockers" })).toHaveAttribute(
      "href",
      "#findings",
    );
    unmount();

    render(<Harness runs={[latest]} blockers={0} />);
    dialog = open();
    expect(within(dialog).queryByRole("link", { name: /blocker/ })).toBeNull();
    expect(within(dialog).getByText("No blockers recorded")).toBeInTheDocument();
  });

  it("does not expose technical run IDs in the run choices", () => {
    render(<Harness runs={[latest, previous]} />);
    const dialog = open();
    const select = within(dialog).getByLabelText("Selected deployment");
    const options = within(select).getAllByRole("option");
    expect(options).toHaveLength(2);
    for (const option of options) {
      expect(option.textContent).not.toContain(latest.deployment_id);
      expect(option.textContent).not.toContain(previous.deployment_id);
    }
  });

  it("renders a concise empty state with an analysis action", () => {
    const start = vi.fn();
    render(
      <DeploymentDetailsPopover
        projectId="prj_test"
        runs={[]}
        selectedRun={null}
        selectedIndex={-1}
        health={null}
        hydrating={false}
        blockers={0}
        loading={false}
        error={null}
        executionMode={null}
        starting={false}
        canStartRun
        onSelectRun={vi.fn()}
        onRetry={vi.fn()}
        onStartRun={start}
      />,
    );
    const dialog = open();
    expect(within(dialog).getByText("No runs yet")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Run analysis" }));
    expect(start).toHaveBeenCalledTimes(1);
  });

  it("renders loading without inventing a run status", () => {
    render(<Harness runs={[]} loading />);
    const dialog = open();
    expect(within(dialog).getByText("Loading deployment details…")).toBeInTheDocument();
    expect(within(dialog).queryByText(/Pipeline/)).toBeNull();
  });

  it("renders a compact retryable error state", () => {
    const retry = vi.fn();
    render(
      <DeploymentDetailsPopover
        projectId="prj_test"
        runs={[]}
        selectedRun={null}
        selectedIndex={-1}
        health={null}
        hydrating={false}
        blockers={0}
        loading={false}
        error="Backend unavailable"
        executionMode={null}
        starting={false}
        canStartRun
        onSelectRun={vi.fn()}
        onRetry={retry}
        onStartRun={vi.fn()}
      />,
    );
    const dialog = open();
    expect(within(dialog).getByText("Backend unavailable")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Retry" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });
});
