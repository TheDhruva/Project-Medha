import { render, screen, waitForElementToBeRemoved } from "@testing-library/react";
import { describe, expect, it, vi, afterEach } from "vitest";
import type { ProductScore, ScoresResponse } from "@/lib/api/client";

const { fetchScoresMock } = vi.hoisted(() => ({ fetchScoresMock: vi.fn() }));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/api/client");
  return { ...original, fetchScores: fetchScoresMock };
});

import { ScoresPanel } from "@/components/scores/ScoresPanel";

function productScore(value: number | null, evidence: Record<string, unknown>): ProductScore {
  return {
    value,
    version: "scores-v2",
    computed_at: "2026-10-23T04:00:00Z",
    inputs_hash: "hash",
    target_sha: null,
    evidence,
  };
}

function respond(scores: Record<string, ProductScore>): void {
  const payload: ScoresResponse = {
    deployment_id: "dep_1",
    is_demo: false,
    label: null,
    scores,
  };
  fetchScoresMock.mockResolvedValue(payload);
}

/** Matches the innermost element whose full textContent equals `text` (whitespace-normalized). */
function byText(text: string) {
  return screen.getByText(
    (_, el) => el?.tagName !== "A" && el?.textContent?.replace(/\s+/g, " ").trim() === text,
  );
}

afterEach(() => {
  fetchScoresMock.mockReset();
});

describe("ScoresPanel summary and findings", () => {
  it("shows a compact clickable summary and evidence-backed findings with file/line", async () => {
    respond({
      code_quality: productScore(80, {
        coverage: { assessed: 1, applicable: 5, passed: 1, failed: 0, warnings: 0 },
        caps_applied: [
          {
            cap: "no_static_analysis",
            reason: "no static-analysis coverage for code quality",
            trigger: "no_static_analysis",
          },
        ],
        checks: [
          {
            id: "build",
            title: "Build validation",
            status: "failed",
            score_impact: 20,
            finding: "Build failed at build",
            evidence_source: "execution.result.build",
            reference: null,
            findings: [{ path: "src/app.py", line: 42, message: "error: expected token" }],
          },
        ],
      }),
    });

    render(<ScoresPanel projectId="prj_test" runId="dep_1" />);
    await waitForElementToBeRemoved(() => screen.queryByText("Loading scores…"));

    // Compact summary: name · score, coverage on the same row, linked to findings.
    expect(await byText("Code quality · 80/100")).toBeInTheDocument();
    expect(byText("1/5 checks completed")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Code quality/ })).toHaveAttribute(
      "href",
      "#findings",
    );
    // Categories without evidence stay honest, never fabricated scores.
    expect(byText("Security · Not measured")).toBeInTheDocument();

    // Findings distinguish "analysis never ran" from a confirmed code problem.
    expect(screen.getByText("Check not run")).toBeInTheDocument();
    expect(
      screen.getByText("The code check has not run, so the score cannot go above 80."),
    ).toBeInTheDocument();
    expect(screen.getByText("Code issue")).toBeInTheDocument();
    expect(screen.getByText("Build failed at build")).toBeInTheDocument();
    expect(screen.getByText("−20 points")).toBeInTheDocument();
    expect(screen.getByText(/src\/app\.py:42/)).toBeInTheDocument();
    expect(screen.getByText(/error: expected token/)).toBeInTheDocument();
  });

  it("reports an unassessed score in plain English without fabricating a number", async () => {
    respond({
      security: productScore(null, {
        reason: "no security scanner completed; security coverage is unknown",
        coverage: { assessed: 0, applicable: 4, passed: 0, failed: 0, warnings: 0 },
        checks: [],
      }),
    });

    render(<ScoresPanel projectId="prj_test" runId="dep_1" />);
    await waitForElementToBeRemoved(() => screen.queryByText("Loading scores…"));

    expect(await byText("Security · Not assessed")).toBeInTheDocument();
    expect(screen.getByText("Check not run")).toBeInTheDocument();
    expect(screen.getByText("The security scan has not finished.")).toBeInTheDocument();
    expect(screen.queryByText(/\/100/)).not.toBeInTheDocument();
  });

  it("shows a single Passed finding when all completed checks passed", async () => {
    respond({
      verification_confidence: productScore(100, {
        coverage: { assessed: 10, applicable: 10, passed: 10, failed: 0, warnings: 0 },
        checks: [{ id: "yaml", title: "YAML schema", status: "passed", score_impact: 0 }],
      }),
    });

    render(<ScoresPanel projectId="prj_test" runId="dep_1" />);
    await waitForElementToBeRemoved(() => screen.queryByText("Loading scores…"));

    expect(await byText("Verification · 100/100")).toBeInTheDocument();
    expect(byText("10/10 checks passed")).toBeInTheDocument();
    expect(screen.getByText("Passed")).toBeInTheDocument();
    expect(screen.getByText("All completed checks passed.")).toBeInTheDocument();
    // Deployment readiness has no evidence here; its row links to run details.
    expect(screen.getByRole("link", { name: /Deployment readiness/ })).toHaveAttribute(
      "href",
      "/projects/prj_test/runs/dep_1",
    );
  });
});
