import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScoreExplanationModal } from "./ScoreExplanationModal";
import type { ScorecardMetric } from "@/lib/projects/metrics";

function makeMetric(id: ScorecardMetric["id"], value: number | null): ScorecardMetric {
  return {
    id,
    title:
      id === "code-quality"
        ? "Code Quality"
        : id === "security"
          ? "Security Posture"
          : id === "verification"
            ? "Verification Confidence"
            : "Deployment Readiness",
    value,
    evidence: "Passed 12 of 14 static checks without critical severity issues",
    status: value != null && value >= 80 ? "healthy" : "warning",
    statusLabel: "Assessed",
    coverage: { assessed: 12, applicable: 14 },
    assessedAt: "2026-10-29T10:00:00Z",
    revision: "a1b2c3d",
    stale: false,
    refreshing: false,
    isDemo: false,
    href: "/projects/prj_1/verification",
  };
}

describe("ScoreExplanationModal", () => {
  it("explains Code Quality with all required sections in plain language", () => {
    const onClose = vi.fn();
    render(
      <ScoreExplanationModal
        metric={makeMetric("code-quality", 88)}
        onClose={onClose}
        previousValue={82}
      />,
    );

    expect(screen.getByText("Code Quality")).toBeInTheDocument();
    expect(screen.getByText("88/100")).toBeInTheDocument();
    expect(screen.getByText("+6 points")).toBeInTheDocument();
    expect(screen.getByText("What this score means")).toBeInTheDocument();
    expect(screen.getByText(/maintainability, structural clarity/)).toBeInTheDocument();
    expect(screen.getByText("Scoring factors & evidence")).toBeInTheDocument();
    expect(screen.getByText(/Passed 12 of 14 static checks/)).toBeInTheDocument();
    expect(screen.getByText("What could not be checked")).toBeInTheDocument();
    expect(screen.getByText("How to improve this score")).toBeInTheDocument();

    const closeBtn = screen.getAllByRole("button", { name: "Close" })[0];
    fireEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it("explains Security Posture and notes that clean score does not guarantee zero risk", () => {
    render(
      <ScoreExplanationModal
        metric={makeMetric("security", 95)}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Security Posture")).toBeInTheDocument();
    expect(screen.getByText(/Static scanning cannot detect all runtime/)).toBeInTheDocument();
    expect(screen.getByText(/Rotate any credentials/)).toBeInTheDocument();
  });

  it("explains Deployment Readiness and why Docker or non-deployable apps block readiness", () => {
    render(
      <ScoreExplanationModal
        metric={makeMetric("readiness", null)}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByText("Deployment Readiness")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
    expect(screen.getByText(/If Docker is not running or the project is a standalone library/)).toBeInTheDocument();
    expect(screen.getByText(/Ensure Docker Desktop or the container runtime/)).toBeInTheDocument();
  });
});
