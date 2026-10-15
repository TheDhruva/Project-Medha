import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const push = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/verify",
  useParams: () => ({}),
  useSearchParams: () => new URLSearchParams(search),
}));

const { setFormMock, startDeploymentMock, createProjectRunMock, fetchProjectMock, sharedForm } =
  vi.hoisted(() => ({
    setFormMock: vi.fn(),
    startDeploymentMock: vi.fn(),
    createProjectRunMock: vi.fn(),
    fetchProjectMock: vi.fn(),
    sharedForm: {
      repositoryUrl: "https://github.com/example/app",
      targetHost: "localhost",
      targetPort: "8080",
      intent: "Deploy",
      scenario: "PORT_CONFLICT",
      mode: "real",
      baseRevision: "",
      targetRevision: "",
    },
  }));

vi.mock("@/context/DeploymentContext", () => ({
  DeploymentProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useOptionalDeployment: () => null,
  useDeployment: () => ({
    // Mutable shared state: setForm updates it so submit-time reads see the
    // values fireEvent.change wrote (the component itself does not re-render).
    form: sharedForm,
    setForm: (patch: Record<string, unknown>) => {
      setFormMock(patch);
      Object.assign(sharedForm, patch);
    },
    startDeployment: startDeploymentMock,
    isRunning: false,
    snapshot: { deploymentId: null, runStatus: "idle" },
    connectionError: null,
  }),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    fetchProject: (...args: unknown[]) => fetchProjectMock(...args),
    fetchConfigStatus: vi.fn().mockResolvedValue(null),
    createProjectRun: (...args: unknown[]) => createProjectRunMock(...args),
  };
});

import { StartVerificationFlow } from "@/components/verify/StartVerificationFlow";

describe("StartVerificationFlow", () => {
  beforeEach(() => {
    push.mockClear();
    setFormMock.mockClear();
    startDeploymentMock.mockClear();
    createProjectRunMock.mockClear();
    fetchProjectMock.mockClear();
    Object.assign(sharedForm, { baseRevision: "", targetRevision: "" });
    fetchProjectMock.mockResolvedValue({
      project_id: "prj_test",
      repository: "https://github.com/example/locked",
    });
    createProjectRunMock.mockResolvedValue({ deployment_id: "dep_123", project_id: "prj_test" });
    search = "";
  });

  it("renders the real-repository analysis form with no demo choice", () => {
    render(<StartVerificationFlow />);
    expect(screen.getByText("New analysis")).toBeInTheDocument();
    expect(screen.getByLabelText("Repository")).toBeInTheDocument();
    expect(screen.getByLabelText("Base revision")).toBeInTheDocument();
    expect(screen.queryByText("Demo scenario")).not.toBeInTheDocument();
  });

  it("forces real mode on mount", () => {
    render(<StartVerificationFlow />);
    expect(setFormMock).toHaveBeenCalledWith({ mode: "real" });
  });

  it("keeps advanced options collapsed by default", () => {
    render(<StartVerificationFlow />);
    expect(screen.getByText("Advanced options")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Target host/)).not.toBeInTheDocument();
  });

  it("wires revision inputs into the deployment form", () => {
    render(<StartVerificationFlow />);
    fireEvent.change(screen.getByLabelText("Base revision"), {
      target: { value: "main" },
    });
    fireEvent.change(screen.getByLabelText("Target revision"), {
      target: { value: "HEAD" },
    });
    expect(setFormMock).toHaveBeenCalledWith({ baseRevision: "main" });
    expect(setFormMock).toHaveBeenCalledWith({ targetRevision: "HEAD" });
  });

  it("starts a real analysis from the form", () => {
    render(<StartVerificationFlow />);
    fireEvent.click(screen.getByText("Analyze change"));
    expect(startDeploymentMock).toHaveBeenCalled();
  });

  it("rejects non-40-hex revisions before calling the API", () => {
    render(<StartVerificationFlow />);
    fireEvent.change(screen.getByLabelText("Base revision"), {
      target: { value: "main" },
    });
    fireEvent.click(screen.getByText("Analyze change"));
    expect(screen.getByText(/full 40-character commit SHA/)).toBeInTheDocument();
    expect(startDeploymentMock).not.toHaveBeenCalled();
  });

  describe("project-locked mode (?project=)", () => {
    beforeEach(() => {
      search = "project=prj_test";
    });

    it("locks the repository to the project's stored identity", async () => {
      render(<StartVerificationFlow />);
      await waitFor(() =>
        expect(screen.getByLabelText("Repository")).toHaveValue(
          "https://github.com/example/locked",
        ),
      );
      expect(screen.getByLabelText("Repository")).toHaveAttribute("readonly");
      expect(screen.getByText(/Locked to this project/)).toBeInTheDocument();
    });

    it("creates a project-bound run instead of a bare deployment", async () => {
      render(<StartVerificationFlow />);
      await waitFor(() => expect(fetchProjectMock).toHaveBeenCalledWith("prj_test"));
      fireEvent.click(screen.getByText("Analyze change"));
      await waitFor(() =>
        expect(createProjectRunMock).toHaveBeenCalledWith(
          "prj_test",
          expect.objectContaining({ intent: "Deploy" }),
        ),
      );
      expect(startDeploymentMock).not.toHaveBeenCalled();
      await waitFor(() => expect(push).toHaveBeenCalledWith("/projects/prj_test/runs/dep_123"));
    });

    it("rejects non-40-hex revisions with an actionable message", async () => {
      render(<StartVerificationFlow />);
      await waitFor(() => expect(fetchProjectMock).toHaveBeenCalled());
      fireEvent.change(screen.getByLabelText("Base revision"), {
        target: { value: "main" },
      });
      fireEvent.click(screen.getByText("Analyze change"));
      expect(await screen.findByText(/full 40-character commit SHA/)).toBeInTheDocument();
      expect(createProjectRunMock).not.toHaveBeenCalled();
      expect(startDeploymentMock).not.toHaveBeenCalled();
    });
  });
});
