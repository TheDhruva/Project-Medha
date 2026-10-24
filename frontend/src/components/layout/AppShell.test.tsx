import { fireEvent, render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ProjectSummary } from "@/lib/projects/projects";
import type { RunSummary } from "@/lib/api/client";

type SidebarProject = ProjectSummary;

const { pathnameMock, paramsMock, projectsState, pushMock } = vi.hoisted(() => {
  const project = (overrides: Partial<SidebarProject> = {}): SidebarProject => ({
    id: "prj_alpha",
    projectId: "prj_alpha",
    connectionStatus: "connected",
    legacy: false,
    repositoryUrl: "https://github.com/example/alpha",
    name: "Alpha App",
    repoOwner: "example",
    repoName: "alpha",
    branch: "main",
    summary: null,
    totalRuns: 0,
    latest: null,
    lastActivity: null,
    demoRuns: 0,
    realRuns: 0,
    failedRuns: 0,
    awaitingApproval: 0,
    attention: [],
    ...overrides,
  });
  return {
    pathnameMock: vi.fn(),
    paramsMock: vi.fn(),
    pushMock: vi.fn(),
    projectsState: {
      projects: [] as SidebarProject[],
      loading: false,
      project,
    },
  };
});

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock(),
  useParams: () => paramsMock(),
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/projects/projects", async (importOriginal) => {
  const original =
    (await importOriginal()) as typeof import("@/lib/projects/projects");
  return {
    ...original,
    useProjects: () => ({
      projects: projectsState.projects,
      runs: [],
      total: 0,
      loading: projectsState.loading,
      error: null,
      backendReachable: true,
      refresh: vi.fn(),
      createProject: vi.fn(),
    }),
  };
});

import { AppShell } from "@/components/layout/AppShell";

const project = (overrides: Partial<SidebarProject> = {}) =>
  projectsState.project(overrides);

function setRoute(pathname: string, id?: string) {
  pathnameMock.mockReturnValue(pathname);
  paramsMock.mockReturnValue(id ? { id } : {});
}

function renderShell() {
  return render(
    <AppShell>
      <div>child</div>
    </AppShell>,
  );
}

function nav(name: "Workspace" | "Project") {
  return screen.getByRole("navigation", { name });
}

function activeLabels() {
  return screen
    .getAllByRole("link")
    .filter((link) => link.getAttribute("aria-current") === "page")
    .map((link) => link.textContent);
}

beforeEach(() => {
  pathnameMock.mockReset();
  paramsMock.mockReset();
  pushMock.mockReset();
  projectsState.projects = [];
  projectsState.loading = false;
});

describe("AppShell workspace sidebar", () => {
  it("shows only Projects, Run History, and Workspace settings on the projects home", () => {
    setRoute("/projects");
    renderShell();

    const links = within(nav("Workspace")).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Project Hub",
      "Run History",
      "Workspace settings",
    ]);
    expect(activeLabels()).toEqual(["Project Hub"]);
    expect(screen.queryByRole("navigation", { name: "Project" })).toBeNull();
    expect(screen.queryByText("Current project")).toBeNull();
    expect(screen.queryByLabelText("Active project")).toBeNull();
    expect(screen.queryByText("Select a project…")).toBeNull();
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it.each([
    ["/runs/dep_1", "Run History"],
    ["/runs/", "Run History"],
    ["/settings/team", "Workspace settings"],
  ])("marks %s as %s", (pathname, expected) => {
    setRoute(pathname);
    renderShell();
    expect(activeLabels()).toEqual([expected]);
  });
});

