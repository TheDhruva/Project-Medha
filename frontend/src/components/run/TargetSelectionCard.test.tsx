import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { TargetSelectionCard } from "@/components/run/TargetSelectionCard";
import { createIdleSnapshot } from "@/lib/demo/frames";
import type { DeploymentSnapshot } from "@/lib/demo/types";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
}));

const { updateProjectMock, createProjectRunMock, fetchProjectTargetsMock } =
  vi.hoisted(() => ({
    updateProjectMock: vi.fn(),
    createProjectRunMock: vi.fn(),
    fetchProjectTargetsMock: vi.fn(),
  }));

vi.mock("@/lib/api/client", () => ({
  updateProject: (...args: unknown[]) => updateProjectMock(...args),
  createProjectRun: (...args: unknown[]) => createProjectRunMock(...args),
  fetchProjectTargets: (...args: unknown[]) =>
    fetchProjectTargetsMock(...args),
}));

function snap(overrides: Partial<DeploymentSnapshot>): DeploymentSnapshot {
  return { ...createIdleSnapshot(), ...overrides };
}

function blockedSnap(): DeploymentSnapshot {
  return snap({
    runStatus: "failed",
    result: {
      kind: "failed",
      title: "MULTIPLE_APPS_REQUIRE_TARGET",
      message:
        "Multiple applications detected in this repository. Choose one explicit deployment target before MEDHA can plan.",
      durationLabel: "analyze",
      servicesLabel: "0 / 0 started",
      verificationScore: null,
      constraintsResolved: 0,
      rollbackScope: null,
      code: "MULTIPLE_APPS_REQUIRE_TARGET",
      target_selection: {
        candidates: [
          {
            path: "backend",
            technologies: ["python-fastapi"],
            evidence: ["backend/requirements.txt"],
          },
          {
            path: "frontend",
            technologies: ["node-frontend"],
            evidence: ["frontend/package.json"],
          },
        ],
        relationship: "fullstack",
        reason: "full-stack pair requires an explicit single-service target",
        next_actions: ["select_target", "reanalyze"],
        supported_targets: ["backend", "frontend"],
        selected_target: null,
        project_id: "prj_1",
      },
    },
  });
}

describe("TargetSelectionCard", () => {
  beforeEach(() => {
    push.mockClear();
    updateProjectMock.mockClear();
    createProjectRunMock.mockClear();
    fetchProjectTargetsMock.mockClear();
    updateProjectMock.mockResolvedValue({ project_id: "prj_1" });
    createProjectRunMock.mockResolvedValue({
      deployment_id: "dep_new",
      project_id: "prj_1",
    });
  });

  it("stays hidden for non-target failures", () => {
    const { container } = render(
      <TargetSelectionCard
        snapshot={snap({ runStatus: "failed" })}
        deploymentId="dep_old"
        projectId="prj_1"
      />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(fetchProjectTargetsMock).not.toHaveBeenCalled();
  });

  it("lists detected applications with their stacks", () => {
    render(
      <TargetSelectionCard
        snapshot={blockedSnap()}
        deploymentId="dep_old"
        projectId="prj_1"
      />,
    );
    expect(
      screen.getByText("Choose one application to deploy"),
    ).toBeInTheDocument();
    expect(screen.getByText("backend")).toBeInTheDocument();
    expect(screen.getByText("frontend")).toBeInTheDocument();
    expect(screen.getByText("python-fastapi")).toBeInTheDocument();
  });

  it("saves the target and retries with it explicitly", async () => {
    render(
      <TargetSelectionCard
        snapshot={blockedSnap()}
        deploymentId="dep_old"
        projectId="prj_1"
      />,
    );
    fireEvent.click(screen.getByText("backend"));
    fireEvent.click(screen.getByText("Save target & retry"));
    await waitFor(() =>
      expect(updateProjectMock).toHaveBeenCalledWith("prj_1", {
        deploy_target: "backend",
      }),
    );
    await waitFor(() =>
      expect(createProjectRunMock).toHaveBeenCalledWith("prj_1", {
        deployment_target: "backend",
      }),
    );
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith("/projects/prj_1/runs/dep_new"),
    );
  });

  it("shows the repository-analysis report when deployment is blocked", () => {
    const base = blockedSnap();
    render(
      <TargetSelectionCard
        snapshot={{
          ...base,
          result: base.result
            ? {
                ...base.result,
                analysis_status: "completed",
                deployment_status: "blocked",
                repository_analysis: {
                  analysis_status: "completed",
                  applications: [{ path: "backend" }, { path: "frontend" }],
                  languages: [{ language: "python" }, { language: "javascript" }],
                  coverage: { gaps: ["security:gitleaks: unavailable"] },
                },
              }
            : base.result,
        }}
        deploymentId="dep_old"
        projectId="prj_1"
      />,
    );
    expect(screen.getByText("Repository analysis")).toBeInTheDocument();
    expect(
      screen.getByText(/Analysis completed across 2 applications/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/python, javascript/)).toBeInTheDocument();
  });

  it("falls back to project targets when the run has no candidates", async () => {
    fetchProjectTargetsMock.mockResolvedValue({
      project_id: "prj_1",
      deploy_target: null,
      candidates: [
        { path: "api", technologies: ["node"], evidence: ["api/package.json"] },
      ],
      relationship: "single",
      source_run: "dep_old",
      note: "one target",
    });
    const legacy = blockedSnap();
    render(
      <TargetSelectionCard
        snapshot={{
          ...legacy,
          result: legacy.result
            ? { ...legacy.result, target_selection: { candidates: [] } }
            : legacy.result,
        }}
        deploymentId="dep_old"
        projectId="prj_1"
      />,
    );
    expect(await screen.findByText("api")).toBeInTheDocument();
  });
});
