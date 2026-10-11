"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  EdgeLabelRenderer,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { fetchDemoChangeImpact } from "@/lib/api/client";
import { layoutCig } from "@/lib/changeintel/layout";
import type {
  ChangeIntelAnalysis,
  ChangeIntelConfidence,
  ChangeIntelEdge,
  ChangeIntelNode,
  ChangeIntelNodeType,
  ChangeIntelRelationship,
} from "@/lib/demo/types";

type CigFlowNode = Node<{ node: ChangeIntelNode }, "cig">;

const NODE_STYLE: Record<
  ChangeIntelNodeType,
  { border: string; bg: string; text: string; badge: string }
> = {
  changed: { border: "#b45309", bg: "#fef4e3", text: "#7c3c05", badge: "CHANGED" },
  affected: { border: "#6d4fb5", bg: "#f0ecfb", text: "#4b3490", badge: "AFFECTED" },
  context: { border: "#aab2bd", bg: "#ffffff", text: "#5a6573", badge: "CONTEXT" },
  config: { border: "#0f766e", bg: "#e6f5f3", text: "#0b4f4a", badge: "CONFIG" },
  test: { border: "#1b7a4a", bg: "#e6f5ed", text: "#145c38", badge: "TEST" },
};

const RELATION_COLOR: Record<ChangeIntelRelationship, string> = {
  import: "#8791a0",
  call: "#9aa3b0",
  reference: "#9aa3b0",
  extends: "#b4529b",
  implements: "#b4529b",
  inherits: "#b4529b",
  "api-consumer": "#7c5cd1",
  "schema-consumer": "#0f766e",
  "configuration-dependency": "#a56a12",
  "test-covers": "#1b7a4a",
  unknown: "#c9ced8",
};

function confidenceStyle(confidence: ChangeIntelConfidence): string {
  return confidence === "heuristic" ? "dashed" : "solid";
}

function riskTone(level: string): string {
  switch (level) {
    case "high":
      return "border-medha-danger/30 bg-medha-danger-soft text-medha-danger";
    case "medium":
      return "border-medha-warning/30 bg-medha-warning-soft text-medha-warning";
    case "low":
      return "border-medha-success/30 bg-medha-success-soft text-medha-success";
    default:
      return "border-medha-border bg-medha-muted text-medha-tertiary";
  }
}

function CigNode({ data, selected }: NodeProps<CigFlowNode>) {
  const node = data.node;
  const style = NODE_STYLE[node.node_type] ?? NODE_STYLE.context;
  return (
    <div
      className={`min-w-[150px] rounded-lg border-2 px-3 py-2 shadow-sm ${selected ? "ring-2 ring-medha-accent ring-offset-2" : ""}`}
      style={{ borderColor: style.border, background: style.bg, color: style.text }}
    >
      <Handle type="target" position={Position.Top} className="!h-2 !w-2 !border-0 !bg-medha-strong" />
      <p className="medha-mono text-[10px] font-semibold uppercase tracking-wide opacity-80">
        {style.badge} · {node.language}
      </p>
      <p className="mt-0.5 medha-mono truncate text-xs font-medium">{node.path}</p>
      {node.symbol ? (
        <p className="medha-mono truncate text-[10px] opacity-75">{node.symbol}</p>
      ) : null}
      <Handle type="source" position={Position.Bottom} className="!h-2 !w-2 !border-0 !bg-medha-strong" />
    </div>
  );
}

const nodeTypes = { cig: CigNode };

