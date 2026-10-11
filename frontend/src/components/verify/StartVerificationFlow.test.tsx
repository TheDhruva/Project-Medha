import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

const push = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => "/verify",
  useParams: () => ({}),
}));

const { setFormMock } = vi.hoisted(() => ({ setFormMock: vi.fn() }));

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
      mode: "demo",
      baseRevision: "",
      targetRevision: "",
    },
    setForm: setFormMock,
    startDeployment: vi.fn(),
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
  });

  it("asks what to verify with two clear choices", () => {
    render(<StartVerificationFlow />);
    expect(screen.getByText("What would you like to verify?")).toBeInTheDocument();
    expect(screen.getByText("Demo scenario")).toBeInTheDocument();
    expect(screen.getByText("Git change")).toBeInTheDocument();
  });

  it("opens the demo scenario picker without advanced host/port fields", () => {
    render(<StartVerificationFlow />);
    fireEvent.click(screen.getByText("Demo scenario"));
    expect(screen.getByText("Choose scenario")).toBeInTheDocument();
    expect(screen.getByText("Port Conflict")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Target host/)).not.toBeInTheDocument();
  });

  it("opens the git flow with collapsed advanced options", () => {
    render(<StartVerificationFlow />);
    fireEvent.click(screen.getByText("Git change"));
    expect(screen.getByLabelText("Repository")).toBeInTheDocument();
    expect(screen.getByLabelText("Base revision")).toBeInTheDocument();
    expect(screen.getByText("Advanced options")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Target host/)).not.toBeInTheDocument();
  });

  it("wires revision inputs into the deployment form", () => {
    render(<StartVerificationFlow />);
    fireEvent.click(screen.getByText("Git change"));
    fireEvent.change(screen.getByLabelText("Base revision"), {
      target: { value: "main" },
    });
    fireEvent.change(screen.getByLabelText("Target revision"), {
      target: { value: "HEAD" },
    });
    expect(setFormMock).toHaveBeenCalledWith({ baseRevision: "main" });
    expect(setFormMock).toHaveBeenCalledWith({ targetRevision: "HEAD" });
  });
});
