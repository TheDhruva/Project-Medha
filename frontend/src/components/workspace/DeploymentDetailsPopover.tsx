"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Activity, ChevronDown, RefreshCw } from "lucide-react";
import { Badge } from "@/components/ui/primitives";
import { deployStateOf } from "@/components/workspace/DashboardSections";
import type { RunHealth, RunSummary } from "@/lib/api/client";
import { formatActivity, isRunningStatus } from "@/lib/projects/projects";
import { cn } from "@/lib/ui/cn";

type Tone = "success" | "warning" | "error" | "info" | "neutral";

function pipelineTone(status: string): Tone {
  if (status === "partial_recovery" || status === "awaiting_approval") return "warning";
  if (status === "failed" || status === "cancelled") return "error";
  if (isRunningStatus(status)) return "info";
  return "neutral";
}

function runLabel(index: number): string {
  if (index <= 0) return "Latest deployment";
  if (index === 1) return "Previous deployment";
  return "Earlier attempt";
}

function storedHealth(run: RunSummary): string | null {
  const health = (run.health_status ?? "").toLowerCase();
  if (health === "healthy") return "healthy";
  if (health === "unhealthy" || health === "failed") return "unhealthy";
  if (health === "running" || health === "degraded") return "health unverified";
  if (health === "not_deployed" || health === "not-deployed" || health === "stopped") {
    return "not deployed";
  }
  return null;
}

const ACTION_CLASS =
  "inline-flex items-center justify-center rounded-md border border-medha-border bg-medha-surface px-2.5 py-1.5 text-[13px] font-semibold text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent";

