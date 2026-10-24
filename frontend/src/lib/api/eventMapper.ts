import { emptyGraph, initialAgents, initialPipeline, setStages } from "@/lib/demo/scenarios";
import type {
  AgentActivity,
  CegGraph,
  ChangeIntelAnalysis,
  ConstraintView,
  CriticView,
  DeploymentResultView,
  DeploymentSnapshot,
  ExecutionMode,
  NegotiationView,
  PipelineStage,
  RollbackSummary,
  RuntimeLogsView,
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

export function toneForEvent(type: string, level: string): TraceEvent["tone"] {
  if (type.includes("failed") || level === "error") return "error";
  if (type.includes("conflict") || level === "warning" || type.includes("replan"))
    return "warning";
  if (
    type.includes("completed") ||
    type.includes("passed") ||
    type.includes("resolved") ||
    type.includes("ready") ||
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
  isDemo = false,
): DeploymentSnapshot {
  return {
    deploymentId,
    isDemo: false,
    // No evidence yet at start: unknown, never a fabricated executor claim.
    executionMode: null,
    runtimeLogs: null,
    scenario: null,
    runStatus: "running",
    explain: {
      currentStage: null,
      round: null,
      statusLabel: "Started",
      simpleText:
        "Deployment accepted. Waiting for real analysis / CNP events…",
      technicalText:
        `deployment_id=${deploymentId} · source=api+sse · workflow=planning · phases=10-12`,
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
    durationSeconds: null,
  };
}

export function applyBackendEvent(
  snapshot: DeploymentSnapshot,
  event: BackendSystemEvent,
): DeploymentSnapshot {
  const data = event.data || {};
  const appended: TraceEvent[] = [
    ...snapshot.trace,
    {
      id: event.event_id,
      time: formatClock(event.ts),
      tone: toneForEvent(event.type, event.level),
      message: event.message,
      technical: technicalLine(event, data),
    },
  ];
  // Bound in-memory trace growth for long runs; full history stays
  // available via GET /api/deploy/{id}/logs. Render window slices further.
  const nextTrace: TraceEvent[] =
    appended.length > 500 ? appended.slice(appended.length - 500) : appended;

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
    // A terminal run never keeps executing: resolve stages the backend
    // left "running" (e.g. real-path EXECUTE before the source fix).
    pipeline = resolveTerminalPipeline(pipeline, runStatus, event.message, rollback);
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
    pipeline = resolveTerminalPipeline(pipeline, runStatus, event.message, rollback);
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

  if (event.type === "deployment.cancelled") {
    runStatus = "failed";
    if (!data.pipeline) {
      pipeline = setStages(pipeline, {
        COMPLETE: { status: "failed", detail: "Cancelled by owner" },
      });
    }
    pipeline = resolveTerminalPipeline(pipeline, runStatus, event.message, rollback);
    explain = {
      currentStage: snapshot.explain.currentStage,
      round: null,
      statusLabel: "Cancelled",
      simpleText: simpleFromEvent || event.message,
      technicalText:
        technicalFromEvent ||
        `event=deployment.cancelled · deployment_id=${event.deployment_id}`,
    };
    result = (data.result as DeploymentResultView) || {
      kind: "failed",
      title: "CANCELLED",
      message: event.message,
      durationLabel: "demo",
      servicesLabel: "n/a",
      verificationScore: null,
      constraintsResolved: 0,
      rollbackScope: null,
    };
  }

  if (event.type === "proposal.ready") {
    runStatus = "awaiting_approval";
    if (!data.pipeline) {
      pipeline = setStages(pipeline, {
        COMPLETE: { status: "success", detail: "Plan ready — awaiting approval" },
      });
    }
    explain = {
      currentStage: "COMPLETE",
      round: negotiationRound(data, negotiation),
      statusLabel: "Waiting for approval",
      simpleText:
        simpleFromEvent ||
        "Verified plan ready. Nothing will execute until a human approves it.",
      technicalText:
        technicalFromEvent ||
        `event=proposal.ready · status=${event.status} · is_demo=${event.is_demo}`,
    };
    result = (data.result as DeploymentResultView) || {
      kind: "plan_awaiting_approval",
      title: "AWAITING APPROVAL",
      message: event.message,
      durationLabel: "analysis",
      servicesLabel: "see plan",
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
  awaiting_approval: "awaiting_approval",
};

/**
 * Terminal pipeline reconciliation (the fix for "Execute: Running" on a
 * terminal failed run).
 *
 * The backend historically left the in-flight stage "running" when the run
 * terminated (real-path EXECUTE had no completed event before the source
 * fix), so the log-derived pipeline contradicted the terminal status.
 * At a terminal state a still-"running" stage cannot still be executing:
 * on failure it is the failure point, on success the workflow finished.
 * Completed stages are never touched — analysis/verification results stand.
 * RECOVER resolves from the persisted rollback artifact (recorded scope vs
 * none), never as an invented "pending".
 */
export function resolveTerminalPipeline(
  pipeline: PipelineStage[],
  runStatus: DeploymentSnapshot["runStatus"],
  detail: string,
  rollback: RollbackSummary | null,
): PipelineStage[] {
  if (runStatus !== "failed" && runStatus !== "succeeded" && runStatus !== "partial_recovery") {
    return pipeline;
  }
  const updates: Partial<Record<StageId, Partial<PipelineStage>>> = {};
  for (const stage of pipeline) {
    if (stage.id === "COMPLETE" || stage.id === "RECOVER") continue;
    if (stage.status !== "running") continue;
    updates[stage.id] = {
      status:
        runStatus === "failed" ? "failed" : runStatus === "partial_recovery" ? "warning" : "success",
      detail,
    };
  }
  const recover = pipeline.find((p) => p.id === "RECOVER");
  if (recover && (recover.status === "pending" || recover.status === "running")) {
    if (rollback) {
      const affected = (rollback.failed ?? 0) + (rollback.rolledBack ?? 0);
      updates.RECOVER = {
        status: affected > 0 ? "warning" : "success",
        detail: `${rollback.rolledBack ?? 0} rolled back · ${rollback.preserved ?? 0} preserved`,
      };
    } else {
      updates.RECOVER = {
        status: "skipped",
        detail: runStatus === "succeeded" ? "No recovery needed" : "No rollback recorded",
      };
    }
  }
  return Object.keys(updates).length > 0 ? setStages(pipeline, updates) : pipeline;
}

/**
 * Measured run duration in seconds: backend stage timings first
 * (`result.timings.totalMs`), else the persisted created/updated span.
 * Null when neither is determinable — never the execution-mode label.
 */
export function durationFromApi(api: DeploymentApiSnapshot): number | null {
  const result = api.result as Record<string, unknown> | null | undefined;
  const timings = result?.["timings"] as Record<string, unknown> | undefined;
  const totalMs = timings?.["totalMs"];
  if (typeof totalMs === "number" && Number.isFinite(totalMs) && totalMs >= 0) {
    return Math.round(totalMs / 1000);
  }
  const start = Date.parse(api.created_at);
  const end = Date.parse(api.updated_at);
  if (!Number.isNaN(start) && !Number.isNaN(end) && end >= start) {
    return Math.round((end - start) / 1000);
  }
  return null;
}

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
        : runStatus === "awaiting_approval"
          ? "Waiting for approval"
          : "Failed";
  return {
    ...snapshot,
    runStatus,
    isDemo: api.is_demo,
    pipeline: resolveTerminalPipeline(
      snapshot.pipeline,
      runStatus,
      runStatus === "failed"
        ? (api.error_summary || "Run failed")
        : statusLabel,
      snapshot.rollback,
    ),
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
  executionMode?: string | null;
  runtimeLogs?: RuntimeLogsView | null;
  constraints?: ConstraintView[] | null;
  negotiation?: NegotiationView | null;
  verification?: VerificationView | null;
  critic?: CriticView | null;
  graph?: CegGraph | null;
  rollback?: RollbackSummary | null;
  changeIntel?: ChangeIntelAnalysis | null;
}

/**
 * Resolve how a run actually executed. Explicit backend `execution_mode`
 * (from /logs, falling back to the stored result) wins. When there is no
 * backend evidence a demo run is "demo"; anything else is `null` (unknown) —
 * never a fabricated "simulator", so a real failure is never reported as a
 * simulation and an unknown mode never renders as "real".
 */
export function resolveExecutionMode(
  executionMode: string | null | undefined,
  result: Record<string, unknown> | null | undefined,
  isDemo: boolean,
): ExecutionMode | null {
  const raw =
    (typeof executionMode === "string" && executionMode) ||
    (typeof result?.["execution_mode"] === "string" ? (result["execution_mode"] as string) : "");
  const normalized = raw.trim().toLowerCase();
  if (
    normalized === "demo" ||
    normalized === "simulator" ||
    normalized === "controlled_test" ||
    normalized === "real" ||
    normalized === "unconfigured"
  ) {
    return normalized;
  }
  return isDemo ? "demo" : null;
}

export function buildBackendSnapshot(input: BackendHydrationInput): DeploymentSnapshot {
  const { api } = input;
  const isDemo = api.is_demo;
  const runStatus = TERMINAL_RUN_STATUS[api.status] ?? "running";
  const logs = input.logs ?? [];
  const terminalDetail =
    runStatus === "failed"
      ? api.error_summary || "Run failed"
      : runStatus === "partial_recovery"
        ? "Partial recovery after scoped rollback"
        : "Run completed";
  const pipeline = resolveTerminalPipeline(
    pipelineFromLogs(logs, runStatus),
    runStatus,
    terminalDetail,
    input.rollback ?? null,
  );
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
          : runStatus === "awaiting_approval"
            ? "Waiting for approval"
            : "Complete";

  const apiResult = api.result as DeploymentResultView | null | undefined;
  // A still-running deployment has no result yet — never fabricate SUCCESS.
  const hydratedResult =
    runStatus === "running" && !apiResult ? null : (apiResult ?? terminalResultFallback(runStatus));

  return {
    deploymentId: api.deployment_id,
    isDemo,
    executionMode: resolveExecutionMode(
      input.executionMode,
      api.result as Record<string, unknown> | null | undefined,
      isDemo,
    ),
    runtimeLogs: input.runtimeLogs ?? null,
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
              : runStatus === "awaiting_approval"
                ? "Verified plan ready. Nothing executes until a human approves it."
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
    result: hydratedResult as DeploymentResultView,
    trace,
    frameIndex: 0,
    totalFrames: 0,
    changeIntel: input.changeIntel ?? null,
    durationSeconds: durationFromApi(api),
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
