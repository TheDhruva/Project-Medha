"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchProject,
  fetchProposals,
  fetchRunHealth,
  fetchRunHydration,
  fetchRunsList,
  subscribeDeploymentEventsShared,
  type AgentSnapshotRow,
  type Project,
  type Proposal,
  type RunHealth,
  type RunLogLine,
  type RunSummary,
  type RuntimeLogsResponse,
} from "@/lib/api/client";
import type {
  CegEdge,
  CegNode,
  ChangeIntelAnalysis,
  ConstraintView,
  NegotiationView,
  RollbackSummary,
} from "@/lib/demo/types";
import { canonicalRepoKey, repoForProjectId, shortNameForRepo } from "./projects";

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
  summary: string | null;
  blocking: string[];
}

export function summarizeVerification(raw: Record<string, unknown> | null): VerificationSummary | null {
  if (!raw) return null;
  const checks = Array.isArray(raw.checks) ? raw.checks : [];
  const failed = checks.filter(
    (c) => typeof c === "object" && c !== null && (c as { status?: unknown }).status === "fail",
  ).length;
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
 * blocked stage is the execute gate itself; upstream stages remain done. */
export const CONFIG_BLOCK_CODES = new Set([
  "EXECUTION_NOT_CONFIGURED",
  "EXECUTION_DISABLED",
  "EXECUTION_DISABLED_HOSTED",
  "REAL_EXECUTION_NOT_ENABLED",
  "REAL_BUILDER_UNAVAILABLE",
]);

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
 * backend evidence — the reported current stage, else the configured-block
 * target (execute), else the furthest observed stage (remediation/rollback
 * excluded — it runs after the failure point).
 */
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

  // Failure point (first match wins): current stage evidence, then the
  // configuration gate target, then the furthest observed pre-remediation stage.
  let blockedId: string | null = null;
  let blockedReason: "config" | "failure" = "failure";
  if (failed) {
    const currentId =
      current && current !== "complete" ? STAGE_ORDER.find((s) => matches(s, current)) ?? null : null;
    const configBlocked = errorCode != null && CONFIG_BLOCK_CODES.has(errorCode);
    const observed = STAGE_ORDER.filter((s) => s !== "recover" && observedFor(s));
    blockedId = currentId ?? (configBlocked ? "execute" : null) ?? observed[observed.length - 1] ?? null;
    blockedReason = configBlocked && blockedId === "execute" ? "config" : "failure";
  }

  return STAGE_ORDER.map((stage) => {
    const observed = observedFor(stage);
    const isCurrent = current ? matches(stage, current) : false;
    let state: PipelineStage["state"] = observed ? "done" : "idle";
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
