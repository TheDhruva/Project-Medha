import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import { MetricCard } from "@/components/workspace/MetricCard";
import type { ScorecardMetric } from "@/lib/projects/metrics";

beforeAll(() => {
  if (!window.matchMedia) {
    window.matchMedia = () => ({
      matches: true,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      media: "",
      onchange: null,
      dispatchEvent: () => false,
    }) as MediaQueryList;
  }
});

function metric(overrides: Partial<ScorecardMetric> = {}): ScorecardMetric {
  return {
    id: "security",
    title: "Security Posture",
    value: 72,
    evidence: "1 high-severity finding",
    status: "warning",
    statusLabel: "Needs attention",
    coverage: { assessed: 8, applicable: 10 },
    assessedAt: "2026-01-01T00:01:00Z",
    revision: "deadbeef",
    stale: false,
    refreshing: false,
    isDemo: false,
    href: "/projects/prj_1/verification?run=dep_1",
    ...overrides,
  };
}

describe("MetricCard", () => {
  it("shows the real score, status and findings link on a compact card", () => {
    render(<MetricCard metric={metric()} />);
    expect(screen.getByText("Security Posture")).toBeInTheDocument();
    expect(screen.getByText("72/100")).toBeInTheDocument();
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText(/View findings/)).toBeInTheDocument();

    // Compact card: no prose, coverage or revision lines as visible text.
    expect(screen.queryByText("1 high-severity finding")).not.toBeInTheDocument();
    expect(screen.queryByText(/Checks completed/)).not.toBeInTheDocument();
    expect(screen.queryByText(/deadbeef/)).not.toBeInTheDocument();

    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("href", "/projects/prj_1/verification?run=dep_1");
    // Evidence, coverage and assessment context stay accessible to screen readers.
    expect(link).toHaveAttribute(
      "aria-label",
      expect.stringContaining("1 high-severity finding"),
    );
    expect(link).toHaveAttribute(
      "aria-label",
      expect.stringContaining("Checks completed: 8/10 checks"),
    );
  });

  it("renders an honest not-assessed state instead of a perfect score", () => {
    render(
      <MetricCard
        metric={metric({
          value: null,
          evidence: "Not assessed: no security scanner completed.",
          status: "not_assessed",
          statusLabel: "Not assessed",
          coverage: { assessed: 0, applicable: 4 },
        })}
      />,
    );
    expect(screen.getAllByText("Not assessed").length).toBeGreaterThan(0);
    expect(screen.queryByText("100/100")).not.toBeInTheDocument();
    const link = screen.getByRole("link");
    expect(link).toHaveAttribute("data-status", "not_assessed");
    expect(link).toHaveAttribute(
      "aria-label",
      expect.stringContaining("no security scanner completed"),
    );
  });

  it("marks stale results and demo runs visibly", () => {
    render(
      <MetricCard
        metric={metric({ isDemo: true, stale: true, status: "stale", statusLabel: "Stale assessment" })}
      />,
    );
    expect(screen.getByText("DEMO")).toBeInTheDocument();
    expect(screen.getByText("Stale assessment")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("data-status", "stale");
  });
});