export function ChangeImpactPanel({
  analysis,
}: {
  analysis?: ChangeIntelAnalysis | null;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [demo, setDemo] = useState<ChangeIntelAnalysis | null>(analysis ?? null);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [loadingDemo, setLoadingDemo] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);
  useEffect(() => {
    setDemo(analysis ?? null);
    setSelectedId(null);
  }, [analysis]);

  const view = analysis ?? demo;
  const nodeById = useMemo(() => {
    const map = new Map<string, ChangeIntelNode>();
    for (const n of view?.graph.nodes ?? []) map.set(n.id, n);
    return map;
  }, [view]);

  const nodes: Node[] = useMemo(() => {
    if (!view) return [];
    const positions = layoutCig(view.graph.nodes, view.graph.edges);
    return view.graph.nodes.map((n) => ({
      id: n.id,
      type: "cig" as const,
      position: positions[n.id] ?? { x: 0, y: 0 },
      data: { node: n },
      selected: n.id === selectedId,
    }));
  }, [view, selectedId]);

  const edges: Edge[] = useMemo(() => {
    if (!view) return [];
    return view.graph.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      markerEnd: {
        type: MarkerType.ArrowClosed,
        width: 14,
        height: 14,
        color: RELATION_COLOR[e.relationship] ?? "#8791a0",
      },
      style: {
        stroke: RELATION_COLOR[e.relationship] ?? "#8791a0",
        strokeWidth: 1.5,
        strokeDasharray: confidenceStyle(e.confidence) === "dashed" ? "5 4" : undefined,
      },
    }));
  }, [view]);

  const edgeLabels = useMemo(() => {
    if (!view) return [];
    const positions = layoutCig(view.graph.nodes, view.graph.edges);
    return view.graph.edges
      .map((e) => {
        const s = positions[e.source];
        const t = positions[e.target];
        if (!s || !t) return null;
        return {
          ...e,
          x: (s.x + t.x) / 2,
          y: (s.y + t.y) / 2,
        };
      })
      .filter(
        (v): v is ChangeIntelEdge & { x: number; y: number } => v !== null,
      );
  }, [view]);

  const selectedNode = selectedId ? nodeById.get(selectedId) ?? null : null;
  const selectedEdges = useMemo(() => {
    if (!selectedId || !view) return [];
    return view.graph.edges.filter(
      (e) => e.source === selectedId || e.target === selectedId,
    );
  }, [selectedId, view]);

  async function loadDemo() {
    setLoadingDemo(true);
    setDemoError(null);
    try {
      const response = await fetchDemoChangeImpact();
      setDemo(response.analysis);
      setSelectedId(null);
    } catch {
      setDemoError("Could not load the demo fixture. Is the backend running on :8000?");
    } finally {
      setLoadingDemo(false);
    }
  }

  if (!view) {
    return (
      <section className="medha-panel animate-medha-in">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-medha-border px-4 py-3 sm:px-5">
          <div>
            <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
              CHANGE IMPACT GRAPH
            </h2>
            <p className="mt-1 text-xs text-medha-secondary">
              Phase 2 — repository dependency impact, distinct from the execution graph
            </p>
          </div>
        </div>
        <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center">
          <p className="max-w-lg text-sm text-medha-secondary">
            No change-intelligence analysis yet. It appears alongside live deployments
            with git revisions, or load the canned fixture to explore the CIG, risk, and
            verification requirements.
          </p>
          <button
            className="medha-btn"
            type="button"
            onClick={() => void loadDemo()}
            disabled={loadingDemo}
          >
            {loadingDemo ? "Loading…" : "Load demo fixture"}
          </button>
          {demoError ? <p className="text-sm text-medha-danger">{demoError}</p> : null}
        </div>
      </section>
    );
  }

  const counts = view.changeset.counts;

  return (
    <section className="medha-panel animate-medha-in overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-medha-border px-4 py-3 sm:px-5">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <h2 className="font-display text-sm font-semibold tracking-wide text-medha-text">
              CHANGE IMPACT GRAPH
            </h2>
            <p className="mt-1 text-xs text-medha-secondary">
              Repository dependency impact — evidence-based, no LLM. Research contribution #3.
            </p>
          </div>
          {view.label ? (
            <span className="rounded-full border border-medha-warning/40 bg-medha-warning-soft px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-medha-warning">
              {view.label}
            </span>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`rounded-medha-sm border px-2 py-1 text-[11px] font-semibold uppercase tracking-wide ${riskTone(view.risk.level)}`}
          >
            Risk: {view.risk.level}
          </span>
          <span className="medha-mono rounded-medha-sm border border-medha-border bg-medha-muted px-2 py-1 text-[10px] text-medha-tertiary">
            {String(counts.modified)}M · {counts.added}A · {counts.deleted}D ·{" "}
            {counts.renamed}R
          </span>
        </div>
      </div>

      <div className="grid lg:grid-cols-[1fr_320px]">
        <div className="relative h-[380px] border-b border-medha-border bg-[#fafbfc] lg:border-b-0 lg:border-r">
          {nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center px-6 text-center text-sm text-medha-secondary">
              The change set produced no dependency graph.
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
              fitViewOptions={{ padding: 0.25 }}
              minZoom={0.4}
              maxZoom={1.5}
              proOptions={{ hideAttribution: true }}
              onNodeClick={(_, n) => setSelectedId(n.id)}
              onPaneClick={() => setSelectedId(null)}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable
            >
              <Background gap={18} size={1} color="#e2e5eb" />
              <Controls showInteractive={false} />
              <EdgeLabelRenderer>
                {edgeLabels.map((lbl) => (
                  <div
                    key={lbl.id}
                    className="pointer-events-none absolute z-10 -translate-x-1/2 -translate-y-1/2 rounded-full border border-medha-border bg-white/90 px-1.5 py-0.5 text-[9px] font-semibold text-medha-secondary shadow-sm"
                    style={{ left: lbl.x, top: lbl.y }}
                  >
                    {lbl.relationship}
                    <span className="ml-1 font-normal lowercase opacity-70">
                      {lbl.confidence}
                    </span>
                  </div>
                ))}
              </EdgeLabelRenderer>
            </ReactFlow>
          )}
        </div>

        <aside className="max-h-[560px] space-y-5 overflow-y-auto p-4">
          <RiskSummary analysis={view} />
          <ChangedFiles analysis={view} />
          <ImpactSummary analysis={view} />
          <EvidenceList analysis={view} />
          <RequirementsList analysis={view} />
          {selectedNode ? <SelectedNodeDetail node={selectedNode} edges={selectedEdges} /> : null}
        </aside>
      </div>
    </section>
  );
}

