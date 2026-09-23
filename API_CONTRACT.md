# API_CONTRACT.md — MEDHA V1 HTTP API

Status: **Phases 10–11 IMPLEMENTED/TESTED**. Demo Mode + real local pipeline + evaluation endpoints. Docker mutate opt-in (`MEDHA_DOCKER_EXECUTE`).

Base URL (dev): `http://127.0.0.1:8000`

Content type: `application/json` unless noted (SSE is `text/event-stream`).

---

## 1. Conventions

### 1.1 Modes

| `mode` | Meaning |
|--------|---------|
| `demo` | Deterministic offline engine; all results labelled DEMO/MOCK |
| `real` | Uses git/Docker (and optional LLM mediation) |

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
| 404 | Unknown `deployment_id` |
| 409 | Illegal state transition (e.g., already terminal) |
| 422 | Pydantic validation failure |
| 500 | Unexpected server error |
| 501 | Endpoint scaffolded but behavior not implemented yet |
| 503 | Real mode requested but required dependency unavailable (Docker/git) |

### 1.3 Status values (deployment)

`queued` · `started` · `preflight` · `analyzing` · `negotiating` · `verifying` · `executing` · `rolling_back` · `succeeded` · `failed` · `cancelled`

Exact subset may grow; clients should treat unknown strings as non-terminal unless documented otherwise.

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
| `repository_url` | string (URI) | yes* | *May be ignored/fixture-driven in some demo scenarios; still accepted |
| `mode` | `"demo"` \| `"real"` | yes | |
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

- `400` unknown scenario in demo mode
- `400` real mode with non-local target host
- `503` real mode without Docker (when executor would be required immediately — may instead start and fail later with honest events; prefer fail-fast preflight)
- Phase 10–12: real mode runs analyze → CNP → verify → execute (simulator default; Docker opt-in).
  Unsupported repositories may end with `DEPLOYMENT_UNSUPPORTED`. Demo Mode remains offline fixtures.

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

- Stream starts from connection time; optional `?after=event_id` for resume (Phase 2+/3).
- Heartbeats as SSE comments (`: ping`) every N seconds.
- Terminal deployment may send a final `deployment.terminal` event then close.

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
  ]
}
```

---

## 8. Supporting endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Liveness |
| GET | `/api/demo/scenarios` | List demo scenarios |
| GET | `/api/evaluation` | Latest measured evaluation artifacts (null if not run) |
| POST | `/api/evaluation/run/cnp` | Execute CNP evaluation runner |
| POST | `/api/evaluation/run/ceg` | Execute CEG evaluation runner |
| GET | `/api/evaluation/latest/{kind}` | Fetch one artifact (`cnp`/`ceg`/`combined`) |
| POST | `/api/deploy/{id}/cancel` | Best-effort cancel (V1 best-effort only) |

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

## 10. Demo labelling rule

Whenever `mode=demo` or synthetic data is used:

- JSON includes `"is_demo": true` where a deployment context exists.
- SSE events include `"is_demo": true`.
- UI must render **DEMO MODE** (see `UI_SPEC.md`).

---

## 10. Implementation note

- **Demo Mode:** deterministic Phase 3 scenarios via `DemoRunner` (DEMO/MOCK labelled).
- **Real Mode:** analyze → specialists → CNP → verify → critic → bounded replan → execute (simulator by default) → CEG → scoped rollback on failure.
- Do **not** claim real Docker mutation unless `MEDHA_DOCKER_EXECUTE=true` and a verified plan ran against the local Docker host.
- No Redis, PostgreSQL, Kubernetes, remote deploy, or mandatory paid LLM.
