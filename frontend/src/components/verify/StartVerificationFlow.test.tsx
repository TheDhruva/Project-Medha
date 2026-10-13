import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/verify",
  useParams: () => ({}),
}));

const { setFormMock, startDeploymentMock } = vi.hoisted(() => ({
  setFormMock: vi.fn(),
  startDeploymentMock: vi.fn(),
}));

vi.mock("@/context/DeploymentContext", () => ({
  DeploymentProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  useOptionalDeployment: () => null,
  useDeployment: () => ({
    form: {
      repositoryUrl: "https://github.com/example/app",
      targetHost: "localhost",
      targetPort: "8080",
      intent: "Deploy",
      scenario: "PORT_CONFLICT",
      mode: "real",
      baseRevision: "",
      targetRevision: "",
    },
    setForm: setFormMock,
    startDeployment: startDeploymentMock,
    isRunning: false,
    snapshot: { deploymentId: null, runStatus: "idle" },
    connectionError: null,
  }),
}));

import { StartVerificationFlow } from "@/components/verify/StartVerificationFlow";

describe("StartVerificationFlow", () => {
  beforeEach(() => {
    push.mockClear();
    setFormMock.mockClear();
    startDeploymentMock.mockClear();
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
});
