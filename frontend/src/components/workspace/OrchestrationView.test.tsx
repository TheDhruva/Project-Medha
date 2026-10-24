import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentSnapshotRow, RunHealth } from "@/lib/api/client";

const { projectData } = vi.hoisted(() => {
  const run = (overrides: Record<string, unknown> = {}) => ({
    deployment_id: "dep_latest_1234567890",
    status: "completed",
    is_demo: false,
    label: null,
    scenario: null,
    repository_url: "https://github.com/example/app",
    updated_at: "2026-10-20T10:01:00Z",
    created_at: "2026-10-20T09:59:00Z",
    current_stage: "COMPLETE",
    duration_seconds: 94 as number | null,
    ...overrides,
  });
  return {
    projectData: {
      repo: "https://github.com/example/app",
      name: "Example App",
      runs: [
        run(),
        run({
          deployment_id: "dep_failed_1234567890",
          status: "failed",
          duration_seconds: null,
          updated_at: "2026-10-19T10:01:00Z",
        }),
      ],
      loading: false,
      error: null,
      backendReachable: true,
      selectedId: "dep_latest_1234567890",
      selectRun: vi.fn(),
      hydration: {
        logs: [
          {
            ts: "2026-10-20T10:00:00Z",
            level: "info",
            source: "ANALYZE",
            message: "MEDHA is identifying the application's deployment structure.",
            type: "stage.started",
            stage: "ANALYZE",
            status: null,
            is_demo: false,
          },
          {
            ts: "2026-10-20T10:00:01Z",
            level: "info",
            source: "system",
            message: "analyzer started",
            type: "agent.started",
            stage: null,
            status: null,
            is_demo: false,
          },
          {
            ts: "2026-10-20T10:00:05Z",
            level: "info",
            source: "system",
            message: "Repository analysis found 2 services.",
            type: "agent.completed",
            stage: null,
            status: "success",
            is_demo: false,
          },
          {
            ts: "2026-10-20T10:00:06Z",
            level: "info",
            source: "system",
            message: "docker started",
            type: "agent.started",
            stage: null,
            status: null,
            is_demo: false,
          },
          {
            ts: "2026-10-20T10:00:08Z",
            level: "info",
            source: "VERIFY",
            message: "Verification failed: compose schema error.",
            type: "stage.completed",
            stage: "VERIFY",
            status: "failed",
            is_demo: false,
          },
          {
            ts: "2026-10-20T10:00:10Z",
            level: "info",
            source: "system",
            message: "Deployment completed successfully.",
            type: "deployment.completed",
            stage: null,
            status: "success",
            is_demo: false,
          },
        ],
        agents: [
          {
            id: "analyzer",
            name: "Code Analyzer",
            status: "complete",
            activity: "Repository analysis found 2 services.",
            lastEvent: "Repository analysis found 2 services.",
            durationMs: 4000,
            startedAt: null,
            finishedAt: null,
            deps: ["preflight"],
          },
          {
            id: "docker",
            name: "Docker",
            status: "complete",
            activity: "Container plan ready.",
            lastEvent: "Container plan ready.",
            durationMs: 3000,
            startedAt: null,
            finishedAt: null,
            deps: ["analyzer"],
          },
        ] as AgentSnapshotRow[] | null,
        executionMode: "real",
        constraints: [],
        negotiation: null,
        verification: null,
        critic: null,
        graph: { nodes: [], edges: [] },
        rollback: null,
        changeImpact: null,
        changeImpactLabel: null,
        changeImpactIsDemo: false,
        health: null as RunHealth | null,
        runtimeLogs: null,
      },
      hydrating: false,
      refresh: vi.fn(),
    },
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/projects/useProjectData", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/projects/useProjectData");
  return { ...original, useProjectData: () => projectData };
});

import { OrchestrationView } from "@/components/workspace/ProjectSections";

const BASE_RUNS = projectData.runs;
const BASE_HYDRATION = projectData.hydration;

