"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import {
  ChevronDown,
  GitBranch,
  GitCommit,
  Loader2,
  Maximize2,
  Minus,
  Plus,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import {
  fetchCommitDetail,
  fetchCommitHistory,
  type CommitDetail,
  type HistoryCommit,
  type RunSummary,
} from "@/lib/api/client";
import { buildGitGraphDAG, type CommitNodeData } from "@/lib/git/gitGraphLayout";
import { CommitNode } from "@/components/history/CommitNode";
import { CommitDetailsPanel } from "@/components/history/CommitDetailsPanel";
import { cn } from "@/lib/ui/cn";

const PAGE_SIZE = 30;
const MAX_COMMITS = 150;

const nodeTypes = {
  commitNode: CommitNode,
};

interface GitCommitGraphProps {
  projectId: string;
  defaultBranch?: string | null;
  runs: RunSummary[];
}

function GraphViewInner({
  nodes,
  edges,
  selectedSha,
  onSelectSha,
  onDeselect,
}: {
  nodes: Node<CommitNodeData>[];
  edges: Edge[];
  selectedSha: string | null;
  onSelectSha: (sha: string) => void;
  onDeselect: () => void;
}) {
  const { fitView, zoomIn, zoomOut } = useReactFlow();

  const handleRecenter = useCallback(() => {
    fitView({ padding: 0.2, duration: 400 });
  }, [fitView]);

  return (
    <div className="relative h-full min-h-[500px] w-full flex-1 bg-medha-surface-soft/40">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelectSha(node.id)}
        onPaneClick={onDeselect}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={1.8}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={true}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#CBD5E1" gap={20} size={1} />
      </ReactFlow>

      {/* Floating minimal canvas controls */}
      <div
        className="absolute bottom-3 left-3 z-20 flex items-center gap-1 rounded-lg border border-medha-border bg-white/95 p-1 shadow-xs backdrop-blur-xs"
        aria-label="Canvas controls"
      >
        <button
          type="button"
          onClick={() => zoomIn({ duration: 200 })}
          title="Zoom in"
          aria-label="Zoom in"
          className="rounded p-1 text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={() => zoomOut({ duration: 200 })}
          title="Zoom out"
          aria-label="Zoom out"
          className="rounded p-1 text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text"
        >
          <Minus className="h-3.5 w-3.5" />
        </button>
        <div className="mx-0.5 h-3.5 w-px bg-medha-border" />
        <button
          type="button"
          onClick={handleRecenter}
          title="Fit graph to view"
          aria-label="Fit graph to view"
          className="rounded p-1 text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
        <button
          type="button"
          onClick={handleRecenter}
          title="Recenter"
          aria-label="Recenter"
          className="rounded p-1 text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text"
        >
          <RotateCcw className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* Subtle interaction tip */}
      <div className="pointer-events-none absolute top-3 left-3 z-10 hidden sm:block">
        <span className="rounded bg-white/90 px-2 py-1 text-[11px] text-medha-secondary border border-medha-border/60 shadow-xs">
          Click a node to highlight ancestry & inspect
        </span>
      </div>
    </div>
  );
}

