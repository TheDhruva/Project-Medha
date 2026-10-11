import type { ChangeIntelEdge, ChangeIntelGraph, ChangeIntelNode } from "@/lib/demo/types";

export interface CigPosition {
  x: number;
  y: number;
}

const COLUMN_GAP = 260;
const ROW_GAP = 78;

/**
 * Deterministic, edge-direction-aware layout for the Change Impact Graph.
 *
 * Edge direction is "source depends on target", so impact flows along the
 * reverse direction (target → source). We rank nodes by dependency distance
 * from the changed set: changed artifacts sit on the left, direct dependents
 * one column right, transitive dependents further right. Unreached (context)
 * nodes fall to the last column so the graph always lays out.
 */
export function layoutCig(
  nodes: ChangeIntelNode[],
  edges: ChangeIntelEdge[],
): Record<string, CigPosition> {
  const positions: Record<string, CigPosition> = {};
  if (nodes.length === 0) return positions;

  const changedIds = new Set(
    nodes.filter((n) => n.node_type === "changed" || n.change_type).map((n) => n.id),
  );

  const dependents = new Map<string, string[]>();
  for (const edge of edges) {
    const list = dependents.get(edge.target) || [];
    list.push(edge.source);
    dependents.set(edge.target, list);
  }

  // Column = dependency depth from the changed set (0 = changed/leftmost).
  const column = new Map<string, number>();
  for (const id of changedIds) column.set(id, 0);

  let frontier = [...changedIds];
  let depth = 0;
  while (frontier.length > 0) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const dependent of dependents.get(id) || []) {
        if (column.has(dependent)) continue;
        column.set(dependent, depth + 1);
        next.push(dependent);
      }
    }
    frontier = next;
    depth += 1;
  }

  const maxDepth = Math.max(0, ...column.values());
  for (const node of nodes) {
    if (!column.has(node.id)) column.set(node.id, maxDepth + 1);
  }

  const columns = new Map<number, string[]>();
  for (const [id, col] of column) {
    const list = columns.get(col) || [];
    list.push(id);
    columns.set(col, list);
  }

  for (const [col, ids] of columns) {
    const sorted = ids.sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
    const blockHeight = (sorted.length - 1) * ROW_GAP;
    sorted.forEach((id, row) => {
      positions[id] = {
        x: col * COLUMN_GAP,
        y: blockHeight === 0 ? 0 : row * ROW_GAP - blockHeight / 2,
      };
    });
  }

  return positions;
}

export function isCigEmpty(graph: ChangeIntelGraph | null): boolean {
  return !graph || graph.nodes.length === 0;
}