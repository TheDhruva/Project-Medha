import type {
  CegEdge,
  CegNode,
  ChangeIntelAnalysis,
  ConstraintView,
  NegotiationView,
  RollbackSummary,
  ScenarioId,
} from "@/lib/demo/types";

// Same-origin by default: the hosted service proxies /api/* and /health to
// FastAPI through Next.js rewrites, so no absolute URL is needed. An explicit
// NEXT_PUBLIC_API_BASE_URL still overrides this for split local development.
const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") || "";

export function getApiBaseUrl(): string {
  return API_BASE;
}

export interface DeployApiRequest {
  repository_url: string;
  mode: "demo" | "real";
  scenario?: ScenarioId | null;
  target: { host: string; port: number };
  intent?: string;
  base_revision?: string | null;
  target_revision?: string | null;
}

export interface DeployApiResponse {
  deployment_id: string;
  status: string;
  mode: string;
  is_demo: boolean;
}

export interface BackendSystemEvent {
  event_id: string;
  deployment_id: string;
  ts: string;
  stage: string | null;
  type: string;
  level: string;
  message: string;
  status: string | null;
  is_demo: boolean;
  data?: Record<string, unknown>;
}

export interface DeploymentApiSnapshot {
  deployment_id: string;
  status: string;
  mode: string;
  is_demo: boolean;
  scenario: ScenarioId | null;
  repository_url: string;
  target: { host: string; port: number };
  intent: string | null;
  current_stage: string | null;
  explain?: { simple?: string | null; technical?: string | null };
  created_at: string;
  updated_at: string;
  error_summary?: string | null;
  result?: Record<string, unknown> | null;
  label?: string | null;
}

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = await response.json();
    return new ApiError(
      body?.error?.message || response.statusText,
      response.status,
      body?.error?.code,
    );
  } catch {
    return new ApiError(response.statusText || "Request failed", response.status);
  }
}

