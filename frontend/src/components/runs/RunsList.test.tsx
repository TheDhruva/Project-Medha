import { render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { RunsList } from "@/components/runs/RunsList";
import { fetchRunsList } from "@/lib/api/client";

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = (await importOriginal()) as Record<string, unknown>;
  return {
    ...original,
    fetchRunsList: vi.fn(),
    checkBackendHealth: vi.fn().mockResolvedValue(true),
  };
});

const run = {
  deployment_id: "dep_1",
  status: "completed",
  mode: "demo",
  is_demo: true,
  label: "DEMO/MOCK",
  scenario: "PARTIAL_FAILURE" as const,
  repository_url: "https://github.com/example/medha-sample-app",
  intent: "Deploy",
  base_revision: "abc1234",
  target_revision: "def5678",
  current_stage: "COMPLETE",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:42Z",
  duration_seconds: 42,
  risk: "high",
  result_kind: "partial_recovery",
  error_summary: null,
};

describe("RunsList", () => {
  beforeEach(() => {
    vi.mocked(fetchRunsList).mockReset();
  });

  it("shows a loading state before results arrive", () => {
    vi.mocked(fetchRunsList).mockReturnValue(new Promise(() => {}));
    render(<RunsList />);
    expect(screen.getByText(/Loading runs/)).toBeInTheDocument();
  });

  it("renders runs with DEMO label, status badge and row link", async () => {
    vi.mocked(fetchRunsList).mockResolvedValue({
      runs: [run],
      total: 1,
      limit: 50,
      offset: 0,
      filters: { status: null, mode: null, repository: null },
    });
    render(<RunsList />);
    const link = await screen.findByRole("link", { name: /Partial Failure/ });
    expect(link).toBeInTheDocument();
    expect(link.getAttribute("href")).toBe("/runs/dep_1");
    expect(within(link).getByText("DEMO")).toBeInTheDocument();
    expect(within(link).getByText(/Completed/)).toBeInTheDocument();
  });

  it("shows the backend error message when the fetch fails", async () => {
    vi.mocked(fetchRunsList).mockRejectedValue(new Error("backend exploded"));
    render(<RunsList />);
    await screen.findByRole("alert");
    expect(screen.getByText(/backend exploded/)).toBeInTheDocument();
  });

  it("shows an empty state when no runs exist", async () => {
    vi.mocked(fetchRunsList).mockResolvedValue({
      runs: [],
      total: 0,
      limit: 50,
      offset: 0,
      filters: { status: null, mode: null, repository: null },
    });
    render(<RunsList />);
    await waitFor(() => expect(screen.queryByText(/Loading runs/)).not.toBeInTheDocument());
    expect(screen.getByText("No runs yet.")).toBeInTheDocument();
  });
});