import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { Dashboard } from "@/components/dashboard/Dashboard";
import { fetchRunsList } from "@/lib/api/client";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = (await importOriginal()) as Record<string, unknown>;
  return { ...original, fetchRunsList: vi.fn() };
});

describe("Overview", () => {
  beforeEach(() => {
    vi.mocked(fetchRunsList).mockResolvedValue({
      runs: [],
      total: 0,
      limit: 3,
      offset: 0,
      filters: { status: null, mode: null, repository: null },
    });
  });

  it("explains Medha in plain language with a primary action", () => {
    render(<Dashboard />);
    expect(screen.getByRole("heading", { name: "MEDHA" })).toBeInTheDocument();
    expect(
      screen.getByText("Deploy infrastructure changes with confidence."),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Start verification/ })).toHaveAttribute(
      "href",
      "/verify",
    );
  });

  it("shows the four-step flow without technical jargon by default", () => {
    render(<Dashboard />);
    for (const step of ["Analyze", "Resolve", "Verify", "Deploy"]) {
      expect(screen.getAllByText(step).length).toBeGreaterThan(0);
    }
    // Global navigation (Verify, Runs, …) lives in AppShell's sidebar, not in
    // this legacy panel — the primary entry point stays on the /verify route.
    expect(screen.getByRole("link", { name: /Start verification/ })).toHaveAttribute(
      "href",
      "/verify",
    );
    expect(screen.queryByText(/Constraint Negotiation Protocol/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Causal Execution Graph/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Change Impact Graph/)).not.toBeInTheDocument();
  });
});
