import { emptyGraph, initialAgents, initialPipeline, setStages } from "@/lib/demo/scenarios";
import type {
  AgentActivity,
  CegGraph,
  ChangeIntelAnalysis,
  ConstraintView,
  CriticView,
  DeploymentResultView,
  DeploymentSnapshot,
  NegotiationView,
  PipelineStage,
  RollbackSummary,
  ScenarioId,
  StageId,
  TraceEvent,
  VerificationView,
} from "@/lib/demo/types";
import type {
  BackendSystemEvent,
  DeploymentApiSnapshot,
  RunLogLine,
  VerificationArtifact,
} from "@/lib/api/client";

function formatClock(isoOrClock: string): string {
  if (/^\d{2}:\d{2}:\d{2}/.test(isoOrClock)) return isoOrClock.slice(0, 8);
  const date = new Date(isoOrClock);
  if (Number.isNaN(date.getTime())) return isoOrClock;
  return date.toISOString().slice(11, 19);
}

function toneForEvent(type: string, level: string): TraceEvent["tone"] {
  if (type.includes("failed") || level === "error") return "error";
  if (type.includes("conflict") || level === "warning" || type.includes("replan"))
    return "warning";
  if (
    type.includes("completed") ||
    type.includes("passed") ||
    type.includes("resolved") ||
    type.includes("success")
  ) {
    return "success";
  }
  if (type.startsWith("stage.")) return "info";
  return "neutral";
}

export function createRunningSnapshot(
  deploymentId: string,
  scenario: ScenarioId | null,
  isDemo = true,
): DeploymentSnapshot {
  return {
    deploymentId,
    isDemo,
    scenario: isDemo ? scenario : null,
    runStatus: "running",
    explain: {
      currentStage: null,
      round: null,
      statusLabel: "Started",
      simpleText: isDemo
        ? "Deployment accepted by MEDHA backend. Waiting for DEMO pipeline events…"
        : "Deployment accepted. Waiting for real analysis / CNP events…",
      technicalText: isDemo
        ? `deployment_id=${deploymentId} · source=api+sse · workflow=demo · is_demo=true`
        : `deployment_id=${deploymentId} · source=api+sse · workflow=planning · phases=10-12`,
    },
    pipeline: initialPipeline(),
    agents: initialAgents(),
    constraints: [],
    negotiation: null,
    verification: null,
    critic: null,
    graph: { nodes: [], edges: [] },
    selectedNodeId: null,
    rollback: null,
    result: null,
    trace: [],
    frameIndex: 0,
    totalFrames: 0,
    changeIntel: null,
  };
}

