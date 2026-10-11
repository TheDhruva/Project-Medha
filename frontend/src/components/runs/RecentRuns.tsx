"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ArrowRight, CheckCircle2, AlertTriangle, XCircle, Loader2 } from "lucide-react";
import { fetchRunsList, type RunSummary } from "@/lib/api/client";
import { EnvBadge } from "@/components/ui/Section";
import { scenarioDisplayName } from "@/lib/runs/display";

function outcomeFor(run: RunSummary): { icon: React.ReactNode; label: string } {
  if (run.status === "completed") {
    return {
      icon: <CheckCircle2 className="h-4 w-4 text-medha-success" aria-hidden />,
      label: "Completed",
    };
  }
  if (run.status === "partial_recovery") {
    return {
      icon: <AlertTriangle className="h-4 w-4 text-medha-warning" aria-hidden />,
      label: "Recovered",
    };
  }
  if (run.status === "failed" || run.status === "cancelled") {
    return {
      icon: <XCircle className="h-4 w-4 text-medha-danger" aria-hidden />,
      label: run.status === "cancelled" ? "Cancelled" : "Blocked",
    };
  }
  if (run.status === "running" || run.status === "started" || run.status === "queued") {
    return {
      icon: <Loader2 className="h-4 w-4 animate-spin text-medha-accent" aria-hidden />,
      label: "Running",
    };
  }
  return {
    icon: <span className="status-dot bg-medha-tertiary" aria-hidden />,
    label: run.status.replace(/_/g, " "),
  };
}

export function RecentRuns({ limit = 3 }: { limit?: number }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    let cancelled = false;
    fetchRunsList({ limit, offset: 0 })
      .then((response) => {
        if (cancelled) return;
        setRuns(response.runs);
        setState("ready");
      })
      .catch(() => {
        if (cancelled) return;
        setState("error");
      });
    return () => {
      cancelled = true;
    };
  }, [limit]);

  if (state === "loading") {
    return (
      <section aria-label="Recent runs" aria-busy="true">
        <p className="py-2 text-sm text-medha-secondary">Loading recent runs…</p>
      </section>
    );
  }

  if (state === "error" || runs.length === 0) {
    return (
      <section aria-label="Recent runs">
        <p className="py-2 text-sm text-medha-secondary">
          {state === "error"
            ? "Recent runs are unavailable while the backend is unreachable."
            : "No runs yet. Start your first verification to see it here."}
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Recent runs">
      <ul className="divide-y divide-medha-border overflow-hidden rounded-xl border border-medha-border bg-white">
        {runs.map((run) => {
          const outcome = outcomeFor(run);
          return (
            <li key={run.deployment_id}>
              <Link
                href={`/runs/${run.deployment_id}`}
                className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-medha-muted/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
              >
                {outcome.icon}
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-medha-text">
                    {scenarioDisplayName(run)}
                  </span>
                  <span className="mt-0.5 block text-xs text-medha-secondary">
                    {outcome.label}
                    {run.duration_seconds != null
                      ? ` · ${run.duration_seconds.toFixed(1)}s`
                      : ""}
                  </span>
                </span>
                <EnvBadge isDemo={run.is_demo} size="sm" />
              </Link>
            </li>
          );
        })}
      </ul>
      <Link
        href="/runs"
        className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
      >
        View all runs <ArrowRight className="h-3.5 w-3.5" aria-hidden />
      </Link>
    </section>
  );
}