export function DeploymentDetailsPopover({
  projectId,
  runs,
  selectedRun,
  selectedIndex,
  health,
  hydrating,
  blockers,
  loading,
  error,
  executionMode,
  starting,
  canStartRun,
  onSelectRun,
  onRetry,
  onStartRun,
}: {
  projectId: string;
  runs: RunSummary[];
  selectedRun: RunSummary | null;
  selectedIndex: number;
  health: RunHealth | null;
  hydrating: boolean;
  blockers: number;
  loading: boolean;
  error: string | null;
  executionMode: string | null;
  starting: boolean;
  canStartRun: boolean;
  onSelectRun: (id: string) => void;
  onRetry: () => void;
  onStartRun: () => void;
}) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointer(event: PointerEvent) {
      if (wrapRef.current && !wrapRef.current.contains(event.target as Node)) setOpen(false);
    }
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const runHref = selectedRun
    ? `/projects/${projectId}/runs/${selectedRun.deployment_id}`
    : null;
  const deploy = deployStateOf(selectedRun, health);
  const pipeline = selectedRun?.status.replace(/_/g, " ") ?? null;
  const healthLabel = hydrating
    ? "Checking health…"
    : deploy.state === "unknown"
      ? selectedRun && isRunningStatus(selectedRun.status)
        ? "Health pending"
        : "Health status unavailable"
      : deploy.state === "not-deployed"
        ? "Deployment not deployed"
        : `Deployment ${deploy.label.toLowerCase()}`;
  const healthTone: Tone = hydrating ? "neutral" : deploy.tone;

  return (
    <div ref={wrapRef} className="relative w-full">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="deployment-details-popover"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex h-9 w-full items-center justify-center gap-1.5 rounded-lg border border-medha-border bg-medha-surface px-3 text-[13.5px] font-semibold text-medha-secondary transition hover:bg-medha-surface-muted hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
        data-testid="deployment-details-trigger"
      >
        <Activity className="h-3.5 w-3.5" aria-hidden />
        Deployment details
        <ChevronDown
          className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")}
          aria-hidden
        />
      </button>

      {open ? (
        <div
          id="deployment-details-popover"
          role="dialog"
          aria-label="Deployment details"
          className="fixed inset-x-3 bottom-3 z-50 max-h-[min(70vh,32rem)] overflow-y-auto rounded-xl border border-medha-border bg-medha-surface p-3 text-left shadow-medha sm:absolute sm:inset-x-auto sm:bottom-auto sm:right-0 sm:top-full sm:mt-2 sm:w-[21rem] sm:max-w-[calc(100vw-2rem)]"
        >
          {error ? (
            <div role="alert" className="rounded-lg border border-medha-danger/30 bg-medha-danger-soft p-3 text-[13.5px] leading-relaxed text-medha-text">
              <p className="font-semibold">Deployment details unavailable.</p>
              <p className="mt-0.5">{error}</p>
              <button
                type="button"
                onClick={onRetry}
                className="mt-2 inline-flex items-center gap-1 rounded-md border border-medha-danger/30 bg-white px-2 py-1 text-[13px] font-semibold hover:bg-medha-danger-soft focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
              >
                <RefreshCw className="h-3 w-3" aria-hidden /> Retry
              </button>
            </div>
          ) : loading ? (
            <p role="status" className="text-[13.5px] text-medha-secondary">
              Loading deployment details…
            </p>
          ) : !selectedRun ? (
            <div>
              <p className="text-[13.5px] font-medium text-medha-text">No runs yet</p>
              <p className="mt-0.5 text-[13px] text-medha-secondary">
                Start an analysis to see pipeline and deployment status.
              </p>
              {canStartRun ? (
                <button
                  type="button"
                  onClick={onStartRun}
                  disabled={starting}
                  className="mt-2 rounded-md bg-medha-accent px-3 py-1.5 text-[13px] font-semibold text-white hover:bg-medha-accent-hover disabled:opacity-60 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent"
                >
                  {starting ? "Starting…" : "Run analysis"}
                </button>
              ) : (
                <Link href="/verify" className="mt-2 inline-block rounded-md bg-medha-accent px-3 py-1.5 text-[13px] font-semibold text-white">
                  Run analysis
                </Link>
              )}
            </div>
          ) : (
            <>
              <div className="flex items-center justify-between gap-2">
                <p className="medha-label">
                  {runLabel(selectedIndex)}
                </p>
                <span className="text-[12.5px] text-medha-tertiary">
                  {formatActivity(selectedRun.created_at)}
                </span>
              </div>

              {runs.length > 1 ? (
                <label className="mt-1.5 block">
                  <span className="sr-only">Selected deployment</span>
                  <select
                    value={selectedRun.deployment_id}
                    onChange={(event) => onSelectRun(event.target.value)}
                    className="w-full rounded-md border border-medha-border bg-medha-surface px-2 py-1.5 text-[13px] text-medha-text focus:border-medha-accent focus:outline-none focus:ring-2 focus:ring-medha-accent/30"
                  >
                    {runs.map((run, index) => {
                      const healthText = storedHealth(run);
                      return (
                        <option key={run.deployment_id} value={run.deployment_id}>
                          {runLabel(index)} · {formatActivity(run.created_at)} ·{" "}
                          {run.status.replace(/_/g, " ")}
                          {healthText ? ` · ${healthText}` : ""}
                        </option>
                      );
                    })}
                  </select>
                </label>
              ) : null}

              <dl className="mt-2 space-y-1.5 text-[13.5px]">
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-medha-tertiary">Pipeline</dt>
                  <dd>
                    <Badge tone={pipelineTone(selectedRun.status)}>
                      {pipeline === "completed" ? "Pipeline completed" : `Pipeline ${pipeline}`}
                    </Badge>
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-medha-tertiary">Deployment</dt>
                  <dd>
                    <Badge tone={healthTone}>{healthLabel}</Badge>
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-medha-tertiary">Blockers</dt>
                  <dd>
                    {hydrating ? (
                      <span className="text-medha-tertiary">Checking blockers…</span>
                    ) : blockers > 0 ? (
                      <a
                        href="#findings"
                        onClick={() => setOpen(false)}
                        className="rounded font-semibold text-medha-danger hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                      >
                        {blockers} blocker{blockers === 1 ? "" : "s"}
                      </a>
                    ) : (
                      <span className="text-medha-secondary">No blockers recorded</span>
                    )}
                  </dd>
                </div>
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-medha-tertiary">Duration</dt>
                  <dd className="text-medha-text">
                    {selectedRun.duration_seconds != null
                      ? `${selectedRun.duration_seconds}s`
                      : "Not available"}
                  </dd>
                </div>
              </dl>

              <div className="mt-2.5 grid grid-cols-3 gap-1.5 border-t border-medha-border pt-2">
                {runHref ? (
                  <Link href={runHref} onClick={() => setOpen(false)} className={ACTION_CLASS}>
                    Run details
                  </Link>
                ) : null}
                <Link
                  href={`/projects/${projectId}/verification?run=${encodeURIComponent(selectedRun.deployment_id)}`}
                  onClick={() => setOpen(false)}
                  className={ACTION_CLASS}
                >
                  Verification
                </Link>
                <Link
                  href={`/projects/${projectId}/runs`}
                  onClick={() => setOpen(false)}
                  className={ACTION_CLASS}
                >
                  Run history
                </Link>
              </div>

              <details className="mt-2 border-t border-medha-border pt-1.5 text-[12.5px] text-medha-secondary">
                <summary className="cursor-pointer rounded font-medium text-medha-tertiary hover:text-medha-text focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
                  Technical details
                </summary>
                <dl className="mt-1 space-y-0.5">
                  <div className="flex gap-1.5">
                    <dt className="text-medha-tertiary">Run</dt>
                    <dd className="medha-mono truncate">{selectedRun.deployment_id}</dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="text-medha-tertiary">Revision</dt>
                    <dd className="medha-mono">
                      {selectedRun.target_revision ?? "not bound"}
                    </dd>
                  </div>
                  <div className="flex gap-1.5">
                    <dt className="text-medha-tertiary">Execution</dt>
                    <dd>{executionMode ?? "not reported"}</dd>
                  </div>
                </dl>
              </details>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
