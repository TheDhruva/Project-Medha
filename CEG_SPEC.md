# CEG_SPEC.md — Causal Execution Graph + Scoped Rollback

Status: **TESTED** (Phases 8–9). Core research contribution.

CEG records causal/dependency relationships among deployment actions and drives **scoped rollback**.

---

## 1. Goal

1. Represent every meaningful deployment action as a node.
2. Capture parent/dependency edges that explain *why* an action exists.
3. On failure, compute minimal **downstream** rollback scope.
4. Preserve causally independent successful services (and successful ancestors).

---

## 2. Node Contract

Each `ExecutionNode`:

| Field | Meaning |
|-------|---------|
| `node_id` | Stable unique id (e.g. `n_backend`) |
| `action` | Verb (`create_network`, `start_container`, …) |
| `service` | Logical service name |
| `timestamp` | Last transition time |
| `status` | `pending` / `running` / `success` / `failed` / `rolled_back` / `skipped` / `preserved` |
| `parent_nodes` / `child_nodes` | Causal parents / dependents |
| `reversible` / `rollback_action` | Undo payload or unavailable |
| `metadata` | Non-secret details |

Graph is built **from `ExecutionPlan` before execution** (`build_ceg_from_plan`).

---

## 3. Edge Semantics

`depends_on`: target requires source success. Example:

```
network → database → backend → frontend
network → analytics   (independent of backend)
```

Do **not** invent edges between independent branches.

---

## 4. Failure + Scoped Rollback Algorithm

When node `F` fails:

1. Mark `F` failed; stop scheduling dependents that have not run.
2. Traverse **downstream** dependents of `F`.
3. Build `RollbackScope`: failed / affected / rollback / preserved / skipped / not_rollbackable.
4. Rollback reversible affected nodes in **reverse dependency order**.
5. Preserve successful ancestors and independent branches.
6. Do **not** roll back ancestors merely because `F` depended on them.

### Critical example

```
Network → Database → Backend → Frontend
Analytics (independent)

Backend fails → roll back Frontend
Preserve Network, Database, Analytics
```

---

## 5. RollbackScope

```json
{
  "failed_nodes": ["n_backend"],
  "affected_nodes": ["n_frontend"],
  "nodes_to_rollback": ["n_frontend"],
  "nodes_preserved": ["n_network", "n_database", "n_analytics"],
  "rationale": "…"
}
```

Non-reversible actions → recorded as `not_rollbackable` / `NOT_ROLLBACKABLE`. Rollback failures must not be reported as success (`ROLLBACK_FAILED` when applicable).

---

## 6. Execution abstraction

| Executor | Behavior |
|----------|----------|
| `SimulatorExecutor` | Deterministic in-process; default for tests + real mode unless opted in |
| `DockerExecutor` | Local Docker only; mutates only when `MEDHA_DOCKER_EXECUTE=true`; otherwise falls back to simulator |
| Demo Mode | Phase 3 `DemoRunner` fixtures (DEMO/MOCK labelled); does not use Docker |

Never execute arbitrary repo scripts / Makefiles / npm scripts outside a verified plan.

---

## 7. Events

`ceg.created`, `execution.node.started|completed|failed`, `rollback.started`, `rollback.scope_determined`, `rollback.node`, `rollback.completed`, `deployment.completed`.

---

## 8. Implementation map

| Piece | Location |
|-------|----------|
| Plan + CEG build | `backend/app/execution/plan_builder.py` |
| Executors | `backend/app/execution/executor.py` |
| Rollback | `backend/app/ceg/rollback.py` |
| Models | `backend/app/models/execution.py` |
| API | `GET /api/deploy/{id}/graph`, `/execution`, `/rollback` |
| Docker fixture | `backend/tests/fixtures/docker/` |

---

## 9. Academic honesty

MEDHA provides **deterministic conflict handling**, **pre-execution verification**, **causal dependency tracking**, and **scoped rollback with independent-branch preservation**.

Do **not** claim optimality, 100% reliability, or proven superiority over other systems. Evaluation metrics are measured separately.
