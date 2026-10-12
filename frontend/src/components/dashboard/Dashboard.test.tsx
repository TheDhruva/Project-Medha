import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { fetchRunsList } from "@/lib/api/client";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = (await importOriginal()) as Record<string, unknown>;
  return { ...original, fetchRunsList: vi.fn() };
});

// Dashboard reads live deployment state via context (same pattern as
// StartVerificationFlow.test.tsx): provide the real idle snapshot the
// provider guarantees, so the overview renders deterministically.
const { mockDeployment } = vi.hoisted(() => ({ mockDeployment: vi.fn() }));

vi.mock("@/context/DeploymentContext", async (importOriginal) => {
  const { createIdleSnapshot } = await import("@/lib/demo/frames");
  return {
    DeploymentProvider: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
    useOptionalDeployment: () => mockDeployment(),
    useDeployment: () => ({ snapshot: createIdleSnapshot() }),
  };
});

describe("Overview", () => {
  beforeEach(() => {
    mockDeployment.mockReturnValue(null);
    vi.mocked(fetchRunsList).mockResolvedValue({
      runs: [],
      total: 0,
      limit: 3,
      offset: 0,
      filters: { status: null, mode: null, repository: null },
    });
  });

  it("explains the project in plain language with its live mode badge", () => {
    render(<Dashboard />);
    expect(screen.getByRole("heading", { name: "My Project" })).toBeInTheDocument();
    expect(screen.getByText(/Repository on /)).toBeInTheDocument();
    // Idle (non-demo) state is labelled honestly as local execution.
    expect(screen.getByText("LIVE · LOCAL")).toBeInTheDocument();
    expect(screen.queryByText(/DEMO · SIMULATED/)).not.toBeInTheDocument();
  });

  it("labels demo execution distinctly with its primary new-run action", () => {
    mockDeployment.mockReturnValue({
      form: { mode: "demo", repositoryUrl: "https://github.com/atlas-labs/atlas-commerce", baseRevision: "main" },
    });
    render(<Dashboard />);
    expect(screen.getByText("DEMO · SIMULATED")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "New run" })).toBeInTheDocument();
  });

  it("shows the pipeline stages without protocol jargon by default", async () => {
    render(<Dashboard />);
    // Plain-language stage panels are visible. The execution graph is
    // lazy-loaded (dynamic import), so its heading resolves asynchronously.
    for (const panel of ["CONSTRAINT NEGOTIATION", "VERIFICATION"]) {
      expect(screen.getByRole("heading", { name: panel })).toBeInTheDocument();
    }
    expect(
      await screen.findByRole("heading", { name: "CAUSAL EXECUTION GRAPH" }),
    ).toBeInTheDocument();
    // Protocol-level jargon stays out of the default overview.
    expect(screen.queryByText(/Constraint Negotiation Protocol/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Change Impact Graph/)).not.toBeInTheDocument();
  });
});
