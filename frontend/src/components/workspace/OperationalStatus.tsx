"use client";

import Link from "next/link";
import { AlertTriangle, RotateCcw } from "lucide-react";
import { Badge, Panel } from "@/components/ui/primitives";
import { deployStateOf } from "@/components/workspace/DashboardSections";
import type { RunHealth, RunLogLine, RunSummary } from "@/lib/api/client";
import type { NegotiationView, RollbackSummary } from "@/lib/demo/types";
import type { PipelineStage, VerificationSummary } from "@/lib/projects/useProjectData";
import {
  PIPELINE_PHASES,
  STATE_LABEL,
  STATE_TONE,
  activityFor,
  derivePhaseStates,
  formatDuration,
  firstOfType,
  isGenericStageEvent,
  observedTime,
  phaseHref,
  phaseLogs,
  runStatusBadge,
  type Phase,
  type PhaseId,
  type VisualState,
} from "@/lib/projects/executionPhases";

function truncate(text: string, max = 220): string {
  const value = text.trim();
  return value.length > max ? `${value.slice(0, max - 1)}…` : value;
}

function verificationLine(verification: VerificationSummary | null): string {
  if (!verification) return "No verification artifact was stored for this run.";
  if (verification.total === 0) return "No verification checks were recorded.";
  if (verification.assessed === 0) {
    return `No assessed checks; ${verification.pending} pending.`;
  }
  const parts = [`Passed ${verification.passedCount} of ${verification.assessed} assessed checks`];
  if (verification.failed > 0) parts.push(`${verification.failed} failed`);
  if (verification.warnings > 0) {
    parts.push(`${verification.warnings} warning${verification.warnings === 1 ? "" : "s"}`);
  }
  if (verification.pending > 0) parts.push(`${verification.pending} pending`);
  return parts.join(" · ");
}

function negotiationLine(negotiation: NegotiationView | null): string | null {
  if (!negotiation) return null;
  if (negotiation.status === "resolved") {
    const via = negotiation.method ? ` via ${negotiation.method}` : "";
    const detail = negotiation.resolution ? ` ${truncate(negotiation.resolution, 180)}` : "";
    return `Constraints resolved${via}.${detail}`.trim();
  }
  if (negotiation.status === "failed") {
    return negotiation.conflictSummary
      ? `Negotiation failed: ${truncate(negotiation.conflictSummary, 180)}`
      : "Negotiation failed.";
  }
  if (negotiation.status === "none") {
    return "No constraint negotiation was required for this run.";
  }
  if (negotiation.status === "detecting" || negotiation.status === "resolving") {
    return negotiation.conflictSummary
      ? `Negotiation is in progress: ${truncate(negotiation.conflictSummary, 180)}`
      : "Negotiation is in progress.";
  }
  return null;
}

function completedPhaseDetail(
  phase: Phase,
  run: RunSummary | null,
  logs: RunLogLine[],
  verification: VerificationSummary | null,
  negotiation: NegotiationView | null,
  executionMode: string | null,
): string {
  const activity = activityFor(logs, phase.id);
  if (phase.id === "analyze") {
    const summary = run?.repository_summary;
    const tech = summary?.technologies?.filter(Boolean) ?? [];
    const text = summary?.text?.trim();
    if (tech.length > 0 || text) {
      const detected = tech.length > 0
        ? `Detected ${tech.slice(0, 5).join(", ")}${tech.length > 5 ? "…" : ""}.`
        : "";
      return truncate([detected, text].filter(Boolean).join(" "));
    }
  }
  if (phase.id === "cnp") {
    return negotiationLine(negotiation) ?? activity ?? "Negotiation completed; no CNP artifact was stored.";
  }
  if (phase.id === "verify") {
    return verification
      ? verificationLine(verification)
      : "Verification phase completed; no verification artifact was stored.";
  }
  if (phase.id === "execute") {
    const mode = executionMode ? `Executed in ${executionMode} mode.` : "Execute phase completed; execution mode was not recorded.";
    return activity ? `${mode} ${truncate(activity)}` : mode;
  }
  return activity ?? `${phase.label} completed; no additional detail was recorded.`;
}

