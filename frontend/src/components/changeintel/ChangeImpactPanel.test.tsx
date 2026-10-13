import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChangeImpactPanel } from "@/components/changeintel/ChangeImpactPanel";
import type { ChangeIntelAnalysis } from "@/lib/demo/types";

const demoAnalysis: ChangeIntelAnalysis = {
  deployment_id: null,
  repository_url: "github.com/acme/checkout-service (demo)",
  is_demo: true,
  label: "DEMO/MOCK",
  generated_at: "2026-01-01T00:00:00+00:00",
  changeset: {
    base_revision: "e2f31a4",
    target_revision: "9c61d02",
    base_sha: "e2f31a4c9b2d",
    target_sha: "9c61d02e27b4",
    source_method: "demo",
    is_git: true,
    counts: { modified: 2, added: 0, deleted: 0, renamed: 0 },
    files: [
      {
        path: "services/checkout.py",
        old_path: null,
        change_type: "modified",
        added_lines: 18,
        deleted_lines: 6,
      },
      {
        path: "config.yaml",
        old_path: null,
        change_type: "modified",
        added_lines: 2,
        deleted_lines: 1,
      },
    ],
    unsupported: [],
  },
  changed_symbols: [],
  graph: {
    nodes: [
      {
        id: "services/checkout.py",
        path: "services/checkout.py",
        node_type: "changed",
        change_type: "modified",
        symbol: null,
        symbol_id: null,
        kind: null,
        language: "python",
        direct: true,
      },
      {
        id: "services/cart.py",
        path: "services/cart.py",
        node_type: "affected",
        change_type: null,
        symbol: null,
        symbol_id: null,
        kind: null,
        language: "python",
        direct: true,
      },
    ],
    edges: [
      {
        id: "e1",
        source: "services/cart.py",
        target: "services/checkout.py",
        relationship: "import",
        confidence: "high",
        evidence: "services/cart.py:1 import checkout",
        direct: true,
        note: null,
      },
    ],
  },
  traversal: {
    max_depth: 3,
    depth_used: 1,
    direct_targets: ["services/cart.py"],
    transitive_targets: [],
    cycles_detected: [],
  },
  unresolved: [
    {
      path: "services/pricing.py",
      line: 3,
      target: "payment_gateway",
      kind: "import",
      reason: "bare import could not be mapped to a repository file",
    },
  ],
  risk: {
    level: "medium",
    factors: [
      {
        code: "unresolved_dependencies",
        level: "medium",
        reason: "1 import(s) could not be resolved inside the repository",
      },
      {
        code: "configuration_dependencies",
        level: "medium",
        reason: "configuration references changed source artifacts",
      },
    ],
  },
  requirements: [
    {
      id: "req1",
      target_path: "config.yaml",
      target_symbol: null,
      requirement: "Re-validate the modified configuration against its referenced services.",
      reason: "config file 'config.yaml' changed (modified)",
      check_category: "config",
      executable: true,
      status: "executable",
    },
    {
      id: "req2",
      target_path: "services/cart.py",
      target_symbol: null,
      requirement: "Re-verify 'services/cart.py' against its changed dependencies (regression).",
      reason: "services/cart.py is directly affected",
      check_category: "preflight",
      executable: false,
      status: "not_executable",
    },
  ],
};

vi.mock("@xyflow/react", () => ({
  Background: () => null,
  Controls: () => null,
  Handle: () => null,
  Position: { Top: "top", Bottom: "bottom" },
  MarkerType: { ArrowClosed: "arrowclosed" },
  EdgeLabelRenderer: ({ children }: { children: import("react").ReactNode }) => (
    <div data-testid="cig-edge-labels">{children}</div>
  ),
  ReactFlow: () => <div data-testid="cig-canvas" />,
}));

describe("ChangeImpactPanel", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders risk, DEMO/MOCK label and change counts from the analysis", () => {
    render(<ChangeImpactPanel analysis={demoAnalysis} />);
    expect(screen.getByText("Risk: medium")).toBeInTheDocument();
    expect(screen.getByText("DEMO/MOCK")).toBeInTheDocument();
    expect(screen.getByText(/2M/)).toBeInTheDocument();
  });

  it("lists changed files, unresolved dependencies and verification requirements", () => {
    render(<ChangeImpactPanel analysis={demoAnalysis} />);
    expect(screen.getByText("services/checkout.py")).toBeInTheDocument();
    expect(screen.getByText("config.yaml")).toBeInTheDocument();
    expect(screen.getByText("services/pricing.py:3 → payment_gateway")).toBeInTheDocument();
    expect(
      screen.getByText("Re-validate the modified configuration against its referenced services."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Re-verify 'services/cart.py' against its changed dependencies (regression)."),
    ).toBeInTheDocument();
    expect(screen.getByText(/directly affected/)).toBeInTheDocument();
  });

  it("shows evidence and executable status without faking source-level checks", () => {
    render(<ChangeImpactPanel analysis={demoAnalysis} />);
    expect(screen.getByText(/services\/cart.py:1 import checkout/)).toBeInTheDocument();
    expect(screen.getByText("executable")).toBeInTheDocument();
    expect(screen.getByText("not_executable")).toBeInTheDocument();
    expect(screen.getByText(/source-level check \(not faked\)/)).toBeInTheDocument();
  });

  it("renders an idle state when no analysis is available", () => {
    render(<ChangeImpactPanel analysis={null} />);
    expect(screen.getByText(/No change-intelligence analysis yet/)).toBeInTheDocument();
    expect(screen.queryByText("Load demo fixture")).toBeNull();
  });
});