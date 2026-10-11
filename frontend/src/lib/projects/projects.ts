import { useCallback, useEffect, useMemo, useState } from "react";
import {
  createDeployment,
  fetchRunsList,
  type DeployApiRequest,
  type RunSummary,
} from "@/lib/api/client";

/* ------------------------------------------------------------------ */
/* Project identity                                                     */
/*                                                                      */
/* The backend has no separate projects table: durable records are      */
/* deployments (runs), each carrying repository_url + owner. A          */
/* "project" is therefore the set of runs for one repository URL,       */
/* derived entirely from backend state — never invented locally.        */
/* ------------------------------------------------------------------ */

export interface ProjectSummary {
  /** URL-safe id: encodeURIComponent(repository_url). */
  id: string;
  repositoryUrl: string;
  name: string;
  totalRuns: number;
  latest: RunSummary | null;
  lastActivity: string | null;
  demoRuns: number;
  realRuns: number;
  failedRuns: number;
  awaitingApproval: number;
  /** Short human-readable attention reasons, empty when healthy. */
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

export function deriveProjects(runs: RunSummary[]): ProjectSummary[] {
  const byRepo = new Map<string, RunSummary[]>();
  for (const run of runs) {
    const key = (run.repository_url || "unknown").trim() || "unknown";
    const list = byRepo.get(key);
    if (list) list.push(run);
    else byRepo.set(key, [run]);
  }
  const projects: ProjectSummary[] = [];
  for (const [repositoryUrl, list] of byRepo) {
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
    projects.push({
      id: projectIdForRepo(repositoryUrl),
      repositoryUrl,
      name: shortNameForRepo(repositoryUrl),
      totalRuns: sorted.length,
      latest,
      lastActivity: latest?.updated_at ?? null,
      demoRuns: sorted.filter((r) => r.is_demo).length,
      realRuns: sorted.filter((r) => !r.is_demo).length,
      failedRuns: failedRecent,
      awaitingApproval: sorted.filter((r) => r.status === "awaiting_approval").length,
      attention,
    });
  }
  return projects.sort((a, b) => (b.lastActivity ?? "").localeCompare(a.lastActivity ?? ""));
}

export type ProjectStatusFilter = "all" | "healthy" | "attention" | "running" | "demo" | "real";

export function projectHealth(p: ProjectSummary): "attention" | "running" | "healthy" | "idle" {
  const s = p.latest?.status ?? null;
  if (s && ["queued", "started", "running"].includes(s)) return "running";
  if (p.attention.length > 0) return "attention";
  if (s === "completed") return "healthy";
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
      case "healthy":
        return health === "healthy";
      case "attention":
        return health === "attention";
      case "running":
        return health === "running";
      case "demo":
        return p.demoRuns > 0 && p.realRuns === 0;
      case "real":
        return p.realRuns > 0;
    }
  });
}

/* ------------------------------------------------------------------ */
/* Hook: live project list backed by /api/deploys                       */
/* ------------------------------------------------------------------ */

export interface CreateProjectInput {
  repositoryUrl: string;
  mode: "demo" | "real";
  scenario?: string | null;
  port?: number;
  intent?: string;
}

export function useProjects(limit = 200) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [backendReachable, setBackendReachable] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await fetchRunsList({ limit, offset: 0 });
      setRuns(response.runs);
      setTotal(response.total);
      setBackendReachable(true);
    } catch (err) {
      setBackendReachable(false);
      setError(err instanceof Error ? err.message : "Cannot reach MEDHA backend.");
      setRuns([]);
      setTotal(0);
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    void load();
  }, [load]);

  const projects = useMemo(() => deriveProjects(runs), [runs]);

  const createProject = useCallback(
    async (input: CreateProjectInput): Promise<string> => {
      const payload: DeployApiRequest = {
        repository_url: input.repositoryUrl.trim(),
        mode: input.mode,
        scenario: input.mode === "demo" ? ((input.scenario ?? "SUCCESSFUL_DEPLOYMENT") as DeployApiRequest["scenario"]) : null,
        target: { host: "localhost", port: input.port ?? 8080 },
        intent: input.intent?.trim() || undefined,
      };
      const created = await createDeployment(payload);
      await load();
      return created.deployment_id;
    },
    [load],
  );

  return { projects, runs, total, loading, error, backendReachable, refresh: load, createProject };
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
