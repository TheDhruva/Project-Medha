# DATA_MODEL.md — MEDHA Conceptual Schemas

Status: **IMPLEMENTED** through Phases 7–9 (`backend/app/models/domain.py`, `backend/app/models/execution.py`). SQLite persists deployment artifacts as JSON columns.

Conventions:

- `id` strings use opaque prefixed IDs (`dep_`, `c_`, `n_`, `evt_`).
- Timestamps are UTC ISO-8601.
- `is_demo: bool` marks synthetic/demo provenance where relevant.
- Required fields are marked **R**; optional **O**.

---

## Entity Relationship (conceptual)

```
DeploymentRequest
       │
       ▼
 Deployment (runtime record)
       │
       ├─► TaskSpecification ─► InferredStack
       ├─► AgentResult[]
       ├─► ConstraintSet ─► Constraint[]
       ├─► NegotiationResult
       ├─► VerificationResult
       ├─► CriticResult
       ├─► ExecutionGraph ─► ExecutionNode[]
       ├─► RollbackScope?
       ├─► DeploymentResult
       └─► SystemEvent[]
```

---

## DeploymentRequest

**Purpose:** API input to start a pipeline.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `repository_url` | string | R | URI |
| `mode` | enum(`demo`,`real`) | R | |
| `scenario` | enum \| null | O | Required when `mode=demo` |
| `target` | TargetRef | R | |
| `intent` | string | O | Operator intent |

`TargetRef`: `{ host: string, port: int }` — V1 host must be local.

**Lifecycle:** Created at API edge → validated → persisted as deployment seed.

---

## TaskSpecification

**Purpose:** Normalized deployment task derived from request + analysis.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `task_id` | string | R | |
| `deployment_id` | string | R | |
| `repository_url` | string | R | |
| `intent` | string | O | |
| `target` | TargetRef | R | |
| `mode` | enum | R | |
| `scenario` | enum \| null | O | |
| `inferred_stack` | InferredStack \| null | O | Filled after analysis |
| `created_at` | datetime | R | |

**Lifecycle:** Draft after accept → enriched by Code Analyzer → immutable inputs for specialists.

---

## InferredStack

**Purpose:** Manifest-based stack guess.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `services` | ServiceHint[] | R | May be empty if unknown |
| `language_runtime` | string \| null | O | e.g. `node`, `python` |
| `has_dockerfile` | bool | R | |
| `has_compose` | bool | R | |
| `package_managers` | string[] | R | |
| `suggested_ports` | int[] | O | |
| `confidence` | float | O | 0–1 |
| `manifests_examined` | string[] | R | Paths |
| `notes` | string[] | O | Human-readable, not CoT |
| `framework` / `framework_version` | string \| null | O | Detected framework + version hint |
| `lockfiles` | string[] | O | Detected lockfiles |
| `entry_points` | string[] | O | Build/start commands with provenance |
| `env_names` | string[] | O | Variable names only, never values |
| `health_hints` | string[] | O | HEALTHCHECK / health script hints |
| `app_candidates` | string[] | O | Monorepo deployable candidates |
| `ci_configs` | string[] | O | CI workflow files (bounded scan) |
| `test_suites` | string[] | O | Detected test files (bounded scan) |
| `auth_hints` | string[] | O | Auth-sensitive modules (names only) |
| `openapi_hints` | string[] | O | OpenAPI/Swagger references |
| `db_hints` | string[] | O | Migration/schema hints |
| `perf_notes` | string[] | O | Explicit measurement gaps / scan caps |
| `source_file_count` / `source_bytes_approx` | int \| null | O | Processing-budget accounting |

`ServiceHint`: `{ name, role, evidence_paths[] }`

**Lifecycle:** Produced by Code Analyzer; consumed by specialists.

---

## AgentResult

**Purpose:** Uniform envelope for logical agent outputs.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `agent` | enum | R | One of the 10 logical agents |
| `ok` | bool | R | |
| `started_at` | datetime | R | |
| `finished_at` | datetime | R | |
| `summary` | string | R | Observable reason |
| `artifacts` | object | O | Config fragments, etc. |
| `constraints` | Constraint[] | O | Published constraints |
| `errors` | string[] | O | |
| `is_demo` | bool | R | |

