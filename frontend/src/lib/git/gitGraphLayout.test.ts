import { describe, expect, it } from "vitest";
import type { HistoryCommit, RunSummary } from "@/lib/api/client";
import {
  assignCommitPositions,
  buildGitGraphDAG,
  categorizeImpact,
  getCommitAncestry,
  LANE_WIDTH,
  ROW_HEIGHT,
  X_OFFSET,
  Y_OFFSET,
} from "./gitGraphLayout";

function makeCommit(partial: Partial<HistoryCommit>): HistoryCommit {
  return {
    sha: "c111111111111111111111111111111111111111",
    parents: [],
    author: "Engineer <eng@example.com>",
    committed_at: "2026-10-20T10:00:00Z",
    message: "feat: initial commit",
    branch: "main",
    github_url: null,
    summary: "Created files",
    ...partial,
  };
}

describe("gitGraphLayout", () => {
  describe("categorizeImpact", () => {
    it("categorizes files into engineering impact areas deterministically", () => {
      const files = [
        { path: "package.json" },
        { path: "src/auth/service.ts" },
        { path: "docker-compose.yml" },
        { path: "tests/api.test.ts" },
        { path: "src/ui/Button.tsx" },
      ];

      const categories = categorizeImpact(files);
      expect(categories).toContain("Dependencies");
      expect(categories).toContain("Security-sensitive");
      expect(categories).toContain("Build & Deployment");
      expect(categories).toContain("Tests");
      expect(categories).toContain("Application code");
    });

    it("returns only Application code for typical app files", () => {
      const categories = categorizeImpact([{ path: "src/components/Header.tsx" }]);
      expect(categories).toEqual(["Application code"]);
    });
  });

  describe("getCommitAncestry", () => {
    it("returns empty set if selectedSha is null", () => {
      const commits = [makeCommit({ sha: "a1" })];
      expect(getCommitAncestry(commits, null).size).toBe(0);
    });

    it("recursively traces parent hierarchy in the DAG", () => {
      // a3 -> a2 -> a1
      const c1 = makeCommit({ sha: "a1", parents: [] });
      const c2 = makeCommit({ sha: "a2", parents: ["a1"] });
      const c3 = makeCommit({ sha: "a3", parents: ["a2"] });

      const ancestors = getCommitAncestry([c3, c2, c1], "a3");
      expect(ancestors.has("a3")).toBe(true);
      expect(ancestors.has("a2")).toBe(true);
      expect(ancestors.has("a1")).toBe(true);
    });

    it("includes multiple parents for merge commits", () => {
      // c_merge -> [branch_head, main_parent]
      const root = makeCommit({ sha: "root", parents: [] });
      const mainCommit = makeCommit({ sha: "main1", parents: ["root"] });
      const featCommit = makeCommit({ sha: "feat1", parents: ["root"] });
      const mergeCommit = makeCommit({ sha: "merge1", parents: ["main1", "feat1"] });

      const ancestors = getCommitAncestry([mergeCommit, featCommit, mainCommit, root], "merge1");
      expect(ancestors.has("merge1")).toBe(true);
      expect(ancestors.has("main1")).toBe(true);
      expect(ancestors.has("feat1")).toBe(true);
      expect(ancestors.has("root")).toBe(true);
    });

    it("does not include unrelated commits outside the lineage", () => {
      const root = makeCommit({ sha: "root", parents: [] });
      const branchA = makeCommit({ sha: "a1", parents: ["root"] });
      const branchB = makeCommit({ sha: "b1", parents: ["root"] });

      const ancestors = getCommitAncestry([branchA, branchB, root], "a1");
      expect(ancestors.has("a1")).toBe(true);
      expect(ancestors.has("root")).toBe(true);
      expect(ancestors.has("b1")).toBe(false);
    });
  });

  describe("assignCommitPositions", () => {
    it("keeps linear history in lane 0", () => {
      const c1 = makeCommit({ sha: "c1", parents: ["c2"] });
      const c2 = makeCommit({ sha: "c2", parents: ["c3"] });
      const c3 = makeCommit({ sha: "c3", parents: [] });

      const pos = assignCommitPositions([c1, c2, c3]);
      expect(pos.get("c1")?.lane).toBe(0);
      expect(pos.get("c2")?.lane).toBe(0);
      expect(pos.get("c3")?.lane).toBe(0);

      expect(pos.get("c1")?.row).toBe(0);
      expect(pos.get("c2")?.row).toBe(1);
      expect(pos.get("c3")?.row).toBe(2);
    });

    it("assigns separate branch lanes for forks and merges", () => {
      // merge commit has 2 parents: p1 continues lane, p2 gets new lane
      const merge = makeCommit({ sha: "merge", parents: ["p1", "p2"] });
      const p1 = makeCommit({ sha: "p1", parents: ["root"] });
      const p2 = makeCommit({ sha: "p2", parents: ["root"] });
      const root = makeCommit({ sha: "root", parents: [] });

      const pos = assignCommitPositions([merge, p1, p2, root]);
      expect(pos.get("merge")?.lane).toBe(0);
      expect(pos.get("p1")?.lane).toBe(0);
      expect(pos.get("p2")?.lane).toBe(1);
    });
  });

  describe("buildGitGraphDAG", () => {
    it("generates nodes and directed edges with coordinates", () => {
      const c1 = makeCommit({ sha: "c1", parents: ["c2"] });
      const c2 = makeCommit({ sha: "c2", parents: [] });

      const { nodes, edges } = buildGitGraphDAG({
        commits: [c1, c2],
        runs: [],
        selectedSha: null,
      });

      expect(nodes).toHaveLength(2);
      expect(nodes[0].id).toBe("c1");
      expect(nodes[0].position.x).toBe(X_OFFSET);
      expect(nodes[0].position.y).toBe(Y_OFFSET);

      expect(nodes[1].id).toBe("c2");
      expect(nodes[1].position.x).toBe(X_OFFSET);
      expect(nodes[1].position.y).toBe(Y_OFFSET + ROW_HEIGHT);

      expect(edges).toHaveLength(1);
      expect(edges[0].source).toBe("c1");
      expect(edges[0].target).toBe("c2");
    });

    it("highlights ancestry path when a commit is selected", () => {
      const c1 = makeCommit({ sha: "c1", parents: ["c2"] });
      const c2 = makeCommit({ sha: "c2", parents: [] });
      const unrelated = makeCommit({ sha: "unrelated", parents: [] });

      const { nodes, edges } = buildGitGraphDAG({
        commits: [c1, c2, unrelated],
        runs: [],
        selectedSha: "c1",
      });

      const nodeC1 = nodes.find((n) => n.id === "c1");
      const nodeC2 = nodes.find((n) => n.id === "c2");
      const nodeUnrelated = nodes.find((n) => n.id === "unrelated");

      expect(nodeC1?.data.isSelected).toBe(true);
      expect(nodeC1?.data.isAncestor).toBe(true);

      expect(nodeC2?.data.isSelected).toBe(false);
      expect(nodeC2?.data.isAncestor).toBe(true);

      expect(nodeUnrelated?.data.isSelected).toBe(false);
      expect(nodeUnrelated?.data.isAncestor).toBe(false);

      expect(edges[0].style?.stroke).toBe("#635BFF"); // highlighted accent color
    });
  });
});

