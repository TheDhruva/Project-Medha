"use client";

import { useEffect, useMemo, useState } from "react";
import { cn } from "@/lib/ui/cn";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useDeployment } from "@/context/DeploymentContext";
import { labelStatus, statusGlyph } from "@/lib/ui/status";
import type { CegNode, NodeStatus } from "@/lib/demo/types";

type CegFlowNode = Node<{ node: CegNode }, "ceg">;

function nodeColors(status: NodeStatus): { border: string; bg: string; text: string } {
  switch (status) {
    case "success":
    case "preserved":
      return { border: "#1b7a4a", bg: "#164e3d", text: "#a8d5c2" };
    case "failed":
      return { border: "#b42318", bg: "#3f232a", text: "#ffa3a5" };
    case "rolled_back":
      return { border: "#a56a12", bg: "#3a2a1a", text: "#d4c5a8" };
    case "running":
      return { border: "#1a4f9c", bg: "#0e2d5a", text: "#a3c4e7" };
    default:
      return { border: "#465368", bg: "#1f2d3d", text: "#6b7a8c" };
  }
}

function CegServiceNode({ data, selected }: NodeProps<CegFlowNode>) {
  const node = data.node;
  const colors = nodeColors(node.status);
  return (
    <div
      className={`min-w-[140px] rounded-md px-3 py-2 shadow-sm ${selected ? "ring-2 ring-medha-accent ring-offset-2" : ""}`}
      style={{ borderColor: colors.border, background: colors.bg, color: colors.text }}
    >
      <Handle type="target" position={Position.Top} className="!bg-medha-accent !h-2 !w-2" />
      <p className="text-[10px] font-semibold tracking-wide">{node.service}</p>
      <p className="mt-0.5 text-xs opacity-80">
        <span aria-hidden>{statusGlyph(node.status)} </span>
        {labelStatus(node.status)}
      </p>
      <Handle type="source" position={Position.Bottom} className="!bg-medha-accent !h-2 !w-2" />
    </div>
  );
}

const nodeTypes = { ceg: CegServiceNode };

