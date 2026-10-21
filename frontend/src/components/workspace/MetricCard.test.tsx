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
  it("shows the real score, status, explanation, coverage and findings link", () => {
    render(<MetricCard metric={metric()} />);
    expect(screen.getByText("Security Posture")).toBeInTheDocument();
    expect(screen.getByText("72/100")).toBeInTheDocument();
    expect(screen.getByText("Needs attention")).toBeInTheDocument();
    expect(screen.getByText("1 high-severity finding")).toBeInTheDocument();
    expect(screen.getByText("Assessment coverage: 8/10 checks")).toBeInTheDocument();
    expect(screen.getByText(/View findings/)).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/projects/prj_1/verification?run=dep_1",
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
    expect(screen.getByText(/no security scanner completed/)).toBeInTheDocument();
  });

  it("marks stale results and demo runs visibly", () => {
    render(
      <MetricCard
        metric={metric({ isDemo: true, stale: true, status: "stale", statusLabel: "Stale assessment" })}
      />,
    );
    expect(screen.getByText("DEMO")).toBeInTheDocument();
    expect(screen.getByText("Stale assessment")).toBeInTheDocument();
    expect(screen.getByText(/not current revision/)).toBeInTheDocument();
  });
});
