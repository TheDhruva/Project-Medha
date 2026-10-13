import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const { pathnameMock, paramsMock } = vi.hoisted(() => ({
  pathnameMock: vi.fn(),
  paramsMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => pathnameMock(),
  useParams: () => paramsMock(),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/projects/projects", async (importOriginal) => {
  const original =
    (await importOriginal()) as typeof import("@/lib/projects/projects");
  return {
    ...original,
    useProjects: () => ({
      projects: [],
      runs: [],
      total: 0,
      loading: false,
      error: null,
      backendReachable: true,
      refresh: vi.fn(),
      createProject: vi.fn(),
    }),
  };
});

import { AppShell } from "@/components/layout/AppShell";

const REMOVED = [
  "Project hub",
  "Try demo",
  "Proposals",
  "New analysis",
  "Research eval",
  "Global settings",
  "Orchestration",
  "Changes & Reviews",
  "Verification",
  "Graphs & Impact",
  "Evaluations",
];

describe("AppShell navigation", () => {
  it("exposes exactly Projects, All runs, and Workspace settings as workspace destinations", () => {
    pathnameMock.mockReturnValue("/projects");
    paramsMock.mockReturnValue({});
    render(
      <AppShell>
        <div>child</div>
      </AppShell>,
    );
    const global = screen.getByRole("navigation", { name: "Workspace" });
    const links = within(global).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual(["Projects", "All runs", "Workspace settings"]);
    for (const label of REMOVED) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });

  it("shows only project destinations in project context, with settings included", () => {
    const id = encodeURIComponent("https://github.com/example/app");
    pathnameMock.mockReturnValue(`/projects/${id}`);
    paramsMock.mockReturnValue({ id });
    render(
      <AppShell>
        <div>child</div>
      </AppShell>,
    );
    const project = screen.getByRole("navigation", { name: "Current project" });
    const links = within(project).getAllByRole("link");
    expect(links.map((l) => l.textContent)).toEqual([
      "Project overview",
      "Project runs",
      "Project settings",
    ]);
    for (const label of REMOVED) {
      expect(screen.queryByText(label)).toBeNull();
    }
  });
});