**Lifecycle:** Append-only per stage; stored with deployment.

---

## Constraint

**Purpose:** Typed infrastructure claim/requirement for CNP.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `constraint_id` | string | R | |
| `type` | ConstraintType | R | See below |
| `priority` | Priority | R | SECURITY/RESOURCE/DEPENDENCY/PREFERENCE |
| `source_agent` | string | R | |
| `service` | string \| null | O | Affected service |
| `payload` | object | R | Type-specific |
| `alternatives` | object[] | O | Suggested alternatives |
| `status` | enum | R | `proposed`/`accepted`/`rejected`/`superseded` |
| `is_demo` | bool | R | |

**ConstraintType (V1):**

- `PORT_CLAIM`
- `ENV_VAR`
- `VOLUME_MOUNT`
- `NETWORK_POLICY`
- `SECURITY_POLICY`
- `EXEC_ORDER`

**Lifecycle:** Proposed by specialists → negotiated → accepted/rejected.

---

## ConstraintSet

**Purpose:** Snapshot of constraints for a deployment at a point in time.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `deployment_id` | string | R | |
| `constraints` | Constraint[] | R | |
| `version` | int | R | Increments each apply |
| `updated_at` | datetime | R | |

**Relationships:** Input/output of CNP rounds.

---

## NegotiationResult

**Purpose:** Outcome of CNP for a deployment.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `deployment_id` | string | R | |
| `status` | enum | R | `pending`/`resolved`/`failed`/`exhausted` |
| `rounds_used` | int | R | ≤ `max_rounds` |
| `max_rounds` | int | R | V1 = 3 |
| `conflicts` | ConflictRecord[] | R | |
| `decisions` | DecisionRecord[] | R | |
| `final_constraints` | Constraint[] | O | Present if resolved |
| `is_demo` | bool | R | |

`ConflictRecord`: `{ conflict_id, constraint_ids[], reason, priority_span }`  
`DecisionRecord`: `{ conflict_id, method, winner_ids[], loser_ids[], rationale }`  
`method`: `priority` | `alternative` | `deterministic_tiebreak` (V1 has no LLM-mediation path)

**Lifecycle:** Updated each CNP round; terminal when resolved/failed/exhausted.

---

## VerificationResult

**Purpose:** Hard checks before execution.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `deployment_id` | string | R | |
| `passed` | bool | R | |
| `checks` | CheckResult[] | R | |
| `blocking_failures` | string[] | R | |
| `finished_at` | datetime | R | |
| `is_demo` | bool | R | |

`CheckResult`: `{ check_id, name, passed, severity, message, data? }`

**Lifecycle:** Produced by Verifier; gate for Executor.

---

## CriticResult

**Purpose:** Quality critique; may warn or block per policy.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `deployment_id` | string | R | |
| `score` | float | R | 0–100 |
| `verdict` | enum | R | `pass`/`warn`/`block` |
| `findings` | Finding[] | R | |
| `summary` | string | R | |
| `finished_at` | datetime | R | |
| `is_demo` | bool | R | |

`Finding`: `{ id, category, severity, message, related_constraint_ids[] }`

**Lifecycle:** After or with verification; before execution.

---

## ExecutionNode

**Purpose:** Single CEG node for a meaningful action.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `node_id` | string | R | |
| `action` | string | R | e.g. `create_network` |
| `service` | string \| null | O | |
| `timestamp` | datetime | R | |
| `status` | enum | R | `pending`/`running`/`succeeded`/`failed`/`rolled_back`/`skipped` |
| `parent_nodes` | string[] | R | Causal parents |
| `metadata` | object | O | |
| `reversible_action` | object \| null | O | Enough to undo |
| `is_demo` | bool | R | |

**Lifecycle:** Created pending → running → terminal status; may later become `rolled_back`.

---

## ExecutionGraph

**Purpose:** Full CEG for a deployment.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `deployment_id` | string | R | |
| `nodes` | ExecutionNode[] | R | |
| `edges` | Edge[] | R | Derived or explicit |
| `updated_at` | datetime | R | |
| `is_demo` | bool | R | |