export async function createDeployment(
  payload: DeployApiRequest,
): Promise<DeployApiResponse> {
  const response = await fetch(`${API_BASE}/api/deploy`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function fetchDeployment(
  deploymentId: string,
): Promise<DeploymentApiSnapshot> {
  const response = await fetch(
    `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}`,
  );
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export function eventsUrl(deploymentId: string): string {
  return `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/events`;
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const response = await fetch(`${API_BASE}/health`, { cache: "no-store" });
    return response.ok;
  } catch {
    return false;
  }
}

export interface EvaluationSummary {
  cnp: Record<string, unknown> | null;
  ceg: Record<string, unknown> | null;
  combined: Record<string, unknown> | null;
  runs: Array<Record<string, unknown>>;
  note: string;
  commands: Record<string, string>;
}

export async function fetchEvaluationSummary(): Promise<EvaluationSummary> {
  const response = await fetch(`${API_BASE}/api/evaluation`, { cache: "no-store" });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function runEvaluation(kind: "cnp" | "ceg"): Promise<Record<string, unknown>> {
  const response = await fetch(`${API_BASE}/api/evaluation/run/${kind}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

// --- Phase 2 Change Intelligence ---

export interface ChangeImpactRequest {
  repository_url: string;
  base_revision: string;
  target_revision: string;
  deployment_id?: string | null;
}

export interface ChangeImpactResponse {
  deployment_id: string | null;
  is_demo: boolean;
  label: string | null;
  generated_at?: string;
  note?: string;
  analysis: ChangeIntelAnalysis;
}

export async function analyzeChangeImpact(
  payload: ChangeImpactRequest,
): Promise<ChangeImpactResponse> {
  const response = await fetch(`${API_BASE}/api/change-impact/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function fetchChangeImpact(
  deploymentId: string,
): Promise<ChangeImpactResponse> {
  const response = await fetch(
    `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/change-impact`,
    {
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function fetchDemoChangeImpact(): Promise<ChangeImpactResponse> {
  const response = await fetch(`${API_BASE}/api/change-impact/demo/fixture`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

// --- Phase 3 Product API (runs list, artifacts, timeline) ---

export interface RunSummary {
  deployment_id: string;
  status: string;
  mode: string;
  is_demo: boolean;
  label: string | null;
  scenario: ScenarioId | null;
  repository_url: string;
  intent: string | null;
  base_revision: string | null;
  target_revision: string | null;
  current_stage: string | null;
  created_at: string;
  updated_at: string;
  duration_seconds: number | null;
  risk: string | null;
  result_kind: string | null;
  error_summary: string | null;
}

export interface RunsListResponse {
  runs: RunSummary[];
  total: number;
  limit: number;
  offset: number;
  filters: { status: string | null; mode: string | null; repository: string | null };
}

export async function fetchRunsList(params?: {
  status?: string;
  mode?: string;
  repository?: string;
  limit?: number;
  offset?: number;
}): Promise<RunsListResponse> {
  const query = new URLSearchParams();
  if (params?.status) query.set("status", params.status);
  if (params?.mode) query.set("mode", params.mode);
  if (params?.repository) query.set("repository", params.repository);
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await fetch(`${API_BASE}/api/deploys${suffix}`, { cache: "no-store" });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export interface RunLogLine {
  ts: string;
  level: string;
  source: string;
  message: string;
  type: string;
  stage: string | null;
  status: string | null;
  is_demo: boolean;
}

export interface RunLogsResponse {
  deployment_id: string;
  is_demo: boolean;
  label: string | null;
  lines: RunLogLine[];
}

export async function fetchRunLogs(deploymentId: string): Promise<RunLogsResponse> {
  const response = await fetch(
    `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/logs`,
    {
      cache: "no-store",
    },
  );
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export interface ConstraintsArtifact {
  constraints: ConstraintView[];
  negotiation: NegotiationView | null;
}

export async function fetchConstraintsArtifact(
  deploymentId: string,
): Promise<ConstraintsArtifact | null> {
  const response = await fetch(
    `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/constraints`,
    {
      cache: "no-store",
    },
  );
  if (!response.ok) return null;
  const body = (await response.json()) as {
    constraints?: ConstraintView[];
    negotiation?: NegotiationView | null;
  };
  if (!body.constraints) return null;
  return { constraints: body.constraints, negotiation: body.negotiation ?? null };
}

export interface VerificationArtifact {
  verification: Record<string, unknown> | null;
  critic: Record<string, unknown> | null;
}

export async function fetchVerificationArtifact(
  deploymentId: string,
): Promise<VerificationArtifact | null> {
  const response = await fetch(
    `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/verification`,
    {
      cache: "no-store",
    },
  );
  if (!response.ok) return null;
  const body = (await response.json()) as {
    verification?: Record<string, unknown> | null;
    critic?: Record<string, unknown> | null;
  };
  if (body.verification == null && body.critic == null) return null;
  return { verification: body.verification ?? null, critic: body.critic ?? null };
}

export interface GraphArtifact {
  graph: { nodes: CegNode[]; edges: CegEdge[] };
  rollback: RollbackSummary | null;
}

export async function fetchGraphArtifact(deploymentId: string): Promise<GraphArtifact | null> {
  const response = await fetch(
    `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/graph`,
    {
      cache: "no-store",
    },
  );
  if (!response.ok) return null;
  const body = (await response.json()) as {
    graph?: { nodes?: CegNode[]; edges?: CegEdge[] };
    rollback?: RollbackSummary | null;
  };
  if (!body.graph) return null;
  return {
    graph: { nodes: body.graph.nodes ?? [], edges: body.graph.edges ?? [] },
    rollback: body.rollback ?? null,
  };
}

/**
 * Load every stored artifact for a run in parallel. Each artifact is optional:
 * failures map to null so the UI can show honest "not available" states instead
 * of crashing when a run never reached that stage.
 */
export async function fetchRunHydration(deploymentId: string): Promise<{
  logs: RunLogLine[];
  constraints: ConstraintsArtifact | null;
  verification: VerificationArtifact | null;
  graph: GraphArtifact | null;
  changeImpact: ChangeImpactResponse | null;
}> {
  const [logs, constraints, verification, graph, changeImpact] = await Promise.allSettled([
    fetchRunLogs(deploymentId),
    fetchConstraintsArtifact(deploymentId),
    fetchVerificationArtifact(deploymentId),
    fetchGraphArtifact(deploymentId),
    fetchChangeImpact(deploymentId),
  ]);
  return {
    logs: logs.status === "fulfilled" ? logs.value.lines : [],
    constraints: constraints.status === "fulfilled" ? constraints.value : null,
    verification: verification.status === "fulfilled" ? verification.value : null,
    graph: graph.status === "fulfilled" ? graph.value : null,
    changeImpact: changeImpact.status === "fulfilled" ? changeImpact.value : null,
  };
}
