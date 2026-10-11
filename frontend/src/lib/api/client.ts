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

/* --- Clerk session forwarding -------------------------------------------
 * When a user is signed in, the app registers an async token getter (see
 * components/auth/ClerkTokenSync). Every API request then carries
 * `Authorization: Bearer <Clerk session JWT>` so the FastAPI layer can
 * verify identity and enforce per-user ownership when MEDHA_AUTH_MODE=clerk.
 * Signed-out callers (guest demo) send no header; in the default off-mode
 * backend the header is ignored and behavior is unchanged.
 * ------------------------------------------------------------------------ */

let tokenGetter: (() => Promise<string | null>) | null = null;

export function registerAuthTokenGetter(fn: (() => Promise<string | null>) | null): void {
  tokenGetter = fn;
}

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  try {
    const token = tokenGetter ? await tokenGetter() : null;
    if (token) headers.set("Authorization", `Bearer ${token}`);
  } catch {
    /* Token unavailable (signed out) — proceed unauthenticated. */
  }
  return globalThis.fetch(`${API_BASE}${path}`, { ...init, headers });
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
  ai?: Record<string, unknown> | null;
  owner_sub?: string | null;
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
  const response = await apiFetch(`/api/deploy`, {
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
  const response = await apiFetch(
    `/api/deploy/${encodeURIComponent(deploymentId)}`,
  );
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export function eventsUrl(deploymentId: string): string {
  return `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/events`;
}

const TERMINAL_SSE_TYPES = new Set([
  "deployment.completed",
  "deployment.failed",
  "proposal.ready",
]);

export interface EventSubscription {
  close: () => void;
  readonly closed: boolean;
}

/**
 * Subscribe to a deployment's SSE stream with the Clerk session attached.
 *
 * EventSource cannot send Authorization headers, so this uses fetch +
 * streaming reads with the same Bearer injection as apiFetch. The backend
 * replays persisted events first, then live events; terminal event types
 * close the subscription automatically.
 */
export function subscribeDeploymentEvents(
  deploymentId: string,
  handlers: {
    onEvent: (event: BackendSystemEvent) => void;
    onError?: (message: string) => void;
    onTerminal?: () => void;
  },
): EventSubscription {
  const controller = new AbortController();
  let closed = false;

  async function authHeader(): Promise<Headers> {
    const headers = new Headers({ Accept: "text/event-stream" });
    try {
      const token = tokenGetter ? await tokenGetter() : null;
      if (token) headers.set("Authorization", `Bearer ${token}`);
    } catch {
      /* Signed out — proceed without credentials. */
    }
    return headers;
  }

  function fail(message: string): void {
    if (!closed) handlers.onError?.(message);
  }

  void (async () => {
    let headers: Headers;
    try {
      headers = await authHeader();
    } catch {
      fail("Cannot reach MEDHA backend event stream.");
      return;
    }
    let response: Response;
    try {
      response = await fetch(
        `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/events`,
        { headers, signal: controller.signal },
      );
    } catch (err) {
      if (!controller.signal.aborted) fail("Cannot reach MEDHA backend event stream.");
      return;
    }
    if (!response.ok || !response.body) {
      try {
        const err = await parseError(response);
        fail(err.status === 401 || err.status === 503 ? err.message : "Cannot reach MEDHA backend event stream.");
      } catch {
        fail("Cannot reach MEDHA backend event stream.");
      }
      return;
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        if (closed) break;
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          for (const rawLine of frame.split("\n")) {
            const line = rawLine.trim();
            if (!line.startsWith("data:")) continue;
            const payload = line.slice("data:".length).trim();
            if (!payload) continue;
            try {
              const event = JSON.parse(payload) as BackendSystemEvent;
              handlers.onEvent(event);
              if (TERMINAL_SSE_TYPES.has(event.type)) {
                handlers.onTerminal?.();
                return;
              }
            } catch {
              fail("Failed to parse backend event.");
            }
          }
          if (closed) return;
        }
      }
    } catch {
      fail("Lost connection to MEDHA backend event stream.");
    } finally {
      try {
        reader.releaseLock();
      } catch {
        /* noop */
      }
    }
  })();

  return {
    close: () => {
      closed = true;
      try {
        controller.abort();
      } catch {
        /* noop */
      }
    },
    get closed() {
      return closed;
    },
  };
}

