# API_CONTRACT.md — MEDHA V1 HTTP API

Status: **Phases 12–14 IMPLEMENTED/TESTED**. Real local pipeline (SHA-pinned source → CNP → verify → genuine execution) + durable jobs + incremental tiers + versioned scores + real commit history + evaluation endpoints. Demo execution removed from the product (410/404; isolated test fixtures only). Docker mutate opt-in (`MEDHA_DOCKER_EXECUTE`).

Base URL (dev): `http://127.0.0.1:8000`

Content type: `application/json` unless noted (SSE is `text/event-stream`).

---

## 1. Conventions

### 1.1 Modes

| `mode` | Meaning |
|--------|---------|
| `demo` | **Removed from the product.** `POST /api/deploy` with `mode=demo` returns `410 DEMO_REMOVED`. Historical records keep `is_demo`/`DEMO/MOCK` labels; `backend/app/demo/*` survives as isolated test fixtures only |
| `real` | Verified source analysis → CNP → verify → genuine execution (explicit simulator only in tests, isolated Docker builder otherwise) |

### 1.2 Common error shape

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Human-readable summary",
    "details": {}
  }
}
```

| HTTP | When |
|------|------|
| 400 | Invalid validation / unsupported scenario |
| 401 | Mutating route without a valid `X-Medha-Token` (when a token is configured) |
| 404 | Unknown `deployment_id` |
| 409 | Illegal state transition (e.g., already terminal) |
| 422 | Pydantic validation failure |
| 500 | Unexpected server error |
| 501 | Endpoint scaffolded but behavior not implemented yet |
| 503 | Real mode requested but required dependency unavailable (Docker/git); or production mutating route with no API token configured |

### 1.3 Status values (deployment)

`queued` · `started` · `running` · `completed` · `failed` · `partial_recovery` · `cancelled` · `awaiting_approval`

These are the `DeploymentStatus` enum values (`backend/app/core/enums.py`).
Terminal statuses are `completed`, `failed`, `partial_recovery`, `cancelled`,
`awaiting_approval` (plan-only analysis is done; a human decision is pending —
see §12). Terminal SSE event types are `deployment.completed`,
`deployment.failed`, and `proposal.ready`.
Clients should treat unknown strings as non-terminal unless documented otherwise.

---

## 2. POST `/api/deploy`

Start a deployment pipeline.

### Request

```json
{
  "repository_url": "https://github.com/example/app",
  "mode": "demo",
  "scenario": "port_conflict",
  "target": {
    "host": "localhost",
    "port": 8080
  },
  "intent": "Deploy the application securely"
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `repository_url` | string (URI) | yes* | *Demo runs (when enabled) treat this as fixture metadata only; real runs verify readability, resolve exactly one commit SHA, and analyze that snapshot |
| `mode` | `"demo"` \| `"real"` | yes | demo requires `MEDHA_ENABLE_DEMO=true`, else `403 DEMO_DISABLED` |
| `scenario` | string \| null | demo: yes | See `DEMO_MODE.md`. Ignored or null in real mode |
| `target.host` | string | yes | V1: `localhost` / `127.0.0.1` only |
| `target.port` | integer | yes | Desired primary publish port |
| `intent` | string | no | Free-text operator intent; not chain-of-thought |

Scenario enum (canonical):

- `SUCCESSFUL_DEPLOYMENT`
- `PORT_CONFLICT`
- `SECURITY_CONFLICT`
- `VERIFICATION_FAILURE`
- `PARTIAL_FAILURE`

API may accept case-insensitive aliases (`port_conflict` → `PORT_CONFLICT`).

### Response `202 Accepted` (preferred) or `200 OK`

```json
{
  "deployment_id": "dep_01HZX...",
  "status": "started",
  "mode": "demo",
  "is_demo": true
}
```

### Errors

- `410 DEMO_REMOVED` for `mode=demo` (demo execution removed from the product)
- `422` for malformed `base_revision`/`target_revision` (must be 40-hex SHA or omitted)
- `400` real mode with non-local target host
- `503` real mode without Docker (when executor would be required immediately — may instead start and fail later with honest events; prefer fail-fast preflight)
- Real mode runs analyze → CNP → verify → execute (explicit simulator in tests only, otherwise `EXECUTION_NOT_CONFIGURED` without an isolated builder; Docker opt-in).
  Unsupported repositories end with `DEPLOYMENT_UNSUPPORTED`. `base_revision`/`target_revision` accept only exact 40-hex SHAs or null (server resolves HEAD).

---

## 3. GET `/api/deploy/{id}`

Fetch deployment snapshot.

### Response `200`

```json
{
  "deployment_id": "dep_01HZX...",
  "status": "negotiating",
  "mode": "demo",
  "is_demo": true,
  "scenario": "PORT_CONFLICT",
  "repository_url": "https://github.com/example/app",
  "target": { "host": "localhost", "port": 8080 },
  "intent": "Deploy the application securely",
  "created_at": "2026-09-03T04:50:00Z",
  "updated_at": "2026-09-03T04:50:12Z",
  "result": null,
  "error_summary": null
}
```

When finished, `result` may embed a `DeploymentResult` summary (see `DATA_MODEL.md`).

---

## 4. GET `/api/deploy/{id}/events`

Server-Sent Events stream of `SystemEvent` objects.

### Headers

- `Accept: text/event-stream`
- Response: `Content-Type: text/event-stream`

### Event payload

Each SSE `data:` line is JSON:

```json
{
  "event_id": "evt_123",
  "deployment_id": "dep_01HZX...",
  "ts": "2026-09-03T04:50:12Z",
  "stage": "cnp",
  "type": "constraint.conflict_detected",
  "level": "info",
  "message": "Port 8080 claimed by docker and nginx",
  "is_demo": true,
  "data": {
    "constraint_ids": ["c_port_docker", "c_port_nginx"]
  }
}
```

### Behavior

- Stream replays persisted events first, then live events (no `?after=` resume).
- Heartbeats as SSE comments (`: ping`) after 15s without events.
- Terminal `deployment.completed` / `deployment.failed` event ends the stream.

### Errors

- `404` unknown id (before upgrading to stream)
- Non-SSE clients should use polling via GET deploy + logs instead

---

## 5. GET `/api/deploy/{id}/constraints`

Return constraint set + negotiation summary.

### Response `200`

```json
{
  "deployment_id": "dep_01HZX...",
  "is_demo": true,
  "constraints": [],
  "negotiation": {
    "rounds_used": 1,
    "max_rounds": 3,
    "status": "resolved",
    "conflicts_resolved": [],
    "resolution_methods": []
  }
}
```

Shapes follow `Constraint`, `ConstraintSet`, `NegotiationResult` in `DATA_MODEL.md` / `CNP_SPEC.md`.

If negotiation not started: empty constraints, `negotiation.status = "pending"`.

---

## 6. GET `/api/deploy/{id}/graph`

Return Causal Execution Graph snapshot.

### Response `200`

```json
{
  "deployment_id": "dep_01HZX...",
  "is_demo": true,
  "graph": {
    "nodes": [],
    "edges": []
  },
  "rollback": null
}
```

See `ExecutionGraph`, `ExecutionNode`, `RollbackScope`.

---

## 7. GET `/api/deploy/{id}/logs`

Return aggregated structured log lines (not raw Docker multiplex blobs by default).

### Query

| Param | Type | Notes |
|-------|------|-------|
| `limit` | int | default 200, max 2000 |
| `since` | ISO timestamp \| event_id | optional |

### Response `200`

```json
{
  "deployment_id": "dep_01HZX...",
  "is_demo": true,
  "lines": [
    {
      "ts": "2026-09-03T04:50:12Z",
      "level": "info",
      "source": "mediator",
      "message": "Conflict resolved by RESOURCE priority",
      "is_demo": true
    }
  ],
  "agents": [
    {
      "id": "mediator",
      "name": "Mediator",
      "status": "complete",
      "activity": "Constraint set accepted as proposed",
      "lastEvent": "Constraint set accepted as proposed",
      "durationMs": 12.4,
      "startedAt": "2026-09-03T04:50:11Z",
      "finishedAt": "2026-09-03T04:50:12Z",
      "deps": ["docker", "nginx", "security"]
    }
  ]
}
```

`agents` is the latest backend agent lifecycle snapshot (10 stable rows;
`status` ∈ `idle|running|complete|failed|skipped|cancelled|timed_out`;
`durationMs` measured server-side). `null` when no event carried a snapshot
yet — the UI must render unknown/pending, never infer activity. No secrets,
tokens, or repository contents appear in this surface.

---

## 8. Supporting endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness (includes DB reachability) |
| GET | `/api/evaluation` | Latest measured evaluation artifacts (null if not run) |
| POST | `/api/evaluation/run/cnp` | Execute CNP evaluation runner (token-guarded) |
| POST | `/api/evaluation/run/ceg` | Execute CEG evaluation runner (token-guarded) |
| GET | `/api/evaluation/latest/{kind}` | Fetch one artifact (`cnp`/`ceg`/`combined`) |
| GET | `/api/deploys` | List runs (`status`, `mode`, `repository`, `project_id`, `limit`, `offset`); each summary carries `error_code` when the stored result has a structured failure/block code (e.g. `EXECUTION_NOT_CONFIGURED`) |
| GET | `/api/deploy/{id}/verification` | Stored verification + critic artifacts |
| GET | `/api/deploy/{id}/rollback` | Stored rollback scope |
| GET | `/api/deploy/{id}/execution` | Stored result + graph + rollback |
| GET | `/api/deploy/{id}/scores` | Four versioned evidence-backed scores (`scores-v1`; §18) |
| GET | `/api/scores/history` | Score history by `run_id` or `project_id` (§18) |
| GET | `/api/deploy/{id}/health` | Observed runtime health (live probe; `healthy` only on evidence, else `unhealthy`/`unknown`/`test_only`/`demo`) |
| GET | `/api/config/status` | Presence-only environment diagnostics (booleans, never secret values) + structured `execution_readiness` (`status`/`reason_code`/`message`/`next_actions`/restart & operator flags; §17) |
| GET | `/api/metrics` | Safe operational counters + LLM budgets (no secrets/source) |
| GET | `/api/ai/status` | Safe AI provider status (no secrets; §11) |
| POST | `/api/webhooks/github` | GitHub push receiver (HMAC-SHA256; full 40-hex SHA required; §12) |
| GET | `/api/proposals` | List approval proposals (§12) |
| GET | `/api/proposals/{id}` | One proposal with plan + hash |
| POST | `/api/proposals/{id}/approve` | Approve + revalidated execution (token-guarded; §12) |
| POST | `/api/proposals/{id}/reject` | Reject a ready proposal (token-guarded; §12) |
| POST | `/api/projects` | Connect a GitHub repo as an owner-scoped project (§13) |
| GET | `/api/projects` | List the caller's projects (§13) |
| GET | `/api/projects/{id}` | One project (owner only; §13) |
| PATCH | `/api/projects/{id}` | Rename / change watched branch (§13) |
| POST | `/api/projects/{id}/verify` | Prove readability via `git ls-remote` (§13) |
| GET | `/api/projects/{id}/history` | Real Git commit ancestry, paginated (§19) |
| GET | `/api/projects/{id}/history/{sha}` | Commit diff summary + GitHub link (§19) |
| POST | `/api/projects/{id}/disconnect` | Stop routing webhooks/runs (§13) |
| DELETE | `/api/projects/{id}` | Remove the mapping; history preserved (§13) |
| POST | `/api/projects/{id}/runs` | Start a project-bound real analysis (§13) |

Real mode may return `409 DEPLOYMENT_BUSY` when another real deployment is running.
Unsupported repositories may fail with `DEPLOYMENT_UNSUPPORTED` / `PLAN_REQUIRES_REVIEW`.

---

## 9. Phase 12 (2) — Change Intelligence endpoints

Deterministic change-impact analysis over a local git repository
(`CIG_SPEC.md`). All three endpoints return a top-level object with
`deployment_id`, `is_demo`, `label` (always `"DEMO/MOCK"` for mock fixtures),
optional `generated_at` / `note`, and `analysis` (the to_ui change-impact
payload: `changeset`, `changed_symbols`, `graph`, `traversal`, `unresolved`,
`risk`, `requirements`).

### 9.1 POST `/api/change-impact/analyze`

**Request**

```json
{
  "repository_url": "C:/src/sample-app",
  "base_revision": "base",
  "target_revision": "target",
  "deployment_id": null
}
```

- `repository_url` — local path or `file://` URL (remote URLs rejected, V1).
- `deployment_id` — optional; when set and the deployment exists, the analysis
  is persisted onto it (`deployments.change_intel_json`).

**Response `200`** — `analysis` incl. `graph.nodes`, `graph.edges` (each edge
has `relationship`, `confidence`, `evidence`), `risk.level`, `requirements[]`.

**Errors** (`{"error": {"code", "message", "details"}}`):

| Code | HTTP | Meaning |
|------|------|---------|
| `NOT_A_GIT_REPOSITORY` | 400 | Path exists but is not a git repo |
| `NOT_LOCAL_REPOSITORY` | 400 | Remote URL in V1 |
| `REPO_NOT_FOUND` | 400 | Local path does not exist |
| `REVISION_INVALID` | 400 | Revision string cannot be resolved by git |
| `REVISION_NOT_FOUND` | 400 | Revision does not exist in repo |
| `IDENTICAL_REVISIONS` | 400 | base == target, nothing to analyse |
| `GIT_COMMAND_FAILED` / `GIT_TIMEOUT` / `GIT_UNAVAILABLE` | 500 | Git tooling failed |
| `NOT_FOUND` | 404 | `deployment_id` unknown |

### 9.2 GET `/api/deploy/{id}/change-impact`

Persisted analysis attached to a deployment (set by `POST` with
`deployment_id`, or during the real pipeline's ANALYZE stage).

- `200` with the stored analysis (`is_demo` + `label` preserved).
- `404 NOT_FOUND` unknown deployment; `404 CHANGE_INTEL_NOT_FOUND` when the
  deployment has none.

### 9.3 GET `/api/change-impact/demo/fixture`

Canned demo fixture: `is_demo: true`, `label: "DEMO/MOCK"`, `note` stating the
data is canned (not derived from a real repository). Deterministic, offline.

### 9.4 SSE integration

The real pipeline emits a `system.message` during ANALYZE whose `data.change_intel`
carries the full to_ui payload (see §4 event `data`). Remote URLs and missing
revisions are skipped honestly (event level `info`/`warning`, `change_intel`
absent) — the UI never sees fabricated evidence.

---

## 11. AI provider status

`GET /api/ai/status` returns safe configuration + health metadata only:

```json
{
  "enabled": false,
  "primary_provider": "groq",
  "fallback_provider": "gemini",
  "primary_model": "openai/gpt-oss-20b",
  "fallback_model": "gemini-3.8-flash",
  "max_calls_per_run": 6,
  "health": {
    "enabled": false,
    "providers": {
      "groq": {"configured": false, "model": null, "reachable": false,
               "latency_s": 0.0, "failure_category": "not_configured"},
      "gemini": {"configured": false, "model": null, "reachable": false,
                 "latency_s": 0.0, "failure_category": "not_configured"}
    }
  }
}
```

Never includes keys, tokens, request bodies, or upstream error text.
Per-run AI metadata (`outcome`, `provider`, `model`, `fallback_used`,
`duration_s`, `failure_category`, `schema_valid`) is stored on the deployment
record (`ai`) and summarized in `GET /api/deploys` as `ai_outcome`/`ai_provider`.

---

## 12. Webhook + approval proposals

Authenticated by the GitHub webhook secret (`GITHUB_WEBHOOK_SECRET`,
HMAC-SHA256 over the raw body, constant-time compare) — independent of Clerk
sessions. Unset secret → `503 WEBHOOK_NOT_CONFIGURED`. Only `push` events to
watched branches (`MEDHA_WEBHOOK_BRANCHES`, default `main`) are processed.
Branch deletions (null SHA) and non-push events are recorded and ignored.
Duplicate `X-GitHub-Delivery` IDs return
`{"status": "duplicate"}` without side effects.

**Project routing (§13):** a signed push must resolve to at least one
*connected* project watching the pushed branch. Once any project exists, pushes
for unmapped/disconnected repositories are ignored (`no connected project`) —
an unauthenticated endpoint must not analyze arbitrary repositories. With zero
projects configured, the legacy server allowlist applies
(`MEDHA_WEBHOOK_ALLOWED_REPOS`; empty fails closed in production).

**Exact-commit binding:** the verified `after` SHA is checked out in an
isolated workspace (`git fetch` + detached checkout) and `HEAD` is asserted
equal before analysis; mismatch fails closed (`SHA_MISMATCH`/`GIT_CLONE_FAILED`
→ proposal `failed`). The payload's `commits[]` file lists become
payload-derived change intelligence (`source_method=webhook_push`), verified
file-by-file against the checkout.

`POST /api/webhooks/github` → `202 {"status": "analyzing", "proposal_id",
"deployment_id"}` (or `"proposals": [...]` when several connected projects
watch the same repository). Analysis runs plan-only: on success the deployment
reaches `awaiting_approval` and the proposal `ready` with `plan_hash` (SHA-256
over the canonical plan) plus the stored `push` summary. `proposal.ready` is a
terminal SSE event for that stream.

`POST /api/proposals/{id}/approve` (token-guarded; Clerk subject in `clerk`
mode) requires `ready` status, project-owner match for project-bound proposals
(foreign-owner → `403`), a still-`connected` project watching the same
repository/branch/URL, an `awaiting_approval` deployment, and an exact
`target_sha` + recomputed-plan-hash match — otherwise `409 STALE_PROPOSAL`
and the proposal is marked `stale`. Approval re-runs the deterministic
pipeline with `expected_plan_hash`; any drift fails closed (`STALE_PLAN`)
before execution. Replayed approvals return the current state
(`duplicate: true`) without executing twice.
`POST /api/proposals/{id}/reject` closes a ready proposal without execution.

`GET /api/proposals` accepts `project_id` (owner-checked) and never leaks
another owner's project-bound proposals; `GET /api/deploys` accepts
`project_id` likewise. Startup recovery fails orphaned `queued/started/running`
deployments and pre-`ready` proposals closed (`failed` + terminal event);
`ready` proposals and their plans survive restarts unchanged.

---

## 13. Project-scoped repository connections

Any signed-in owner can connect their own eligible GitHub repositories —
no founder-edited global allowlist per project. All endpoints require the
Clerk subject (or the legacy single-operator subject); all rows carry
`owner_sub` and cross-owner access returns `404` (no existence oracle).

- `POST /api/projects` `{repository, name?, branch?}` — `repository` accepts
  `owner/name` or a `github.com` URL (anything else → `400
  NON_GITHUB_REPOSITORY` / `INVALID_REPOSITORY_REF`). `name` defaults to the
  repository name; `branch` defaults to the remote default branch
  (`ls-remote --symref`, falling back to `main`). Stores configuration
  only (`pending`/`unverified`) — never credentials, never proof of access.
  Duplicate `(owner, repository)` → `409 PROJECT_EXISTS`. → `201` project.
- `GET /api/projects` — caller's projects only. `GET /api/projects/{id}` —
  one project. `PATCH /api/projects/{id}` — rename / change branch.
- `POST /api/projects/{id}/verify` — bounded `git ls-remote HEAD`:
  reachable → `connected`/`public` (+ `head_sha`); otherwise `failed`/
  `unverified` with an honest reason. Private repositories are reported as
  unsupported (GitHub App required — not implemented) and stay unconnected.
- `POST /api/projects/{id}/disconnect` — stops webhook routing and project
  runs (`disconnected`). `DELETE /api/projects/{id}` — removes the mapping;
  run/proposal history is preserved but no longer routable. Deletion is
  refused with `409 ACTIVE_RUNS` while a run is in flight.
- `POST /api/projects/{id}/runs` `{intent?, base_revision? (40-hex),
  target_revision? (40-hex), target_host?, target_port?}` — starts a
  real-mode analysis bound to the project (`connected` required, else
  `409 PROJECT_NOT_CONNECTED`). Omitting both revisions runs a full
  analysis of the project's current HEAD; when given, revisions must be
  exact 40-hex SHAs (`400 INVALID_SHA`) and `target_revision` is checked
  out exactly (see §12).

---

## 16. Historical demo labelling rule

Demo execution is removed from the product, but historical records keep
their provenance:

- Historical JSON includes `"is_demo": true` + `"label": "DEMO/MOCK"`.
- Historical SSE payloads include `"is_demo": true`.
- UI renders historical runs with DEMO badges (see `UI_SPEC.md`); it never
  creates new demo runs.

---

## 17. Implementation note

- **Demo:** removed from product routes (`410 DEMO_REMOVED` / 404).
  `backend/app/demo/*` survives as isolated test fixtures only.
- **Real Mode:** analyze (SHA-pinned source) → specialists → CNP → verify → critic → bounded replan → execute (explicit simulator in tests, isolated `RealExecutor` with supported profiles otherwise; unconfigured execution fails closed) → CEG → scoped rollback on failure. Plans contain exactly the discovered topology — no synthetic services.
- Do **not** claim real Docker mutation unless `MEDHA_DOCKER_EXECUTE=true` and a verified plan ran against the local Docker host.
- No Redis, Kubernetes, remote deploy, or mandatory paid LLM. PostgreSQL
  (Supabase) is the configured persistent backend when `MEDHA_DATABASE_URL`
  is set; SQLite remains the zero-config fallback.

---

## 18. Scores (`scores-v1`)

`GET /api/deploy/{id}/scores` computes four deterministic scores from stored
evidence and persists snapshots: `deployment_readiness`, `performance`,
`optimization`, `security`. Higher always means better. Missing evidence
yields `value: null` (unmeasured), never success. Each entry carries
`version`, `computed_at`, `inputs_hash`, `target_sha`, and `evidence`.
`GET /api/scores/history?run_id=…&project_id=…` queries snapshots.

## 19. Commit history

`GET /api/projects/{id}/history?limit=&since=` returns real Git ancestry
(`sha`, `parents`, `author`, `committed_at`, `message`, `github_url`),
`partial`/`shallow` flags when history is bounded. Detail endpoint adds
per-file added/deleted counts. CIG (dependency impact) and CEG (execution
causality) remain distinct graphs with their own evidence.