function phaseResult(
  phase: Phase,
  state: VisualState,
  run: RunSummary | null,
  logs: RunLogLine[],
  verification: VerificationSummary | null,
  negotiation: NegotiationView | null,
  executionMode: string | null,
  hydrating: boolean,
): string {
  if (state === "skipped") {
    return `Execution was not attempted${run?.error_code ? ` (${run.error_code})` : ""}; analysis and verification evidence remain valid.`;
  }
  if (state === "failed") {
    if (run?.error_summary?.trim()) return run.error_summary.trim();
    const error = [...phaseLogs(logs, phase.id)].reverse().find((line) => line.level === "error");
    return error?.message.trim() || "The backend recorded this phase as failed; no error summary was stored.";
  }
  if (state === "running") {
    return activityFor(logs, phase.id) ?? "Running; no activity line has been recorded yet.";
  }
  if (state === "waiting") return "Waiting to start; this phase has not run yet.";
  if (state === "unknown") {
    return hydrating
      ? "Observed phase data is still loading."
      : "No phase data was recorded for this run.";
  }
  return completedPhaseDetail(phase, run, logs, verification, negotiation, executionMode);
}

function executionSummary(
  run: RunSummary | null,
  states: Record<PhaseId, VisualState>,
): { label: string; tone: "success" | "warning" | "error" | "info" | "neutral"; detail: string } {
  const badge = runStatusBadge(run?.status);
  const completed = PIPELINE_PHASES.filter((phase) => states[phase.id] === "completed").length;
  const failed = PIPELINE_PHASES.find((phase) => states[phase.id] === "failed");
  const skipped = PIPELINE_PHASES.find((phase) => states[phase.id] === "skipped");

  if (!run) return { ...badge, detail: "No run selected." };
  if (run.status === "failed") {
    if (skipped) {
      return {
        ...badge,
        detail: `Execution was not attempted${run.error_code ? ` (${run.error_code})` : ""}.`,
      };
    }
    const cause = run.error_summary?.trim();
    return {
      ...badge,
      detail: failed
        ? `Failed at ${failed.label}${cause ? ` — ${cause}` : "."}`
        : cause
          ? `Failed — ${cause}`
          : "The run failed; the failing phase was not recorded.",
    };
  }
  if (run.status === "completed") {
    return {
      ...badge,
      detail:
        completed === PIPELINE_PHASES.length
          ? "All six phases completed."
          : completed > 0
            ? `Run marked completed; ${completed} of ${PIPELINE_PHASES.length} phases have observed completion evidence.`
            : "Run marked completed; no phase completion evidence was recorded.",
    };
  }
  if (run.status === "queued") {
    return { ...badge, detail: "Queued; no phase has started." };
  }
  return {
    ...badge,
    detail: `In progress; ${completed} of ${PIPELINE_PHASES.length} phases completed.`,
  };
}

function applicationExplanation(
  run: RunSummary | null,
  health: RunHealth | null,
  label: string,
): string {
  if (!run) return "No run selected.";
  if (health?.reason?.trim()) return truncate(health.reason);
  if (label === "Healthy") return "The last health probe reported the application healthy.";
  if (label === "Unhealthy") return "The last health probe reported the application unhealthy.";
  if (label === "Running - health unverified") {
    return "The application is running, but health has not been verified.";
  }
  if (label === "Not deployed") return "No deployed application was observed for this run.";
  if (label === "Deploying") return "Deployment is still in progress; health is not verified yet.";
  if (run.status === "completed") {
    return "No health probe was recorded; a completed pipeline does not confirm a healthy application.";
  }
  if (run.status === "failed") return "The run failed; no application health was confirmed.";
  return "No health probe has been recorded for this run.";
}