export function applyBackendEvent(
  snapshot: DeploymentSnapshot,
  event: BackendSystemEvent,
): DeploymentSnapshot {
  const data = event.data || {};
  const nextTrace: TraceEvent[] = [
    ...snapshot.trace,
    {
      id: event.event_id,
      time: formatClock(event.ts),
      tone: toneForEvent(event.type, event.level),
      message: event.message,
      technical: technicalLine(event, data),
    },
  ];

  let pipeline = snapshot.pipeline;
  let explain = snapshot.explain;
  let runStatus = snapshot.runStatus;
  let result = snapshot.result;
  let agents = snapshot.agents;
  let constraints = snapshot.constraints;
  let negotiation = snapshot.negotiation;
  let verification = snapshot.verification;
  let critic = snapshot.critic;
  let graph = snapshot.graph;
  let rollback = snapshot.rollback;
  let selectedNodeId = snapshot.selectedNodeId;
  let changeIntel = snapshot.changeIntel;

  const simpleFromEvent =
    typeof data.simple === "string" ? data.simple : undefined;
  const technicalFromEvent =
    typeof data.technical === "string" ? data.technical : undefined;

  if (Array.isArray(data.agents)) {
    agents = data.agents as AgentActivity[];
  }
  if (Array.isArray(data.constraints)) {
    constraints = data.constraints as ConstraintView[];
  }
  if (data.negotiation && typeof data.negotiation === "object") {
    negotiation = data.negotiation as NegotiationView;
  }
  if (data.verification && typeof data.verification === "object") {
    verification = data.verification as VerificationView;
  }
  if (data.critic && typeof data.critic === "object") {
    critic = data.critic as CriticView;
  }
  if (data.graph && typeof data.graph === "object") {
    graph = data.graph as DeploymentSnapshot["graph"];
  }
  if (data.change_intel && typeof data.change_intel === "object") {
    changeIntel = data.change_intel as ChangeIntelAnalysis;
  }
  if (data.rollback && typeof data.rollback === "object") {
    rollback = data.rollback as RollbackSummary;
  }
  if (typeof data.selected_node_id === "string") {
    selectedNodeId = data.selected_node_id;
  }
  if (data.result && typeof data.result === "object") {
    result = data.result as DeploymentResultView;
  }
  if (data.pipeline && typeof data.pipeline === "object") {
    pipeline = applyPipelinePatch(
      pipeline,
      data.pipeline as Record<string, Partial<PipelineStage>>,
    );
  }

  if (event.type === "deployment.created" || event.type === "deployment.started") {
    explain = {
      ...explain,
      statusLabel: "Running",
      simpleText: simpleFromEvent || event.message,
      technicalText:
        technicalFromEvent ||
        `event=${event.type} · deployment_id=${event.deployment_id} · is_demo=${event.is_demo}`,
    };
  }

  if (event.type === "stage.started" && event.stage) {
    const stage = event.stage as StageId;
    if (!data.pipeline) {
      pipeline = markStage(pipeline, stage, "running", event.message);
    }
    explain = {
      currentStage: stage,
      round: negotiationRound(data, negotiation),
      statusLabel: "Running",
      simpleText: simpleFromEvent || humanStageMessage(stage, "started"),
      technicalText:
        technicalFromEvent ||
        `stage=${stage} · event=stage.started · is_demo=${event.is_demo}`,
    };
  }

  if (event.type === "stage.completed" && event.stage) {
    const stage = event.stage as StageId;
    if (!data.pipeline) {
      const status =
        event.status === "failed"
          ? "failed"
          : event.status === "warning"
            ? "warning"
            : "success";
      pipeline = markStage(pipeline, stage, status, `${stage} completed`);
    }
    explain = {
      ...explain,
      currentStage: stage,
      statusLabel: "Running",
      simpleText: simpleFromEvent || humanStageMessage(stage, "completed"),
      technicalText:
        technicalFromEvent ||
        `stage=${stage} · event=stage.completed · is_demo=${event.is_demo}`,
    };
  }

  if (
    event.type === "constraint.conflict" ||
    event.type === "negotiation.started" ||
    event.type === "negotiation.resolved" ||
    event.type === "constraint.published" ||
    event.type === "verification.failed" ||
    event.type === "verification.passed" ||
    event.type === "verification.check" ||
    event.type === "critic.started" ||
    event.type === "critic.completed" ||
    event.type === "replan.started" ||
    event.type === "replan.completed" ||
    event.type === "execution.started" ||
    event.type === "execution.node.started" ||
    event.type === "execution.node.completed" ||
    event.type === "execution.node.failed" ||
    event.type === "execution.service_status" ||
    event.type === "execution.failed" ||
    event.type === "ceg.created" ||
    event.type === "ceg.node.updated" ||
    event.type === "rollback.started" ||
    event.type === "rollback.scope_determined" ||
    event.type === "rollback.node" ||
    event.type === "rollback.completed"
  ) {
    explain = {
      currentStage: (event.stage as StageId) || explain.currentStage,
      round: negotiationRound(data, negotiation),
      statusLabel: statusLabelFor(event.type),
      simpleText: simpleFromEvent || event.message,
      technicalText: technicalFromEvent || technicalLine(event, data),
    };
  }

  if (event.type === "deployment.completed") {
    const finalStatus = event.status || "";
    if (finalStatus === "partial_recovery" || result?.kind === "partial_recovery") {
      runStatus = "partial_recovery";
      if (!data.pipeline) {
        pipeline = setStages(pipeline, {
          COMPLETE: { status: "warning", detail: "Partial recovery" },
        });
      }
    } else {
      runStatus = "succeeded";
      if (!data.pipeline) {
        pipeline = setStages(pipeline, {
          COMPLETE: { status: "success", detail: "Deployment finished" },
        });
      }
    }
    explain = {
      currentStage: "COMPLETE",
      round: negotiationRound(data, negotiation),
      statusLabel: runStatus === "partial_recovery" ? "Recovered" : "Complete",
      simpleText: simpleFromEvent || event.message,
      technicalText:
        technicalFromEvent ||
        `event=deployment.completed · status=${event.status} · is_demo=${event.is_demo}`,
    };
    if (!result) {
      result = {
        kind: runStatus === "partial_recovery" ? "partial_recovery" : "success",
        title: runStatus === "partial_recovery" ? "PARTIAL_FAILURE" : "SUCCESS",
        message: event.message,
        durationLabel: "demo",
        servicesLabel: "see graph",
        verificationScore: null,
        constraintsResolved: 0,
        rollbackScope: null,
      };
    }
  }

  if (event.type === "deployment.failed") {
    runStatus = "failed";
    if (!data.pipeline) {
      pipeline = setStages(pipeline, {
        COMPLETE: { status: "failed", detail: "Deployment failed" },
      });
    }
    explain = {
      currentStage: snapshot.explain.currentStage,
      round: null,
      statusLabel: "Failed",
      simpleText: simpleFromEvent || event.message,
      technicalText:
        technicalFromEvent ||
        `event=deployment.failed · deployment_id=${event.deployment_id}`,
    };
    result = (data.result as DeploymentResultView) || {
      kind: "failed",
      title: "FAILED",
      message: event.message,
      durationLabel: "demo",
      servicesLabel: "n/a",
      verificationScore: null,
      constraintsResolved: 0,
      rollbackScope: null,
    };
  }

  return {
    ...snapshot,
    pipeline,
    agents,
    constraints,
    negotiation,
    verification,
    critic,
    graph,
    rollback,
    selectedNodeId,
    explain,
    runStatus,
    result,
    trace: nextTrace,
    isDemo: event.is_demo,
    changeIntel,
  };
}

