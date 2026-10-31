"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  ExternalLink,
  FileCode,
  GitBranch,
  GitCommit,
  Loader2,
  RefreshCw,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import {
  fetchCommitDetail,
  fetchCommitHistory,
  type CommitDetail,
  type HistoryCommit,
  type RunSummary,
} from "@/lib/api/client";
import { formatActivity, isRunningStatus } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

interface CommitTimelineProps {
  projectId: string;
  defaultBranch?: string | null;
  runs: RunSummary[];
}

const PAGE_SIZE = 15;

/** Categorize changed files into engineering impact areas deterministically */
function categorizeImpact(files: { path: string }[]): string[] {
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

export function CommitTimeline({
  projectId,
  defaultBranch = "main",
  runs,
}: CommitTimelineProps) {
  const initialBranch = defaultBranch || "main";
  const [selectedBranch, setSelectedBranch] = useState<string>(initialBranch);
  const [branches, setBranches] = useState<string[]>([initialBranch]);
  const [commits, setCommits] = useState<HistoryCommit[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);

  // Inline expansion state
  const [expandedSha, setExpandedSha] = useState<string | null>(null);
  const [detailsCache, setDetailsCache] = useState<Record<string, CommitDetail>>({});
  const [detailsLoading, setDetailsLoading] = useState<Record<string, boolean>>({});
  const [detailsError, setDetailsError] = useState<Record<string, string>>({});

  // Map of runs by target_revision (lower-cased)
  const runsByRevision = useMemo(() => {
    const map = new Map<string, RunSummary>();
    for (const r of runs) {
      if (r.target_revision) {
        map.set(r.target_revision.toLowerCase(), r);
      }
    }
    return map;
  }, [runs]);

  // Fetch commits when branch changes
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

        setCommits(res.commits);
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

  // Load more pagination
  const handleLoadMore = useCallback(async () => {
    if (loadingMore || commits.length === 0) return;
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

      setCommits((prev) => [...prev, ...fresh]);
      setHasMore(res.partial && fresh.length > 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load additional history.");
    } finally {
      setLoadingMore(false);
    }
  }, [commits, loadingMore, projectId, selectedBranch]);

  // Toggle inline commit expansion
  const toggleExpand = useCallback(
    async (sha: string) => {
      if (expandedSha === sha) {
        setExpandedSha(null);
        return;
      }
      setExpandedSha(sha);

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
    [detailsCache, detailsLoading, expandedSha, projectId],
  );

  return (
    <div
      className="rounded-lg border border-medha-border bg-medha-surface p-4 sm:p-5 shadow-sm"
      data-testid="commit-timeline"
    >
      {/* Header bar: title, branch selector, refresh */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-medha-border pb-3.5">
        <div>
          <h2 className="text-[16px] font-semibold text-medha-text">Commit History</h2>
          <p className="text-[12.5px] text-medha-secondary">
            Lineage, assessment records, and code changes
          </p>
        </div>

        <div className="flex items-center gap-2">
          {/* Branch selector */}
          <div className="relative inline-flex items-center">
            <GitBranch className="pointer-events-none absolute left-2.5 h-3.5 w-3.5 text-medha-secondary" aria-hidden />
            <select
              value={selectedBranch}
              onChange={(e) => {
                setSelectedBranch(e.target.value);
                setExpandedSha(null);
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
            <ChevronDown className="pointer-events-none absolute right-2 h-3.5 w-3.5 text-medha-secondary" aria-hidden />
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
            <RefreshCw className={cn("h-3.5 w-3.5", loading && "animate-spin")} aria-hidden />
          </button>
        </div>
      </div>

      {/* Main Content */}
      <div className="pt-4">
        {loading && commits.length === 0 ? (
          <div className="space-y-4 py-4" aria-label="Loading commits">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="flex gap-3">
                <div className="h-4 w-4 shrink-0 rounded-full bg-medha-border animate-pulse" />
                <div className="flex-1 space-y-2">
                  <div className="h-4 w-3/4 rounded bg-medha-border animate-pulse" />
                  <div className="h-3 w-1/3 rounded bg-medha-border/60 animate-pulse" />
                </div>
              </div>
            ))}
          </div>
        ) : error && commits.length === 0 ? (
          <div className="rounded-lg border border-medha-danger/20 bg-medha-danger-soft p-4 text-[13px] text-medha-text">
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
        ) : commits.length === 0 ? (
          <div className="py-8 text-center text-medha-secondary">
            <GitCommit className="mx-auto h-8 w-8 text-medha-secondary/50" aria-hidden />
            <p className="mt-2 text-[14px] font-semibold text-medha-text">No commits found</p>
            <p className="mt-0.5 text-[12.5px]">
              No recorded commits found for branch <span className="font-mono">{selectedBranch}</span>.
            </p>
          </div>
        ) : (
          <div className="relative space-y-0">
            {/* Vertical connector line */}
            <div
              className="pointer-events-none absolute bottom-4 left-[15px] top-4 w-px bg-medha-border"
              aria-hidden
            />

            {/* Commits list */}
            {commits.map((commit, index) => {
              const isLast = index === commits.length - 1;
              const matchedRun = runsByRevision.get(commit.sha.toLowerCase());
              const isExpanded = expandedSha === commit.sha;
              const detail = detailsCache[commit.sha];
              const isLoadingDetail = detailsLoading[commit.sha];
              const detailErr = detailsError[commit.sha];

              const shortSha = commit.sha.slice(0, 7);
              const firstLine = (commit.message ?? "No commit message").split("\n")[0];
              const restBody = (commit.message ?? "")
                .split("\n")
                .slice(1)
                .join("\n")
                .trim();
              const relTime = formatActivity(commit.committed_at);

              // Assessment state
              const isAssessed = matchedRun != null;
              const isRunFailed = matchedRun?.status === "failed";
              const isAnalyzing = matchedRun ? isRunningStatus(matchedRun.status) : false;

              return (
                <div key={commit.sha} className="relative group">
                  {/* Row container */}
                  <div
                    onClick={() => void toggleExpand(commit.sha)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" || e.key === " ") {
                        e.preventDefault();
                        void toggleExpand(commit.sha);
                      }
                    }}
                    role="button"
                    tabIndex={0}
                    aria-expanded={isExpanded}
                    aria-label={`Commit ${shortSha}: ${firstLine}`}
                    className={cn(
                      "flex cursor-pointer items-start gap-3 rounded-lg px-2 py-2.5 transition hover:bg-medha-surface-muted/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent",
                      isExpanded && "bg-medha-surface-muted/50",
                    )}
                  >
                    {/* Node Dot */}
                    <div className="relative z-10 mt-1 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-medha-surface">
                      {isAnalyzing ? (
                        <span className="h-3 w-3 rounded-full bg-medha-info ring-2 ring-medha-surface" />
                      ) : isRunFailed ? (
                        <span className="h-3 w-3 rounded-full bg-medha-danger ring-2 ring-medha-surface" />
                      ) : isAssessed ? (
                        <span className="h-3 w-3 rounded-full bg-medha-success ring-2 ring-medha-surface" />
                      ) : (
                        <span className="h-2.5 w-2.5 rounded-full border border-medha-secondary/60 bg-medha-surface ring-2 ring-medha-surface" />
                      )}
                    </div>

                    {/* Commit summary */}
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline justify-between gap-x-2 gap-y-0.5">
                        <p className="min-w-0 font-medium text-[13.5px] text-medha-text truncate">
                          {firstLine}
                        </p>
                        <span className="shrink-0 text-[12px] text-medha-secondary">
                          {relTime}
                        </span>
                      </div>

                      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-medha-secondary">
                        <span className="font-mono text-[12px] font-medium text-medha-text">
                          {shortSha}
                        </span>
                        <span>·</span>
                        <span>{commit.author ?? "Unknown"}</span>

                        {selectedBranch === "all" && commit.branch ? (
                          <>
                            <span>·</span>
                            <span className="rounded bg-medha-surface-soft px-1.5 py-0.5 text-[11px] font-mono text-medha-secondary">
                              {commit.branch}
                            </span>
                          </>
                        ) : null}

                        {/* Assessment badge */}
                        <span>·</span>
                        {isAnalyzing ? (
                          <span className="inline-flex items-center gap-1 font-medium text-medha-info">
                            <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                            Analyzing…
                          </span>
                        ) : isRunFailed ? (
                          <span className="inline-flex items-center gap-1 font-medium text-medha-danger">
                            <XCircle className="h-3 w-3" aria-hidden />
                            Assessment failed
                          </span>
                        ) : isAssessed ? (
                          <span className="inline-flex items-center gap-1 font-medium text-medha-success">
                            <CheckCircle2 className="h-3 w-3" aria-hidden />
                            Assessed
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-medha-secondary/80">
                            <Clock className="h-3 w-3" aria-hidden />
                            Not assessed
                          </span>
                        )}

                        {/* Findings info if assessed */}
                        {isAssessed && matchedRun?.result_kind === "success" ? (
                          <>
                            <span>·</span>
                            <span className="text-medha-secondary">Validated</span>
                          </>
                        ) : null}
                      </div>
                    </div>

                    {/* Expand icon */}
                    <div className="shrink-0 pt-0.5 text-medha-secondary">
                      {isExpanded ? (
                        <ChevronDown className="h-4 w-4" aria-hidden />
                      ) : (
                        <ChevronRight className="h-4 w-4 opacity-70 group-hover:opacity-100" aria-hidden />
                      )}
                    </div>
                  </div>

                  {/* ============================================================ */}
                  {/* Inline Expanded Commit Details                               */}
                  {/* ============================================================ */}
                  {isExpanded ? (
                    <div
                      className="my-2 ml-7 rounded-lg border border-medha-border bg-medha-surface p-4 text-[12.5px] shadow-sm"
                      data-testid={`commit-detail-${shortSha}`}
                    >
                      {isLoadingDetail ? (
                        <div className="flex items-center gap-2 py-3 text-medha-secondary">
                          <Loader2 className="h-4 w-4 animate-spin text-medha-accent" />
                          <span>Loading commit details…</span>
                        </div>
                      ) : detailErr ? (
                        <div className="rounded-md border border-medha-danger/20 bg-medha-danger-soft p-3 text-medha-danger">
                          <p className="font-semibold">Unable to load commit diff</p>
                          <p className="mt-0.5 text-[12px]">{detailErr}</p>
                        </div>
                      ) : (
                        <div className="space-y-4">
                          {/* A. What Changed? */}
                          <div>
                            <div className="flex items-center justify-between gap-2 border-b border-medha-border pb-1.5">
                              <h4 className="text-[12px] font-semibold uppercase tracking-wider text-medha-secondary">
                                What Changed?
                              </h4>
                              {commit.github_url ? (
                                <a
                                  href={commit.github_url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="inline-flex items-center gap-1 text-[11.5px] font-medium text-medha-accent hover:underline"
                                >
                                  View on GitHub <ExternalLink className="h-3 w-3" />
                                </a>
                              ) : null}
                            </div>

                            <p className="mt-2 text-[13px] font-medium text-medha-text">
                              {firstLine}
                            </p>
                            {restBody ? (
                              <p className="mt-1 whitespace-pre-wrap font-mono text-[12px] text-medha-secondary">
                                {restBody}
                              </p>
                            ) : null}

                            {/* Diff stats + deterministic summary */}
                            <div className="mt-2.5 rounded-md border border-medha-border bg-medha-surface-soft p-2.5">
                              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
                                <span className="font-medium text-medha-text">
                                  {detail?.files?.length ?? 0} changed files
                                </span>
                                <span className="font-medium text-medha-success">
                                  +{detail?.added ?? 0}
                                </span>
                                <span className="font-medium text-medha-danger">
                                  -{detail?.deleted ?? 0}
                                </span>
                              </div>
                              <p className="mt-1 text-[12px] text-medha-secondary">
                                {detail?.summary ?? "File-level diff explanation unavailable."}
                              </p>
                            </div>
                          </div>

                          {/* B. Impact */}
                          <div>
                            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-medha-secondary">
                              Engineering Impact
                            </h4>
                            <div className="mt-1.5 flex flex-wrap gap-1.5">
                              {detail && detail.files.length > 0 ? (
                                categorizeImpact(detail.files).map((cat) => (
                                  <span
                                    key={cat}
                                    className="rounded border border-medha-border bg-medha-surface-muted px-2 py-0.5 text-[11px] font-medium text-medha-text"
                                  >
                                    {cat}
                                  </span>
                                ))
                              ) : (
                                <span className="text-[12px] text-medha-secondary">
                                  Impact areas unavailable without diff files.
                                </span>
                              )}
                            </div>
                          </div>

                          {/* C. Assessment */}
                          <div>
                            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-medha-secondary">
                              MEDHA Assessment
                            </h4>
                            <div className="mt-1.5 rounded-md border border-medha-border bg-medha-surface-soft p-2.5">
                              {isAssessed && matchedRun ? (
                                <div className="space-y-1.5">
                                  <div className="flex items-center justify-between">
                                    <span className="font-semibold text-medha-text">
                                      {matchedRun.status === "completed"
                                        ? "Assessment Complete"
                                        : `Assessment ${matchedRun.status}`}
                                    </span>
                                    <Link
                                      href={`/projects/${projectId}/runs/${matchedRun.deployment_id}`}
                                      className="text-[12px] font-semibold text-medha-accent hover:underline"
                                    >
                                      Inspect run evidence →
                                    </Link>
                                  </div>
                                  <p className="text-[12px] text-medha-secondary">
                                    Recorded {formatActivity(matchedRun.updated_at)} · Target revision {shortSha}
                                  </p>
                                </div>
                              ) : (
                                <p className="text-[12px] text-medha-secondary">
                                  Not assessed: No analysis run recorded for this commit.
                                </p>
                              )}
                            </div>
                          </div>

                          {/* D. Files Changed */}
                          <div>
                            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-medha-secondary">
                              Files Changed ({detail?.files?.length ?? 0})
                            </h4>
                            {detail && detail.files.length > 0 ? (
                              <div className="mt-1.5 max-h-48 overflow-y-auto rounded-md border border-medha-border divide-y divide-medha-border">
                                {detail.files.map((file) => (
                                  <div
                                    key={file.path}
                                    className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-[12px]"
                                  >
                                    <div className="flex items-center gap-1.5 min-w-0">
                                      <FileCode className="h-3.5 w-3.5 shrink-0 text-medha-secondary" aria-hidden />
                                      <span className="font-mono text-medha-text truncate">
                                        {file.path}
                                      </span>
                                    </div>
                                    <div className="flex items-center gap-1.5 shrink-0 font-mono text-[11px]">
                                      {file.added > 0 ? (
                                        <span className="text-medha-success">+{file.added}</span>
                                      ) : null}
                                      {file.deleted > 0 ? (
                                        <span className="text-medha-danger">-{file.deleted}</span>
                                      ) : null}
                                    </div>
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <p className="mt-1 text-[12px] text-medha-secondary">
                                File list unavailable.
                              </p>
                            )}
                          </div>

                          {/* E. Deployment */}
                          <div>
                            <h4 className="text-[12px] font-semibold uppercase tracking-wider text-medha-secondary">
                              Deployment
                            </h4>
                            <p className="mt-1 text-[12px] text-medha-secondary">
                              {matchedRun && matchedRun.status === "completed"
                                ? `Deployment recorded for run ${matchedRun.deployment_id.slice(0, 14)}…`
                                : matchedRun && isRunFailed
                                  ? "Deployment failed during execution pipeline."
                                  : "No deployment attempted for this commit."}
                            </p>
                          </div>
                        </div>
                      )}
                    </div>
                  ) : null}
                </div>
              );
            })}

            {/* Pagination button */}
            {hasMore ? (
              <div className="pt-3 text-center">
                <button
                  type="button"
                  onClick={() => void handleLoadMore()}
                  disabled={loadingMore}
                  className="inline-flex items-center gap-1.5 rounded-md border border-medha-border bg-medha-surface px-3 py-1.5 text-[12.5px] font-medium text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text disabled:opacity-50"
                >
                  {loadingMore ? (
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      Loading more commits…
                    </>
                  ) : (
                    "Load more commits"
                  )}
                </button>
              </div>
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}