export function OperationalStatus({
  projectId,
  run,
  stages,
  logs,
  hydrating = false,
  health,
  verification,
  negotiation,
  rollback,
  executionMode,
  selectedPhase,
  onClear,
}: {
  projectId: string;
  run: RunSummary | null;
  stages: PipelineStage[];
  logs: RunLogLine[];
  hydrating?: boolean;
  health: RunHealth | null;
  verification: VerificationSummary | null;
  negotiation: NegotiationView | null;
  rollback: RollbackSummary | null;
  executionMode: string | null;
  selectedPhase: PhaseId | null;
  onClear: () => void;
}) {
  const phase = selectedPhase
    ? PIPELINE_PHASES.find((item) => item.id === selectedPhase) ?? null
    : null;
  const stageById = new Map(stages.map((stage) => [stage.id, stage]));
  const states = derivePhaseStates({ run, stages, hydrating });
  const overall = executionSummary(run, states);
  const deploy = deployStateOf(run, health);
  const failedPhase = PIPELINE_PHASES.find((item) => states[item.id] === "failed") ?? null;
  const configSkipped = PIPELINE_PHASES.some((item) => states[item.id] === "skipped");
  const failureHref =
    run?.status === "failed" && !configSkipped
      ? failedPhase
        ? phaseHref(projectId, run.deployment_id, failedPhase.id, true)
        : {
            href: `/projects/${projectId}/runs/${run.deployment_id}#diagnosis`,
            label: "Open error details",
          }
      : null;

  const recoverStage = stageById.get("recover");
  const rollbackRelevant =
    rollback != null ||
    recoverStage?.state === "active" ||
    recoverStage?.state === "blocked" ||
    run?.status === "partial_recovery";
  const rollbackState: VisualState =
    recoverStage?.state === "active"
      ? "running"
      : recoverStage?.state === "blocked"
        ? "failed"
        : recoverStage?.state === "done" || run?.status === "partial_recovery" || rollback
          ? "completed"
          : "unknown";

  if (phase) {
    const state = states[phase.id];
    const stage = stageById.get(phase.id);
    const result = phaseResult(
      phase,
      state,
      run,
      logs,
      verification,
      negotiation,
      executionMode,
      hydrating,
    );
    const link =
      state === "skipped"
        ? { href: `/projects/${projectId}/settings`, label: "Configure execution" }
        : phaseHref(projectId, run?.deployment_id ?? null, phase.id, state === "failed");
    const selectedLogs = phaseLogs(logs, phase.id).filter((line) => !isGenericStageEvent(line));
    const evidence = selectedLogs
      .filter(
        (line) =>
          (line.level === "warning" || line.level === "error") &&
          line.message.trim() !== result,
      )
      .slice(-3);

    return (
      <Panel
        id="operational-status-panel"
        className="lg:col-span-5"
        title="Operational status"
        eyebrow={`${phase.label} phase details`}
        action={
          <button
            type="button"
            onClick={onClear}
            className="rounded text-[13px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
          >
            Back to overview
          </button>
        }
      >
        <section aria-label={`${phase.label} details`} className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={STATE_TONE[state]}>{STATE_LABEL[state]}</Badge>
            {phase.id === "execute" && executionMode ? (
              <span className="text-[12.5px] text-medha-tertiary">Mode: {executionMode}</span>
            ) : null}
          </div>
          <p className="mt-1 text-[12.5px] text-medha-tertiary">{phase.description}</p>

          <p className="mt-2 break-words text-[13.5px] leading-relaxed text-medha-text">{result}</p>

          <dl className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1.5 text-[12.5px]">
            <div className="flex gap-1">
              <dt className="text-medha-tertiary">Started</dt>
              <dd className="medha-mono text-medha-secondary">
                {observedTime(firstOfType(logs, phase.id, "stage.started")?.ts) ?? "Not observed"}
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="text-medha-tertiary">Finished</dt>
              <dd className="medha-mono text-medha-secondary">
                {observedTime(firstOfType(logs, phase.id, "stage.completed")?.ts) ?? "Not observed"}
              </dd>
            </div>
            <div className="flex gap-1">
              <dt className="text-medha-tertiary">Duration</dt>
              <dd className="medha-mono text-medha-secondary">
                {formatDuration(stage?.durationMs) ?? "Not observed"}
              </dd>
            </div>
          </dl>

          {evidence.length > 0 ? (
            <div className="mt-2 border-t border-medha-border pt-2">
              <p className="medha-label">
                Warnings and errors
              </p>
              <ul className="mt-1 space-y-1">
                {evidence.map((line, index) => (
                  <li
                    key={`${line.ts}-${index}`}
                    className="flex min-w-0 gap-2 text-[12.5px]"
                    title={line.message}
                  >
                    <span className="medha-mono shrink-0 text-medha-tertiary">
                      {observedTime(line.ts) ?? line.ts}
                    </span>
                    <span className="min-w-0 break-words text-medha-danger">{line.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          <div className="mt-2 flex justify-end border-t border-medha-border pt-2">
            <Link
              href={link.href}
              className="rounded text-[13px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
            >
              {link.label} →
            </Link>
          </div>
        </section>
      </Panel>
    );
  }

  return (
    <Panel
      id="operational-status-panel"
      className="lg:col-span-5"
      title="Operational status"
      eyebrow="Execution overview"
      action={
        <Link
          href={`/projects/${projectId}/orchestration`}
          className="rounded text-[13px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
        >
          Activity →
        </Link>
      }
    >
      <dl className="space-y-2.5 text-[13.5px] leading-5">
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <dt className="w-24 shrink-0 font-medium text-medha-secondary">Execution</dt>
          <dd className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <Badge tone={overall.tone}>{overall.label}</Badge>
              <span className="min-w-0 break-words text-medha-secondary">{overall.detail}</span>
            </span>
            {failureHref ? (
              <Link
                href={failureHref.href}
                className="mt-0.5 inline-block rounded text-[12.5px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
              >
                {failureHref.label} →
              </Link>
            ) : null}
          </dd>
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <dt className="w-24 shrink-0 font-medium text-medha-secondary">Application</dt>
          <dd className="min-w-0 flex-1">
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-semibold text-medha-text">{deploy.label}</span>
              <Link
                href="#deployment-health"
                className="rounded text-[12.5px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
              >
                Health details →
              </Link>
            </span>
            <span className="mt-0.5 block break-words text-[12.5px] text-medha-tertiary">
              {applicationExplanation(run, health, deploy.label)}
            </span>
          </dd>
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
          <dt className="w-24 shrink-0 font-medium text-medha-secondary">Verification</dt>
          <dd className="min-w-0 flex-1">
            <span className="break-words text-medha-text">
              {verification
                ? verificationLine(verification)
                : hydrating
                  ? "Loading observed verification evidence…"
                  : "No verification artifact was recorded."}
            </span>
            <span className="mt-0.5 flex flex-wrap items-center gap-x-2">
              {verification?.failed ? (
                <span className="flex items-center gap-1 text-[12.5px] text-medha-danger">
                  <AlertTriangle className="h-3 w-3" aria-hidden />
                  {verification.failed} failed check{verification.failed === 1 ? "" : "s"}
                </span>
              ) : null}
              <Link
                href={phaseHref(projectId, run?.deployment_id ?? null, "verify", false).href}
                className="rounded text-[12.5px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
              >
                Verification details →
              </Link>
            </span>
          </dd>
        </div>

        {rollbackRelevant ? (
          <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
            <dt className="flex w-24 shrink-0 items-center gap-1 font-medium text-medha-secondary">
              <RotateCcw className="h-3.5 w-3.5" aria-hidden />
              Recovery
            </dt>
            <dd className="min-w-0 flex-1">
              <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-semibold text-medha-text">
                  {rollbackState === "running"
                    ? "Running"
                    : rollbackState === "failed"
                      ? "Failed"
                      : rollbackState === "completed"
                        ? "Completed"
                        : "Unknown"}
                </span>
                {rollback ? (
                  <span className="text-[12.5px] text-medha-tertiary">
                    {rollback.rolledBack} rolled back · {rollback.preserved} preserved
                  </span>
                ) : null}
                <Link
                  href={`/projects/${projectId}/graphs`}
                  className="rounded text-[12.5px] font-semibold text-medha-accent hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent"
                >
                  Rollback evidence →
                </Link>
              </span>
              {rollback?.headline ? (
                <span className="mt-0.5 block break-words text-[12.5px] text-medha-tertiary">
                  {truncate(rollback.headline)}
                </span>
              ) : null}
            </dd>
          </div>
        ) : null}
      </dl>
    </Panel>
  );
}