afterEach(() => {
  projectData.runs = BASE_RUNS;
  projectData.hydration = BASE_HYDRATION;
});

function timelineItems(): HTMLElement[] {
  return within(screen.getByRole("list", { name: "Recorded conversation timeline" })).getAllByRole("listitem");
}

describe("OrchestrationView", () => {
  it("shows a conversation panel with roster and drops the old panels", () => {
    render(<OrchestrationView projectId="prj_test" />);

    expect(screen.getByRole("heading", { level: 1, name: "Activity Center" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Agent conversation" })).toBeInTheDocument();
    // Standalone Pipeline / Agents / Event log panels are gone.
    expect(screen.queryByRole("heading", { name: "Pipeline" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Event log" })).not.toBeInTheDocument();

    // Header facts come straight from the run record, in local time.
    expect(screen.getAllByText("Completed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText(/1m 34s/).length).toBeGreaterThanOrEqual(1);
    expect(document.querySelector("time")?.getAttribute("dateTime")).toBe("2026-10-20T10:01:00Z");
    // Internal ids stay in values/routing, never in visible labels.
    expect(document.body.textContent).not.toMatch(/dep_/);
    const options = within(screen.getByRole("combobox")).getAllByRole("option");
    expect(options).toHaveLength(2);
    expect(options[0].textContent).toMatch(/— Completed$/);
    expect(options[1].textContent).toMatch(/— Failed$/);

    // Agent chips discover actual participants from the run, not a fixed roster.
    const chips = within(screen.getByRole("list", { name: "Participating agents" })).getAllByRole("listitem");
    expect(chips).toHaveLength(2);
    expect(chips[0].textContent).toContain("Code Analyzer");
    expect(chips[0].textContent).toContain("CA");
    expect(chips[1].textContent).toContain("Docker");
    expect(chips[1].textContent).toContain("DO");

    // Timeline is chronological with recorded messages, oldest first.
    const items = timelineItems();
    expect(items).toHaveLength(6);
    expect(items[0].textContent).toContain("identifying the application's deployment structure.");
    expect(items[5].textContent).toContain("Deployment completed successfully.");

    // Agent attribution from recorded evidence + one recorded handoff.
    expect(screen.getAllByText("Code Analyzer").length).toBeGreaterThanOrEqual(2);
    const handoff = screen.getByText(/Inputs from/);
    expect(
      within(handoff).getByRole("link", { name: "Code Analyzer" }).getAttribute("href"),
    ).toMatch(/^#feed-\d+$/);

    // The one real failure is easy to notice and links to actual diagnostics.
    expect(screen.getByText(/1 error recorded in this run/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Open error details/ })).toHaveAttribute(
      "href",
      "/projects/prj_test/runs/dep_latest_1234567890#diagnosis",
    );
  });

  it("gives each agent a stable identity and balanced alignment", () => {
    render(<OrchestrationView projectId="prj_test" />);

    // Registry-order parity: analyzer left, docker right — deterministic.
    const analyzer = document.querySelector('li[data-agent="analyzer"]');
    const docker = document.querySelector('li[data-agent="docker"]');
    expect(analyzer?.getAttribute("data-side")).toBe("left");
    expect(docker?.getAttribute("data-side")).toBe("right");
    // Every agent bubble names its sender (never alignment alone).
    const agentBubbles = document.querySelectorAll("li[data-agent]");
    expect(agentBubbles.length).toBe(3);
    agentBubbles.forEach((b) => {
      expect(["Code Analyzer", "Docker"]).toContain(b.querySelector("p span")?.textContent ?? "");
    });
    // System events are centered notices, not bubbles with a sender.
    const notices = timelineItems().filter((i) => i.getAttribute("data-agent") == null);
    expect(notices).toHaveLength(3);
  });

  it("keeps health independent from run status, exposes sidebar and collapsed details", () => {
    projectData.hydration = {
      ...projectData.hydration,
      health: {
        deployment_id: "dep_latest_1234567890",
        is_demo: false,
        health_status: "unhealthy",
        checked_at: "2026-10-20T10:02:00Z",
        source: "stored",
        reason: "The container exited after deployment.",
        execution_mode: "real",
        container: null,
      },
    };
    render(<OrchestrationView projectId="prj_test" />);

    // Completed run + unhealthy application, both stated accurately.
    expect(screen.getAllByText("Completed").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByRole("heading", { level: 2, name: "Application health" })).toBeInTheDocument();
    expect(screen.getByText("Unhealthy")).toBeInTheDocument();
    expect(screen.getByText("The container exited after deployment.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Health details/ })).toHaveAttribute(
      "href",
      "/projects/prj_test#deployment-health",
    );

    // Sidebar Run status shows real phases derived from recorded stage events.
    expect(screen.getByRole("heading", { level: 2, name: "Run status" })).toBeInTheDocument();
    const phases = screen.getByRole("list", { name: "Pipeline phases" });
    expect(within(phases).getByText("Analyze")).toBeInTheDocument();
    expect(within(phases).getByText("Verify")).toBeInTheDocument();

    // Agents sidebar lists snapshot state without inventing anything.
    const agentsList = screen.getByRole("list", { name: "Run agents" });
    expect(within(agentsList).getByText("Code Analyzer")).toBeInTheDocument();
    expect(within(agentsList).getByText("Docker")).toBeInTheDocument();

    const details = document.getElementById("technical-details") as HTMLDetailsElement;
    expect(details.tagName).toBe("DETAILS");
    expect(details).not.toHaveAttribute("open");
    fireEvent.click(screen.getByText("Technical details"));
    expect(details).toHaveAttribute("open");
    // Raw event records (event type, level) stay accessible when expanded.
    expect(screen.getByText("stage.started")).toBeInTheDocument();
  });

  it("handles a running run with no recorded events or health", () => {
    projectData.runs = [
      {
        ...BASE_RUNS[0],
        status: "running",
        current_stage: "ANALYZE",
        duration_seconds: null,
      },
    ];
    projectData.hydration = { ...BASE_HYDRATION, logs: [], agents: null };
    render(<OrchestrationView projectId="prj_test" />);

    expect(screen.getAllByText("Running").length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText(/1m 34s/)).not.toBeInTheDocument();
    expect(screen.getByText("No events are stored for this run yet.")).toBeInTheDocument();
    expect(document.getElementById("technical-details")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Application health" })).not.toBeInTheDocument();
    // Empty roster is stated honestly, never faked.
    expect(screen.getByText("No agent activity recorded for this run.")).toBeInTheDocument();
  });

  it("does not leak messages across runs and survives unknown events", () => {
    const { rerender } = render(<OrchestrationView projectId="prj_test" />);
    expect(timelineItems()[5].textContent).toContain("Deployment completed successfully.");

    // Switch to another run's hydration (run isolation = full content replace).
    projectData.hydration = {
      ...BASE_HYDRATION,
      logs: [
        {
          ts: "2026-10-19T09:00:00Z",
          level: "info",
          source: "system",
          message: "A wholly different recorded event.",
          type: "totally.unknown.event",
          stage: null,
          status: null,
          is_demo: false,
        },
      ],
      agents: null,
    };
    rerender(<OrchestrationView projectId="prj_test" />);

    // Previous run's messages are gone; unknown event renders as a safe notice.
    expect(screen.queryByText("Repository analysis found 2 services.")).not.toBeInTheDocument();
    expect(timelineItems()).toHaveLength(1);
    expect(timelineItems()[0].textContent).toContain("A wholly different recorded event.");
    // No agent chips, no crash — unknown types are honest system notices.
    expect(screen.queryByRole("list", { name: "Participating agents" })).not.toBeInTheDocument();
  });
});
