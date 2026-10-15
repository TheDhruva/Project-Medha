import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { DecisionCard, SummaryRow } from "@/components/run-detail/Cards";
import { createIdleSnapshot } from "@/lib/demo/frames";
import type { DeploymentSnapshot } from "@/lib/demo/types";

vi.mock("@/components/ui/Section", () => ({
  EnvBadge: ({ isDemo }: { isDemo: boolean }) => <span>{isDemo ? "DEMO" : "LIVE"}</span>,
  ExecutionModeBadge: ({ mode }: { mode: string | null }) => <span>{mode ?? "UNKNOWN"}</span>,
  Section: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  Collapsible: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  StatusBadge: ({ children }: { children: React.ReactNode }) => <span>{children}</span>,
}));

function snap(overrides: Partial<DeploymentSnapshot>): DeploymentSnapshot {
  return { ...createIdleSnapshot(), ...overrides };
}

const noop = () => {};

describe("DecisionCard", () => {
  it("approves a succeeded run with its score", () => {
    render(
      <DecisionCard
        snapshot={snap({
          runStatus: "succeeded",
          isDemo: true,
          critic: {
            score: 92,
            breakdown: { security: 90, completeness: 90, constraints: 95, intentAlignment: 90 },
            recommendation: "PASS",
            findings: ["ok"],
          },
          result: {
            kind: "success",
            title: "SUCCESS",
            message: "All required verification checks passed.",
            durationLabel: "7.2s",
            servicesLabel: "5 / 5",
            verificationScore: 92,
            constraintsResolved: 1,
            rollbackScope: null,
          },
        })}
        onViewEvidence={noop}
        onViewRecovery={noop}
      />,
    );
    expect(screen.getByText("Deployment approved")).toBeInTheDocument();
    expect(screen.getByText("92")).toBeInTheDocument();
    expect(screen.getByText("DEMO")).toBeInTheDocument();
  });

  it("shows Not evaluated yet instead of a contradictory 0 / 100", () => {
    render(
      <DecisionCard
        snapshot={snap({
          runStatus: "succeeded",
          isDemo: false,
          critic: {
            score: 0,
            breakdown: { security: 0, completeness: 0, constraints: 0, intentAlignment: 0 },
            recommendation: "PASS",
            findings: [],
          },
          result: {
            kind: "success",
            title: "SUCCESS",
            message: "done",
            durationLabel: "—",
            servicesLabel: "see graph",
            verificationScore: null,
            constraintsResolved: 0,
            rollbackScope: null,
          },
        })}
        onViewEvidence={noop}
        onViewRecovery={noop}
      />,
    );
    expect(screen.getByText("Not evaluated yet")).toBeInTheDocument();
    expect(screen.getByText("LIVE")).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("blocks failed runs and recovers partial runs honestly", () => {
    const { rerender } = render(
      <DecisionCard
        snapshot={snap({
          runStatus: "failed",
          result: {
            kind: "failed",
            title: "FAILED",
            message: "A blocking security constraint remains unresolved.",
            durationLabel: "—",
            servicesLabel: "n/a",
            verificationScore: null,
            constraintsResolved: 0,
            rollbackScope: null,
          },
        })}
        onViewEvidence={noop}
        onViewRecovery={noop}
      />,
    );
    expect(screen.getByText("Deployment blocked")).toBeInTheDocument();

    rerender(
      <DecisionCard
        snapshot={snap({
          runStatus: "partial_recovery",
          rollback: {
            headline: "SCOPED",
            preserved: 3,
            failed: 1,
            rolledBack: 1,
            details: [],
            scopeNodeIds: ["a"],
            simpleExplanation: "Affected dependencies were rolled back.",
          },
        })}
        onViewEvidence={noop}
        onViewRecovery={noop}
      />,
    );
    expect(screen.getByText("Deployment recovered")).toBeInTheDocument();
  });
});

describe("SummaryRow", () => {
  it("renders nothing when no metrics exist", () => {
    const { container } = render(<SummaryRow snapshot={snap({ changeIntel: null, verification: null })} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("separates measured duration from execution mode", () => {
    // Regression: result.durationLabel ("real") rendered as "Duration: real".
    render(
      <SummaryRow
        snapshot={snap({
          changeIntel: null,
          verification: null,
          executionMode: "real",
          durationSeconds: 90,
          negotiation: {
            title: "CNP",
            conflictSummary: "none",
            round: 1,
            maxRounds: 3,
            status: "resolved",
            involvedConstraintIds: [],
            simpleExplanation: "ok",
          },
        })}
      />,
    );
    expect(screen.getByText("Mode")).toBeInTheDocument();
    expect(screen.getByText("Real")).toBeInTheDocument();
    expect(screen.getByText("Duration")).toBeInTheDocument();
    expect(screen.getByText("1m 30s")).toBeInTheDocument();
    expect(screen.queryByText("real", { exact: true })).not.toBeInTheDocument();
  });

  it("shows an honest unavailable duration when unmeasured", () => {
    render(
      <SummaryRow
        snapshot={snap({
          changeIntel: null,
          verification: null,
          executionMode: "simulator",
          durationSeconds: null,
          constraints: [
            {
              id: "c1",
              type: "PORT_CLAIM",
              priority: "RESOURCE",
              sourceAgent: "Docker",
              summary: "port",
              detail: "d",
              status: "accepted",
            },
          ],
        })}
      />,
    );
    expect(screen.getByText("Simulated")).toBeInTheDocument();
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});
