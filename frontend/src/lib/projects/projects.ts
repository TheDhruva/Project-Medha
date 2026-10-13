import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createDeployment,
  fetchProjects,
  fetchRunsList,
  type DeployApiRequest,
  type Project,
  type RunSummary,
} from "@/lib/api/client";

/* ------------------------------------------------------------------ */
/* Project identity                                                     */
/*                                                                      */
/* Canonical identity is the database-backed project (`prj_*`, owned per */
/* user, verified via a readability check). Runs carry `project_id` and  */
/* join to it. Runs without a project (created before project routing)  */
/* remain visible as legacy URL groups — read-only compatibility, never  */
/* a substitute for ownership. A URL is never an authorization proof.    */
/* ------------------------------------------------------------------ */

export interface ProjectSummary {
  /** Canonical `prj_*` id, or `encodeURIComponent(repository_url)` for legacy groups. */
  id: string;
  /** Canonical project id when DB-backed, else null (legacy group). */
  projectId: string | null;
  /** Connection status for canonical projects; null for legacy groups. */
  connectionStatus: string | null;
  /** True for legacy URL groups without a project record. */
  legacy: boolean;
  repositoryUrl: string;
  name: string;
  totalRuns: number;
  latest: RunSummary | null;
  lastActivity: string | null;
  demoRuns: number;
  realRuns: number;
  failedRuns: number;
  awaitingApproval: number;
  /** Short human-readable attention reasons, empty when quiet. */
  attention: string[];
}

export function projectIdForRepo(repositoryUrl: string): string {
  return encodeURIComponent(repositoryUrl);
}

export function repoForProjectId(id: string): string | null {
  try {
    const decoded = decodeURIComponent(id);
    return decoded ? decoded : null;
  } catch {
    return null;
  }
}

