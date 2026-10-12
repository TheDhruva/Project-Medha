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
  clearApiCache("/api/deploys");
  clearApiCache("/api/proposals");
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
  "deployment.cancelled",
  "proposal.ready",
]);

/* --- Lightweight diagnostics (bounded, in-memory, no PII) -------------- */
const diag: { sseConnections: number; sseReconnects: number; sseEvents: number } = {
  sseConnections: 0,
  sseReconnects: 0,
  sseEvents: 0,
};

export function getSseDiagnostics() {
  return { ...diag };
}

/* --- Tiny shared GET cache (same-tab, short TTL, explicit invalidation) --
 * Same browser tab == same signed-in user, so URL-keyed caching with an 8s
 * TTL is tenant-safe here. Mutations and terminal SSE events invalidate.
 * Auth-sensitive decisions (ownership, approval) always revalidate via
 * fetchDeployment on open; lists/hydration tolerate seconds of staleness.
 * ------------------------------------------------------------------------ */
const apiCache = new Map<string, { expiry: number; data: unknown }>();
const API_CACHE_TTL_MS = 8000;

export function clearApiCache(prefix?: string): void {
  if (!prefix) {
    apiCache.clear();
    return;
  }
  for (const key of [...apiCache.keys()]) {
    if (key.startsWith(prefix)) apiCache.delete(key);
  }
}

async function cachedGet<T>(path: string, ttlMs = API_CACHE_TTL_MS): Promise<T> {
  const now = Date.now();
  const hit = apiCache.get(path);
  if (hit && hit.expiry > now) return hit.data as T;
  const response = await apiFetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw await parseError(response);
  }
  const data = (await response.json()) as T;
  if (apiCache.size > 200) apiCache.clear();
  apiCache.set(path, { expiry: now + ttlMs, data });
  return data;
}

