import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { FindingView, ProjectFindingsResponse } from "@/lib/api/client";

const { fetchProjectFindingsMock } = vi.hoisted(() => ({
  fetchProjectFindingsMock: vi.fn(),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = (await importOriginal()) as typeof import("@/lib/api/client");
  return { ...original, fetchProjectFindings: fetchProjectFindingsMock };
});

import { FindingsPanel } from "@/components/workspace/FindingsPanel";

function finding(overrides: Partial<FindingView> = {}): FindingView {
  return {
    finding_id: "fnd_1",
    severity: "high",
    status: "open",
    category: "security",
    rule_id: "gitleaks",
    source: "secret_scan",
    confidence: "high",
    path: "src/app.py",
    line: 42,
    message: "Hardcoded token found",
    explanation: "A token was committed.",
    remediation: "Rotate the token.",
    verification_status: "verified",
    first_seen_sha: "aaaaaaa1234567890",
    last_seen_sha: "bbbbbbb1234567890",
    first_seen_at: "2026-10-20T10:00:00Z",
    last_seen_at: "2026-10-21T10:00:00Z",
    is_new_since_baseline: true,
    blocks_merge: true,
    evidence: ["line 42: token = 'ghp_…'"],
    history: [{ at: "2026-10-20T10:00:00Z", status: "open" }],
    is_demo: false,
    ...overrides,
  };
}

function respond(payload: Partial<ProjectFindingsResponse>): void {
  fetchProjectFindingsMock.mockResolvedValue({
    findings: [],
    status_counts: {},
    severity_counts: {},
    lifecycle_states: ["open", "fixed"],
    baseline_sha: null,
    filters: { status: null, severity: null, sort: "severity" },
    total: 0,
    blocking_rule: { severities: ["critical", "high"], statuses: ["open"] },
    ...payload,
  });
}

afterEach(() => {
  fetchProjectFindingsMock.mockReset();
});

describe("FindingsPanel", () => {
  it("lists recorded findings with severity, location and merge impact", async () => {
    respond({
      findings: [finding()],
      total: 1,
      severity_counts: { high: 1 },
      status_counts: { open: 1 },
    });

    render(<FindingsPanel projectId="prj_test" />);
    await waitFor(() => expect(fetchProjectFindingsMock).toHaveBeenCalledTimes(1));
    expect(await screen.findByText(/1 finding total/)).toBeInTheDocument();

    expect(screen.getByText(/high 1/)).toBeInTheDocument();
    expect(screen.getByText("gitleaks")).toBeInTheDocument();
    expect(screen.getByText("src/app.py:42")).toBeInTheDocument();
    expect(screen.getByText("blocks merge")).toBeInTheDocument();
    // Expandable detail carries the recorded explanation and remediation.
    expect(screen.getByText("A token was committed.")).toBeInTheDocument();
    expect(screen.getByText("Rotate the token.")).toBeInTheDocument();
    expect(screen.getByText(/aaaaaaa → bbbbbbb/)).toBeInTheDocument();
  });

  it("passes the chosen filters to the server-side query", async () => {
    respond({ findings: [finding({ severity: "critical" })], total: 1 });

    render(<FindingsPanel projectId="prj_test" />);
    await waitFor(() => expect(fetchProjectFindingsMock).toHaveBeenCalledTimes(1));

    const select = screen.getByLabelText("Severity") as HTMLSelectElement;
    select.value = "critical";
    select.dispatchEvent(new Event("change", { bubbles: true }));

    await waitFor(() =>
      expect(fetchProjectFindingsMock).toHaveBeenCalledWith("prj_test", {
        status: undefined,
        severity: "critical",
        sort: "severity",
      }),
    );
  });

  it("states an empty repository honestly", async () => {
    respond({ findings: [], total: 0 });

    render(<FindingsPanel projectId="prj_test" />);
    expect(await screen.findByText("No findings recorded for this repository.")).toBeInTheDocument();
  });

  it("surfaces backend errors with a retry control", async () => {
    fetchProjectFindingsMock.mockRejectedValueOnce(new Error("findings exploded"));

    render(<FindingsPanel projectId="prj_test" />);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Findings are unavailable: findings exploded",
    );

    respond({ findings: [], total: 0 });
    screen.getByRole("button", { name: "Retry" }).click();
    expect(await screen.findByText("No findings recorded for this repository.")).toBeInTheDocument();
  });
});
