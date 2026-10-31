"use client";

import React, { memo } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";
import type { CommitNodeData } from "@/lib/git/gitGraphLayout";
import { formatActivity, isRunningStatus } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

export const CommitNode = memo(function CommitNode({
  data,
}: NodeProps<Node<CommitNodeData>>) {
  const { commit, run, isSelected, isAncestor, hasSelection } = data;
  const shortSha = commit.sha.slice(0, 7);
  const isMerge = commit.parents && commit.parents.length > 1;
  const firstLine = (commit.message ?? "No commit message").split("\n")[0];
  const relTime = formatActivity(commit.committed_at);

  const isAnalyzing = run ? isRunningStatus(run.status) : false;
  const isFailed = run?.status === "failed";
  const isSuccess = run?.status === "completed" || run?.result_kind === "success";

  return (
    <div
      tabIndex={0}
      role="button"
      aria-label={`Commit ${shortSha}: ${firstLine}`}
      aria-pressed={isSelected}
      className={cn(
        "group relative w-[240px] select-none rounded-lg border bg-white px-2.5 py-2 text-[12px] shadow-xs transition-all focus:outline-none",
        isSelected
          ? "border-medha-accent ring-2 ring-medha-accent shadow-sm z-20"
          : isAncestor
            ? "border-medha-accent/70 ring-1 ring-medha-accent/30 z-10"
            : hasSelection
              ? "border-medha-border opacity-40 hover:opacity-100 hover:border-medha-secondary/40"
              : "border-medha-border hover:border-medha-secondary/40 hover:shadow-sm",
      )}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-2 !w-2 !-top-1 !bg-transparent !border-0"
        aria-hidden
      />

      {/* Header row: Status dot, SHA, Badges */}
      <div className="flex items-center justify-between gap-1.5">
        <div className="flex items-center gap-1.5 min-w-0">
          {/* Status Indicator Dot */}
          <span className="relative flex h-2.5 w-2.5 shrink-0 items-center justify-center">
            {isAnalyzing ? (
              <span className="h-2 w-2 rounded-full bg-medha-info animate-pulse" />
            ) : isFailed ? (
              <span className="h-2 w-2 rounded-full bg-medha-danger" />
            ) : isSuccess ? (
              <span className="h-2 w-2 rounded-full bg-medha-success" />
            ) : (
              <span className="h-2 w-2 rounded-full border border-medha-secondary/60 bg-medha-surface" />
            )}
          </span>

          <span className="font-mono text-[11.5px] font-semibold text-medha-text">
            {shortSha}
          </span>
        </div>

        <div className="flex items-center gap-1 shrink-0">
          {isMerge ? (
            <span className="rounded border border-medha-border bg-medha-surface-soft px-1 text-[10px] font-mono uppercase text-medha-secondary">
              merge
            </span>
          ) : null}
          {commit.branch ? (
            <span className="max-w-[65px] truncate rounded bg-medha-surface-soft px-1 text-[10px] font-mono text-medha-secondary">
              {commit.branch}
            </span>
          ) : null}
        </div>
      </div>

      {/* Commit headline message */}
      <p
        className="mt-1 truncate text-[12px] font-medium text-medha-text leading-snug"
        title={commit.message ?? ""}
      >
        {firstLine}
      </p>

      {/* Author and Relative Time */}
      <div className="mt-1 flex items-center justify-between text-[11px] text-medha-secondary">
        <span className="truncate max-w-[120px]">{commit.author ?? "Unknown"}</span>
        <span className="shrink-0">{relTime}</span>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-2 !w-2 !-bottom-1 !bg-transparent !border-0"
        aria-hidden
      />
    </div>
  );
});