export async function checkBackendHealth(): Promise<boolean> {
  try {
    const response = await apiFetch(`/health`, { cache: "no-store" });
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
  const response = await apiFetch(`/api/evaluation`, { cache: "no-store" });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function runEvaluation(kind: "cnp" | "ceg"): Promise<Record<string, unknown>> {
  const response = await apiFetch(`/api/evaluation/run/${kind}`, {
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
  const response = await apiFetch(`/api/change-impact/analyze`, {
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
  const response = await apiFetch(
    `/api/deploy/${encodeURIComponent(deploymentId)}/change-impact`,
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
  const response = await apiFetch(`/api/change-impact/demo/fixture`, {
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
  ai_outcome?: string | null;
  ai_provider?: string | null;
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
  const response = await apiFetch(`/api/deploys${suffix}`, { cache: "no-store" });
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
  const response = await apiFetch(
    `/api/deploy/${encodeURIComponent(deploymentId)}/logs`,
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
  const response = await apiFetch(
    `/api/deploy/${encodeURIComponent(deploymentId)}/constraints`,
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
  const response = await apiFetch(
    `/api/deploy/${encodeURIComponent(deploymentId)}/verification`,
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
  const response = await apiFetch(
    `/api/deploy/${encodeURIComponent(deploymentId)}/graph`,
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

// --- AI provider status (safe metadata only; never secrets) ---

export interface AiProviderHealth {
  configured: boolean;
  model: string | null;
  reachable: boolean;
  latency_s: number;
  failure_category: string | null;
}

export interface AiStatus {
  enabled: boolean;
  primary_provider: string;
  fallback_provider: string;
  primary_model: string;
  fallback_model: string;
  max_calls_per_run: number;
  request_timeout_seconds: number;
  max_output_tokens: number;
  health: {
    enabled: boolean;
    primary: string;
    fallback: string;
    providers: Record<string, AiProviderHealth>;
  };
}

export async function fetchAiStatus(): Promise<AiStatus> {
  const response = await apiFetch(`/api/ai/status`, { cache: "no-store" });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

// --- Approval proposals (push-triggered, human-gated execution) ---

export interface Proposal {
  proposal_id: string;
  repository: string;
  branch: string;
  base_sha: string | null;
  target_sha: string;
  deployment_id: string | null;
  plan_hash: string | null;
  plan: Record<string, unknown> | null;
  status: string;
  created_by: string | null;
  created_at: string;
  decided_by: string | null;
  decided_at: string | null;
  execution_id: string | null;
}

export interface ProposalsListResponse {
  proposals: Proposal[];
  total: number;
  limit: number;
  offset: number;
}

export async function fetchProposals(params?: {
  repository?: string;
  status?: string;
  limit?: number;
  offset?: number;
}): Promise<ProposalsListResponse> {
  const query = new URLSearchParams();
  if (params?.repository) query.set("repository", params.repository);
  if (params?.status) query.set("status", params.status);
  if (params?.limit != null) query.set("limit", String(params.limit));
  if (params?.offset != null) query.set("offset", String(params.offset));
  const suffix = query.toString() ? `?${query.toString()}` : "";
  const response = await apiFetch(`/api/proposals${suffix}`, { cache: "no-store" });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function decideProposal(
  proposalId: string,
  decision: "approve" | "reject",
  reason?: string,
): Promise<Proposal & { duplicate?: boolean }> {
  const response = await apiFetch(
    `/api/proposals/${encodeURIComponent(proposalId)}/${decision}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: reason ?? null }),
    },
  );
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

// --- Project-scoped repository connections (multi-user) ---

export interface Project {
  project_id: string;
  name: string;
  provider: string;
  repo_owner: string;
  repo_name: string;
  repository: string;
  canonical_url: string;
  branch: string;
  visibility: "unverified" | "public" | "private_unsupported" | string;
  connection_status: "pending" | "connected" | "failed" | "disconnected" | string;
  created_at: string;
  updated_at: string;
}

export interface ProjectsListResponse {
  projects: Project[];
  total: number;
}

export async function fetchProjects(): Promise<ProjectsListResponse> {
  const response = await apiFetch(`/api/projects`, { cache: "no-store" });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function createProject(input: {
  name: string;
  repository: string;
  branch?: string;
}): Promise<Project> {
  const response = await apiFetch(`/api/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function fetchProject(projectId: string): Promise<Project> {
  const response = await apiFetch(`/api/projects/${encodeURIComponent(projectId)}`, {
    cache: "no-store",
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function updateProject(
  projectId: string,
  patch: { name?: string; branch?: string },
): Promise<Project> {
  const response = await apiFetch(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export interface ProjectVerifyResponse {
  project: Project;
  reachable: boolean;
  head_sha?: string;
  reason?: string;
}

export async function verifyProject(projectId: string): Promise<ProjectVerifyResponse> {
  const response = await apiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/verify`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function disconnectProject(projectId: string): Promise<Project> {
  const response = await apiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/disconnect`,
    { method: "POST" },
  );
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function deleteProject(projectId: string): Promise<{ deleted: string }> {
  const response = await apiFetch(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: "DELETE",
  });
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}

export async function createProjectRun(
  projectId: string,
  input?: { intent?: string; target_revision?: string; target_host?: string; target_port?: number },
): Promise<DeployApiResponse & { project_id: string }> {
  const response = await apiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/runs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input ?? {}),
    },
  );
  if (!response.ok) {
    throw await parseError(response);
  }
  return response.json();
}
