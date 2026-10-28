"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchProject,
  fetchProposals,
  fetchRunHealth,
  fetchRunHydration,
  fetchRunsList,
  subscribeDeploymentEventsShared,
  authReady,
  type AgentSnapshotRow,
  type BackendSystemEvent,
  type Project,
  type Proposal,
  type RunHealth,
  type RunLogLine,
  type RunSummary,
  type RuntimeLogsResponse,
  type VerificationCoverage,
} from "@/lib/api/client";
import { toneForEvent } from "@/lib/api/eventMapper";
import type {
  CegEdge,
  CegNode,
  ChangeIntelAnalysis,
  ConstraintView,
  NegotiationView,
  RollbackSummary,
} from "@/lib/demo/types";
import { canonicalRepoKey, repoForProjectId, shortNameForRepo, CONFIG_BLOCK_CODES, isRunningStatus } from "./projects";
// Block-code sets live in projects.ts (single source; avoids an import cycle).
export {
  CONFIG_BLOCK_CODES,
  DEPLOYMENT_BLOCKED_CODES,
} from "./projects";

export interface RunHydration {
  logs: RunLogLine[];
  /** Latest backend agent snapshot; null when the backend reported none. */
  agents: AgentSnapshotRow[] | null;
  /** How the selected run actually executed (real / simulator / controlled_test / demo); null when unknown. */
  executionMode: string | null;
  constraints: ConstraintView[];
  negotiation: NegotiationView | null;
  verification: Record<string, unknown> | null;
  critic: Record<string, unknown> | null;
  /** Normalized verification coverage strip; null when none was recorded. */
  coverage: VerificationCoverage | null;
  graph: { nodes: CegNode[]; edges: CegEdge[] };
  rollback: RollbackSummary | null;
  changeImpact: ChangeIntelAnalysis | null;
  changeImpactLabel: string | null;
  changeImpactIsDemo: boolean;
  /** Observed runtime health (live probe at hydration time); null when unobservable. */
  health: RunHealth | null;
  /** Container stdout/stderr snapshot (real runs only); null when unobserved. */
  runtimeLogs: RuntimeLogsResponse | null;
}

export interface ProjectData {
  projectId: string;
  /** Canonical DB-backed project when the id is a `prj_*` identity; null on legacy URL routes. */
  project: Project | null;
  repo: string | null;
  name: string;
  runs: RunSummary[];
  loading: boolean;
  error: string | null;
  backendReachable: boolean;
  latest: RunSummary | null;
  selectedId: string | null;
  selectRun: (id: string) => void;
  hydration: RunHydration | null;
  hydrating: boolean;
  /** Activity Center feed: REST logs for the selected run plus live SSE appends. */
  feed: FeedEntry[];
  proposals: Proposal[];
  proposalsLoading: boolean;
  refresh: () => void;
}

const EMPTY_HYDRATION: RunHydration = {
  logs: [],
  agents: null,
  executionMode: null,
  constraints: [],
  negotiation: null,
  verification: null,
  critic: null,
  coverage: null,
  graph: { nodes: [], edges: [] },
  rollback: null,
  changeImpact: null,
  changeImpactLabel: null,
  changeImpactIsDemo: false,
  health: null,
  runtimeLogs: null,
};