/** Derive a display name from a repository URL or local path. */
export function shortNameForRepo(repositoryUrl: string): string {
  const trimmed = repositoryUrl.trim().replace(/\/+$/, "");
  if (!trimmed) return "Untitled project";
  const noScheme = trimmed.replace(/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//, "");
  const parts = noScheme.split(/[/\\]/).filter(Boolean);
  const last = parts[parts.length - 1] ?? trimmed;
  return last.replace(/\.git$/i, "") || trimmed;
}

const TERMINAL_OK = new Set(["completed"]);
const ATTENTION_STATUS = new Set(["failed", "awaiting_approval", "partial_recovery"]);

function summarize(
  id: string,
  repositoryUrl: string,
  name: string,
  list: RunSummary[],
  extra?: { projectId?: string | null; connectionStatus?: string | null; legacy?: boolean },
): ProjectSummary {
  const sorted = [...list].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  const latest = sorted[0] ?? null;
  const attention: string[] = [];
  if (latest && latest.status === "failed") {
    attention.push(latest.error_summary || "Latest run failed");
  }
  if (latest && latest.status === "awaiting_approval") {
    attention.push("Plan awaiting approval");
  }
  if (latest && latest.status === "partial_recovery") {
    attention.push("Recovered with scoped rollback — review preserved services");
  }
  const failedRecent = sorted.filter((r) => r.status === "failed").length;
  if (failedRecent > 1 && latest?.status !== "failed") {
    attention.push(`${failedRecent} failed runs on record`);
  }
  void TERMINAL_OK;
  return {
    id,
    projectId: extra?.projectId ?? null,
    connectionStatus: extra?.connectionStatus ?? null,
    legacy: extra?.legacy ?? false,
    repositoryUrl,
    name,
    totalRuns: sorted.length,
    latest,
    lastActivity: latest?.updated_at ?? null,
    demoRuns: sorted.filter((r) => r.is_demo).length,
    realRuns: sorted.filter((r) => !r.is_demo).length,
    failedRuns: failedRecent,
    awaitingApproval: sorted.filter((r) => r.status === "awaiting_approval").length,
    attention,
  };
}

export function deriveProjects(runs: RunSummary[], projects?: Project[]): ProjectSummary[] {
  const out: ProjectSummary[] = [];
  const claimed = new Set<string>();
  for (const p of projects ?? []) {
    const mine = runs
      .filter((r) => r.project_id === p.project_id)
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    for (const r of mine) claimed.add(r.deployment_id);
    out.push(
      summarize(p.project_id, p.canonical_url, p.name, mine, {
        projectId: p.project_id,
        connectionStatus: p.connection_status,
      }),
    );
  }
  // Legacy compatibility: runs without a project record group by exact URL.
  const byRepo = new Map<string, RunSummary[]>();
  for (const run of runs) {
    if (claimed.has(run.deployment_id)) continue;
    const key = (run.repository_url || "unknown").trim() || "unknown";
    const list = byRepo.get(key);
    if (list) list.push(run);
    else byRepo.set(key, [run]);
  }
  for (const [repositoryUrl, list] of byRepo) {
    out.push(
      summarize(projectIdForRepo(repositoryUrl), repositoryUrl, shortNameForRepo(repositoryUrl), list, {
        legacy: true,
      }),
    );
  }
  return out.sort((a, b) => (b.lastActivity ?? "").localeCompare(a.lastActivity ?? ""));
}

export type ProjectStatusFilter = "all" | "attention";

/* ------------------------------------------------------------------ */
/* Card-level display status for the /projects workspace                */
/*                                                                      */
/* Four exhaustive buckets derived from real backend state only:        */
/* - "no_runs": no recorded runs (latest === null).                     */
/* - "running": latest run is genuinely in flight                       */
/*   (queued | started | running).                                      */
/* - "attention": actionable terminal/waiting state — failed,            */
/*   awaiting_approval, partial_recovery, or cancelled (a cancelled run */
/*   never implies success, so it surfaces for review), or any other    */
/*   unknown non-completed status (conservative: never claim success    */
/*   without evidence).                                                 */
/* - "completed": latest run finished with status === "completed".      */
/*   This reports workflow completion only — never deployment health.   */
/* ------------------------------------------------------------------ */

export type ProjectCardStatus = "attention" | "running" | "completed" | "no_runs";

export const PROJECT_CARD_STATUS_META: { id: ProjectCardStatus; label: string }[] = [
  { id: "attention", label: "Needs attention" },
  { id: "running", label: "Running" },
  { id: "completed", label: "Completed" },
  { id: "no_runs", label: "No runs yet" },
];

const RUNNING_STATUS = new Set(["queued", "started", "running"]);

export function projectCardStatus(p: ProjectSummary): ProjectCardStatus {
  if (!p.latest || p.totalRuns === 0) return "no_runs";
  const s = p.latest.status;
  if (RUNNING_STATUS.has(s)) return "running";
  if (p.attention.length > 0) return "attention";
  if (s === "completed") return "completed";
  // Cancelled and any unknown non-completed status: surface for review
  // rather than implying a quiet success.
  return "attention";
}

export type ProjectSort = "recent" | "name" | "status";

const STATUS_ORDER: Record<ProjectCardStatus, number> = {
  attention: 0,
  running: 1,
  completed: 2,
  no_runs: 3,
};

export function sortProjects(list: ProjectSummary[], sort: ProjectSort): ProjectSummary[] {
  const arr = [...list];
  switch (sort) {
    case "name":
      return arr.sort(
        (a, b) =>
          a.name.toLowerCase().localeCompare(b.name.toLowerCase()) ||
          a.repositoryUrl.toLowerCase().localeCompare(b.repositoryUrl.toLowerCase()) ||
          a.id.localeCompare(b.id),
      );
    case "status":
      return arr.sort(
        (a, b) =>
          STATUS_ORDER[projectCardStatus(a)] - STATUS_ORDER[projectCardStatus(b)] ||
          (b.lastActivity ?? "").localeCompare(a.lastActivity ?? "") ||
          a.name.toLowerCase().localeCompare(b.name.toLowerCase()) ||
          a.id.localeCompare(b.id),
      );
    case "recent":
    default:
      return arr.sort(
        (a, b) =>
          (b.lastActivity ?? "").localeCompare(a.lastActivity ?? "") ||
          a.name.toLowerCase().localeCompare(b.name.toLowerCase()) ||
          a.id.localeCompare(b.id),
      );
  }
}

export function filterProjectsByStatus(
  projects: ProjectSummary[],
  query: string,
  active: ReadonlySet<ProjectCardStatus> | ProjectCardStatus[],
): ProjectSummary[] {
  const q = query.trim().toLowerCase();
  const set = active instanceof Set ? active : new Set(active);
  return projects.filter((p) => {
    if (q && !p.name.toLowerCase().includes(q) && !p.repositoryUrl.toLowerCase().includes(q)) {
      return false;
    }
    if (set.size === 0) return true;
    return set.has(projectCardStatus(p));
  });
}

/**
 * Project-level attention state derived from real run outcomes only.
 *
 * There is intentionally no "healthy" state: a completed run means the
 * workflow finished, not that the service is healthy. Runtime health
 * requires observed health-check evidence, which the runs list does not
 * carry — so a quiet project reports "idle", never "healthy".
 */
export function projectHealth(p: ProjectSummary): "attention" | "running" | "idle" {
  const s = p.latest?.status ?? null;
  if (s && ["queued", "started", "running"].includes(s)) return "running";
  if (p.attention.length > 0) return "attention";
  return "idle";
}

export function filterProjects(
  projects: ProjectSummary[],
  query: string,
  status: ProjectStatusFilter,
): ProjectSummary[] {
  const q = query.trim().toLowerCase();
  return projects.filter((p) => {
    if (q && !p.name.toLowerCase().includes(q) && !p.repositoryUrl.toLowerCase().includes(q)) {
      return false;
    }
    const health = projectHealth(p);
    switch (status) {
      case "all":
        return true;
      case "attention":
        return health === "attention";
    }
  });
}

/* ------------------------------------------------------------------ */
/* Hook: live project list backed by /api/deploys                       */
/* ------------------------------------------------------------------ */

export interface CreateProjectInput {
  repositoryUrl: string;
  mode: "real";
  port?: number;
  intent?: string;
}

export function useProjects(limit = 200) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backendReachable, setBackendReachable] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [runsRes, projRes] = await Promise.all([
        fetchRunsList({ limit, offset: 0 }),
        fetchProjects().catch(() => ({ projects: [] as Project[], total: 0 })),
      ]);
      setRuns(runsRes.runs);
      setProjects(projRes.projects ?? []);
      setTotal(runsRes.total);
      setBackendReachable(true);
    } catch (err) {
      setBackendReachable(false);
      setError(err instanceof Error ? err.message : "Cannot reach MEDHA backend.");
      // Preserve cached projects/runs so a refresh failure reports the
      // error without wiping the visible grid (fresh mounts start empty).
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    void load();
  }, [load]);

  const summaries = useMemo(() => deriveProjects(runs, projects), [runs, projects]);

  const createProject = useCallback(
    async (input: CreateProjectInput): Promise<string> => {
      const payload: DeployApiRequest = {
        repository_url: input.repositoryUrl.trim(),
        mode: "real",
        scenario: null,
        target: { host: "localhost", port: input.port ?? 8080 },
        intent: input.intent?.trim() || undefined,
      };
      const created = await createDeployment(payload);
      await load();
      return created.deployment_id;
    },
    [load],
  );

  return { projects: summaries, runs, total, loading, error, backendReachable, refresh: load, createProject };
}

export function formatActivity(iso: string | null): string {
  if (!iso) return "No runs yet";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** True when a run status is non-terminal (still in flight). */
export function isRunningStatus(status: string | null | undefined): boolean {
  return status === "queued" || status === "started" || status === "running";
}

export { ATTENTION_STATUS };
