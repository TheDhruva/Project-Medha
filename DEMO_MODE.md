# DEMO_MODE.md — Deterministic Demo Contract

Status: **IMPLEMENTED (Phase 3)** and **regression-tested through Phases 7–9**. Demo Mode remains labelled DEMO/MOCK. Real mode also runs verify/execute/CEG via `SimulatorExecutor` (separate from this fixture engine).

Demo Mode is **mandatory** (ADR-007). It guarantees MEDHA can be demonstrated when external dependencies are unavailable.

---

## 1. Guarantees

Demo Mode must work **without**:

- GitHub / git remotes
- Docker
- External LLM
- Internet
- Cloud infrastructure
- Redis / PostgreSQL

It uses fixtures + deterministic event sequences inside the FastAPI process.

> **Demo Mode simulates deployment behavior and is not evidence of real infrastructure execution.**

---

## 2. Labelling (non-negotiable)

| Surface | Requirement |
|---------|-------------|
| UI | Persistent **DEMO MODE** indicator |
| API JSON | `"is_demo": true` (+ `"label": "DEMO/MOCK"` where present) |
| SSE events | `"is_demo": true` |
| Results | Explicit DEMO/MOCK labelling; never look like silent real success |

Simulated execution must **never** be presented as real execution.

---

## 3. Scenarios

Canonical ids (implemented in `backend/app/demo/`):

| Scenario | What it demonstrates | Terminal status |
|----------|----------------------|-----------------|
| `SUCCESSFUL_DEPLOYMENT` | Happy path; all services succeed; no conflict/rollback | `completed` / SUCCESS |
| `PORT_CONFLICT` | Same-priority PORT_CLAIM on `host:8080`; alternative → `8081` for Nginx | `completed` / SUCCESS |
| `SECURITY_CONFLICT` | SECURITY > PREFERENCE; unrestricted access rejected | `completed` / SUCCESS |
| `VERIFICATION_FAILURE` | Missing `DATABASE_URL` → fail → replan round 1 → pass → execute | `completed` / SUCCESS |
| `PARTIAL_FAILURE` | Backend fails; Frontend rolled back; Network/Database/Analytics preserved | `partial_recovery` / PARTIAL_FAILURE |

Aliases: API may accept lowercase/`port_conflict` forms; store canonical uppercase.

Repeating the same scenario yields the same structured outcome (deterministic fixtures).

---

## 4. Pipeline shape

Demo scenarios emit the **same stage names** as real mode so the UI stays unified:

`PREFLIGHT → ANALYZE → PLAN → AGENTS → NEGOTIATE → VERIFY → EXECUTE → (RECOVER?) → COMPLETE`

Internal actions are mocked. Delays are fixed (configurable via `MEDHA_WORKFLOW_STEP_DELAY_SECONDS`; tests set `0`).

Typical full run: roughly **5–20 seconds** with default delays.

---

## 5. Implementation layout (Phase 3)

```
backend/app/demo/
  models.py      # DemoStep / DemoScenarioDef / DemoArtifacts
  fixtures.py    # Shared constraints, graphs, results
  scenarios.py   # Five deterministic step sequences
  runner.py      # DemoRunner → persist + SSE via EventBus
```

`POST /api/deploy` with `mode=demo` schedules `DemoRunner` (no git/Docker/LLM).

REST artifacts after/during run:

- `GET /api/deploy/{id}/constraints`
- `GET /api/deploy/{id}/graph`
- `GET /api/deploy/{id}/verification`
- `GET /api/demo/scenarios`

---

## 6. Event flow

Important event types (all with `is_demo: true`):

- `deployment.created` / `deployment.started` / `deployment.completed` / `deployment.failed`
- `stage.started` / `stage.completed`
- `constraint.published` / `constraint.conflict`
- `negotiation.started` / `negotiation.resolved`
- `verification.failed` / `verification.passed` / `replan.started`
- `execution.service_status` / `execution.failed`
- `rollback.started` / `rollback.node` / `rollback.completed`

UI explanations come from observable `message` + `data.simple` / `data.technical` — **not** fake chain-of-thought.

---

## 7. Interaction with real mode

| | Demo | Real |
|--|------|------|
| Start API | `mode=demo` + `scenario` | `mode=real` (Phase 3: rejected) |
| External deps | None | Git + Docker (+ optional LLM) |
| Failure honesty | Scripted fixtures | Actual subsystem results |
| Label | DEMO/MOCK | Not demo |

---

## 8. How to run Demo Mode

1. Start backend: `cd backend && .venv\Scripts\uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
2. Start frontend: `cd frontend && npm run dev`
3. Open `http://localhost:3000`
4. Select a scenario → **Start deployment**
5. Watch live SSE updates in Pipeline / Agents / CNP / Verification / CEG / Result / Trace

No API keys required.

---

## 9. Limitations (honest)

- CNP is **fixture-driven** in Demo Mode (real mode uses the Phase 6 engine).
- CEG rollback in Demo Mode is a **scripted dependency graph**; real mode uses the Phase 8–9 algorithm (`SimulatorExecutor` / optional Docker).
- No real Docker/network/port checks occur.
- No LLM is called; do not claim “LLM decided…”.

Later phases may replace fixtures with real components without changing the API/UI contracts.

---

## 10. Acceptance for Phase 3

- [x] All five scenarios run offline
- [x] SSE updates UI live
- [x] DEMO badge / `is_demo` always present
- [x] Terminal states match scenario intent
- [x] Deterministic repeats
- [x] No GitHub/Docker/LLM required