function technicalLine(
  event: BackendSystemEvent,
  data: Record<string, unknown>,
): string {
  if (typeof data.technical === "string") return data.technical;
  const parts = [`type=${event.type}`];
  if (event.stage) parts.push(`stage=${event.stage}`);
  if (event.status) parts.push(`status=${event.status}`);
  parts.push(`is_demo=${event.is_demo}`);
  return parts.join(" · ");
}

const TERMINAL_RUN_STATUS: Record<string, DeploymentSnapshot["runStatus"]> = {
  completed: "succeeded",
  partial_recovery: "partial_recovery",
  failed: "failed",
  cancelled: "failed",
};

/** True when a backend deployment status means the run cannot progress further. */
export function isTerminalDeploymentStatus(status: string | null | undefined): boolean {
  return Boolean(status && status in TERMINAL_RUN_STATUS);
}

/**
 * Reconcile a snapshot against the last-known deployment record (REST).
 *
 * Used when the SSE stream drops before the terminal event arrived: instead of
 * leaving the UI stuck on "running" forever, resolve the terminal state from
 * the persisted deployment. Returns the snapshot unchanged when the record is
 * not terminal (stream will keep retrying).
 */
export function reconcileTerminalState(
  snapshot: DeploymentSnapshot,
  api: DeploymentApiSnapshot,
): DeploymentSnapshot {
  const runStatus = TERMINAL_RUN_STATUS[api.status];
  if (!runStatus || runStatus === snapshot.runStatus) return snapshot;

  const statusLabel =
    runStatus === "succeeded"
      ? "Complete"
      : runStatus === "partial_recovery"
        ? "Recovered"
        : "Failed";
  return {
    ...snapshot,
    runStatus,
    isDemo: api.is_demo,
    explain: {
      currentStage: (api.current_stage as StageId) || "COMPLETE",
      round: null,
      statusLabel,
      simpleText: api.explain?.simple || `Deployment ${api.status} (reconciled from backend).`,
      technicalText:
        api.explain?.technical || `source=reconcile · status=${api.status} · is_demo=${api.is_demo}`,
    },
    result: (api.result as DeploymentResultView | null | undefined) || snapshot.result,
    trace: [
      ...snapshot.trace,
      {
        id: `reconcile-${api.deployment_id}-${Date.now()}`,
        time: formatClock(api.updated_at),
        tone: runStatus === "failed" ? "error" : "neutral",
        message: runStatus === "failed"
          ? "Connection lost — terminal state recovered from backend."
          : "Connection lost — deployment finished (recovered from backend).",
        technical: `event=sse.error · reconciled=true · status=${api.status}`,
      },
    ],
  };
}

