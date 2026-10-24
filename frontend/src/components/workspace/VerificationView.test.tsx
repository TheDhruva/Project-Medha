import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { projectData, fetchScoresMock } = vi.hoisted(() => ({
  fetchScoresMock: vi.fn(),
  projectData: {
    repo: "https://github.com/example/app",
    name: "Example App",
    runs: [
      {
        deployment_id: "dep_latest_1234567890",
        status: "completed",
        is_demo: false,
        label: null,
        scenario: null,
        repository_url: "https://github.com/example/app",
        updated_at: "2026-10-20T10:01:00Z",
      },
      {
        deployment_id: "dep_previous_1234567890",
        status: "failed",
        is_demo: false,
        label: null,
        scenario: null,
        repository_url: "https://github.com/example/app",
        updated_at: "2026-10-19T10:01:00Z",
      },
    ],
    loading: false,
    error: null,
    backendReachable: true,
    selectedId: "dep_latest_1234567890",
    selectRun: vi.fn(),
    hydration: {
      logs: [],
      agents: null,
      executionMode: "real",
      constraints: [],
      negotiation: null,
      verification: {
        checks: [
          { id: "yaml", name: "YAML schema", status: "pass", message: "compose file is valid", rule: "compose_schema", category: "schema" },
          { id: "secrets", name: "Secret scan", status: "fail", message: "hardcoded token found", rule: "gitleaks", category: "security" },
          { id: "lint", name: "Lint", status: "warning", message: "3 warnings" },
        ],
        passed: false,
        summary: "1 of 3 checks passed.",
        blocking_failures: ["hardcoded token found"],
        warnings: ["3 warnings"],
      },
      critic: {
        score: 76,
        recommendation: "WARN",
        findings: ["Token found in config"],
        breakdown: { security: 60, completeness: 80, constraints: 90, intentAlignment: 70 },
        summary: "Fix before deploying.",
      },
      graph: { nodes: [], edges: [] },
      rollback: null,
      changeImpact: null,
      changeImpactLabel: null,
      changeImpactIsDemo: false,
      health: null,
      runtimeLogs: null,
    },
    hydrating: false,
    refresh: vi.fn(),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(""),
}));

vi.mock("@/components/layout/AppShell", () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/lib/projects/useProjectData", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/projects/useProjectData");
  return { ...original, useProjectData: () => projectData };
});

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/api/client");
  return { ...original, fetchScores: fetchScoresMock };
});

import { VerificationView } from "@/components/workspace/ProjectSections";

afterEach(() => {
  fetchScoresMock.mockReset();
});

describe("VerificationView", () => {
  it("shows a compact plain header with no internal run IDs", async () => {
    fetchScoresMock.mockResolvedValue({
      deployment_id: "dep_latest_1234567890",
      is_demo: false,
      label: null,
      scores: {},
    });
    render(<VerificationView projectId="prj_test" />);

    expect(screen.getByRole("heading", { name: "Verification" })).toBeInTheDocument();
    const stamp = document.querySelector("time");
    expect(stamp?.textContent).toMatch(/ · \d{1,2}:\d{2} (AM|PM)$/);

    // Internal IDs stay in routing/values, never in visible labels.
    expect(document.body.textContent).not.toMatch(/dep_/);
    const select = screen.getByRole("combobox");
    const options = within(select).getAllByRole("option");
    expect(options).toHaveLength(2);
    for (const option of options) {
      expect(option.textContent).toMatch(/— (Passed|Failed|Running|Not run)$/);
      expect(option.textContent).not.toMatch(/dep_/);
    }

    // Scores summary and findings sit side by side; honest "Not measured"
    // for empty score data.
    expect(await screen.findByText("Your scores")).toBeInTheDocument();
    expect(screen.getByText("Findings")).toBeInTheDocument();
    expect((await screen.findAllByText("Not measured")).length).toBeGreaterThan(0);
    expect(screen.getByText("No score evidence was stored for this run.")).toBeInTheDocument();
  });

  it("keeps all checks collapsed by default with the real result visible", async () => {
    fetchScoresMock.mockResolvedValue({
      deployment_id: "dep_latest_1234567890",
      is_demo: false,
      label: null,
      scores: {},
    });
    render(<VerificationView projectId="prj_test" />);

    // The summary row shows the actual outcome — failures are never hidden
    // behind a success state.
    expect(await screen.findByText(/1\/3 passed/)).toBeInTheDocument();
    expect(screen.getByText("· 1 failed")).toBeInTheDocument();
    expect(screen.getByText("· 1 to review")).toBeInTheDocument();
    expect(screen.getAllByText("Failed").length).toBeGreaterThan(0);

    const details = document.getElementById("checks") as HTMLDetailsElement;
    expect(details.tagName).toBe("DETAILS");
    expect(details).not.toHaveAttribute("open");

    // Every check stays accessible behind the expand control.
    fireEvent.click(screen.getByText("Verification checks"));
    expect(details).toHaveAttribute("open");
    expect(screen.getByText("YAML schema")).toBeInTheDocument();
    expect(screen.getByText("Secret scan")).toBeInTheDocument();
    expect(screen.getByText("Lint")).toBeInTheDocument();
    expect((await screen.findAllByText("hardcoded token found")).length).toBeGreaterThan(0);
    expect(screen.getByText("Technical details")).toBeInTheDocument();
  });

  it("keeps the AI review recommendation visible with details collapsed", async () => {
    fetchScoresMock.mockResolvedValue({
      deployment_id: "dep_latest_1234567890",
      is_demo: false,
      label: null,
      scores: {},
    });
    render(<VerificationView projectId="prj_test" />);

    expect(await screen.findByText("Review advised")).toBeInTheDocument();
    expect(screen.getByText("AI score 76/100")).toBeInTheDocument();
    expect(screen.getByText("Token found in config")).toBeInTheDocument();
    // Breakdown labels are plain English and live inside the collapsed section.
    expect(screen.getByText("Matches the request")).toBeInTheDocument();
    expect(screen.getByText("More about this review")).toBeInTheDocument();
  });
});
