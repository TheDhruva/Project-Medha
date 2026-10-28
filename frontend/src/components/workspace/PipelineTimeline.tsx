"use client";

import Link from "next/link";
import {
  Ban,
  CheckCircle2,
  Circle,
  Loader2,
  Minus,
  XCircle,
} from "lucide-react";
import { Badge, Panel } from "@/components/ui/primitives";
import type { RunLogLine, RunSummary } from "@/lib/api/client";
import type { PipelineStage } from "@/lib/projects/useProjectData";
import {
  PIPELINE_PHASES,
  STATE_LABEL,
  activityFor,
  derivePhaseStates,
  formatDuration,
  runStatusBadge,
  type PhaseId,
  type VisualState,
} from "@/lib/projects/executionPhases";
import { cn } from "@/lib/ui/cn";

const CARD = {
  completed:
    "border-medha-success/35 bg-medha-success-soft/40 hover:border-medha-success/60 hover:bg-medha-success-soft/60",
  running:
    "border-medha-run/40 bg-medha-run-soft/60 hover:border-medha-run/70 hover:bg-medha-run-soft",
  failed:
    "border-medha-danger/35 bg-medha-danger-soft/60 hover:border-medha-danger/60 hover:bg-medha-danger-soft",
  blocked:
    "border-medha-warning/40 bg-medha-warning-soft/40 hover:border-medha-warning/60 hover:bg-medha-warning-soft/60",
  waiting: "border-medha-border bg-medha-surface hover:border-medha-border-strong hover:bg-medha-surface-soft",
  skipped: "border-medha-border bg-medha-muted/50 hover:border-medha-border-strong hover:bg-medha-muted",
  unknown: "border-dashed border-medha-border bg-medha-surface hover:border-medha-border-strong",
} as const;

const TOP = {
  completed: "bg-medha-success",
  running: "bg-medha-run",
  failed: "bg-medha-danger",
  blocked: "bg-medha-warning",
  waiting: "bg-medha-border",
  skipped: "bg-medha-border-strong",
  unknown: "bg-medha-border",
} as const;

const STATUS_TEXT = {
  completed: "text-medha-success",
  running: "text-medha-run-ink",
  failed: "text-medha-danger",
  blocked: "text-medha-warning",
  waiting: "text-medha-tertiary",
  skipped: "text-medha-tertiary",
  unknown: "text-medha-tertiary",
} as const;

function StatusIcon({ state }: { state: VisualState }) {
  const common = "h-4 w-4 shrink-0";
  if (state === "completed") return <CheckCircle2 className={common} aria-hidden />;
  if (state === "failed") return <XCircle className={common} aria-hidden />;
  if (state === "blocked") return <Ban className={common} aria-hidden />;
  if (state === "running") {
    return (
      <Loader2
        data-testid="pipeline-running-indicator"
        className={cn(common, "motion-safe:animate-spin")}
        aria-hidden
      />
    );
  }
  if (state === "skipped") return <Minus className={common} aria-hidden />;
  return <Circle className={common} aria-hidden />;
}

export function PipelineTimeline({
  projectId,
  run,
  stages,
  logs,
  hydrating = false,
  selectedPhase,
  onSelectPhase,
}: {
  projectId: string;
  run: RunSummary | null;
  stages: PipelineStage[];
  logs: RunLogLine[];
  hydrating?: boolean;
  selectedPhase: PhaseId | null;
  onSelectPhase: (phase: PhaseId | null) => void;
}) {
  const stageById = new Map(stages.map((stage) => [stage.id, stage]));
  const states = derivePhaseStates({ run, stages, hydrating });

  const completedDurations = PIPELINE_PHASES.map((phase) => stageById.get(phase.id)?.durationMs);
  const observedTotal = completedDurations.every((value) => value != null)
    ? (completedDurations as number[]).reduce((sum, value) => sum + value, 0)
    : null;
  const totalDuration =
    run?.duration_seconds != null
      ? formatDuration(run.duration_seconds * 1000)
      : formatDuration(observedTotal);

  const overall = runStatusBadge(run?.status);

  return (
    <Panel
      className="lg:col-span-7"
      title="Run Timeline"
      eyebrow="Observed backend phases"
      action={
        <Link
          href={`/projects/${projectId}/runs`}
          className="rounded text-[12px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
        >
          All executions →
        </Link>
      }
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span data-testid="pipeline-overall-status">
          <Badge tone={overall.tone}>{overall.label}</Badge>
        </span>
        {totalDuration ? (
          <span className="text-[12px] font-medium text-medha-secondary">Total {totalDuration}</span>
        ) : null}
      </div>

      <ol
        className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3"
        aria-label="Run Timeline phases"
      >
        {PIPELINE_PHASES.map((phase, index) => {
          const state = states[phase.id];
          const stage = stageById.get(phase.id);
          const selected = selectedPhase === phase.id;
          const duration = formatDuration(stage?.durationMs);
          const activity = state === "running" ? activityFor(logs, phase.id) : null;
          return (
            <li key={phase.id} className="min-w-0">
              <button
                type="button"
                aria-pressed={selected}
                aria-controls={selected ? "operational-status-panel" : undefined}
                aria-current={state === "running" ? "step" : undefined}
                data-state={state}
                onClick={() => onSelectPhase(selected ? null : phase.id)}
                className={cn(
                  "relative flex h-full w-full min-w-0 flex-col overflow-hidden rounded-lg border p-3 text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent",
                  CARD[state],
                  selected && "ring-2 ring-medha-accent ring-offset-1 ring-offset-medha-surface",
                )}
              >
                <span aria-hidden className={cn("absolute inset-x-0 top-0 h-0.5", TOP[state])} />
                <span className="flex min-w-0 items-center gap-2">
                  <span
                    aria-hidden
                    className="medha-mono inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-medha-border bg-white text-[12.5px] font-semibold text-medha-secondary"
                  >
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="truncate text-[14.5px] font-semibold text-medha-text">{phase.label}</span>
                  <span className={cn("ml-auto", STATUS_TEXT[state])}>
                    <StatusIcon state={state} />
                  </span>
                </span>
                <span className="mt-1 block pl-8 text-[12.5px] leading-4 text-medha-secondary">
                  {phase.description}
                </span>
                <span className="mt-2 flex min-w-0 items-center gap-2 pl-8">
                  <span className={cn("text-[12.5px] font-semibold", STATUS_TEXT[state])}>
                    {STATE_LABEL[state]}
                  </span>
                  {duration ? (
                    <span className="text-[12px] text-medha-tertiary">· {duration}</span>
                  ) : null}
                  <span className="ml-auto text-[12px] text-medha-tertiary">
                    {selected ? "Selected" : "Details"}
                  </span>
                </span>
                {activity ? (
                  <span
                    className="mt-1 line-clamp-2 block pl-8 text-[12px] leading-4 text-medha-run-ink"
                    title={activity}
                  >
                    {activity}
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ol>

      <p className="mt-3 text-[12.5px] text-medha-tertiary">
        Select a phase to inspect its evidence and diagnostics in Operational status.
      </p>
    </Panel>
  );
}