/**
 * Build a complete snapshot for a previously stored (or currently running) run
 * directly from backend REST artifacts. Everything here is real persisted data:
 * the deployment record, the event log, and the stored constraint/verification/
 * graph/change-intel artifacts. Missing artifacts map to honest "not available"
 * states — never fabricated values.
 */
export interface BackendHydrationInput {
  api: DeploymentApiSnapshot;
  logs?: RunLogLine[];
  constraints?: ConstraintView[] | null;
  negotiation?: NegotiationView | null;
  verification?: VerificationView | null;
  critic?: CriticView | null;
  graph?: CegGraph | null;
  rollback?: RollbackSummary | null;
  changeIntel?: ChangeIntelAnalysis | null;
}

export function buildBackendSnapshot(input: BackendHydrationInput): DeploymentSnapshot {
  const { api } = input;
  const isDemo = api.is_demo;
  const runStatus = TERMINAL_RUN_STATUS[api.status] ?? "running";
  const logs = input.logs ?? [];
  const pipeline = pipelineFromLogs(logs, runStatus);
  const trace: TraceEvent[] = logs.map((line, index) => ({
    id: `log-${index}`,
    time: formatClock(line.ts),
    tone: toneForEvent(line.type, line.level),
    message: line.message,
    technical: technicalLineFromLog(line),
  }));

  const statusLabel =
    runStatus === "running"
      ? api.current_stage
        ? "Running"
        : "Queued"
      : runStatus === "failed"
        ? "Failed"
        : runStatus === "partial_recovery"
          ? "Recovered"
          : "Complete";

  return {
    deploymentId: api.deployment_id,
    isDemo,
    scenario: api.scenario,
    runStatus,
    explain: {
      currentStage: (api.current_stage as StageId | null) ?? (runStatus !== "running" ? "COMPLETE" : null),
      round: input.negotiation?.round ?? null,
      statusLabel,
      simpleText:
        api.explain?.simple ||
        (runStatus === "running"
          ? "Retrieving run state from MEDHA backend."
          : runStatus === "failed"
            ? "Run did not complete. See the result and verification panels for details."
            : runStatus === "partial_recovery"
              ? "Run recovered after a dependency-aware scoped rollback."
              : "Run completed."),
      technicalText:
        api.explain?.technical || `state=hydrated · status=${api.status} · is_demo=${isDemo}`,
    },
    pipeline,
    agents: initialAgents(),
    constraints: input.constraints ?? [],
    negotiation: input.negotiation ?? null,
    verification: input.verification ?? null,
    critic: input.critic ?? null,
    graph: input.graph ?? emptyGraph(),
    selectedNodeId: null,
    rollback: input.rollback ?? null,
    result: (api.result as DeploymentResultView | null | undefined) ?? terminalResultFallback(runStatus),
    trace,
    frameIndex: 0,
    totalFrames: 0,
    changeIntel: input.changeIntel ?? null,
  };
}

