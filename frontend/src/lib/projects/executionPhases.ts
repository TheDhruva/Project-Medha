import type { RunLogLine, RunSummary } from "@/lib/api/client";
import {
  CONFIG_BLOCK_CODES,
  type PipelineStage,
} from "@/lib/projects/useProjectData";
import { isRunningStatus } from "@/lib/projects/projects";

export const PIPELINE_PHASES = [
  { id: "preflight", label: "Preflight", description: "Check environment" },
  { id: "analyze", label: "Analyze", description: "Inspect repository" },
  { id: "plan", label: "Plan", description: "Build deployment plan" },
  { id: "cnp", label: "Negotiate (CNP)", description: "Resolve constraints" },
  { id: "verify", label: "Verify", description: "Validate the plan" },
  { id: "execute", label: "Execute", description: "Build and deploy app" },
] as const;

export type PhaseId = (typeof PIPELINE_PHASES)[number]["id"];
export type Phase = (typeof PIPELINE_PHASES)[number];
export type VisualState = "completed" | "running" | "failed" | "waiting" | "skipped" | "unknown";

export const STATE_LABEL: Record<VisualState, string> = {
  completed: "Completed",
  running: "Running",
  failed: "Failed",
  waiting: "Waiting",
  skipped: "Skipped",
  unknown: "Unknown",
};

export const STATE_TONE: Record<
  VisualState,
  "success" | "info" | "error" | "warning" | "neutral"
> = {
  completed: "success",
  running: "info",
  failed: "error",
  waiting: "neutral",
  skipped: "neutral",
  unknown: "neutral",
};

const PHASE_MATCH: Record<PhaseId, RegExp> = {
  preflight: /preflight/,
  analyze: /analy|repo|agents/,
  plan: /plan/,
  cnp: /cnp|negot|mediat/,
  verify: /verif/,
  execute: /execut/,
};

const PHASE_WORDS: Record<PhaseId, string[]> = {
  preflight: ["preflight"],
  analyze: ["analyzer"],
  plan: ["planner"],
  cnp: ["mediator"],
  verify: ["verifier", "critic"],
  execute: ["executor"],
};

const TERMINAL = new Set(["completed", "failed", "cancelled", "partial_recovery"]);

export function formatDuration(ms: number | null | undefined): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

export function phaseLogs(logs: RunLogLine[], phaseId: PhaseId): RunLogLine[] {
  return logs.filter((line) => {
    const stage = (line.stage ?? "").toLowerCase();
    if (stage) return PHASE_MATCH[phaseId].test(stage);
    // Agent lifecycle lines have no stage. Match only explicit phase/agent
    // names so unrelated system messages never leak into a phase.
    const message = line.message.toLowerCase();
    return PHASE_WORDS[phaseId].some((word) => message.includes(word));
  });
}

export function isGenericStageEvent(line: RunLogLine): boolean {
  if (line.type === "stage.started" || line.type === "stage.completed") return true;
  const message = line.message.trim().toLowerCase();
  return /^(preflight|analy[sz]e|plan|negoti\w*|cnp|verif\w*|execut\w*|agents|recover)\b.*\b(started|completed|finished)\.?$/.test(
    message,
  );
}

export function activityFor(logs: RunLogLine[], phaseId: PhaseId): string | null {
  const observed = phaseLogs(logs, phaseId);
  const latest = [...observed].reverse().find((line) => !isGenericStageEvent(line));
  return latest?.message.trim() || null;
}

export function firstOfType(
  logs: RunLogLine[],
  phaseId: PhaseId,
  type: string,
): RunLogLine | null {
  return phaseLogs(logs, phaseId).find((line) => line.type === type) ?? null;
}

export function observedTime(ts: string | null | undefined): string | null {
  if (!ts) return null;
  const match = /T(\d{2}:\d{2}:\d{2})/.exec(ts);
  return match ? `${match[1]}Z` : ts;
}

function visualStateFor(
  phase: Phase,
  phaseIndex: number,
  stage: PipelineStage | undefined,
  phases: readonly Phase[],
  blocked: PipelineStage | null,
  run: RunSummary | null,
  hydrating: boolean,
): VisualState {
  if (
    phase.id === "execute" &&
    run?.status === "failed" &&
    run.error_code != null &&
    CONFIG_BLOCK_CODES.has(run.error_code)
  ) {
    return "skipped";
  }
  if (!stage) return "unknown";
  if (stage.state === "blocked") return stage.reason === "config" ? "skipped" : "failed";
  if (stage.state === "done") return "completed";
  if (stage.state === "active") return "running";

  if (hydrating || !run) return "unknown";
  if (isRunningStatus(run.status)) return "waiting";

  const blockedIndex = blocked ? phases.findIndex((p) => p.id === blocked.id) : -1;
  if (run.status === "failed" && blockedIndex >= 0 && phaseIndex > blockedIndex) return "waiting";
  if (TERMINAL.has(run.status)) return "unknown";
  return "waiting";
}

export function derivePhaseStates({
  run,
  stages,
  hydrating,
}: {
  run: RunSummary | null;
  stages: PipelineStage[];
  hydrating: boolean;
}): Record<PhaseId, VisualState> {
  const stageById = new Map(stages.map((stage) => [stage.id, stage]));
  const blocked = stages.find((stage) => stage.state === "blocked" && stage.reason !== "config") ?? null;
  return PIPELINE_PHASES.reduce(
    (acc, phase, index) => {
      acc[phase.id] = visualStateFor(
        phase,
        index,
        stageById.get(phase.id),
        PIPELINE_PHASES,
        blocked,
        run,
        hydrating,
      );
      return acc;
    },
    {} as Record<PhaseId, VisualState>,
  );
}

export function phaseHref(
  projectId: string,
  runId: string | null,
  phaseId: PhaseId,
  failed: boolean,
): { href: string; label: string } {
  if (phaseId === "cnp") {
    return { href: `/projects/${projectId}/constraints`, label: "Review constraints and negotiation" };
  }
  if (phaseId === "verify") {
    const query = runId ? `?run=${encodeURIComponent(runId)}` : "";
    return { href: `/projects/${projectId}/verification${query}`, label: "Open verification details" };
  }
  if (!runId) {
    return { href: `/projects/${projectId}/runs`, label: "Open executions" };
  }
  const base = `/projects/${projectId}/runs/${runId}`;
  if (phaseId === "execute") {
    return { href: `${base}#diagnosis`, label: failed ? "Open failure diagnosis" : "Open run details" };
  }
  return { href: base, label: "Open run details" };
}

export function runStatusBadge(status: string | undefined): {
  label: string;
  tone: "success" | "warning" | "error" | "info" | "neutral";
} {
  switch (status) {
    case "completed":
      return { label: "Completed", tone: "success" };
    case "running":
    case "started":
      return { label: "Running", tone: "info" };
    case "queued":
      return { label: "Queued", tone: "neutral" };
    case "failed":
      return { label: "Failed", tone: "error" };
    case "cancelled":
      return { label: "Cancelled", tone: "error" };
    case "awaiting_approval":
      return { label: "Awaiting approval", tone: "warning" };
    case "partial_recovery":
      return { label: "Partial recovery", tone: "warning" };
    default:
      return { label: status ? status.replace(/_/g, " ") : "Unknown", tone: "neutral" };
  }
}
