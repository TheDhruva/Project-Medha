"use client";

import Link from "next/link";
import { useMemo } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock,
  Loader2,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import type { RunSummary } from "@/lib/api/client";
import { formatActivity, isRunningStatus, runOutcome, type OutcomeTone } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

interface RecentActivityProps {
  projectId: string;
  runs: RunSummary[];
}

interface ActivityEvent {
  id: string;
  type: string;
  title: string;
  detail: string;
  timestamp: string;
  tone: OutcomeTone;
  runId: string;
  targetSha: string | null;
}

export function RecentActivity({ projectId, runs }: RecentActivityProps) {
  const events = useMemo<ActivityEvent[]>(() => {
    return runs.slice(0, 5).map((r) => {
      const outcome = runOutcome(r);
      const isRunning = isRunningStatus(r.status);
      const isSuccess = r.status === "completed" || r.result_kind === "success";
      const isFailure = r.status === "failed";
      const shortSha = r.target_revision ? r.target_revision.slice(0, 7) : null;

      let type = "Analysis";
      let title = outcome.analysis.label;
      let tone: OutcomeTone = outcome.analysis.tone;

      if (isRunning) {
        type = "Pipeline";
        title = "Analysis in progress";
        tone = "info";
      } else if (r.status === "awaiting_approval") {
        type = "Proposal";
        title = "Plan awaiting review";
        tone = "warning";
      } else if (isSuccess) {
        if (outcome.deployment) {
          type = "Deployment";
          title = outcome.deployment.label;
          tone = outcome.deployment.tone;
        } else {
          type = "Assessment";
          title = "Assessment completed";
          tone = "success";
        }
      } else if (isFailure) {
        type = "Failure";
        title = r.error_summary ? `Failed: ${r.error_summary}` : "Run failed";
        tone = "error";
      }

      const detail = [
        shortSha ? `commit ${shortSha}` : null,
        r.duration_seconds != null ? `${r.duration_seconds}s` : null,
      ]
        .filter(Boolean)
        .join(" · ");

      return {
        id: r.deployment_id,
        type,
        title,
        detail,
        timestamp: formatActivity(r.updated_at || r.created_at),
        tone,
        runId: r.deployment_id,
        targetSha: shortSha,
      };
    });
  }, [runs]);

  return (
    <div
      className="rounded-lg border border-medha-border bg-medha-surface p-4 sm:p-5 shadow-sm"
      data-testid="recent-activity"
    >
      <div className="flex items-center justify-between border-b border-medha-border pb-3">
        <div>
          <h2 className="text-[15px] font-semibold text-medha-text">Recent Activity</h2>
          <p className="text-[12px] text-medha-secondary">
            Operational pipeline events and verification results
          </p>
        </div>

        <Link
          href={`/projects/${projectId}/runs`}
          className="inline-flex items-center gap-1 text-[12.5px] font-semibold text-medha-accent transition hover:text-medha-accent-hover"
        >
          View all activity <ArrowRight className="h-3 w-3" />
        </Link>
      </div>

      <div className="pt-3">
        {events.length === 0 ? (
          <p className="py-4 text-center text-[13px] text-medha-secondary">
            No operational activity recorded yet.
          </p>
        ) : (
          <ol className="divide-y divide-medha-border" aria-label="Recent activity log">
            {events.map((ev) => (
              <li
                key={ev.id}
                className="flex items-center justify-between gap-3 py-2.5 text-[12.5px]"
              >
                <div className="flex items-center gap-2.5 min-w-0">
                  <span
                    className={cn(
                      "h-2 w-2 rounded-full shrink-0",
                      ev.tone === "success" && "bg-medha-success",
                      ev.tone === "error" && "bg-medha-danger",
                      ev.tone === "warning" && "bg-medha-warning",
                      ev.tone === "info" && "bg-medha-info",
                      ev.tone === "neutral" && "bg-medha-secondary",
                    )}
                    aria-hidden
                  />
                  <span className="font-semibold text-medha-text truncate">
                    {ev.title}
                  </span>
                  {ev.detail ? (
                    <span className="text-medha-secondary font-mono text-[11.5px] truncate">
                      ({ev.detail})
                    </span>
                  ) : null}
                </div>

                <div className="flex items-center gap-3 shrink-0">
                  <span className="text-[11.5px] text-medha-secondary">{ev.timestamp}</span>
                  <Link
                    href={`/projects/${projectId}/runs/${ev.runId}`}
                    className="font-medium text-[12px] text-medha-accent hover:underline"
                  >
                    View run →
                  </Link>
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