export function mapVerificationArtifact(
  artifact: VerificationArtifact | null,
): { verification: VerificationView | null; critic: CriticView | null } {
  if (!artifact) return { verification: null, critic: null };

  const v = artifact.verification;
  let verification: VerificationView | null = null;
  if (v && typeof v === "object" && Array.isArray((v as { checks?: unknown }).checks)) {
    const checks = (v as { checks?: Array<Record<string, unknown>> }).checks ?? [];
    verification = {
      checks: checks.map((c) => ({
        id: String(c.id ?? ""),
        name: String(c.name ?? ""),
        status: (c.status as VerificationView["checks"][number]["status"]) ?? "pending",
        message: String(c.message ?? ""),
        rule: c.rule != null ? String(c.rule) : undefined,
        category: c.category != null ? String(c.category) : undefined,
      })),
      passed: v.passed == null ? null : Boolean(v.passed),
      summary:
        typeof v.summary === "string" ? v.summary : "No verification summary recorded.",
    };
  }

  const c = artifact.critic;
  let critic: CriticView | null = null;
  if (c && typeof c === "object") {
    const raw = c as {
      score?: unknown;
      breakdown?: unknown;
      recommendation?: unknown;
      findings?: unknown;
    };
    critic = {
      score: Number(raw.score ?? 0),
      breakdown: (raw.breakdown ?? {
        security: 0,
        completeness: 0,
        constraints: 0,
        intentAlignment: 0,
      }) as CriticView["breakdown"],
      recommendation: (raw.recommendation as CriticView["recommendation"]) ?? "WARN",
      findings: Array.isArray(raw.findings) ? (raw.findings as string[]) : [],
    };
  }

  return { verification, critic };
}

function pipelineFromLogs(
  logs: RunLogLine[],
  runStatus: DeploymentSnapshot["runStatus"],
): PipelineStage[] {
  let pipeline = initialPipeline();
  for (const line of logs) {
    if (line.type === "stage.started" && line.stage) {
      pipeline = markStage(pipeline, line.stage as StageId, "running", line.message);
    } else if (line.type === "stage.completed" && line.stage) {
      const status: PipelineStage["status"] =
        line.status === "failed"
          ? "failed"
          : line.status === "warning"
            ? "warning"
            : "success";
      pipeline = setStages(
        pipeline,
        { [line.stage]: { status, detail: line.message } } as Partial<
          Record<StageId, Partial<PipelineStage>>
        >,
      );
    } else if (line.type === "deployment.failed") {
      pipeline = setStages(pipeline, {
        COMPLETE: { status: "failed", detail: line.message },
      });
    } else if (line.type === "deployment.completed") {
      pipeline = setStages(pipeline, {
        COMPLETE: {
          status: runStatus === "partial_recovery" ? "warning" : "success",
          detail: line.message,
        },
      });
    }
  }
  if (runStatus !== "running") {
    const complete = pipeline.find((p) => p.id === "COMPLETE");
    if (!complete || complete.status === "pending" || complete.status === "running") {
      pipeline = setStages(pipeline, {
        COMPLETE: {
          status: runStatus === "failed" ? "failed" : runStatus === "partial_recovery" ? "warning" : "success",
          detail:
            runStatus === "failed"
              ? "Run failed"
              : runStatus === "partial_recovery"
                ? "Partial recovery after scoped rollback"
                : "Run completed",
        },
      });
    }
  }
  return pipeline;
}

function technicalLineFromLog(line: RunLogLine): string {
  const parts = [`type=${line.type}`];
  if (line.stage) parts.push(`stage=${line.stage}`);
  if (line.status) parts.push(`status=${line.status}`);
  parts.push(`is_demo=${line.is_demo}`);
  return parts.join(" · ");
}

