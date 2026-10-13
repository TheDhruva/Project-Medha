"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  fetchProject,
  fetchProposals,
  fetchRunHealth,
  fetchRunHydration,
  fetchRunsList,
  type Project,
  type Proposal,
  type RunHealth,
  type RunLogLine,
  type RunSummary,
} from "@/lib/api/client";
import type {
  CegEdge,
  CegNode,
  ChangeIntelAnalysis,
  ConstraintView,
  NegotiationView,
  RollbackSummary,
} from "@/lib/demo/types";
import { repoForProjectId, shortNameForRepo } from "./projects";

export interface RunHydration {
  logs: RunLogLine[];
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

  const load = useCallback(async () => {
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
        setRuns(runsRes.runs);
        setProposals(proposalsRes.proposals ?? []);
        setBackendReachable(true);
        setSelectedId((prev) => {
          if (prev && runsRes.runs.some((r) => r.deployment_id === prev)) return prev;
          return runsRes.runs[0]?.deployment_id ?? null;
        });
      } catch (err) {
        const missing = err instanceof Error && /not found/i.test(err.message);
        setBackendReachable(!missing ? false : true);
        setError(err instanceof Error ? err.message : "Cannot reach MEDHA backend.");
        setRuns([]);
        setProposals([]);
        if (missing) setProject(null);
      } finally {
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
      // Backend filters by substring; keep exact matches to avoid cross-project leaks.
      const exact = runsRes.runs.filter((r) => r.repository_url === repo);
      setRuns(exact);
      setProposals(proposalsRes.proposals ?? []);
      setBackendReachable(true);
      setSelectedId((prev) => {
        if (prev && exact.some((r) => r.deployment_id === prev)) return prev;
        return exact[0]?.deployment_id ?? null;
      });
    } catch (err) {
      setBackendReachable(false);
      setError(err instanceof Error ? err.message : "Cannot reach MEDHA backend.");
      setRuns([]);
      setProposals([]);
    } finally {
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

const STAGE_ORDER = ["preflight", "analyze", "cnp", "verify", "execute"];

/** Backend emits PREFLIGHT / ANALYZE / NEGOTIATE / VERIFY / EXECUTE / COMPLETE. */
const STAGE_MATCH: Record<string, string[]> = {
  preflight: ["preflight"],
  analyze: ["analy", "repo"],
  cnp: ["cnp", "negot", "mediat"],
  verify: ["verif"],
  execute: ["execut"],
};

export interface PipelineStage {
  id: string;
  label: string;
  state: "done" | "active" | "blocked" | "idle";
}

/** Pipeline stepper from observed stages + current stage. Honest about gaps. */
export function derivePipeline(
  logs: RunLogLine[],
  currentStage: string | null,
  runStatus: string | null,
): PipelineStage[] {
  const failed = runStatus === "failed";
  const running = runStatus === "running" || runStatus === "started" || runStatus === "queued";
  const seen = new Set(
    logs.map((l) => (l.stage ?? "").toLowerCase()).filter(Boolean),
  );
  const current = (currentStage ?? "").toLowerCase();
  const seenList = [...seen];
  let blockedAssigned = false;
  return STAGE_ORDER.map((stage) => {
    const observed = (STAGE_MATCH[stage] ?? [stage]).some((m) =>
      seenList.some((s) => s.includes(m)),
    );
    const matchers = STAGE_MATCH[stage] ?? [stage];
    const isCurrent = matchers.some((m) => current.includes(m));
    let state: PipelineStage["state"] = observed ? "done" : "idle";
    if (running && isCurrent) state = "active";
    if (failed && !blockedAssigned && (isCurrent || observed)) {
      // Mark the furthest observed-or-current stage as blocked.
      state = "blocked";
      blockedAssigned = true;
    }
    return {
      id: stage,
      label: stage === "cnp" ? "Negotiate (CNP)" : stage[0].toUpperCase() + stage.slice(1),
      state,
    };
  });
}
