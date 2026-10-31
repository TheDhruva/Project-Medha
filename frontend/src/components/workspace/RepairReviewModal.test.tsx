import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FindingView } from "@/lib/api/client";

const { fetchRepairPlanMock, applyAndVerifyRepairMock, deliverRepairMock } = vi.hoisted(() => ({
  fetchRepairPlanMock: vi.fn(),
  applyAndVerifyRepairMock: vi.fn(),
  deliverRepairMock: vi.fn(),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/api/client");
  return {
    ...original,
    fetchRepairPlan: fetchRepairPlanMock,
    applyAndVerifyRepair: applyAndVerifyRepairMock,
    deliverRepair: deliverRepairMock,
  };
});

import { RepairReviewModal } from "@/components/workspace/RepairReviewModal";

const dummyFinding: FindingView = {
  finding_id: "fnd_sec_102",
  severity: "high",
  status: "detected",
  category: "security",
  rule_id: "SEC-102",
  source: "builtin",
  confidence: "high",
  path: "src/config.py",
  line: 12,
  message: "Potentially unsafe YAML deserialization",
  explanation: "yaml.load without safe loader can execute arbitrary code.",
  remediation: "Use yaml.safe_load",
  verification_status: "unverified",
  first_seen_sha: "aaaaaaa",
  last_seen_sha: "bbbbbbb",
  first_seen_at: "2026-10-20T10:00:00Z",
  last_seen_at: "2026-10-21T10:00:00Z",
  is_new_since_baseline: false,
  blocks_merge: true,
  evidence: [],
  history: [],
  is_demo: false,
};

describe("RepairReviewModal", () => {
  afterEach(() => {
    fetchRepairPlanMock.mockReset();
    applyAndVerifyRepairMock.mockReset();
    deliverRepairMock.mockReset();
  });

  it("fetches and renders the repair plan diff and solution", async () => {
    fetchRepairPlanMock.mockResolvedValueOnce({
      finding_id: "fnd_sec_102",
      rule_id: "SEC-102",
      file_path: "src/config.py",
      line: 12,
      title: "Use yaml.safe_load() instead of unsafe yaml.load()",
      explanation: "yaml.load without safe loader",
      remediation_strategy: "deterministic_ast",
      can_auto_fix: true,
      risk_level: "low",
      original_snippet: "data = yaml.load(raw)",
      patched_snippet: "data = yaml.safe_load(raw)",
      diff_unified: "--- a/src/config.py\n+++ b/src/config.py\n@@ -12 +12 @@\n-data = yaml.load(raw)\n+data = yaml.safe_load(raw)\n",
      message: "Clean, deterministic patch generated.",
    });

    render(
      <RepairReviewModal
        projectId="proj_1"
        finding={dummyFinding}
        onClose={vi.fn()}
        onResolved={vi.fn()}
      />
    );

    expect(screen.getByText(/Analyzing code and generating targeted patch/i)).toBeInTheDocument();

    await waitFor(() => {
      expect(screen.getByText("Use yaml.safe_load() instead of unsafe yaml.load()")).toBeInTheDocument();
      expect(screen.getByText("Validate & Test in Sandbox")).toBeInTheDocument();
    });
  });

  it("executes sandbox verification and advances to approval step", async () => {
    fetchRepairPlanMock.mockResolvedValueOnce({
      finding_id: "fnd_sec_102",
      rule_id: "SEC-102",
      file_path: "src/config.py",
      line: 12,
      title: "Use yaml.safe_load() instead of unsafe yaml.load()",
      explanation: "yaml.load without safe loader",
      remediation_strategy: "deterministic_ast",
      can_auto_fix: true,
      risk_level: "low",
      original_snippet: "data = yaml.load(raw)",
      patched_snippet: "data = yaml.safe_load(raw)",
      diff_unified: "--- a/src/config.py\n+++ b/src/config.py\n",
      message: "Patch ready.",
    });

    applyAndVerifyRepairMock.mockResolvedValueOnce({
      verification: {
        verified: true,
        finding_eliminated: true,
        original_rule_retested: true,
        new_findings_introduced: [],
        verification_evidence: ["Rule SEC-102 produced 0 findings."],
        output: "Verification succeeded.",
      },
      branch_name: "medha/fix-sec-102-fnd_sec_",
      commit_sha: "c0ffee123456",
    });

    render(
      <RepairReviewModal
        projectId="proj_1"
        finding={dummyFinding}
        onClose={vi.fn()}
        onResolved={vi.fn()}
      />
    );

    await waitFor(() => {
      expect(screen.getByText("Validate & Test in Sandbox")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Validate & Test in Sandbox"));

    await waitFor(() => {
      expect(screen.getByText(/Sandbox Verification Passed/i)).toBeInTheDocument();
      expect(screen.getByText("Approve & Create Pull Request")).toBeInTheDocument();
    });
  });
});