function RiskSummary({ analysis }: { analysis: ChangeIntelAnalysis }) {
  if (analysis.risk.factors.length === 0) {
    return (
      <div>
        <p className="medha-label">Risk assessment</p>
        <p className="mt-0.5 text-sm text-medha-secondary">
          No risk factors identified for this change set.
        </p>
      </div>
    );
  }
  return (
    <div>
      <p className="medha-label">Risk factors</p>
      <ul className="mt-1.5 space-y-1.5">
        {analysis.risk.factors.map((f) => (
          <li
            key={f.code}
            className="flex items-start justify-between gap-2 text-xs leading-relaxed"
          >
            <span className="text-medha-text">{f.reason}</span>
            <span
              className={`shrink-0 rounded-full border px-1.5 py-0.5 text-[9px] font-semibold uppercase ${riskTone(f.level)}`}
            >
              {f.level}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ChangedFiles({ analysis }: { analysis: ChangeIntelAnalysis }) {
  const files = analysis.changeset.files;
  if (files.length === 0) {
    return (
      <div>
        <p className="medha-label">Changed files</p>
        <p className="mt-0.5 text-sm text-medha-secondary">No files changed.</p>
      </div>
    );
  }
  return (
    <div>
      <p className="medha-label">Changed files ({files.length})</p>
      <ul className="mt-1.5 space-y-1">
        {files.map((f) => (
          <li key={f.path} className="flex items-baseline justify-between gap-2">
            <span className="medha-mono text-xs text-medha-text">
              {f.change_type === "renamed" && f.old_path ? `${f.old_path} → ` : ""}
              {f.path}
            </span>
            <span className="shrink-0 text-[10px] text-medha-tertiary">
              +{f.added_lines}/−{f.deleted_lines}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ImpactSummary({ analysis }: { analysis: ChangeIntelAnalysis }) {
  const t = analysis.traversal;
  return (
    <div className="grid grid-cols-3 gap-2">
      <div className="rounded-medha-sm border border-medha-border bg-white p-2">
        <p className="text-[9px] font-semibold uppercase tracking-wide text-medha-tertiary">
          Direct
        </p>
        <p className="medha-mono mt-0.5 text-sm font-semibold text-medha-text">
          {t.direct_targets.length}
        </p>
      </div>
      <div className="rounded-medha-sm border border-medha-border bg-white p-2">
        <p className="text-[9px] font-semibold uppercase tracking-wide text-medha-tertiary">
          Transitive
        </p>
        <p className="medha-mono mt-0.5 text-sm font-semibold text-medha-text">
          {t.transitive_targets.length} / depth {t.depth_used}
        </p>
      </div>
      <div className="rounded-medha-sm border border-medha-border bg-white p-2">
        <p className="text-[9px] font-semibold uppercase tracking-wide text-medha-tertiary">
          Cycles
        </p>
        <p className="medha-mono mt-0.5 text-sm font-semibold text-medha-text">
          {t.cycles_detected.length}
        </p>
      </div>
      {analysis.traversal.direct_targets.length > 0 ? (
        <p className="col-span-3 text-[11px] leading-relaxed text-medha-secondary">
          Directly affected:{" "}
          <span className="medha-mono text-[10px]">
            {[...analysis.traversal.direct_targets].sort().join(", ")}
          </span>
        </p>
      ) : null}
      {analysis.unresolved.length > 0 ? (
        <div className="col-span-3">
          <p className="medha-label">Unresolved dependencies ({analysis.unresolved.length})</p>
          <ul className="mt-1 space-y-1">
            {analysis.unresolved.map((u, i) => (
              <li key={`${u.path}:${u.line}:${i}`} className="text-[11px] leading-relaxed text-medha-secondary">
                <span className="medha-mono text-[10px] text-medha-text">
                  {u.path}:{u.line} → {u.target}
                </span>{" "}
                <span className="rounded-full bg-medha-muted px-1.5 py-0.5 text-[9px] uppercase text-medha-tertiary">
                  {u.kind}
                </span>
                <span className="block opacity-80">{u.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function EvidenceList({ analysis }: { analysis: ChangeIntelAnalysis }) {
  if (analysis.graph.edges.length === 0) return null;
  return (
    <div>
      <p className="medha-label">Dependency evidence ({analysis.graph.edges.length})</p>
      <ul className="mt-1.5 space-y-1.5">
        {analysis.graph.edges.map((e) => (
          <li
            key={e.id}
            className="rounded-medha-sm border border-medha-border bg-white px-2.5 py-2"
          >
            <p className="medha-mono text-[10px] text-medha-text">
              {e.source} → {e.target}
            </p>
            <p className="mt-0.5 flex items-center gap-2 text-[10px] uppercase text-medha-secondary">
              <span>{e.relationship}</span>
              <span
                className={`opacity-70 ${e.confidence === "heuristic" ? "italic" : ""}`}
              >
                {e.confidence}
              </span>
            </p>
            <p className="medha-mono mt-1 text-[10px] text-medha-tertiary">{e.evidence}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function RequirementsList({ analysis }: { analysis: ChangeIntelAnalysis }) {
  if (analysis.requirements.length === 0) {
    return (
      <div>
        <p className="medha-label">Verification requirements</p>
        <p className="mt-0.5 text-sm text-medha-secondary">No requirements identified.</p>
      </div>
    );
  }
  return (
    <div>
      <p className="medha-label">
        Verification requirements ({analysis.requirements.length})
      </p>
      <ul className="mt-1.5 space-y-2">
        {analysis.requirements.map((r) => (
          <li key={r.id} className="rounded-medha-sm border border-medha-border bg-white p-2.5">
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-xs font-medium leading-snug text-medha-text">
                {r.requirement}
              </span>
              <span
                className={`text-[9px] font-semibold uppercase ${
                  r.executable
                    ? "text-medha-success"
                    : "text-medha-warning"
                }`}
              >
                {r.status}
              </span>
            </div>
            <p className="mt-1 text-[11px] leading-relaxed text-medha-secondary">
              {r.reason}
            </p>
            <p className="medha-mono mt-1 text-[10px] text-medha-tertiary">
              {r.target_path} · category={r.check_category}
              {r.executable ? " · verifier can run this" : " · source-level check (not faked)"}
            </p>
          </li>
        ))}
      </ul>
    </div>
  );
}

function SelectedNodeDetail({
  node,
  edges: incident,
}: {
  node: ChangeIntelNode;
  edges: ChangeIntelEdge[];
}) {
  return (
    <div className="rounded-medha-sm border border-medha-border bg-medha-accent-soft/40 p-3">
      <p className="text-[9px] font-semibold uppercase tracking-wide text-medha-accent">
        Selected CIG node
      </p>
      <p className="medha-mono mt-1 break-all text-xs font-medium text-medha-text">
        {node.path}
        {node.symbol ? ` :: ${node.symbol}` : ""}
      </p>
      <ul className="mt-2 space-y-1.5">
        {incident.map((e) => (
          <li key={e.id} className="text-[11px] leading-relaxed text-medha-secondary">
            <span className="medha-mono text-[10px] text-medha-text">
              {e.source === node.id ? e.source : e.target}
            </span>{" "}
            {e.source === node.id ? "→" : "←"}{" "}
            <span className="medha-mono text-[10px] text-medha-text">
              {e.source === node.id ? e.target : e.source}
            </span>
            <span className="ml-1 uppercase opacity-70">{e.relationship}</span>
            <span className="block opacity-80">{e.evidence}</span>
          </li>
        ))}
        {incident.length === 0 ? (
          <li className="text-[11px] text-medha-tertiary">No incident graph edges.</li>
        ) : null}
      </ul>
    </div>
  );
}