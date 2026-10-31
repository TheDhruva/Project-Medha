"use client";

import Link from "next/link";
import React, { useState } from "react";
import {
  Check,
  CheckCircle2,
  Clock,
  Copy,
  ExternalLink,
  FileCode,
  GitCommit,
  GitFork,
  Loader2,
  PlayCircle,
  TrendingDown,
  TrendingUp,
  X,
  XCircle,
} from "lucide-react";
import type { CommitDetail, HistoryCommit, RunSummary } from "@/lib/api/client";
import { categorizeImpact } from "@/lib/git/gitGraphLayout";
import { formatActivity, isRunningStatus } from "@/lib/projects/projects";

interface CommitDetailsPanelProps {
  projectId: string;
  commit: HistoryCommit | null;
  run: RunSummary | null;
  detail: CommitDetail | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onSelectSha: (sha: string) => void;
  parentRun?: RunSummary | null;
}

export function CommitDetailsPanel({
  projectId,
  commit,
  run,
  detail,
  loading,
  error,
  onClose,
  onSelectSha,
  parentRun,
}: CommitDetailsPanelProps) {
  const [copied, setCopied] = useState(false);

  const copySha = () => {
    if (!commit) return;
    navigator.clipboard.writeText(commit.sha).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  if (!commit) {
    return (
      <div
        className="flex h-full min-h-[460px] w-full flex-col items-center justify-center p-6 text-center text-medha-secondary"
        data-testid="commit-details-placeholder"
      >
        <GitCommit className="h-10 w-10 text-medha-secondary/40" aria-hidden />
        <h3 className="mt-3 text-[14px] font-semibold text-medha-text">Commit Inspector</h3>
        <p className="mt-1 max-w-[260px] text-[12.5px] leading-relaxed">
          Select any node in the graph to inspect changes, engineering impact, assessment status, and deployment history.
        </p>
      </div>
    );
  }

  const shortSha = commit.sha.slice(0, 7);
  const firstLine = (commit.message ?? "No commit message").split("\n")[0];
  const restBody = (commit.message ?? "")
    .split("\n")
    .slice(1)
    .join("\n")
    .trim();
  const relTime = formatActivity(commit.committed_at);

  const isAssessed = run != null;
  const isFailed = run?.status === "failed";
  const isAnalyzing = run ? isRunningStatus(run.status) : false;

  return (
    <div
      className="flex h-full flex-col overflow-y-auto p-4 sm:p-5 text-[12.5px] space-y-4"
      data-testid={`commit-detail-panel-${shortSha}`}
    >
      {/* Top action row: Title & Close Button */}
      <div className="flex items-start justify-between gap-2 border-b border-medha-border pb-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[12px] font-semibold text-medha-text">
              {shortSha}
            </span>
            <button
              type="button"
              onClick={copySha}
              title="Copy full SHA"
              aria-label="Copy full SHA"
              className="inline-flex items-center gap-1 text-[11px] text-medha-secondary hover:text-medha-text"
            >
              {copied ? (
                <>
                  <Check className="h-3 w-3 text-medha-success" />
                  <span className="text-medha-success font-medium">Copied</span>
                </>
              ) : (
                <>
                  <Copy className="h-3 w-3" />
                  <span>Copy</span>
                </>
              )}
            </button>
            {commit.github_url ? (
              <a
                href={commit.github_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[11.5px] font-medium text-medha-accent hover:underline ml-auto mr-1"
              >
                GitHub <ExternalLink className="h-3 w-3" />
              </a>
            ) : null}
          </div>

          <h3 className="mt-1 font-semibold text-[13.5px] text-medha-text leading-snug">
            {firstLine}
          </h3>

          <div className="mt-1 text-[11.5px] text-medha-secondary">
            <span>{commit.author ?? "Unknown"}</span>
            <span className="mx-1.5">·</span>
            <span>{relTime}</span>
          </div>

          {/* Parents lineage */}
          {commit.parents && commit.parents.length > 0 ? (
            <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11.5px] text-medha-secondary">
              <GitFork className="h-3 w-3 text-medha-secondary" aria-hidden />
              <span>{commit.parents.length > 1 ? "Parents:" : "Parent:"}</span>
              {commit.parents.map((pSha) => (
                <button
                  key={pSha}
                  type="button"
                  onClick={() => onSelectSha(pSha)}
                  className="rounded border border-medha-border bg-medha-surface-soft px-1.5 py-0.5 font-mono text-[11px] font-medium text-medha-text transition hover:border-medha-accent hover:text-medha-accent"
                >
                  {pSha.slice(0, 7)}
                </button>
              ))}
            </div>
          ) : (
            <div className="mt-1.5 text-[11px] text-medha-secondary">Initial root commit</div>
          )}
        </div>

        <button
          type="button"
          onClick={onClose}
          aria-label="Close commit details"
          className="rounded-md p-1 text-medha-secondary hover:bg-medha-surface-muted hover:text-medha-text"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 py-4 text-medha-secondary">
          <Loader2 className="h-4 w-4 animate-spin text-medha-accent" />
          <span>Loading commit details…</span>
        </div>
      ) : error ? (
        <div className="rounded-md border border-medha-danger/20 bg-medha-danger-soft p-3 text-medha-danger">
          <p className="font-semibold text-[12px]">Unable to load commit diff</p>
          <p className="mt-0.5 text-[11.5px]">{error}</p>
        </div>
      ) : (
        <div className="space-y-4">
          {/* 1. What Changed? */}
          <div>
            <h4 className="text-[11.5px] font-semibold uppercase tracking-wider text-medha-secondary">
              What Changed?
            </h4>
            <div className="mt-1.5 rounded-md border border-medha-border bg-medha-surface-soft p-2.5">
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
              <p className="mt-1 text-[12px] text-medha-secondary leading-relaxed">
                {detail?.summary ?? "File-level diff explanation unavailable."}
              </p>
            </div>
            {restBody ? (
              <p className="mt-2 whitespace-pre-wrap font-mono text-[11.5px] text-medha-secondary max-h-32 overflow-y-auto rounded bg-medha-surface-soft p-2">
                {restBody}
              </p>
            ) : null}
          </div>

          {/* 2. Engineering Impact */}
          <div>
            <h4 className="text-[11.5px] font-semibold uppercase tracking-wider text-medha-secondary">
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

          {/* 3. MEDHA Assessment */}
          <div>
            <h4 className="text-[11.5px] font-semibold uppercase tracking-wider text-medha-secondary">
              MEDHA Assessment
            </h4>
            <div className="mt-1.5 rounded-md border border-medha-border bg-medha-surface-soft p-2.5">
              {isAssessed && run ? (
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <span className="inline-flex items-center gap-1.5 font-semibold text-medha-text">
                      {isAnalyzing ? (
                        <>
                          <Loader2 className="h-3.5 w-3.5 animate-spin text-medha-info" />
                          <span>Analyzing…</span>
                        </>
                      ) : isFailed ? (
                        <>
                          <XCircle className="h-3.5 w-3.5 text-medha-danger" />
                          <span>Assessment Failed</span>
                        </>
                      ) : (
                        <>
                          <CheckCircle2 className="h-3.5 w-3.5 text-medha-success" />
                          <span>Assessment Complete</span>
                        </>
                      )}
                    </span>
                    <Link
                      href={`/projects/${projectId}/runs/${run.deployment_id}`}
                      className="text-[11.5px] font-semibold text-medha-accent hover:underline"
                    >
                      Inspect run →
                    </Link>
                  </div>
                  <p className="text-[11.5px] text-medha-secondary">
                    Run {run.deployment_id.slice(0, 10)}… · Recorded {formatActivity(run.updated_at)}
                  </p>
                  {run.error_summary ? (
                    <p className="text-[11.5px] text-medha-danger">{run.error_summary}</p>
                  ) : null}
                  {parentRun && parentRun.result_kind && (
                    <div className="mt-1 pt-1 border-t border-medha-border/60 flex items-center gap-1 text-[11px] text-medha-secondary">
                      <span>Compared to parent revision {parentRun.target_revision?.slice(0, 7)}:</span>
                      <span className="font-medium text-medha-text">
                        {run.result_kind === parentRun.result_kind ? "Maintained status" : `${parentRun.result_kind} → ${run.result_kind}`}
                      </span>
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-1.5 text-medha-secondary">
                  <div className="flex items-center gap-1.5 font-medium text-medha-text">
                    <Clock className="h-3.5 w-3.5 text-medha-secondary" />
                    <span>Not assessed yet</span>
                  </div>
                  <p className="text-[11.5px] leading-relaxed">
                    This commit has not been analyzed by MEDHA. You can inspect its code changes or run an analysis on this exact revision.
                  </p>
                  <Link
                    href={`/verify?project=${encodeURIComponent(projectId)}&rev=${commit.sha}`}
                    className="inline-flex items-center gap-1 text-[11.5px] font-semibold text-medha-accent hover:underline pt-0.5"
                  >
                    Analyze revision {shortSha} →
                  </Link>
                </div>
              )}
            </div>
          </div>

          {/* 4. Files Changed */}
          <div>
            <h4 className="text-[11.5px] font-semibold uppercase tracking-wider text-medha-secondary">
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
                      <span className="font-mono text-medha-text truncate" title={file.path}>
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

          {/* 5. Deployment */}
          <div>
            <h4 className="text-[11.5px] font-semibold uppercase tracking-wider text-medha-secondary">
              Deployment
            </h4>
            <p className="mt-1 text-[12px] text-medha-secondary">
              {run && run.status === "completed"
                ? `Deployment recorded for run ${run.deployment_id.slice(0, 14)}…`
                : run && isFailed
                  ? "Deployment failed during execution pipeline."
                  : "No deployment attempted for this commit."}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
