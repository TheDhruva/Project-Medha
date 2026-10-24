import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectSummary } from "@/lib/projects/projects";

const { pathnameMock, paramsMock, state } = vi.hoisted(() => ({
  pathnameMock: vi.fn(() => "/projects"),
  paramsMock: vi.fn(() => ({})),
  state: {
    projects: [] as ProjectSummary[],
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock(),
  useParams: () => paramsMock(),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/projects/projects", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/projects/projects");
  return {
    ...original,
    useProjects: () => ({
      projects: state.projects,
      runs: [],
      total: state.projects.length,
      loading: false,
      error: null,
      backendReachable: true,
      refresh: vi.fn(),
      createProject: vi.fn(),
    }),
  };
});

import { ProjectHub } from "@/components/workspace/ProjectHub";

function project(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  const activity = new Date();
  activity.setHours(10, 35, 0, 0);
  return {
    id: "prj_medha",
    projectId: "prj_medha",
    connectionStatus: "connected",
    legacy: false,
    repositoryUrl: "https://github.com/TheDhruva/Project-Medha",
    name: "MEDHA",
    repoOwner: "TheDhruva",
    repoName: "Project-Medha",
    branch: "main",
    summary: "A constraint-negotiating DevOps workspace built for verifiable local analysis.",
    totalRuns: 1,
    latest: {
      deployment_id: "dep_1",
      status: "completed",
      updated_at: activity.toISOString(),
    } as ProjectSummary["latest"],
    lastActivity: activity.toISOString(),
    demoRuns: 0,
    realRuns: 1,
    failedRuns: 0,
    awaitingApproval: 0,
    attention: [],
    ...overrides,
  };
}

beforeEach(() => {
  pathnameMock.mockReturnValue("/projects");
  paramsMock.mockReturnValue({});
  state.projects = [project()];
});

describe("ProjectHub", () => {
  it("renders the compact heading, grounded card content, and single activity row", () => {
    render(<ProjectHub />);

    expect(screen.getByRole("heading", { name: "Project Hub" })).toBeInTheDocument();
    expect(screen.queryByText("Your repositories at a glance.")).toBeNull();
    expect(screen.getByRole("button", { name: /New project/ })).toBeInTheDocument();

    const card = screen.getByRole("article", { name: "MEDHA" });
    expect(within(card).getByRole("link", { name: "MEDHA" })).toHaveAttribute(
      "href",
      "/projects/prj_medha",
    );
    expect(within(card).getByText("TheDhruva/Project-Medha")).toBeInTheDocument();
    expect(within(card).getByText("main")).toBeInTheDocument();
    expect(within(card).getByText(/constraint-negotiating/)).toBeInTheDocument();
    expect(within(card).getByText("Completed")).toBeInTheDocument();
    expect(within(card).getByText(/10:35/)).toBeInTheDocument();

    expect(screen.queryByText(/Latest run/)).toBeNull();
    expect(screen.queryByText(/Project status reflects recorded backend runs/)).toBeNull();
  });

  it("keeps the overflow menu independent from the card link", () => {
    render(<ProjectHub />);

    const trigger = screen.getByRole("button", { name: "Actions for MEDHA" });
    expect(trigger.closest("a")).toBeNull();
    fireEvent.click(trigger);

    const menu = screen.getByRole("menu", { name: "Actions for MEDHA" });
    expect(within(menu).getByRole("menuitem", { name: "Open project" })).toHaveAttribute(
      "href",
      "/projects/prj_medha",
    );
    expect(within(menu).getByRole("menuitem", { name: "View runs" })).toHaveAttribute(
      "href",
      "/projects/prj_medha/runs",
    );
    expect(within(menu).getByRole("menuitem", { name: "Copy repository URL" })).toBeInTheDocument();
    expect(within(menu).getByRole("menuitem", { name: "Project settings" })).toHaveAttribute(
      "href",
      "/projects/prj_medha/settings",
    );

    fireEvent.keyDown(menu, { key: "ArrowDown" });
    expect(within(menu).getByRole("menuitem", { name: "Open project" })).toHaveFocus();
  });

  it("filters by status and search inside the compact toolbar", () => {
    render(<ProjectHub />);

    fireEvent.click(screen.getByRole("button", { name: "Filter" }));
    const dialog = screen.getByRole("dialog", { name: "Filter projects" });
    fireEvent.click(within(dialog).getByLabelText(/Needs attention/));
    expect(screen.queryByRole("article", { name: "MEDHA" })).toBeNull();

    fireEvent.click(within(dialog).getByLabelText(/All projects/));
    expect(screen.getByRole("article", { name: "MEDHA" })).toBeInTheDocument();

    const search = screen.getByLabelText("Search projects");
    fireEvent.change(search, { target: { value: "missing" } });
    expect(screen.queryByRole("article", { name: "MEDHA" })).toBeNull();
    expect(screen.getByText("No matching projects")).toBeInTheDocument();
  });

  it("omits activity when no timestamp was recorded", () => {
    state.projects = [
      project({
        latest: null,
        totalRuns: 0,
        realRuns: 0,
        lastActivity: null,
        summary: null,
      }),
    ];
    render(<ProjectHub />);

    const card = screen.getByRole("article", { name: "MEDHA" });
    expect(within(card).getByText("No runs yet")).toBeInTheDocument();
    expect(card.querySelector("time")).toBeNull();
  });
});