export function useProjectData(projectId: string, initialRunId?: string | null): ProjectData {
  const canonicalId = projectId.startsWith("prj_") ? projectId : null;
  const legacyRepo = useMemo(
    () => (canonicalId ? null : repoForProjectId(projectId)),
    [projectId, canonicalId],
  );
  const [project, setProject] = useState<Project | null>(null);
  const repo = project?.canonical_url ?? legacyRepo;
  const name = useMemo(
    () => project?.name ?? (repo ? shortNameForRepo(repo) : "Unknown project"),
    [project, repo],
  );
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backendReachable, setBackendReachable] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(initialRunId ?? null);
  const [hydration, setHydration] = useState<RunHydration | null>(null);
  const [hydrating, setHydrating] = useState(false);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [proposalsLoading, setProposalsLoading] = useState(false);
  // Generation counter: rapid project switches must not let a stale load()
  // overwrite newer state (last-wins without AbortController churn).
  const loadGen = useRef(0);

  const load = useCallback(async () => {
    const gen = ++loadGen.current;
    // Wait for the Clerk token getter to be registered so the first API
    // request carries the Authorization header (prevents a 401 on cold start).
    await authReady;
    if (canonicalId) {
      // Canonical identity: one DB-backed project, runs joined by project_id.
      setLoading(true);
      setError(null);
      setProposalsLoading(true);
      try {
        const proj = await fetchProject(canonicalId);
        setProject(proj);
        const [runsRes, proposalsRes] = await Promise.all([
          fetchRunsList({ project_id: canonicalId, limit: 100, offset: 0 }),
          fetchProposals({ project_id: canonicalId, limit: 50 }).catch(() => ({ proposals: [] as Proposal[] })),
        ]);
        if (gen !== loadGen.current) return;
        setRuns(runsRes.runs);
        setProposals(proposalsRes.proposals ?? []);
        setBackendReachable(true);
        setSelectedId((prev) => {
          if (prev && runsRes.runs.some((r) => r.deployment_id === prev)) return prev;
          return runsRes.runs[0]?.deployment_id ?? null;
        });
      } catch (err) {
        if (gen !== loadGen.current) return;
        const missing = err instanceof Error && /not found/i.test(err.message);
        setBackendReachable(!missing ? false : true);
        setError(err instanceof Error ? err.message : "Cannot reach MEDHA backend.");
        setRuns([]);
        setProposals([]);
        if (missing) setProject(null);
      } finally {
        if (gen !== loadGen.current) return;
        setLoading(false);
        setProposalsLoading(false);
      }
      return;
    }
    if (!repo) {
      setLoading(false);
      setError("This project id does not decode to a repository.");
      return;
    }
    setLoading(true);
    setError(null);
    setProposalsLoading(true);
    try {
      const [runsRes, proposalsRes] = await Promise.all([
        fetchRunsList({ repository: repo, limit: 100, offset: 0 }),
        fetchProposals({ repository: repo, limit: 50 }).catch(() => ({ proposals: [] as Proposal[] })),
      ]);
      // Backend filters by substring; keep canonical-identity matches to
      // avoid cross-project leaks and `.git`/casing splits.
      const want = canonicalRepoKey(repo);
      const exact = runsRes.runs.filter((r) => {
        if (want) return canonicalRepoKey(r.repository_url) === want;
        return r.repository_url === repo;
      });
      if (gen !== loadGen.current) return;
      setRuns(exact);
      setProposals(proposalsRes.proposals ?? []);
      setBackendReachable(true);
      setSelectedId((prev) => {
        if (prev && exact.some((r) => r.deployment_id === prev)) return prev;
        return exact[0]?.deployment_id ?? null;
      });
    } catch (err) {
      if (gen !== loadGen.current) return;
      setBackendReachable(false);
      setError(err instanceof Error ? err.message : "Cannot reach MEDHA backend.");
      setRuns([]);
      setProposals([]);
    } finally {
      if (gen !== loadGen.current) return;
      setLoading(false);
      setProposalsLoading(false);
    }
  }, [repo, canonicalId]);

  useEffect(() => {
    setSelectedId(initialRunId ?? null);
    setHydration(null);
    void load();
  }, [load, initialRunId]);

  useEffect(() => {
    if (!selectedId) {
      setHydration(null);
      return;
    }
    let cancelled = false;
    // Never carry one run's health/artifacts into another run's display.
    setHydration(null);
    setHydrating(true);
    void Promise.all([fetchRunHydration(selectedId), fetchRunHealth(selectedId)])
      .then(([h, health]) => {
        if (cancelled) return;
        setHydration({
          logs: h.logs,
          agents: h.agents ?? null,
          executionMode: h.executionMode ?? null,
          constraints: h.constraints?.constraints ?? [],
          negotiation: h.constraints?.negotiation ?? null,
          verification: (h.verification?.verification as Record<string, unknown> | null) ?? null,
          critic: (h.verification?.critic as Record<string, unknown> | null) ?? null,
          coverage: h.verification?.coverage ?? null,
          graph: h.graph?.graph ?? { nodes: [], edges: [] },
          rollback: h.graph?.rollback ?? null,
          changeImpact: h.changeImpact?.analysis ?? null,
          changeImpactLabel: h.changeImpact?.label ?? null,
          changeImpactIsDemo: h.changeImpact?.is_demo ?? false,
          health,
          runtimeLogs: h.runtimeLogs ?? null,
        });
      })
      .catch(() => {
        if (!cancelled) setHydration(EMPTY_HYDRATION);
      })
      .finally(() => {
        if (!cancelled) setHydrating(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  /* Activity Center feed: REST logs for the selected run are authoritative;
     live SSE events append below (deduped by event key, so the stream's
     replay of already-loaded entries is skipped). */
  const [feed, setFeed] = useState<FeedEntry[]>([]);
  useEffect(() => {
    setFeed(hydration ? buildRunFeed(hydration.logs, hydration.agents) : []);
  }, [hydration]);

  // Subscribe only after the REST snapshot loaded: the stream replays from
  // the beginning, and dedup keeps entries already present out of the feed.
  useEffect(() => {
    if (!selectedId || !hydration) return;
    const sub = subscribeDeploymentEventsShared(selectedId, {
      onEvent: (event) => setFeed((prev) => appendEventToFeed(prev, event)),
    });
    return () => {
      sub.close();
    };
  }, [selectedId, hydration]);

  const latest = useMemo(() => runs[0] ?? null, [runs]);

  // Live project-overview subscription: patch the tracked run's status from
  // its SSE stream so the board reflects backend changes without refresh.
  // REST stays authoritative — terminal events trigger a full reload.
  const latestId = latest?.deployment_id ?? null;
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    if (!latestId) return;
    const sub = subscribeDeploymentEventsShared(latestId, {
      onEvent: (event) => {
        const status = (event as { status?: string }).status;
        if (typeof status === "string" && status) {
          setRuns((prev) =>
            prev.map((r) =>
              r.deployment_id === latestId ? { ...r, status } : r,
            ),
          );
        }
      },
      onTerminal: () => {
        void loadRef.current();
      },
      onError: () => {
        // Reconnects are handled by the stream; the next terminal or
        // manual refresh reconciles from REST (authoritative).
      },
    });
    return () => {
      sub.close();
    };
  }, [latestId]);

  const selectRun = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  // Fallback sync: SSE is primary, but a stream that dies before the
  // terminal event would leave the board stale. Poll lightweight run
  // summaries while the tracked run is active; stop on terminal; refetch
  // when the tab returns to foreground. No fabricated progress — REST is
  // authoritative and each response replaces the row.
  const runActive = latest != null && isRunningStatus(latest.status);
  useEffect(() => {
    if (!runActive) return;
    const poll = setInterval(() => void loadRef.current(), 8000);
    const refetchIfHiddenFlip = () => {
      if (!document.hidden) void loadRef.current();
    };
    document.addEventListener("visibilitychange", refetchIfHiddenFlip);
    return () => {
      clearInterval(poll);
      document.removeEventListener("visibilitychange", refetchIfHiddenFlip);
    };
  }, [runActive]);

  return {
    projectId,
    project,
    repo,
    name,
    runs,
    loading,
    error,
    backendReachable,
    latest,
    selectedId,
    selectRun,
    hydration,
    hydrating,
    feed,
    proposals,
    proposalsLoading,
    refresh: load,
  };
}

/* ---------------- safe artifact summarizers (no invented data) -------- */

export interface VerificationSummary {
  passed: boolean | null;
  score: number | null;
  total: number;
  failed: number;
  /** Checks that actually passed, plus assessed/warning/pending counts. */
  passedCount: number;
  assessed: number;
  warnings: number;
  pending: number;
  summary: string | null;
  blocking: string[];
}

export function summarizeVerification(raw: Record<string, unknown> | null): VerificationSummary | null {
  if (!raw) return null;
  const checks = Array.isArray(raw.checks) ? raw.checks : [];
  const count = (status: string) =>
    checks.filter(
      (c) => typeof c === "object" && c !== null && (c as { status?: unknown }).status === status,
    ).length;
  const failed = count("fail");
  const passedCount = count("pass");
  const warnings = count("warning");
  const pending = count("pending");
  const assessed = passedCount + failed + warnings;
  const passed =
    typeof raw.passed === "boolean"
      ? raw.passed
      : checks.length > 0
        ? failed === 0
        : null;
  return {
    passed,
    score: typeof raw.score === "number" ? raw.score : null,
    total: checks.length,
    failed,
    passedCount,
    assessed,
    warnings,
    pending,
    summary: typeof raw.summary === "string" ? raw.summary : null,
    blocking: Array.isArray(raw.blocking_failures)
      ? raw.blocking_failures.filter((x): x is string => typeof x === "string")
      : [],
  };
}

export interface AgentState {
  id: string;
  label: string;
  state: "done" | "active" | "blocked" | "idle";
  detail: string;
}

const AGENT_STAGES: { id: string; label: string; match: string[] }[] = [
  { id: "preflight", label: "Preflight", match: ["preflight"] },
  { id: "analyzer", label: "Code Analyzer", match: ["analyz", "repo"] },
  { id: "docker", label: "Docker", match: ["docker"] },
  { id: "nginx", label: "Nginx", match: ["nginx"] },
  { id: "security", label: "Security", match: ["secur"] },
  { id: "mediator", label: "Mediator / CNP", match: ["cnp", "mediat", "negot"] },
  { id: "verifier", label: "Verifier", match: ["verif"] },
  { id: "critic", label: "Critic", match: ["critic"] },
  { id: "executor", label: "Executor", match: ["execut"] },
  { id: "rollback", label: "Rollback", match: ["rollback"] },
];

const SNAPSHOT_LABELS: Record<string, string> = {
  preflight: "Preflight",
  analyzer: "Code Analyzer",
  docker: "Docker",
  nginx: "Nginx",
  security: "Security",
  mediator: "Mediator / CNP",
  verifier: "Verifier",
  critic: "Critic",
  executor: "Executor",
  rollback: "Rollback",
};

/**
 * Map a real backend agent snapshot to display states. Only backend-known
 * statuses are shown: complete→done, failed/timed_out→blocked,
 * running→active; cancelled/skipped/idle stay idle (settled, no attention).
 * Unknown statuses degrade to idle — never invented as done.
 */
export function agentsFromSnapshot(rows: AgentSnapshotRow[]): AgentState[] {
  return rows.map((row) => {
    let state: AgentState["state"] = "idle";
    if (row.status === "complete") state = "done";
    else if (row.status === "failed" || row.status === "timed_out") state = "blocked";
    else if (row.status === "running") state = "active";
    const parts = [row.activity || row.lastEvent || "No observed activity for this run."];
    if (typeof row.durationMs === "number") parts.push(`(${(row.durationMs / 1000).toFixed(1)}s)`);
    if (row.error) parts.push(`— ${row.error}`);
    return {
      id: row.id,
      label: SNAPSHOT_LABELS[row.id] ?? row.name ?? row.id,
      state,
      detail: parts.join(" "),
    };
  });
}

/**
 * Prefer the backend snapshot; fall back to log-keyword derivation only when
 * the backend reported no snapshot (null). The fallback never claims
 * unobserved stages as done.
 */
export function resolveAgents(
  hydration: RunHydration,
  currentStage: string | null,
  runStatus: string | null,
): { agents: AgentState[]; source: "backend" | "logs" } {
  if (hydration.agents && hydration.agents.length > 0) {
    return { agents: agentsFromSnapshot(hydration.agents), source: "backend" };
  }
  return { agents: deriveAgentsFromLogs(hydration.logs, currentStage, runStatus), source: "logs" };
}

/**
 * Derive per-agent states from observed backend log lines only.
 * A stage never observed is "idle" — never claimed as done.
 */
export function deriveAgentsFromLogs(
  logs: RunLogLine[],
  currentStage: string | null,
  runStatus: string | null,
): AgentState[] {
  const running = runStatus === "running" || runStatus === "started" || runStatus === "queued";
  return AGENT_STAGES.map((agent) => {
    const lines = logs.filter((l) =>
      agent.match.some(
        (m) =>
          (l.stage ?? "").toLowerCase().includes(m) ||
          l.message.toLowerCase().includes(`${agent.id} `) ||
          l.source.toLowerCase().includes(agent.id),
      ),
    );
    const last = lines[lines.length - 1] ?? null;
    const hasError = lines.some((l) => l.level === "error");
    let state: AgentState["state"] = "idle";
    let detail = "No observed activity for this run.";
    if (lines.length > 0) {
      state = "done";
      detail = last ? last.message : `${lines.length} observed events.`;
    }
    if (hasError) {
      state = "blocked";
      const errLine = [...lines].reverse().find((l) => l.level === "error");
      if (errLine) detail = errLine.message;
    } else if (
      running &&
      currentStage &&
      agent.match.some((m) => currentStage.toLowerCase().includes(m))
    ) {
      state = "active";
      detail = last ? last.message : "Active now.";
    }
    return { id: agent.id, label: agent.label, state, detail };
  });
}

/** Display stages in backend execution order (AGENTS folds into Analyze). */
const STAGE_ORDER = ["preflight", "analyze", "plan", "cnp", "verify", "execute", "recover"];

/** Backend emits PREFLIGHT / ANALYZE / PLAN / AGENTS / NEGOTIATE / VERIFY / EXECUTE / RECOVER / COMPLETE. */
const STAGE_MATCH: Record<string, string[]> = {
  preflight: ["preflight"],
  analyze: ["analy", "repo", "agents"],
  plan: ["plan"],
  cnp: ["cnp", "negot", "mediat"],
  verify: ["verif"],
  execute: ["execut"],
  recover: ["recover", "rollback"],
};

/** Failure codes meaning "execution was never configured/available" — the
 * blocked stage is the execute gate itself; upstream stages remain done.
 * (Defined in projects.ts; re-exported above for existing importers.) */

export interface PipelineStage {
  id: string;
  label: string;
  state: "done" | "active" | "blocked" | "idle";
  /** Observed stage.started → stage.completed span; null when unknown/running. */
  durationMs?: number | null;
  /** Why the stage is blocked: configuration gate vs observed failure. */
  reason?: "config" | "failure";
}

const STAGE_LABELS: Record<string, string> = {
  preflight: "Preflight",
  analyze: "Analyze",
  plan: "Plan",
  cnp: "Negotiate (CNP)",
  verify: "Verify",
  execute: "Execute",
  recover: "Rollback",
};

function parseTs(ts: string): number {
  const value = Date.parse(ts);
  return Number.isNaN(value) ? Number.NaN : value;
}

/**
 * Pipeline stepper from observed stage events + current stage. Honest about
 * gaps: a stage never observed stays idle. On failure the blocked stage is
 * backend evidence only — the reported current stage, else the configured-
 * block target (execute). Without reliable failure-stage evidence no stage
 * is marked blocked: the run "stopped before the failing stage was
 * recorded" — Analyze is never blamed merely for being the furthest
 * observed phase.
 */
/* ================= Activity Center conversation feed ================= */

export interface FeedHandoff {
  /** Feed index of the entry that produced the input (for in-page linking). */
  fromIndex: number;
  fromLabel: string;
}

export interface FeedEntry {
  /** Stable list key (timestamp + position in the ordered feed). */
  key: string;
  /** Raw event timestamp for <time dateTime>; kept verbatim. */
  ts: string;
  /** Local-zone clock label, e.g. "9:24:07 AM"; null when unparseable. */
  timeLabel: string | null;
  /** Recorded agent name, "Agent" for unattributed agent output, or "MEDHA". */
  actor: string;
  isAgent: boolean;
  /** Resolved registry agent id when attribution succeeded; null otherwise. */
  agentId: string | null;
  /** Recorded event type (agent.started, stage.completed, …) for provenance. */
  type: string;
  /** Recorded event message — never rewritten dialogue. */
  message: string;
  outcome: "error" | "warning" | "success" | null;
  /** Measured agent duration from the backend snapshot; null when unknown. */
  durationMs: number | null;
  /** Recorded agent error from the backend snapshot; null when none. */
  error: string | null;
  /** Recorded dependency edges whose completion precedes this agent's start. */
  handoffs: FeedHandoff[];
  /** Badge classification of the recorded event (see kindForEvent). */
  kind: FeedKind;
  /** True when the message needs a details toggle (>160 chars or multiline). */
  longMessage: boolean;
  /** Recorded metadata.technical line when the event carried one; null otherwise. */
  technical: string | null;
  /** Cross-source dedup key (ts|type|message) shared with live SSE appends. */
  eventKey: string;
}

/** Activity Center badge classification for one recorded backend event. */
export type FeedKind =
  | "hypothesis"
  | "challenge"
  | "agent_activity"
  | "verification_started"
  | "verification_check"
  | "verification_passed"
  | "verification_failed"
  | "coordinator_decision"
  | "final_decision"
  | "merge_decision"
  | "finding_submitted"
  | "note";

const asText = (value: unknown): string => (typeof value === "string" ? value : "");

/**
 * Map REAL backend event types to a feed badge kind. This table only
 * classifies events the backend actually emits — messages are never
 * invented here:
 *
 *   constraint.published                      → hypothesis
 *   constraint.conflict                       → challenge
 *   agent.started, agent.completed            → agent_activity
 *   verification.started                      → verification_started
 *   verification.check                        → verification_check
 *   verification.passed                       → verification_passed
 *   verification.failed                       → verification_failed
 *   negotiation.resolved, critic.completed    → coordinator_decision
 *   deployment.completed|failed|cancelled     → final_decision
 *   system.message + metadata.merge_decision  → merge_decision
 *   system.message mentioning "finding" (message / metadata.simple /
 *     metadata.technical, case-insensitive)   → finding_submitted
 *   system.message otherwise, stage.*, any
 *   other type                                → note
 */
export function kindForEvent(event: {
  type: string;
  message: string;
  data?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}): FeedKind {
  switch (event.type) {
    case "constraint.published":
      return "hypothesis";
    case "constraint.conflict":
      return "challenge";
    case "agent.started":
    case "agent.completed":
      return "agent_activity";
    case "verification.started":
      return "verification_started";
    case "verification.check":
      return "verification_check";
    case "verification.passed":
      return "verification_passed";
    case "verification.failed":
      return "verification_failed";
    case "negotiation.resolved":
    case "critic.completed":
      return "coordinator_decision";
    case "deployment.completed":
    case "deployment.failed":
    case "deployment.cancelled":
      return "final_decision";
    case "system.message": {
      const metadata = event.metadata ?? event.data ?? {};
      if ("merge_decision" in metadata) return "merge_decision";
      const text = [event.message, asText(metadata.simple), asText(metadata.technical)].join(" ");
      return /finding/i.test(text) ? "finding_submitted" : "note";
    }
    default:
      return "note";
  }
}

/**
 * Cross-source dedup key for one recorded event. REST log lines and SSE
 * payloads carry the same ts/type/message (SSE additionally has event_id,
 * which REST lines lack — so identity is derived from these three fields).
 * shortcut: two distinct events identical in all three would collide —
 * backend timestamps make that negligible, and buildRunFeed already
 * deduplicates REST lines the same way.
 */
function eventKeyOf(ts: string, type: string, message: string): string {
  return `${ts}|${type}|${message}`;
}

function messageNeedsTruncation(message: string): boolean {
  return message.length > 160 || message.includes("\n");
}

/**
 * Append one live backend event to an Activity Center feed. Returns the
 * same array when the event is already present (stream replay, reconnect,
 * or an entry loaded from REST logs) so appends are idempotent.
 */
export function appendEventToFeed(
  feed: FeedEntry[],
  event: BackendSystemEvent,
): FeedEntry[] {
  const eventKey = eventKeyOf(event.ts, event.type, event.message);
  if (feed.some((entry) => entry.eventKey === eventKey)) return feed;
  // The SSE serializer labels event metadata `data` (backend publishes
  // metadata=... into data); kindForEvent accepts either name.
  const metadata = event.data ?? {};

  let actor = "MEDHA";
  let isAgent = false;
  let agentId: string | null = null;
  if (event.type === "agent.started") {
    const text = event.message.trim();
    const id = text.endsWith(AGENT_STARTED_SUFFIX) ? text.slice(0, -AGENT_STARTED_SUFFIX.length) : "";
    if (id && SNAPSHOT_LABELS[id]) {
      isAgent = true;
      agentId = id;
      actor = SNAPSHOT_LABELS[id] ?? id;
    }
  } else if (event.type === "agent.completed") {
    // No snapshot row here, so attribution stays honestly generic —
    // a hydration rebuild attributes it from recorded evidence.
    isAgent = true;
    actor = "Agent";
  }

  const tone = toneForEvent(event.type, event.level);
  const outcome: FeedEntry["outcome"] =
    event.level === "error" || event.status === "failed" || tone === "error"
      ? "error"
      : event.level === "warning" || event.status === "warning" || tone === "warning"
        ? "warning"
        : tone === "success"
          ? "success"
          : null;

  return [
    ...feed,
    {
      key: `${event.ts}-live-${feed.length}`,
      ts: event.ts,
      timeLabel: formatFeedTime(event.ts),
      actor,
      isAgent,
      agentId,
      type: event.type,
      message: event.message,
      outcome,
      durationMs: null,
      error: null,
      handoffs: [],
      kind: kindForEvent(event),
      longMessage: messageNeedsTruncation(event.message),
      technical: asText(metadata.technical) || null,
      eventKey,
    },
  ];
}

const AGENT_STARTED_SUFFIX = " started";

/**
 * Conversation-style feed for one run, built only from recorded evidence:
 *
 * - `agent.started` messages are constructed backend-side as "{id} started",
 *   so the agent name is parsed from the recorded text (only known ids match).
 * - `agent.completed` messages carry the agent's summary but not its id in the
 *   REST log, so attribution happens only on an exact match against one
 *   snapshot row that recorded the same text; ambiguous or missing matches
 *   stay generic ("Agent") — never guessed.
 * - Handoffs appear only when a declared snapshot dependency recorded its
 *   completion earlier in the feed.
 * - Everything else is a factual system update with the recorded message.
 *
 * There is no agent-to-agent dialogue in the data model; none is invented.
 */
export function buildRunFeed(
  logs: RunLogLine[],
  agents: AgentSnapshotRow[] | null,
): FeedEntry[] {
  // Dedupe identical recorded lines (same ts/type/source/message) that some
  // refreshes return twice. Array sort is stable, so equal timestamps keep
  // their stored order — the key's index is the tie-breaker.
  const seen = new Set<string>();
  const deduped = logs.filter((line) => {
    const sig = `${line.ts}|${line.type}|${line.source}|${line.message}`;
    if (seen.has(sig)) return false;
    seen.add(sig);
    return true;
  });
  const ordered = [...deduped].sort((a, b) => {
    const ta = Date.parse(a.ts);
    const tb = Date.parse(b.ts);
    const va = Number.isNaN(ta) ? Number.MAX_SAFE_INTEGER : ta;
    const vb = Number.isNaN(tb) ? Number.MAX_SAFE_INTEGER : tb;
    return va - vb;
  });
  const rows = agents ?? [];
  const rowById = new Map(rows.map((r) => [r.id, r]));

  // Unique snapshot row recording the exact same summary text — attribution
  // by recorded evidence only; two rows with identical text stay unattributed.
  const attributed: (AgentSnapshotRow | null)[] = ordered.map((line) => {
    if (line.type !== "agent.completed") return null;
    const msg = line.message.trim();
    const matches = rows.filter(
      (r) => (r.activity || "").trim() === msg || (r.lastEvent || "").trim() === msg,
    );
    return matches.length === 1 ? matches[0] : null;
  });
  const completionIndexByAgent = new Map<string, number>();
  attributed.forEach((row, i) => {
    if (row && !completionIndexByAgent.has(row.id)) completionIndexByAgent.set(row.id, i);
  });

  return ordered.map((line, i) => {
    let actor = "MEDHA";
    let isAgent = false;
    let agentId: string | null = null;
    let message = line.message;
    let durationMs: number | null = null;
    let error: string | null = null;
    let handoffs: FeedHandoff[] = [];

    if (line.type === "agent.started") {
      const text = line.message.trim();
      const id = text.endsWith(AGENT_STARTED_SUFFIX)
        ? text.slice(0, -AGENT_STARTED_SUFFIX.length)
        : "";
      if (id && SNAPSHOT_LABELS[id]) {
        isAgent = true;
        agentId = id;
        actor = SNAPSHOT_LABELS[id] ?? id;
        message = "Started.";
        handoffs = (rowById.get(id)?.deps ?? []).flatMap((dep) => {
          const idx = completionIndexByAgent.get(dep);
          const label = SNAPSHOT_LABELS[dep];
          return idx !== undefined && idx < i && label
            ? [{ fromIndex: idx, fromLabel: label }]
            : [];
        });
      }
    } else if (line.type === "agent.completed") {
      isAgent = true;
      const row = attributed[i];
      agentId = row?.id ?? null;
      actor = row ? (SNAPSHOT_LABELS[row.id] ?? row.name ?? "Agent") : "Agent";
      durationMs = row?.durationMs ?? null;
      error = row?.error ?? null;
    }

    const tone = toneForEvent(line.type, line.level);
    const outcome: FeedEntry["outcome"] =
      line.level === "error" || line.status === "failed" || tone === "error"
        ? "error"
        : line.level === "warning" || line.status === "warning" || tone === "warning"
          ? "warning"
          : tone === "success"
            ? "success"
            : null;

    return {
      key: `${line.ts}-${i}`,
      ts: line.ts,
      timeLabel: formatFeedTime(line.ts),
      actor,
      isAgent,
      agentId,
      type: line.type,
      message,
      outcome,
      durationMs,
      error,
      handoffs,
      kind: kindForEvent({ type: line.type, message: line.message }),
      longMessage: messageNeedsTruncation(message),
      // REST log lines carry no metadata; the technical line is only shown
      // for live SSE events that recorded one.
      technical: null,
      // Key from the ORIGINAL recorded message (agent.started is rewritten
      // to "Started." for display) so live SSE appends dedup against it.
      eventKey: eventKeyOf(line.ts, line.type, line.message),
    };
  });
}

/** Local-zone feed clock, e.g. "9:24:07 AM"; null when ts is unparseable. */
export function formatFeedTime(ts: string): string | null {
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleTimeString("en-US", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

export interface RosterAgent {
  id: string;
  label: string;
  /** Initials for the avatar bubble (max 2 letters). */
  initials: string;
  /** Stable conversation side: even roster index left, odd right. */
  side: "left" | "right";
  /** Backend snapshot state when this agent has a row; null when unknown. */
  state: AgentState["state"] | null;
  /** Snapshot-recorded activity/error; null when no snapshot row exists. */
  detail: string | null;
  /** True when this agent authored at least one feed message. */
  spoke: boolean;
}

/** Two-letter initials from a display label ("Code Analyzer" → "CA"). */
export function agentInitials(label: string): string {
  const parts = label.split(/[\s/]+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
}

/**
 * Participating-agent roster for one run, discovered from recorded evidence:
 * agents that authored feed messages, plus snapshot rows with observed
 * activity. Unattributed "Agent" messages get a generic roster entry only
 * when no resolved agent spoke. Sides alternate in registry order so every
 * agent keeps a stable, visually balanced alignment across refreshes.
 */
export function buildRunRoster(
  feed: FeedEntry[],
  agents: AgentSnapshotRow[] | null,
): RosterAgent[] {
  const snapshotById = new Map((agents ?? []).map((r) => [r.id, r]));
  const order: string[] = [];
  const seen = new Set<string>();
  const add = (id: string) => {
    if (!seen.has(id)) {
      seen.add(id);
      order.push(id);
    }
  };
  // Registry order first (stable identity), then any snapshot-only agents.
  for (const id of Object.keys(SNAPSHOT_LABELS)) {
    const inFeed = feed.some((e) => e.agentId === id);
    const row = snapshotById.get(id);
    const observed =
      row != null &&
      (row.status === "running" ||
        row.status === "complete" ||
        row.status === "failed" ||
        row.status === "timed_out");
    if (inFeed || observed) add(id);
  }
  for (const row of agents ?? []) {
    if (!SNAPSHOT_LABELS[row.id]) add(row.id);
  }

  const roster: RosterAgent[] = order.map((id, i) => {
    const row = snapshotById.get(id) ?? null;
    let state: AgentState["state"] | null = null;
    if (row) {
      state = "idle";
      if (row.status === "complete") state = "done";
      else if (row.status === "failed" || row.status === "timed_out") state = "blocked";
      else if (row.status === "running") state = "active";
    }
    const detail = row
      ? row.error || row.activity || row.lastEvent || null
      : null;
    return {
      id,
      label: SNAPSHOT_LABELS[id] ?? row?.name ?? id,
      initials: agentInitials(SNAPSHOT_LABELS[id] ?? row?.name ?? id),
      side: i % 2 === 0 ? "left" : "right",
      state,
      detail: detail === "—" ? null : detail,
      spoke: feed.some((e) => e.agentId === id),
    };
  });

  // Unattributed agent output still deserves a visible, honestly generic sender.
  if (feed.some((e) => e.isAgent && e.agentId === null)) {
    roster.push({
      id: "unattributed",
      label: "Agent",
      initials: "AG",
      side: roster.length % 2 === 0 ? "left" : "right",
      state: null,
      detail: null,
      spoke: true,
    });
  }
  return roster;
}

export function derivePipeline(
  logs: RunLogLine[],
  currentStage: string | null,
  runStatus: string | null,
  errorCode?: string | null,
): PipelineStage[] {
  const failed = runStatus === "failed";
  const running = runStatus === "running" || runStatus === "started" || runStatus === "queued";
  const seen = new Set(
    logs.map((l) => (l.stage ?? "").toLowerCase()).filter(Boolean),
  );
  const current = (currentStage ?? "").toLowerCase();
  const seenList = [...seen];
  const matches = (stage: string, value: string) =>
    (STAGE_MATCH[stage] ?? [stage]).some((m) => value.includes(m));
  const observedFor = (stage: string) => seenList.some((s) => matches(stage, s));
  // Completion evidence, not mere presence: a stage that emitted
  // stage.started but never stage.completed on a failed run is the
  // failure point — never "done".
  const completedFor = (stage: string) =>
    logs.some(
      (l) => l.type === "stage.completed" && matches(stage, (l.stage ?? "").toLowerCase()),
    );
  const startedFor = (stage: string) =>
    logs.some(
      (l) => l.type === "stage.started" && matches(stage, (l.stage ?? "").toLowerCase()),
    );

  // Failure point (first match wins): current stage evidence, then the
  // first stage that started but never completed (the backend resets
  // current_stage to COMPLETE on failure, erasing the failing stage),
  // then the configuration gate target. Never the furthest observed
  // stage — that would falsely blame Analyze for runs that stopped later.
  let blockedId: string | null = null;
  let blockedReason: "config" | "failure" = "failure";
  if (failed) {
    const currentId =
      current && current !== "complete" ? STAGE_ORDER.find((s) => matches(s, current)) ?? null : null;
    const configBlocked = errorCode != null && CONFIG_BLOCK_CODES.has(errorCode);
    const unfinishedId =
      STAGE_ORDER.find((s) => startedFor(s) && !completedFor(s)) ?? null;
    blockedId = currentId ?? unfinishedId ?? (configBlocked ? "execute" : null);
    blockedReason = configBlocked && blockedId === "execute" ? "config" : "failure";
  }

  return STAGE_ORDER.map((stage) => {
    const observed = observedFor(stage);
    const isCurrent = current ? matches(stage, current) : false;
    let state: PipelineStage["state"] = observed ? "done" : "idle";
    // On a failed run, started-without-completed is honest "idle" (or the
    // blocked failure point below) — never "done".
    if (failed && !completedFor(stage)) state = "idle";
    if (running && isCurrent) state = "active";
    if (failed && stage === blockedId) state = "blocked";

    // Duration from stage.started → stage.completed pairs for this stage.
    let durationMs: number | null = null;
    if (observed) {
      const stageLogs = logs.filter((l) => matches(stage, (l.stage ?? "").toLowerCase()));
      const start = stageLogs.find((l) => l.type === "stage.started");
      const done = stageLogs.find((l) => l.type === "stage.completed");
      if (start && done) {
        const t0 = parseTs(start.ts);
        const t1 = parseTs(done.ts);
        if (!Number.isNaN(t0) && !Number.isNaN(t1) && t1 >= t0) durationMs = t1 - t0;
      }
    }

    return {
      id: stage,
      label: STAGE_LABELS[stage] ?? stage[0].toUpperCase() + stage.slice(1),
      state,
      durationMs,
      ...(failed && stage === blockedId ? { reason: blockedReason } : {}),
    };
  });
}
