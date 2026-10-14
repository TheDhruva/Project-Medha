"use client";

import type { PipelineStage } from "@/lib/projects/useProjectData";
import { cn } from "@/lib/ui/cn";

export function formatDuration(ms: number | null | undefined): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

const PILL = {
  done: "border-medha-success bg-medha-success-soft text-medha-success-ink",
  active: "border-medha-run bg-medha-run-soft text-medha-run-ink",
  blocked: "border-medha-danger bg-medha-danger-soft text-medha-danger",
  idle: "border-medha-border bg-medha-surface text-medha-tertiary",
} as const;

const DOT = {
  done: "bg-medha-success",
  active: "bg-medha-run",
  blocked: "bg-medha-danger",
  idle: "bg-medha-border-strong",
} as const;

/**
 * Connected event-driven pipeline. Stages, states, and durations come from
 * observed backend logs — nothing here invents progress. The active stage
 * pulses only while the run is running (and never under reduced motion).
 */
export function PipelineTimeline({
  stages,
  running,
  blockedHint,
}: {
  stages: PipelineStage[];
  running: boolean;
  /** Shown once below the timeline when the run failed at the config gate. */
  blockedHint?: string | null;
}) {
  return (
    <div>
      <ol className="flex flex-wrap items-stretch gap-y-2" aria-label="Execution pipeline stages">
        {stages.map((stage, index) => {
          const duration = formatDuration(stage.durationMs);
          return (
            <li
              key={stage.id}
              aria-current={stage.state === "active" ? "step" : undefined}
              className="flex items-center"
            >
              {index > 0 ? (
                <span
                  aria-hidden
                  className={cn(
                    "mx-1 h-px w-5 shrink-0 sm:w-7",
                    stage.state === "idle" && stages[index - 1].state === "idle"
                      ? "bg-medha-border"
                      : "bg-medha-border-strong",
                  )}
                />
              ) : null}
              <span
                title={
                  stage.state === "blocked"
                    ? stage.reason === "config"
                      ? "Blocked by execution configuration"
                      : "Failed at this stage"
                    : duration
                      ? `Observed duration ${duration}`
                      : undefined
                }
                className={cn(
                  "inline-flex max-w-full flex-col rounded-lg border px-2.5 py-1.5 text-[12px] font-medium leading-tight",
                  PILL[stage.state],
                )}
              >
                <span className="inline-flex items-center gap-1.5">
                  <span
                    aria-hidden
                    className={cn(
                      "status-dot shrink-0",
                      DOT[stage.state],
                      running && stage.state === "active" && "medha-stage-pulse",
                    )}
                  />
                  <span className="truncate">{stage.label}</span>
                </span>
                <span className="mt-0.5 pl-3.5 text-[10.5px] font-normal opacity-80">
                  {stage.state === "blocked"
                    ? stage.reason === "config"
                      ? "not configured"
                      : "failed"
                    : stage.state === "active"
                      ? duration ?? "running…"
                      : stage.state === "done"
                        ? duration ?? "observed"
                        : "not reached"}
                </span>
              </span>
            </li>
          );
        })}
      </ol>
      {blockedHint ? (
        <p className="mt-2.5 border-t border-medha-border pt-2 text-[12.5px] text-medha-secondary">
          {blockedHint}
        </p>
      ) : null}
    </div>
  );
}