describe("AppShell project sidebar", () => {
  it("keeps only project navigation in the sidebar and shows identity in the header", () => {
    setRoute("/projects/prj_alpha", "prj_alpha");
    projectsState.projects = [
      project({
        latest: { deployment_id: "dep_latest" } as RunSummary,
      }),
    ];
    renderShell();

    // Identity lives in the global header; the sidebar no longer repeats it.
    expect(screen.getByText("Alpha App")).toBeInTheDocument();
    expect(screen.queryByText("example/alpha")).toBeNull();
    expect(screen.getByRole("link", { name: "All projects" })).toHaveAttribute(
      "href",
      "/projects",
    );

    const projectLinks = within(nav("Project")).getAllByRole("link");
    expect(projectLinks.map((link) => link.textContent)).toEqual([
      "Overview",
      "Verification",
      "Runs",
      "Architecture Explorer",
      "Settings",
    ]);
    expect(projectLinks.map((link) => link.getAttribute("href"))).toEqual([
      "/projects/prj_alpha",
      "/projects/prj_alpha/verification",
      "/projects/prj_alpha/runs",
      "/projects/prj_alpha/graphs",
      "/projects/prj_alpha/settings",
    ]);
    expect(activeLabels()).toEqual(["Overview"]);

    const workspaceLinks = within(nav("Workspace")).getAllByRole("link");
    expect(workspaceLinks.map((link) => link.textContent)).toEqual([
      "Run History",
      "Workspace settings",
    ]);
    expect(screen.queryByText("Project overview")).toBeNull();
    expect(screen.queryByText("Project runs")).toBeNull();
    expect(screen.queryByText("Project settings")).toBeNull();
  });

  it.each([
    ["/projects/prj_alpha", "Overview"],
    ["/projects/prj_alpha/verification", "Verification"],
    ["/projects/prj_alpha/verification/", "Verification"],
    ["/projects/prj_alpha/runs", "Runs"],
    ["/projects/prj_alpha/runs/", "Runs"],
    ["/projects/prj_alpha/graphs", "Architecture Explorer"],
    ["/projects/prj_alpha/graphs/", "Architecture Explorer"],
    ["/projects/prj_alpha/settings", "Settings"],
    ["/projects/prj_alpha/settings/access", "Settings"],
  ])("marks %s as %s", (pathname, expected) => {
    setRoute(pathname, "prj_alpha");
    renderShell();
    expect(activeLabels()).toEqual([expected]);
  });

  it("does not mark an unrelated nested project route as a project tab", () => {
    setRoute("/projects/prj_alpha/changes/proposal_1", "prj_alpha");
    renderShell();
    expect(activeLabels()).toEqual([]);
  });

  it("updates the active item when the route changes (back/forward)", () => {
    setRoute("/projects/prj_alpha", "prj_alpha");
    const { rerender } = renderShell();
    expect(activeLabels()).toEqual(["Overview"]);

    setRoute("/projects/prj_alpha/runs", "prj_alpha");
    rerender(
      <AppShell>
        <div>child</div>
      </AppShell>,
    );
    expect(activeLabels()).toEqual(["Runs"]);

    setRoute("/projects/prj_alpha", "prj_alpha");
    rerender(
      <AppShell>
        <div>child</div>
      </AppShell>,
    );
    expect(activeLabels()).toEqual(["Overview"]);
  });

  it("updates identity when switching projects", () => {
    const beta = project({
      id: "prj_beta",
      projectId: "prj_beta",
      name: "Beta Service",
      repoOwner: "example",
      repoName: "beta",
      repositoryUrl: "https://github.com/example/beta",
    });
    projectsState.projects = [project(), beta];
    setRoute("/projects/prj_alpha", "prj_alpha");
    const { rerender } = renderShell();
    expect(screen.getByText("Alpha App")).toBeInTheDocument();

    setRoute("/projects/prj_beta", "prj_beta");
    rerender(
      <AppShell>
        <div>child</div>
      </AppShell>,
    );
    expect(screen.getByText("Beta Service")).toBeInTheDocument();
    expect(screen.queryByText("Alpha App")).toBeNull();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "href",
      "/projects/prj_beta",
    );
  });

  it("never shows another project's identity while project data is loading", () => {
    projectsState.projects = [project()];
    projectsState.loading = true;
    setRoute("/projects/prj_beta", "prj_beta");
    renderShell();

    expect(screen.getByText("Loading project…")).toBeInTheDocument();
    expect(screen.queryByText("Alpha App")).toBeNull();
    expect(screen.queryByText("example/alpha")).toBeNull();
    expect(screen.queryByText("Project unavailable")).toBeNull();
  });

  it("shows no stale identity when a project cannot be resolved", () => {
    projectsState.loading = false;
    setRoute("/projects/prj_missing", "prj_missing");
    renderShell();

    expect(screen.queryByText("Project unavailable")).toBeNull();
    expect(screen.queryByText("Alpha App")).toBeNull();
    expect(screen.getByRole("link", { name: "All projects" })).toHaveAttribute(
      "href",
      "/projects",
    );
  });

  it("resolves a legacy repository id without waiting for project data", () => {
    const repository = "https://github.com/example/legacy-app";
    const id = encodeURIComponent(repository);
    setRoute(`/projects/${id}`, id);
    renderShell();

    const sidebar = screen.getByRole("complementary", {
      name: "Workspace navigation",
    });
    // The short name surfaces in the header; the sidebar carries no identity.
    expect(screen.getByText("legacy-app")).toBeInTheDocument();
    expect(within(sidebar).queryByText("legacy-app")).toBeNull();
    expect(screen.getByRole("link", { name: "Overview" })).toHaveAttribute(
      "href",
      `/projects/${id}`,
    );
  });

  it("truncates long names and exposes their full values", () => {
    const longName = `A very long project name ${"x".repeat(80)}`;
    projectsState.projects = [
      project({
        name: longName,
        repoOwner: "the-very-long-owner-name",
        repoName: `${"repository-".repeat(10)}app`,
      }),
    ];
    setRoute("/projects/prj_alpha", "prj_alpha");
    renderShell();

    const name = screen.getByText(longName);
    expect(name).toHaveAttribute("title", longName);
    expect(name.className).toContain("truncate");
    expect(screen.getByRole("navigation", { name: "Project" })).toBeInTheDocument();
  });

  it("keeps the mobile drawer behavior and closes it with Escape", () => {
    setRoute("/projects");
    renderShell();

    expect(screen.getByRole("button", { name: "Open navigation" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    const sidebar = screen.getByRole("complementary", {
      name: "Workspace navigation",
    });
    expect(screen.queryByRole("button", { name: "Open navigation" })).toBeNull();
    expect(
      within(sidebar).getByRole("button", { name: "Close navigation" }),
    ).toBeInTheDocument();
    expect(sidebar).not.toHaveClass("hidden");

    fireEvent.click(
      within(sidebar).getByRole("button", { name: "Close navigation" }),
    );
    expect(screen.getByRole("button", { name: "Open navigation" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );

    fireEvent.click(screen.getByRole("button", { name: "Open navigation" }));
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Open navigation" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });
});