export function GitCommitGraph({
  projectId,
  defaultBranch = "main",
  runs,
}: GitCommitGraphProps) {
  const initialBranch = defaultBranch || "main";
  const [selectedBranch, setSelectedBranch] = useState<string>(initialBranch);
  const [branches, setBranches] = useState<string[]>([initialBranch]);
  const [commits, setCommits] = useState<HistoryCommit[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  // Commit selection state
  const [selectedSha, setSelectedSha] = useState<string | null>(null);
  const [detailsCache, setDetailsCache] = useState<Record<string, CommitDetail>>({});
  const [detailsLoading, setDetailsLoading] = useState<Record<string, boolean>>({});
  const [detailsError, setDetailsError] = useState<Record<string, string>>({});

  // Map of runs by exact commit SHA or 40-char revision (lower-cased)
  const runsByRevision = useMemo(() => {
    const map = new Map<string, RunSummary>();
    for (const r of runs) {
      if (r.analysis_coverage?.commit_sha) {
        map.set(r.analysis_coverage.commit_sha.toLowerCase(), r);
      }
      if (r.target_revision && r.target_revision.length === 40) {
        map.set(r.target_revision.toLowerCase(), r);
      }
    }
    return map;
  }, [runs]);

  // Load commit history
  const loadHistory = useCallback(
    async (branch: string, isRefresh = false) => {
      setLoading(true);
      setError(null);
      try {
        const branchParam = branch === "all" ? undefined : branch;
        const res = await fetchCommitHistory(projectId, {
          branch: branchParam,
          limit: PAGE_SIZE,
          refresh: isRefresh,
        });

        setCommits(res.commits.slice(0, MAX_COMMITS));
        setHasMore(res.partial || res.commits.length >= PAGE_SIZE);

        if (res.branches && res.branches.length > 0) {
          setBranches((prev) => Array.from(new Set([...prev, ...res.branches!])));
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Commit history unavailable.");
      } finally {
        setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    void loadHistory(selectedBranch);
  }, [loadHistory, selectedBranch]);

  // Load more commits
  const handleLoadMore = useCallback(async () => {
    if (loadingMore || commits.length === 0 || commits.length >= MAX_COMMITS) return;
    setLoadingMore(true);
    try {
      const oldest = commits[commits.length - 1];
      const branchParam = selectedBranch === "all" ? undefined : selectedBranch;
      const res = await fetchCommitHistory(projectId, {
        branch: branchParam,
        limit: PAGE_SIZE,
        since: oldest?.committed_at ?? undefined,
      });

      const seen = new Set(commits.map((c) => c.sha));
      const fresh = res.commits.filter((c) => !seen.has(c.sha));

      setCommits((prev) => [...prev, ...fresh].slice(0, MAX_COMMITS));
      // Persisted responses report partial=false, so a full page is the only
      // signal that older commits may still exist.
      setHasMore(
        fresh.length > 0 &&
          (res.partial || res.commits.length >= PAGE_SIZE) &&
          commits.length + fresh.length < MAX_COMMITS,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load additional history.");
    } finally {
      setLoadingMore(false);
    }
  }, [commits, loadingMore, projectId, selectedBranch]);

  // Handle commit selection & detail fetch
  const handleSelectSha = useCallback(
    async (sha: string) => {
      setSelectedSha(sha);

      if (!detailsCache[sha] && !detailsLoading[sha]) {
        setDetailsLoading((prev) => ({ ...prev, [sha]: true }));
        setDetailsError((prev) => {
          const next = { ...prev };
          delete next[sha];
          return next;
        });

        try {
          const detail = await fetchCommitDetail(projectId, sha);
          setDetailsCache((prev) => ({ ...prev, [sha]: detail }));
        } catch (err) {
          setDetailsError((prev) => ({
            ...prev,
            [sha]: err instanceof Error ? err.message : "Details unavailable",
          }));
        } finally {
          setDetailsLoading((prev) => ({ ...prev, [sha]: false }));
        }
      }
    },
    [detailsCache, detailsLoading, projectId],
  );

  // Construct DAG nodes and edges
  const { nodes, edges } = useMemo(() => {
    return buildGitGraphDAG({
      commits,
      runs,
      selectedSha,
    });
  }, [commits, runs, selectedSha]);

  const selectedCommit = useMemo(() => {
    if (!selectedSha) return null;
    return commits.find((c) => c.sha.toLowerCase() === selectedSha.toLowerCase()) ?? null;
  }, [commits, selectedSha]);

  const matchedRun = useMemo(() => {
    if (!selectedSha) return null;
    return runsByRevision.get(selectedSha.toLowerCase()) ?? null;
  }, [runsByRevision, selectedSha]);

  const parentRun = useMemo(() => {
    const parentSha = selectedCommit?.parents?.[0];
    if (!parentSha) return null;
    return runsByRevision.get(parentSha.toLowerCase()) ?? null;
  }, [runsByRevision, selectedCommit]);

  return (
    <div
      className="rounded-lg border border-medha-border bg-medha-surface shadow-sm overflow-hidden"
      data-testid="commit-graph"
    >
      {/* Header bar: title, branch selector, refresh */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-medha-border px-4 py-3 sm:px-5">
        <div>
          <h2 className="text-[16px] font-semibold text-medha-text">Commit History</h2>
          <p className="text-[12.5px] text-medha-secondary">
            Ancestry, branching, and assessment graph
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Branch selector */}
          <div className="relative inline-flex items-center">
            <GitBranch
              className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-medha-secondary"
              aria-hidden
            />
            <select
              value={selectedBranch}
              onChange={(e) => {
                setSelectedBranch(e.target.value);
                setSelectedSha(null);
              }}
              aria-label="Select branch"
              className="h-8 appearance-none rounded-md border border-medha-border bg-medha-surface pl-8 pr-7 text-[12.5px] font-medium text-medha-text transition hover:bg-medha-surface-muted focus:border-medha-accent focus:outline-none"
            >
              {branches.map((b) => (
                <option key={b} value={b}>
                  {b}
                </option>
              ))}
              <option value="all">All branches</option>
            </select>
            <ChevronDown
              className="pointer-events-none absolute right-2 h-3.5 w-3.5 text-medha-secondary"
              aria-hidden
            />
          </div>

          {/* Refresh action */}
          <button
            type="button"
            onClick={() => void loadHistory(selectedBranch, true)}
            title="Refresh commit history"
            aria-label="Refresh commit history"
            disabled={loading}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md border border-medha-border bg-medha-surface text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
          >
            <RefreshCw
              className={cn("h-3.5 w-3.5", loading && "animate-spin")}
              aria-hidden
            />
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      {loading && commits.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-medha-secondary" aria-label="Loading commits">
          <Loader2 className="h-6 w-6 animate-spin text-medha-accent" />
          <p className="mt-2 text-[13px]">Loading Git commit DAG…</p>
        </div>
      ) : error && commits.length === 0 ? (
        <div className="p-5 text-[13px]">
          <div className="rounded-lg border border-medha-danger/20 bg-medha-danger-soft p-4 text-medha-text">
            <p className="font-semibold text-medha-danger">Commit history unavailable</p>
            <p className="mt-0.5 text-medha-secondary">{error}</p>
            <button
              type="button"
              onClick={() => void loadHistory(selectedBranch, true)}
              className="mt-2.5 inline-flex items-center gap-1.5 rounded-md border border-medha-border bg-white px-2.5 py-1 text-[12px] font-semibold text-medha-text hover:bg-medha-surface-muted"
            >
              <RefreshCw className="h-3 w-3" /> Retry
            </button>
          </div>
        </div>
      ) : commits.length === 0 ? (
        <div className="py-12 text-center text-medha-secondary">
          <GitCommit className="mx-auto h-8 w-8 text-medha-secondary/50" aria-hidden />
          <p className="mt-2 text-[14px] font-semibold text-medha-text">No commits found</p>
          <p className="mt-0.5 text-[12.5px]">
            No recorded commits found for branch <span className="font-mono">{selectedBranch}</span>.
          </p>
        </div>
      ) : (
        <div>
          {/* Split View: Graph Canvas (Left) + Details Panel (Right) */}
          <div className="flex flex-col lg:flex-row h-[560px] border-b border-medha-border">
            {/* Canvas */}
            <div className="flex-1 h-full min-h-[360px] overflow-hidden">
              <ReactFlowProvider>
                <GraphViewInner
                  nodes={nodes}
                  edges={edges}
                  selectedSha={selectedSha}
                  onSelectSha={(sha) => void handleSelectSha(sha)}
                  onDeselect={() => setSelectedSha(null)}
                />
              </ReactFlowProvider>
            </div>

            {/* Right-Side Commit Details Panel */}
            <div className="w-full lg:w-[380px] xl:w-[420px] shrink-0 border-t lg:border-t-0 lg:border-l border-medha-border bg-white">
              <CommitDetailsPanel
                projectId={projectId}
                commit={selectedCommit}
                run={matchedRun}
                detail={selectedSha ? detailsCache[selectedSha] ?? null : null}
                loading={selectedSha ? Boolean(detailsLoading[selectedSha]) : false}
                error={selectedSha ? detailsError[selectedSha] ?? null : null}
                onClose={() => setSelectedSha(null)}
                onSelectSha={(sha) => void handleSelectSha(sha)}
                parentRun={parentRun}
              />
            </div>
          </div>

          {/* Bottom Bar: Stats & Pagination */}
          <div className="flex flex-wrap items-center justify-between gap-3 px-4 py-2.5 bg-medha-surface-soft/60 text-[12px] text-medha-secondary">
            <div>
              <span>{commits.length} commits rendered</span>
              {hasMore ? <span> (older commits available)</span> : null}
            </div>

            {hasMore ? (
              <button
                type="button"
                onClick={() => void handleLoadMore()}
                disabled={loadingMore}
                className="inline-flex items-center gap-1.5 rounded-md border border-medha-border bg-white px-2.5 py-1 text-[12px] font-medium text-medha-text shadow-2xs hover:bg-medha-surface-muted disabled:opacity-50"
              >
                {loadingMore ? (
                  <>
                    <Loader2 className="h-3 w-3 animate-spin" />
                    Loading…
                  </>
                ) : (
                  "Load older commits"
                )}
              </button>
            ) : null}
          </div>
        </div>
      )}
    </div>
  );
}

