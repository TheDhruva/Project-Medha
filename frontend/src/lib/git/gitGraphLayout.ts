import { MarkerType, type Edge, type Node } from "@xyflow/react";
import type { HistoryCommit, RunSummary } from "@/lib/api/client";
import { isRunningStatus } from "@/lib/projects/projects";

export interface CommitNodeData extends Record<string, unknown> {
  commit: HistoryCommit;
  run: RunSummary | null;
  isSelected: boolean;
  isAncestor: boolean;
  hasSelection: boolean;
  lane: number;
}

export const LANE_WIDTH = 260;
export const ROW_HEIGHT = 96;
export const X_OFFSET = 30;
export const Y_OFFSET = 30;

/**
 * Categorize modified files into deterministic engineering impact areas.
 */
export function categorizeImpact(files: { path: string }[]): string[] {
  const categories = new Set<string>();
  for (const f of files) {
    const p = f.path.toLowerCase();
    if (
      p.includes("package.json") ||
      p.includes("requirements.txt") ||
      p.includes("pipfile") ||
      p.includes("go.mod") ||
      p.includes("cargo.toml") ||
      p.includes("pom.xml")
    ) {
      categories.add("Dependencies");
    } else if (
      p.includes("auth") ||
      p.includes("security") ||
      p.includes("crypto") ||
      p.includes("secret") ||
      p.includes("token") ||
      p.includes("permission")
    ) {
      categories.add("Security-sensitive");
    } else if (
      p.includes("docker") ||
      p.includes(".github") ||
      p.includes("nginx") ||
      p.includes("k8s") ||
      p.includes("deploy")
    ) {
      categories.add("Build & Deployment");
    } else if (
      p.includes("test") ||
      p.includes("spec") ||
      p.includes("__tests__")
    ) {
      categories.add("Tests");
    } else {
      categories.add("Application code");
    }
  }
  return Array.from(categories);
}

/**
 * Traverses parent pointers in the DAG to compute all ancestor SHAs for the selected commit.
 */
export function getCommitAncestry(commits: HistoryCommit[], selectedSha: string | null): Set<string> {
  const ancestors = new Set<string>();
  if (!selectedSha) return ancestors;

  const bySha = new Map<string, HistoryCommit>();
  for (const c of commits) {
    bySha.set(c.sha.toLowerCase(), c);
  }

  const queue = [selectedSha.toLowerCase()];
  while (queue.length > 0) {
    const current = queue.shift()!;
    if (ancestors.has(current)) continue;
    ancestors.add(current);

    const commit = bySha.get(current);
    if (commit && commit.parents) {
      for (const p of commit.parents) {
        const lowerParent = p.toLowerCase();
        if (!ancestors.has(lowerParent)) {
          queue.push(lowerParent);
        }
      }
    }
  }

  return ancestors;
}

/**
 * Assigns topological lane columns and rows to commits, preserving Git branch topology.
 */
export function assignCommitPositions(commits: HistoryCommit[]): Map<string, { lane: number; row: number }> {
  const positions = new Map<string, { lane: number; row: number }>();
  const activeLanes: (string | null)[] = [];

  commits.forEach((commit, index) => {
    // 1. Check if an active lane was reserved for this commit's SHA
    const existingLaneIndex = activeLanes.indexOf(commit.sha);
    let lane: number;

    if (existingLaneIndex !== -1) {
      lane = existingLaneIndex;
      activeLanes[lane] = null;
    } else {
      // Find the first free lane or allocate a new column
      const freeLaneIndex = activeLanes.indexOf(null);
      if (freeLaneIndex !== -1) {
        lane = freeLaneIndex;
      } else {
        lane = activeLanes.length;
        activeLanes.push(null);
      }
    }

    positions.set(commit.sha, { lane, row: index });

    // 2. Reserve lanes for parents
    if (commit.parents && commit.parents.length > 0) {
      // The first parent continues the current lane
      activeLanes[lane] = commit.parents[0];

      // Subsequent parents (merges) get their own branch lanes
      for (let pIdx = 1; pIdx < commit.parents.length; pIdx++) {
        const parentSha = commit.parents[pIdx];
        if (!activeLanes.includes(parentSha)) {
          const nextFree = activeLanes.indexOf(null);
          if (nextFree !== -1) {
            activeLanes[nextFree] = parentSha;
          } else {
            activeLanes.push(parentSha);
          }
        }
      }
    }
  });

  return positions;
}

/**
 * Builds nodes and edges for React Flow from commits, runs, and current selection.
 */
export function buildGitGraphDAG({
  commits,
  runs,
  selectedSha,
}: {
  commits: HistoryCommit[];
  runs: RunSummary[];
  selectedSha: string | null;
}): {
  nodes: Node<CommitNodeData>[];
  edges: Edge[];
} {
  const bySha = new Map(commits.map((c) => [c.sha, c]));
  const runsByRevision = new Map<string, RunSummary>();
  for (const r of runs) {
    if (r.analysis_coverage?.commit_sha) {
      runsByRevision.set(r.analysis_coverage.commit_sha.toLowerCase(), r);
    }
    if (r.target_revision && r.target_revision.length === 40) {
      runsByRevision.set(r.target_revision.toLowerCase(), r);
    }
  }

  const positions = assignCommitPositions(commits);
  const ancestry = getCommitAncestry(commits, selectedSha);
  const hasSelection = Boolean(selectedSha);

  const nodes: Node<CommitNodeData>[] = commits.map((commit) => {
    const pos = positions.get(commit.sha) ?? { lane: 0, row: 0 };
    const isSelected = selectedSha?.toLowerCase() === commit.sha.toLowerCase();
    const isAncestor = ancestry.has(commit.sha.toLowerCase());
    const matchedRun = runsByRevision.get(commit.sha.toLowerCase()) ?? null;

    return {
      id: commit.sha,
      type: "commitNode",
      position: {
        x: X_OFFSET + pos.lane * LANE_WIDTH,
        y: Y_OFFSET + pos.row * ROW_HEIGHT,
      },
      data: {
        commit,
        run: matchedRun,
        isSelected,
        isAncestor,
        hasSelection,
        lane: pos.lane,
      },
    };
  });

  const edges: Edge[] = [];
  for (const commit of commits) {
    if (!commit.parents) continue;
    for (const parentSha of commit.parents) {
      if (bySha.has(parentSha)) {
        const edgeId = `${commit.sha.slice(0, 8)}->${parentSha.slice(0, 8)}`;
        const isChildAncestor = ancestry.has(commit.sha.toLowerCase());
        const isParentAncestor = ancestry.has(parentSha.toLowerCase());
        const isHighlighted = hasSelection && isChildAncestor && isParentAncestor;
        const matchedRun = runsByRevision.get(commit.sha.toLowerCase());
        const isAnalyzing = matchedRun ? isRunningStatus(matchedRun.status) : false;

        edges.push({
          id: edgeId,
          source: commit.sha,
          target: parentSha,
          type: "smoothstep",
          animated: isAnalyzing,
          style: {
            stroke: isHighlighted ? "#635BFF" : hasSelection ? "#E2E8F0" : "#CBD5E1",
            strokeWidth: isHighlighted ? 2.5 : 1.5,
            opacity: hasSelection && !isHighlighted ? 0.35 : 1,
            transition: "stroke 0.2s, stroke-width 0.2s, opacity 0.2s",
          },
          markerEnd: {
            type: MarkerType.ArrowClosed,
            color: isHighlighted ? "#635BFF" : hasSelection ? "#CBD5E1" : "#94A3B8",
            width: 12,
            height: 12,
          },
        });
      }
    }
  }

  return { nodes, edges };
}
