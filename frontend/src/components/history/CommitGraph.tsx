"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  fetchCommitDetail,
  fetchCommitHistory,
  type CommitDetail,
  type HistoryCommit,
} from "@/lib/api/client";

const PAGE_SIZE = 50;
const MAX_NODES = 200;

function CommitNode({ data }: NodeProps) {
  const commit = (data as { commit: HistoryCommit }).commit;
  const short = commit.sha.slice(0, 8);
  const multi = commit.parents.length > 1;
  return (
    <div className="rounded-lg border border-medha-border bg-white px-2.5 py-1.5 text-[12px] shadow-sm">
      <Handle type="target" position={Position.Top} />
      <p className="medha-mono font-semibold text-medha-text">
        {short}
        {multi ? <span className="ml-1 rounded bg-medha-warning-soft px-1 text-[10px] text-medha-warning">merge</span> : null}
      </p>
      <p className="max-w-[220px] truncate text-medha-secondary" title={commit.message ?? ""}>
        {commit.message ?? "No message"}
      </p>
      <p className="text-[11px] text-medha-tertiary">
        {commit.author ?? "Unknown"} · {(commit.committed_at ?? "").slice(0, 10)}
      </p>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

const nodeTypes = { commit: CommitNode };

export function CommitGraph({ projectId }: { projectId: string }) {
  const canonical = projectId.startsWith("prj_");
  const [commits, setCommits] = useState<HistoryCommit[]>([]);
  const [partial, setPartial] = useState(false);
  const [shallow, setShallow] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedSha, setSelectedSha] = useState<string | null>(null);
  const [detail, setDetail] = useState<CommitDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  useEffect(() => {
    if (!canonical) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchCommitHistory(projectId, { limit: PAGE_SIZE })
      .then((res) => {
        if (cancelled) return;
        setCommits(res.commits.slice(0, MAX_NODES));
        setPartial(res.partial || res.commits.length >= MAX_NODES);
        setShallow(res.shallow);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "History unavailable.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, canonical]);

  const loadMore = useCallback(async () => {
    if (commits.length === 0 || loadingMore) return;
    setLoadingMore(true);
    try {
      const oldest = commits[commits.length - 1];
      const res = await fetchCommitHistory(projectId, {
        limit: PAGE_SIZE,
        since: oldest.committed_at ?? undefined,
      });
      const seen = new Set(commits.map((c) => c.sha));
      const fresh = res.commits.filter((c) => !seen.has(c.sha)).slice(0, MAX_NODES - commits.length);
      setCommits((prev) => [...prev, ...fresh]);
      setPartial(res.partial);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Could not load more history.");
    } finally {
      setLoadingMore(false);
    }
  }, [commits, loadingMore, projectId]);

  const select = useCallback(
    async (sha: string) => {
      setSelectedSha(sha);
      setDetail(null);
      setDetailError(null);
      setDetailLoading(true);
      try {
        const res = await fetchCommitDetail(projectId, sha);
        setDetail(res);
      } catch (err: unknown) {
        setDetailError(err instanceof Error ? err.message : "Commit detail unavailable.");
      } finally {
        setDetailLoading(false);
      }
    },
    [projectId],
  );

  const { nodes, edges } = useMemo(() => {
    const bySha = new Map(commits.map((c) => [c.sha, c]));
    const nodes: Node[] = commits.map((c, i) => ({
      id: c.sha,
      type: "commit",
      position: { x: (i % 4) * 260, y: Math.floor(i / 4) * 130 },
      data: { commit: c },
    }));
    const edges: Edge[] = [];
    for (const c of commits) {
      for (const parent of c.parents) {
        if (bySha.has(parent)) {
          edges.push({
            id: `${c.sha.slice(0, 8)}->${parent.slice(0, 8)}`,
            source: c.sha,
            target: parent,
            markerEnd: { type: MarkerType.ArrowClosed, width: 12, height: 12 },
          });
        }
      }
    }
    return { nodes, edges };
  }, [commits]);

  const selected = useMemo(
    () => commits.find((c) => c.sha === selectedSha) ?? null,
    [commits, selectedSha],
  );

  if (!canonical) {
    return (
      <p className="text-[13px] text-medha-secondary">
        Commit history requires a connected project. Connect a repository to browse real Git ancestry.
      </p>
    );
  }
  if (loading) {
    return <p className="text-[13px] text-medha-secondary">Loading real commit history…</p>;
  }
  if (error && commits.length === 0) {
    return (
      <div className="space-y-2">
        <p className="text-[13px] text-medha-secondary">History unavailable: {error}</p>
        <button type="button" className="medha-btn" onClick={() => window.location.reload()}>
          Retry
        </button>
      </div>
    );
  }
  if (commits.length === 0) {
    return <p className="text-[13px] text-medha-secondary">No commits found for this repository.</p>;
  }

  return (
    <div className="space-y-3">
      {shallow ? (
        <p className="rounded-lg border border-medha-warning/30 bg-medha-warning-soft px-2.5 py-1.5 text-[12px] text-medha-warning">
          Shallow history: ancestry may be partial. Deeper history appears as more commits are recorded.
        </p>
      ) : null}
      <div className="h-[380px] rounded-xl border border-medha-border bg-medha-surface">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          onNodeClick={(_, node) => void select(node.id)}
          fitView
          nodesDraggable={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background />
          <Controls />
        </ReactFlow>
      </div>
      <div className="flex items-center gap-2">
        <p className="text-[12px] text-medha-tertiary">
          {commits.length} commit(s){partial ? " — older history truncated" : ""}
        </p>
        {partial ? (
          <button type="button" className="medha-btn" disabled={loadingMore} onClick={() => void loadMore()}>
            {loadingMore ? "Loading…" : "Load older"}
          </button>
        ) : null}
      </div>
      {selected ? (
        <div className="rounded-xl border border-medha-border bg-white p-3">
          <p className="medha-mono text-[13px] font-semibold text-medha-text">{selected.sha}</p>
          <p className="mt-1 text-[13px] text-medha-text">{selected.message ?? "No message"}</p>
          <p className="mt-0.5 text-[12px] text-medha-tertiary">
            {selected.author ?? "Unknown"} · {selected.committed_at ?? "Unknown time"} ·{" "}
            {selected.parents.length > 1 ? `merge (${selected.parents.length} parents)` : selected.parents.length === 1 ? `parent ${selected.parents[0].slice(0, 8)}` : "root commit"}
          </p>
          {selected.github_url ? (
            <a href={selected.github_url} target="_blank" rel="noreferrer" className="mt-1 inline-block text-[12px] font-semibold text-medha-accent hover:underline">
              Open on GitHub →
            </a>
          ) : null}
          <div className="mt-2 border-t border-medha-border pt-2">
            {detailLoading ? (
              <p className="text-[12px] text-medha-secondary">Loading diff summary…</p>
            ) : detailError ? (
              <p className="text-[12px] text-medha-secondary">Diff summary unavailable: {detailError}</p>
            ) : detail ? (
              <>
                <p className="text-[12px] font-semibold text-medha-text">
                  {detail.files.length} file(s) · +{detail.added} −{detail.deleted}
                  {detail.truncated ? " (truncated)" : ""}
                </p>
                <ul className="mt-1 max-h-48 space-y-0.5 overflow-y-auto">
                  {detail.files.slice(0, 50).map((f) => (
                    <li key={f.path} className="medha-mono flex justify-between gap-2 text-[11px] text-medha-secondary">
                      <span className="truncate">{f.path}</span>
                      <span className="shrink-0">+{f.added} −{f.deleted}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-[12px] text-medha-secondary">Select a commit node to see its diff summary.</p>
            )}
          </div>
        </div>
      ) : (
        <p className="text-[12px] text-medha-tertiary">Click a commit node for author, timestamp, message, SHA, changed files, and the GitHub link.</p>
      )}
    </div>
  );
}