`Edge`: `{ from_node_id, to_node_id, relation: "causal"|"depends_on" }`

**Relationships:** Source of truth for rollback scope.

---

## RollbackScope

**Purpose:** Computed set of nodes to undo after failure.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `deployment_id` | string | R | |
| `failed_node_id` | string | R | |
| `nodes_to_rollback` | string[] | R | Reverse-exec order |
| `nodes_preserved` | string[] | R | Independent successes |
| `rationale` | string | R | Observable explanation |
| `is_demo` | bool | R | |

**Lifecycle:** Computed on failure → applied by Rollback Agent → summarized in result.

---

## DeploymentResult

**Purpose:** Terminal summary for UI/API.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `deployment_id` | string | R | |
| `final_status` | enum | R | `succeeded`/`failed`/`cancelled` |
| `services` | ServiceOutcome[] | R | |
| `negotiation_summary` | object | O | |
| `verification_passed` | bool \| null | O | |
| `critic_score` | float \| null | O | |
| `rollback` | RollbackScope \| null | O | |
| `message` | string | R | |
| `is_demo` | bool | R | |

`ServiceOutcome`: `{ name, status, endpoint? }`

---

## SystemEvent

**Purpose:** Live observable event for SSE/UI/logs.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `event_id` | string | R | |
| `deployment_id` | string | R | |
| `ts` | datetime | R | |
| `stage` | string | R | e.g. `preflight`,`cnp`,`execute` |
| `type` | string | R | Machine-readable |
| `level` | enum | R | `debug`/`info`/`warn`/`error` |
| `message` | string | R | Human-readable |
| `data` | object | O | Structured details |
| `is_demo` | bool | R | |

**Lifecycle:** Append-only; streamed via SSE; optionally persisted.

---

## Persistence Notes (V1)

SQLite tables (Postgres mirrors in `schema_pg.sql`) map closely to:

- `deployments` (+ `owner_sub`, `project_id`, JSON artifact columns)
- `events` (persisted `system_events`)
- `users` (`clerk_sub`, audit timestamps)
- `webhook_deliveries` (delivery-ID idempotency)
- `proposals` (+ `project_id`, `push_json` push-evidence summary)
- `projects` (owner-scoped repo connections; see below)
- `jobs` (durable analysis jobs: delivery, repo/branch, base/target SHA,
  branch `seq`, status `queued|running|succeeded|failed|cancelled|superseded|dead_letter`,
  attempts/backoff; schema v8)
- `commits` (commit history metadata per project + SHA)
- `scores` (versioned score snapshots per run + score name, with inputs hash)
- `analysis_cache` (repository-inventory reuse keyed by commit + target +
  scanner configuration + installed-tool signature; failed payloads never
  stored)
- `findings` (cross-run finding ledger: sha256 fingerprint identity,
  lifecycle `status` + `verification_status`, first/last seen SHA,
  observation `evidence` and transition `history` JSON; schema v11)

No Redis caches required for correctness.

## Project (repository connection)

**Purpose:** one owner's view of one GitHub repository + watched branch.
The unit of multi-user isolation; webhook routing key.

| Field | Type | R/O | Notes |
|-------|------|-----|-------|
| `project_id` | string | R | `prj_` prefixed |
| `owner_sub` | string | R | Verified Clerk `sub` (or `local-operator`) |
| `name` | string | R | Display name |
| `provider` | string | R | `github` (V1) |
| `repo_owner` / `repo_name` | string | R | Original case |
| `repository` | string | R | Lowercased `owner/name` (routing key) |
| `canonical_url` | string | R | `https://github.com/owner/name.git` |
| `branch` | string | R | Watched branch (default `main`) |
| `visibility` | enum | R | `unverified` / `public` / `private_unsupported` |
| `connection_status` | enum | R | `pending` / `connected` / `failed` / `disconnected` |
| `deploy_target` | string? | R | Saved single-service target (repo-relative path, `"."` = detected root app; NULL = auto-resolve) |

UNIQUE(`owner_sub`, `repository`). No credentials stored — ever.
