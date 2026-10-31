import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  HumanProgressView,
  deriveProgressPhases,
  parsePlainLanguageError,
} from "./HumanProgressView";
import type { DeploymentSnapshot } from "@/lib/demo/types";

function mockSnapshot(overrides: Partial<DeploymentSnapshot> = {}): DeploymentSnapshot {
  return {
    deploymentId: "dep_test_1",
    isDemo: false,
    executionMode: "real",
    runtimeLogs: null,
    scenario: null,
    runStatus: "succeeded",
    durationSeconds: 2,
    explain: {
      currentStage: "COMPLETE",
      round: 1,
      statusLabel: "Completed",
      simpleText: "",
      technicalText: "",
    },
    pipeline: [
      { id: "PREFLIGHT", label: "Preflight", status: "success", detail: "ok", durationMs: 100 },
      { id: "ANALYZE", label: "Analyzer", status: "success", detail: "ok", durationMs: 500 },
      { id: "PLAN", label: "Plan", status: "success", detail: "ok", durationMs: 300 },
      { id: "VERIFY", label: "Verifier", status: "success", detail: "ok", durationMs: 200 },
      { id: "EXECUTE", label: "Execute", status: "success", detail: "ok", durationMs: 1200 },
    ],
    agents: [],
    constraints: [],
    negotiation: null,
    verification: {
      checks: [
        { id: "chk_1", name: "YAML validation", status: "pass", message: "Valid compose" },
      ],
      passed: true,
      summary: "Checks passed",
    },
    critic: null,
    graph: { nodes: [], edges: [] },
    selectedNodeId: null,
    rollback: null,
    result: {
      kind: "success",
      title: "Success",
      code: "SUCCESS",
      message: "Deployment succeeded",
      durationLabel: "2s",
      servicesLabel: "1 service",
      verificationScore: 100,
      constraintsResolved: 0,
      rollbackScope: null,
    },
    trace: [],
    frameIndex: 0,
    totalFrames: 1,
    changeIntel: null,
    ...overrides,
  };
}

describe("HumanProgressView", () => {
  it("derives all six human-readable phases from backend pipeline", () => {
    const snapshot = mockSnapshot();
    const phases = deriveProgressPhases(snapshot);

    expect(phases).toHaveLength(6);
    expect(phases[0].title).toBe("Connecting to repository");
    expect(phases[1].title).toBe("Understanding the code");
    expect(phases[2].title).toBe("Checking code and security");
    expect(phases[3].title).toBe("Verifying the project");
    expect(phases[4].title).toBe("Preparing deployment assessment");
    expect(phases[5].title).toBe("Preparing results");
  });

  it("labels deployment as 'not_needed' when deployment is not applicable", () => {
    const snapshot = mockSnapshot({
      runStatus: "failed",
      result: {
        kind: "failed",
        title: "Blocked",
        durationLabel: "1s",
        servicesLabel: "0",
        verificationScore: 100,
        constraintsResolved: 0,
        rollbackScope: null,
        code: "NO_DEPLOYABLE_APP",
        message: "This repository has no deployable web application.",
      },
    });

    const phases = deriveProgressPhases(snapshot);
    const deployPhase = phases.find((p) => p.id === "deploy");
    expect(deployPhase?.status).toBe("not_needed");
    expect(deployPhase?.statusNote).toContain("Not needed for this project");
  });

  it("formats Docker unavailable error with What happened, Why it matters, and What you can do", () => {
    const err = parsePlainLanguageError("Docker daemon is not running");
    expect(err.whatHappened).toContain("Docker is not running");
    expect(err.whyItMatters).toContain("Repository checks and security analysis");
    expect(err.whatYouCanDo).toContain("Start Docker Desktop and retry deployment");
  });

  it("renders structured error box and actionable steps when run is failed", () => {
    const snapshot = mockSnapshot({
      runStatus: "failed",
      result: {
        kind: "failed",
        title: "Blocked",
        durationLabel: "1s",
        servicesLabel: "0",
        verificationScore: 100,
        constraintsResolved: 0,
        rollbackScope: null,
        code: "DOCKER_DAEMON_UNAVAILABLE",
        message:
          "What happened: MEDHA could not start Docker environment.\n\nWhy it matters: Cannot launch container.\n\nWhat you can do: Start Docker Desktop.",
      },
    });

    render(<HumanProgressView snapshot={snapshot} />);

    expect(screen.getByTestId("plain-language-error")).toBeInTheDocument();
    expect(screen.getByText("What happened:")).toBeInTheDocument();
    expect(screen.getByText(/MEDHA could not start Docker environment/)).toBeInTheDocument();
    expect(screen.getByText("Why it matters:")).toBeInTheDocument();
    expect(screen.getByText(/Cannot launch container/)).toBeInTheDocument();
    expect(screen.getByText("What you can do:")).toBeInTheDocument();
    expect(screen.getByText(/Start Docker Desktop/)).toBeInTheDocument();
  });

  it("renders toggle button to inspect technical details", () => {
    const onToggle = vi.fn();
    const snapshot = mockSnapshot();

    render(
      <HumanProgressView
        snapshot={snapshot}
        onToggleTechnical={onToggle}
        isTechnicalOpen={false}
      />,
    );

    const toggleBtn = screen.getByText(/Inspect technical details/);
    fireEvent.click(toggleBtn);
    expect(onToggle).toHaveBeenCalled();
  });
});