export function CausalExecutionGraph() {
  const { snapshot, selectNode, viewMode } = useDeployment();
  const [mounted, setMounted] = useState(false);
  const selected = snapshot.graph.nodes.find((n) => n.id === snapshot.selectedNodeId);

  useEffect(() => {
    setMounted(true);
  }, []);

  const nodes: Node[] = useMemo(
    () =>
      snapshot.graph.nodes.map((n) => ({
        id: n.id,
        type: "ceg" as const,
        position: n.position,
        data: { node: n },
        selected: n.id === snapshot.selectedNodeId,
      })),
    [snapshot.graph.nodes, snapshot.selectedNodeId],
  );

  const edges = useMemo(
    () =>
      snapshot.graph.edges.map((e) => ({
        id: e.id,
        source: e.source,
        target: e.target,
        markerEnd: { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#465368" },
        style: { stroke: "#465368", strokeWidth: 1.5 },
      })),
    [snapshot.graph.edges],
  );

  return (
    <section className="medha-panel animate-medha-in overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-medha-border px-4 py-3 sm:px-5">
        <div>
          <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
            CAUSAL EXECUTION GRAPH
          </h2>
          <p className="mt-1 text-xs text-medha-secondary">
            Dependency-aware recovery — research contribution #2
          </p>
        </div>
        <span className="text-[10px] text-medha-tertiary">Click a node for details</span>
      </div>

      <div className="grid lg:grid-cols-[1fr_280px]">
        <div className="h-[360px] border-b border-medha-border bg-medha-surface lg:border-b-0 lg:border-r">
          {snapshot.graph.nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm text-medha-secondary">
              Deployment recovery data is not available for this run.
            </div>
          ) : !mounted ? (
            <div className="flex h-full items-center justify-center text-sm text-medha-secondary">
              Loading graph…
            </div>
          ) : (
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              fitView
              fitViewOptions={{ padding: 0.2 }}
              minZoom={0.5}
              maxZoom={1.4}
              proOptions={{ hideAttribution: true }}
              onNodeClick={(_, node) => selectNode(node.id)}
              onPaneClick={() => selectNode(null)}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable
            >
              <Background gap={18} size={1} color="#1f2d3d" />
              <Controls showInteractive={false} />
            </ReactFlow>
          )}
        </div>

        <aside className="p-4">
          {selected ? (
            <div className="animate-medha-in space-y-3">
              <div>
                <p className="medha-label">Service</p>
                <p className="font-display text-lg font-semibold text-medha-text">
                  {selected.service}
                </p>
              </div>
              <Row
                label="Status"
                value={`${statusGlyph(selected.status)} ${labelStatus(selected.status)}`}
              />
              <Row label="Action" value={selected.action} />
              <Row label="Timestamp" value={selected.timestamp} />
              {selected.reason ? <Row label="Reason" value={selected.reason} /> : null}
              <Row label="Dependents" value={(selected.dependents ?? []).join(", ") || "None"} />
              <Row label="Rollback" value={selected.rollbackRequired ? "Required" : "Not required"} />
              <Row label="Preserved" value={selected.preserved ? "Yes" : "No"} />
              {viewMode === "technical" ? (
                <>
                  <Row label="Node ID" value={selected.id} mono />
                  <Row
                    label="Dependencies"
                    value={selected.dependencies.join(", ") || "—"}
                    mono
                  />
                </>
              ) : null}
            </div>
          ) : (
            <p className="text-sm text-medha-secondary">
              Select a graph node to inspect service status, dependents, and rollback membership.
            </p>
          )}

          {snapshot.rollback ? (
            <div className="mt-5 space-y-3">
              <div className="rounded-md border border-medha-danger/25 bg-medha-danger-soft/50 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-medha-danger">
                  Failure detected
                </p>
                <p className="mt-1 text-sm text-medha-text">
                  {viewMode === "simple"
                    ? "A service failed during execution."
                    : `failed_nodes=[${snapshot.rollback.scopeNodeIds.length ? "see scope" : "—"}] · see details`}
                </p>
              </div>
              <div className="rounded-md border border-medha-warning/30 bg-medha-warning-soft/60 p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-medha-warning">
                  {snapshot.rollback.headline}
                </p>
                <ol className="mt-2 space-y-1.5 text-xs leading-relaxed text-medha-secondary">
                  <li>
                    <span className="font-medium text-medha-text">Dependency analysis</span>
                    {" — "}
                    {viewMode === "simple"
                      ? "MEDHA traced the dependency graph."
                      : `scope=[${snapshot.rollback.scopeNodeIds.join(", ")}]`}
                  </li>
                  <li>
                    <span className="font-medium text-medha-text">Rollback scope</span>
                    {" — "}
                    {snapshot.rollback.rolledBack} service(s) rolled back
                  </li>
                  <li>
                    <span className="font-medium text-medha-text">Preserved</span>
                    {" — "}
                    {snapshot.rollback.preserved} independent / upstream success(es) kept
                  </li>
                </ol>
                <p className="mt-2 text-sm text-medha-text">
                  {snapshot.rollback.preserved} preserved · {snapshot.rollback.failed} failed ·{" "}
                  {snapshot.rollback.rolledBack} rolled back
                </p>
                <p className="mt-2 text-xs leading-relaxed text-medha-secondary">
                  {viewMode === "simple"
                    ? snapshot.rollback.simpleExplanation
                    : `scope=[${snapshot.rollback.scopeNodeIds.join(", ")}]`}
                </p>
                <ul className="mt-3 space-y-1.5">
                  {snapshot.rollback.details.map((d) => (
                    <li key={d.service} className="flex items-start justify-between gap-2 text-xs">
                      <span className="font-medium text-medha-text">
                        {d.service}{" "}
                        <span className="font-normal text-medha-secondary">
                          {statusGlyph(d.status)} {labelStatus(d.status)}
                        </span>
                      </span>
                      {viewMode === "technical" && d.note ? (
                        <span className="medha-mono text-[9px] text-medha-tertiary">{d.note}</span>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="medha-label">{label}</p>
      <p className={cn("mt-0.5 text-sm text-medha-text", mono ? "medha-mono text-xs" : "")}>
        {value}
      </p>
    </div>
  );
}