async function cachedGetOrNull<T>(path: string, ttlMs = API_CACHE_TTL_MS): Promise<T | null> {
  try {
    return await cachedGet<T>(path, ttlMs);
  } catch {
    return null;
  }
}

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
  opts?: { after?: string | null; limit?: number },
): EventSubscription {
  const controller = new AbortController();
  let closed = false;
  diag.sseConnections += 1;

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
    const seen = new Set<string>();
    // Bound dedup memory for very long runs; IDs are unique so eviction
    // only risks reprocessing an ancient event after 5k+ uniques.
    const MAX_SEEN = 5000;
    let attempt = 0;
    let afterCursor = opts?.after ?? null;
    const limit = Math.max(1, Math.min(opts?.limit ?? 100, 500));
    while (!closed && attempt <= 5) {
      let headers: Headers;
      try {
        headers = await authHeader();
      } catch {
        fail("Cannot reach MEDHA backend event stream.");
        return;
      }
      let response: Response;
      try {
        const params = new URLSearchParams();
        params.set("limit", String(limit));
        if (afterCursor) params.set("after", afterCursor);
        response = await fetch(
          `${API_BASE}/api/deploy/${encodeURIComponent(deploymentId)}/events?${params.toString()}`,
          { headers, signal: controller.signal },
        );
      } catch (err) {
        if (controller.signal.aborted) return;
        attempt += 1;
        if (attempt > 5) {
          fail("Cannot reach MEDHA backend event stream.");
          return;
        }
        await new Promise((r) => setTimeout(r, Math.min(1000 * 2 ** attempt, 8000)));
        continue;
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
      let disconnected = false;
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
                const key = (event as { event_id?: string }).event_id ?? `${event.type}:${event.ts}`;
                if (seen.has(key)) continue;
                seen.add(key);
                if (seen.size > MAX_SEEN) {
                  const first = seen.values().next().value;
                  if (first) seen.delete(first);
                }
                afterCursor = key;
                diag.sseEvents += 1;
                handlers.onEvent(event);
                if (TERMINAL_SSE_TYPES.has(event.type)) {
                  clearApiCache(`/api/deploy/${encodeURIComponent(deploymentId)}`);
                  clearApiCache("/api/deploys");
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
        disconnected = true;
      } finally {
        try {
          reader.releaseLock();
        } catch {
          /* noop */
        }
      }
      if (closed) return;
      if (!disconnected) return; // clean EOF without terminal: stop, state reconciles via REST
      attempt += 1;
      diag.sseReconnects += 1;
      if (attempt > 5) {
        fail("Lost connection to MEDHA backend event stream.");
        return;
      }
      await new Promise((r) => setTimeout(r, Math.min(1000 * 2 ** attempt, 8000)));
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

/* --- Shared per-deployment subscription (refcounted, duplicate-safe) -----
 * Multiple components mounting for the same deployment in one tab share a
 * single HTTP stream; each subscriber keeps its own dedup via handlers.
 * The underlying stream closes when the last subscriber releases it or a
 * terminal event arrives.
 * ------------------------------------------------------------------------ */
const sharedSubs = new Map<
  string,
  { sub: EventSubscription; refs: number; handlers: Set<(e: BackendSystemEvent) => void> }
>();

export function subscribeDeploymentEventsShared(
  deploymentId: string,
  handlers: {
    onEvent: (event: BackendSystemEvent) => void;
    onError?: (message: string) => void;
    onTerminal?: () => void;
  },
): EventSubscription {
  const existing = sharedSubs.get(deploymentId);
  if (existing && !existing.sub.closed) {
    existing.refs += 1;
    existing.handlers.add(handlers.onEvent);
    let released = false;
    return {
      close: () => {
        if (released) return;
        released = true;
        existing.handlers.delete(handlers.onEvent);
        existing.refs -= 1;
        if (existing.refs <= 0) {
          existing.sub.close();
          sharedSubs.delete(deploymentId);
        }
      },
      get closed() {
        return released || existing.sub.closed;
      },
    };
  }
  const handlersSet = new Set<(e: BackendSystemEvent) => void>([handlers.onEvent]);
  const sub = subscribeDeploymentEvents(
    deploymentId,
    {
      onEvent: (e) => {
        for (const fn of [...handlersSet]) {
          try {
            fn(e);
          } catch {
            /* one bad subscriber must not break the shared stream */
          }
        }
      },
      onError: handlers.onError,
      onTerminal: () => {
        handlers.onTerminal?.();
        sharedSubs.delete(deploymentId);
      },
    },
    { limit: 100 },
  );
  sharedSubs.set(deploymentId, { sub, refs: 1, handlers: handlersSet });
  let released = false;
  return {
    close: () => {
      if (released) return;
      released = true;
      const entry = sharedSubs.get(deploymentId);
      if (!entry) return;
      entry.handlers.delete(handlers.onEvent);
      entry.refs -= 1;
      if (entry.refs <= 0) {
        entry.sub.close();
        sharedSubs.delete(deploymentId);
      }
    },
    get closed() {
      return released;
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
  const path = `/api/deploy/${encodeURIComponent(deploymentId)}/change-impact`;
  const now = Date.now();
  const hit = apiCache.get(path);
  // change-impact is immutable once computed for a run; cache longer but
  // fall back to direct fetch (404 when not yet computed is normal).
  if (hit && hit.expiry > now) return hit.data as ChangeImpactResponse;
  const response = await apiFetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw await parseError(response);
  }
  const data = (await response.json()) as ChangeImpactResponse;
  apiCache.set(path, { expiry: now + 30000, data });
  return data;
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
  return cachedGet<RunsListResponse>(`/api/deploys${suffix}`);
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

export interface RuntimeLogsResponse {
  available: boolean;
  container?: string | null;
  code?: string | null;
  stdout?: string;
  stderr?: string;
}

export interface RunLogsResponse {
  deployment_id: string;
  is_demo: boolean;
  label: string | null;
  execution_mode: string | null;
  lines: RunLogLine[];
  runtime_logs: RuntimeLogsResponse | null;
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
  const body = await cachedGetOrNull<{
    constraints?: ConstraintView[];
    negotiation?: NegotiationView | null;
  }>(`/api/deploy/${encodeURIComponent(deploymentId)}/constraints`);
  if (!body?.constraints) return null;
  return { constraints: body.constraints, negotiation: body.negotiation ?? null };
}

export interface VerificationArtifact {
  verification: Record<string, unknown> | null;
  critic: Record<string, unknown> | null;
}

export async function fetchVerificationArtifact(
  deploymentId: string,
): Promise<VerificationArtifact | null> {
  const body = await cachedGetOrNull<{
    verification?: Record<string, unknown> | null;
    critic?: Record<string, unknown> | null;
  }>(`/api/deploy/${encodeURIComponent(deploymentId)}/verification`);
  if (body?.verification == null && body?.critic == null) return null;
  if (!body) return null;
  return { verification: body.verification ?? null, critic: body.critic ?? null };
}

export interface GraphArtifact {
  graph: { nodes: CegNode[]; edges: CegEdge[] };
  rollback: RollbackSummary | null;
}

export async function fetchGraphArtifact(deploymentId: string): Promise<GraphArtifact | null> {
  const body = await cachedGetOrNull<{
    graph?: { nodes?: CegNode[]; edges?: CegEdge[] };
    rollback?: RollbackSummary | null;
  }>(`/api/deploy/${encodeURIComponent(deploymentId)}/graph`);
  if (!body?.graph) return null;
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
  executionMode: string | null;
  runtimeLogs: RuntimeLogsResponse | null;
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
  const logsValue = logs.status === "fulfilled" ? logs.value : null;
  return {
    logs: logsValue?.lines ?? [],
    executionMode: logsValue?.execution_mode ?? null,
    runtimeLogs: logsValue?.runtime_logs ?? null,
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
  return cachedGet<ProposalsListResponse>(`/api/proposals${suffix}`);
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
  return cachedGet<ProjectsListResponse>(`/api/projects`);
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