function terminalResultFallback(runStatus: DeploymentSnapshot["runStatus"]): DeploymentResultView {
  if (runStatus === "failed") {
    return {
      kind: "failed",
      title: "FAILED",
      message: "Run did not complete.",
      durationLabel: "—",
      servicesLabel: "n/a",
      verificationScore: null,
      constraintsResolved: 0,
      rollbackScope: null,
    };
  }
  if (runStatus === "partial_recovery") {
    return {
      kind: "partial_recovery",
      title: "PARTIAL RECOVERY",
      message: "Run recovered with a dependency-aware scoped rollback.",
      durationLabel: "—",
      servicesLabel: "see graph",
      verificationScore: null,
      constraintsResolved: 0,
      rollbackScope: null,
    };
  }
  return {
    kind: "success",
    title: "SUCCESS",
    message: "Run completed.",
    durationLabel: "—",
    servicesLabel: "see graph",
    verificationScore: null,
    constraintsResolved: 0,
    rollbackScope: null,
  };
}

function negotiationRound(
  data: Record<string, unknown>,
  negotiation: NegotiationView | null,
): number | null {
  const nested = data.negotiation;
  if (nested && typeof nested === "object" && "round" in nested) {
    const round = (nested as { round?: unknown }).round;
    if (typeof round === "number") return round;
  }
  return negotiation?.round ?? null;
}

function statusLabelFor(type: string): string {
  if (type.includes("conflict")) return "Conflict";
  if (type.includes("negotiation")) return "Negotiating";
  if (type.includes("verification")) return "Verifying";
  if (type.includes("replan")) return "Replanning";
  if (type.includes("execution")) return "Executing";
  if (type.includes("rollback")) return "Recovering";
  return "Running";
}

function applyPipelinePatch(
  pipeline: PipelineStage[],
  patch: Record<string, Partial<PipelineStage>>,
): PipelineStage[] {
  return setStages(pipeline, patch as Partial<Record<StageId, Partial<PipelineStage>>>);
}

function markStage(
  pipeline: PipelineStage[],
  stage: StageId,
  status: PipelineStage["status"],
  detail: string,
): PipelineStage[] {
  const order: StageId[] = [
    "PREFLIGHT",
    "ANALYZE",
    "PLAN",
    "AGENTS",
    "NEGOTIATE",
    "VERIFY",
    "EXECUTE",
    "RECOVER",
    "COMPLETE",
  ];
  const index = order.indexOf(stage);
  const updates: Partial<Record<StageId, Partial<PipelineStage>>> = {
    [stage]: { status, detail },
  };
  for (let i = 0; i < index; i += 1) {
    const id = order[i];
    const current = pipeline.find((p) => p.id === id);
    if (current && (current.status === "pending" || current.status === "running")) {
      updates[id] = { status: "success", detail: `${id} completed` };
    }
  }
  return setStages(pipeline, updates);
}

function humanStageMessage(stage: StageId, kind: "started" | "completed"): string {
  const map: Record<string, { started: string; completed: string }> = {
    PREFLIGHT: {
      started: "MEDHA is checking the deployment prerequisites.",
      completed: "Preflight checks completed.",
    },
    ANALYZE: {
      started: "MEDHA is identifying the application's deployment structure.",
      completed: "Repository analysis stage completed.",
    },
    PLAN: {
      started: "MEDHA is drafting a deployment task from the inferred structure.",
      completed: "Planning stage completed.",
    },
    AGENTS: {
      started: "Specialist agents are preparing deployment requirements.",
      completed: "Specialist agents finished publishing requirements.",
    },
    NEGOTIATE: {
      started: "MEDHA is collecting typed constraints before execution.",
      completed: "Constraint negotiation completed.",
    },
    VERIFY: {
      started: "MEDHA is checking the generated configuration before execution.",
      completed: "Verification gate passed.",
    },
    EXECUTE: {
      started: "MEDHA is applying the agreed plan.",
      completed: "Execution finished.",
    },
    RECOVER: {
      started: "MEDHA is rolling back only the affected dependency branch.",
      completed: "Scoped rollback finished.",
    },
    COMPLETE: {
      started: "Finalizing deployment result.",
      completed: "Deployment completed successfully.",
    },
  };
  return map[stage]?.[kind] || `${stage} ${kind}.`;
}
