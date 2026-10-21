"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { Plus, CheckCircle2, AlertTriangle, XCircle, Loader2 } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { EnvBadge } from "@/components/ui/Section";
import { fetchRunsList, type RunSummary } from "@/lib/api/client";
import { scenarioDisplayName } from "@/lib/runs/display";
import { summarizeRunFailure } from "@/lib/projects/projects";

function outcomeFor(status: string): { icon: React.ReactNode; label: string } {
  switch (status) {
    case "completed":
      return {
        icon: <CheckCircle2 className="h-4 w-4 shrink-0 text-medha-success" aria-hidden />,
        label: "Completed",
      };
    case "partial_recovery":
      return {
        icon: <AlertTriangle className="h-4 w-4 shrink-0 text-medha-warning" aria-hidden />,
        label: "Recovered",
      };
    case "failed":
      return {
        icon: <XCircle className="h-4 w-4 shrink-0 text-medha-danger" aria-hidden />,
        label: "Blocked",
      };
    case "cancelled":
      return {
        icon: <XCircle className="h-4 w-4 shrink-0 text-medha-danger" aria-hidden />,
        label: "Cancelled",
      };
    case "running":
    case "started":
    case "queued":
      return {
        icon: <Loader2 className="h-4 w-4 shrink-0 animate-spin text-medha-run" aria-hidden />,
        label: status === "queued" ? "Queued" : "Running",
      };
    default:
      return {
        icon: <span className="status-dot bg-medha-tertiary" aria-hidden />,
        label: status.replace(/_/g, " "),
      };
  }
}

function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function conciseOutcome(run: RunSummary): string | null {
  if (run.result_kind === "partial_recovery") return "Recovered with scoped rollback";
  if (run.result_kind === "failed") return summarizeRunFailure(run);
  if (run.status === "completed") return "All checks passed";
  if (run.status === "failed") return summarizeRunFailure(run);
  return null;
}

export function RunsList() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchRunsList({ limit: 50, offset: 0 });
      setRuns(response.runs);
      setTotal(response.total);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Cannot reach MEDHA backend.",
      );
      setRuns([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppShell>
      <div className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-[28px] font-semibold tracking-tight text-medha-text">Runs</h1>
            <p className="mt-1 text-[14px] text-medha-secondary">
              Every verification Medha has performed, with its decision and evidence.
            </p>
          </div>
          <Link
            href="/verify"
            className="inline-flex items-center gap-1.5 rounded-md bg-medha-accent px-4 py-2 text-sm font-semibold text-white transition hover:bg-medha-accent-hover focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
          >
            <Plus className="h-4 w-4" aria-hidden /> New verification
          </Link>
        </div>

        {loading ? (
          <p className="text-sm text-medha-secondary" aria-live="polite">
            Loading runs…
          </p>
        ) : error ? (
          <section
            role="alert"
            className="rounded-md border border-medha-danger/30 bg-medha-danger-soft p-4 text-[13.5px] leading-relaxed text-medha-text"
          >
            <p className="font-semibold">Unable to load runs.</p>
            <p className="mt-1">{error}</p>
            <button
              type="button"
              onClick={() => void load()}
              className="mt-3 rounded-md border border-medha-danger/30 bg-white px-3 py-1.5 text-[12.5px] font-semibold text-medha-danger hover:bg-medha-danger-soft"
            >
              Retry
            </button>
          </section>
        ) : runs.length === 0 ? (
          <section className="flex flex-col items-center rounded-md border border-medha-border bg-medha-surface p-8 text-center">
            <p className="text-[15px] font-semibold text-medha-text">No runs yet.</p>
            <p className="mt-1 max-w-md text-[13.5px] leading-relaxed text-medha-secondary">
              Start your first verification to see Medha analyze, resolve, and verify
              a change.
            </p>
            <Link
              href="/verify"
              className="mt-4 rounded-md bg-medha-accent px-4 py-2 text-sm font-semibold text-white hover:bg-medha-accent-hover"
            >
              Start verification
            </Link>
          </section>
        ) : (
          <>
            <p className="text-[12.5px] text-medha-secondary" aria-live="polite">
              {total} run{total === 1 ? "" : "s"}
            </p>
            <section aria-label="Runs">
              <ul className="divide-y divide-medha-border overflow-hidden rounded-md border border-medha-border bg-medha-surface">
                {runs.map((run) => {
                  const outcome = outcomeFor(run.status);
                  const detail = conciseOutcome(run);
                  return (
                    <li key={run.deployment_id}>
                      <Link
                        href={`/runs/${run.deployment_id}`}
                        className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-medha-surface-muted/60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                      >
                        {outcome.icon}
                        <span className="min-w-0 flex-1">
                          <span className="block truncate text-[14.5px] font-semibold text-medha-text">
                            {scenarioDisplayName(run)}
                          </span>
                          <span className="mt-0.5 line-clamp-2 block text-[12.5px] leading-4 text-medha-secondary">
                            {outcome.label}
                            {detail ? ` · ${detail}` : ""}
                            {run.duration_seconds != null
                              ? ` · ${run.duration_seconds.toFixed(1)}s`
                              : ""}
                            {` · ${formatDateTime(run.created_at)}`}
                          </span>
                        </span>
                        <EnvBadge isDemo={run.is_demo} size="sm" />
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </section>
          </>
        )}
      </div>
    </AppShell>
  );
}