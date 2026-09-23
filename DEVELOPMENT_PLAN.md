# DEVELOPMENT_PLAN.md — MEDHA Phases 0–12

Status labels refer to the **phase work**, not the whole product.

Rule: implement **only** the current phase. Each phase must leave the project runnable (or document a temporary blocker). Do not start Phase N+1 until Phase N acceptance criteria pass unless explicitly directed.

---

## PHASE 0 — Architecture + Project Contracts

**Status:** IN DEVELOPMENT → docs complete this phase.

### Objective
Establish architecture, contracts, directory structure, rules, and technical specifications. No MEDHA runtime features.

### Components
- Root documentation set
- Empty `frontend/`, `backend/`, `tests/`, `docs/` scaffolds
- `.env.example`, `.gitignore`, `AGENTS.md`

### Files likely involved
`README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `PROJECT_SCOPE.md`, `DEVELOPMENT_PLAN.md`, `API_CONTRACT.md`, `DATA_MODEL.md`, `CNP_SPEC.md`, `CEG_SPEC.md`, `VERIFICATION_SPEC.md`, `DEMO_MODE.md`, `UI_SPEC.md`, `DECISIONS.md`, `docs/**`

### Dependencies
None (documentation only).

### Acceptance criteria
- [x] Architecture diagram and agent list documented
- [x] CNP and CEG contracts written
- [x] API and data model contracts written
- [x] Demo Mode and UI specs written
- [x] ADRs recorded
- [x] V1 in/out of scope consistent
- [x] No premature runtime implementation

### Testing requirements
Manual consistency review of docs (no automated tests required).

### Must NOT implement yet
Any real UI, FastAPI routes, LangGraph graphs, Docker, CNP/CEG code, auth, Redis, Postgres, K8s, DNS, CI/CD.

---

## PHASE 1 — Bright Mode UI

**Status:** IMPLEMENTED (mock/demo UI; build verified).

### Objective
Build the Bright Mode dashboard shell wired to mock/static data or placeholder API clients.

### Components
- Next.js app scaffold
- Header, Demo indicator, repo/target/scenario forms
- Pipeline + panels layout per `UI_SPEC.md`
- SIMPLE / TECHNICAL toggle (UI only)
- Placeholder CEG canvas (`@xyflow/react`)

### Files likely involved
`frontend/package.json`, `frontend/src/app/**`, `frontend/src/components/**`, `frontend/tailwind.config.*`, `UI_SPEC.md`

### Dependencies
Phase 0 docs. No backend required if mocks are used.

### Acceptance criteria
- [x] Bright Mode UI matches design direction (not dark hacker UI)
- [x] All main panels present (may use mock data)
- [x] DEMO MODE indicator visible when demo selected
- [x] App builds and runs locally

### Testing requirements
Manual UI checklist; basic smoke build. (`npm run build` passed)

### Must NOT implement yet
Real SSE, real deploy calls, CNP/CEG logic, Docker, LLM.

---

## PHASE 2 — Backend Foundation

**Status:** IMPLEMENTED (pytest + live health/deploy/SSE verified).

### Objective
Stand up FastAPI + SQLite + settings + health/deploy scaffolding without full agent logic.

### Components
- FastAPI app entry
- Pydantic settings from `.env`
- SQLite schema for deployments/events
- Routes matching `API_CONTRACT.md` (constraints/graph placeholders)
- CORS for local frontend
- In-process event bus + SSE
- Minimal foundation workflow (PREFLIGHT → ANALYZE → PLAN → COMPLETE)

### Files likely involved
`backend/app/**`, `backend/tests/**`, `.env.example`, frontend API client / DeploymentContext

### Dependencies
Phase 0 contracts; Phase 1 UI.

### Acceptance criteria
- [x] Server starts with Uvicorn
- [x] Health endpoint works
- [x] Deploy create/get return contract-shaped JSON
- [x] SQLite file creates on startup
- [x] SSE streams events
- [x] Frontend connects via REST + SSE

### Testing requirements
pytest for health + deploy create/get + events + SSE. (`12 passed`)

### Must NOT implement yet
LangGraph agents, real CNP, CEG execution, Docker SDK usage, detailed demo scenario engines.

---

## PHASE 3 — Demo Engine + Live Pipeline

**Status:** IMPLEMENTED (pytest scenario suite + frontend event mapper wired to live SSE).

### Objective
Deterministic Demo Mode engine that emits labelled SSE events through a fake pipeline.

### Components
- Scenario runners for five demo scenarios (`backend/app/demo/`)
- In-process event bus → SSE
- Pipeline stage progression matching UI
- Explicit `DEMO` / `MOCK` labels on all results
- Frontend `eventMapper` consumes rich demo event payloads

### Files likely involved
`backend/app/demo/**`, `backend/app/api/deploy.py`, `DEMO_MODE.md`, `frontend/src/lib/api/eventMapper.ts`

### Dependencies
Phases 1–2.

### Acceptance criteria
- [x] All five scenarios runnable offline
- [x] UI shows live updates via SSE
- [x] No GitHub/Docker/LLM required
- [x] Never presents demo as real

### Testing requirements
pytest scenario determinism; SSE smoke test. (Phase 3 suite in `backend/tests/test_demo_scenarios.py`)

### Must NOT implement yet
Real git clone, real Docker, real CNP resolution (may simulate CNP events).

---

## PHASE 4 — Repository Analysis

**Status:** IMPLEMENTED (local path + shallow clone; fixture-tested).

### Objective
Shallow clone + manifest-focused stack inference for real mode.

### Components
- Preflight Agent (git/docker host checks)
- Code Analyzer Agent
- `InferredStack` / `ApplicationProfile` production
- Workspace cleanup helpers

### Files likely involved
`backend/app/agents/preflight.py`, `backend/app/agents/analyzer.py`, `backend/app/services/git_service.py`

### Dependencies
Phase 2. Demo Mode may continue using fixtures.

### Acceptance criteria
- [x] Shallow clone works for a sample public repo (when network available)
- [x] Local/fixture paths work offline
- [x] Manifests produce structured `InferredStack` / `ApplicationProfile`
- [x] Failures are honest and typed

### Testing requirements
Unit tests with fixture repos (no network in CI if possible).

### Must NOT implement yet
Full specialist CNP, Docker deploy, rollback.

---

## PHASE 5 — Specialist Agents

**Status:** IMPLEMENTED (Docker / Nginx / Security constraint publishers).

### Objective
Docker, Nginx, and Security agents emit configs + typed constraints.

### Components
- Docker Agent
- Nginx Agent
- Security Agent
- Constraint publishers into shared state

### Files likely involved
`backend/app/agents/docker_agent.py`, `nginx_agent.py`, `security_agent.py`, `DATA_MODEL.md` Constraint types

### Dependencies
Phase 4 outputs.

### Acceptance criteria
- [x] Agents produce validated `Constraint` lists
- [x] Config fragments are structured (YAML/JSON), not free prose
- [x] No execution side effects yet

### Testing requirements
Fixture-driven unit tests per agent.

### Must NOT implement yet
Full CNP mediation loops, Executor, CEG writes.

---

## PHASE 6 — Constraint Negotiation Protocol

**Status:** IMPLEMENTED (deterministic CNP; max 3 rounds; no mandatory LLM).

### Objective
Implement CNP per `CNP_SPEC.md` with max 3 rounds.

### Components
- Constraint bus (in-process list collect)
- Conflict detection / grouping
- Priority resolution + alternative search
- Deterministic tiebreak when same-priority alternatives exhausted (LLM optional / not required)
- `NegotiationResult` persistence/events

### Files likely involved
`backend/app/cnp/engine.py`, `backend/app/workflow/planning.py`, `CNP_SPEC.md`

### Dependencies
Phase 5 constraints.

### Acceptance criteria
- [x] Deterministic resolution for priority-differing conflicts
- [x] Hard stop at 3 rounds
- [x] LLM path not required for V1 laptop/demo (deterministic_tiebreak)
- [x] Secrets never enter prompts

### Testing requirements
Unit tests for each conflict class; round-limit test; offline fixtures.

### Must NOT implement yet
Docker execution, rollback engine (may emit planned graph only).

---

## PHASE 7 — Verification + Critic

**Status:** TESTED (combined with Phases 8–9).

### Objective
Hard verification gate + critic scoring before execution.

### Components
- Verifier Agent (`backend/app/agents/verifier.py`)
- Critic Agent (`backend/app/agents/critic.py`)
- Bounded replan (max 3 rounds)
- Events for verification + critic panels

### Files likely involved
`backend/app/agents/verifier.py`, `backend/app/agents/critic.py`, `backend/app/models/execution.py`, `VERIFICATION_SPEC.md`

### Dependencies
Phase 6 agreed `ConstraintSet`.

### Acceptance criteria
- [x] Failed verification blocks Executor
- [x] Critic returns structured score + findings
- [x] Demo scenarios can force fail paths
- [x] Replanning bounded to 3 rounds

### Testing requirements
Pass/fail fixture suites (`tests/test_phase79_core.py`).

### Must NOT implement yet
Cloud deploy, remote hosts (still out of scope).

---

## PHASE 8 — Executor + Causal Execution Graph

**Status:** TESTED (combined with Phases 7–9). Real Docker mutate is opt-in.

### Objective
Execute verified plan locally; record CEG nodes/edges.

### Components
- Executor abstraction + `SimulatorExecutor` + `DockerExecutor`
- CEG store (`ExecutionNode`, `ExecutionGraph`)
- Graph API + UI binding

### Files likely involved
`backend/app/execution/**`, `backend/app/ceg/**`, `CEG_SPEC.md`, frontend CEG view

### Dependencies
Phases 6–7.

### Acceptance criteria
- [x] Meaningful actions create CEG nodes with parents + reversible_action
- [x] Graph endpoint returns current graph
- [x] Failures mark node status honestly
- [x] Verified plans only execute
- [x] Local Docker only (no remote)

### Testing requirements
Simulator tests; graph structure tests. Docker optional via fixture.

### Must NOT implement yet
Remote rollback, K8s, DNS undo.

---

## PHASE 9 — Scoped Rollback

**Status:** TESTED (combined with Phases 7–9).

### Objective
Dependency-aware rollback preserving independent successes.

### Components
- `compute_rollback_scope` / `apply_scope_to_graph`
- Reverse-order undo for reversible dependents
- Rollback summary events/UI

### Files likely involved
`backend/app/ceg/rollback.py`, `CEG_SPEC.md`

### Dependencies
Phase 8 CEG.

### Acceptance criteria
- [x] Partial failure rolls back dependents only
- [x] Independent successful services remain
- [x] Summary explains scope
- [x] Non-reversible actions reported honestly

### Testing requirements
Graph fixtures for independent-branch cases; PARTIAL_FAILURE demo regression.

### Must NOT implement yet
Remote rollback, K8s undo, DNS undo.

---

## PHASE 10 — Real End-to-End Deployment

**Status:** TESTED (combined with Phase 11; Docker E2E skipped when daemon unavailable).

### Objective
Wire real mode path end-to-end on local Docker host.

### Components
- Hardened preflight (Docker CLI/daemon, port, workspace)
- Plan supportability gate (`DEPLOYMENT_UNSUPPORTED`)
- Real `DockerExecutor` (labeled resources, health, scoped Docker rollback)
- Single real-deployment lock
- Clear DEMO vs REAL UI labelling

### Files likely involved
`backend/app/execution/**`, `backend/app/agents/preflight.py`, `backend/app/workflow/planning.py`, frontend real-mode controls

### Dependencies
Phases 4–9.

### Acceptance criteria
- [x] Verified plans only execute
- [x] Local Docker mutate opt-in (`MEDHA_DOCKER_EXECUTE`)
- [x] MEDHA-owned labels; refuse foreign cleanup
- [x] Failure path triggers scoped rollback
- [x] Demo Mode still works offline
- [x] Concurrent real deploys rejected (`DEPLOYMENT_BUSY`)

### Testing requirements
pytest + optional `@pytest.mark.docker` E2E.

### Must NOT implement yet
Cloud targets, DNS, CI/CD, multi-host.

---

## PHASE 11 — Testing + Evaluation

**Status:** TESTED (offline CNP/CEG runners; measured artifacts written to `data/evaluation/`).

### Objective
Harden test suite and produce evaluation artifacts for the major project.

### Components
- Expanded pytest coverage
- CNP / CEG evaluation runners + datasets
- GLOBAL_ROLLBACK baseline comparison
- `EVALUATION.md` + `/evaluation` UI
- Metrics notes under `docs/evaluation/`

### Dependencies
Phases 3–10.

### Acceptance criteria
- [x] CNP dataset + runner (measured, not fabricated)
- [x] CEG dataset + baseline comparison
- [x] Demo + Phase 7–9 regression still pass
- [x] Docker E2E skip-clean when Docker missing
- [x] No invented academic superiority claims

### Testing requirements
`pytest`, `python -m app.evaluation.run_all`, frontend typecheck/lint/build.

### Must NOT implement yet
Phase 12 visual redesign / documentation polish extravagance.

### Files likely involved
`tests/**`, `docs/evaluation/**`

### Dependencies
Phases 3–10.

### Acceptance criteria
- Core CNP/CEG/demo tests green
- Evaluation doc describes method and results honestly

### Testing requirements
CI-local runnable suite (no Redis/Postgres).

### Must NOT implement yet
New product features outside polish needs.

---

## PHASE 12 — Final Polish + Documentation

**Status:** TESTED (docs, viva packaging, validation matrix; no new architecture).

### Objective
Align docs with reality; polish UI copy; freeze V1 claims; viva + demo scripts.

### Components
- README walkthrough + honest Implemented/Measured/Not supported
- Architecture + research Mermaid diagrams
- `docs/VIVA_GUIDE.md`, `docs/DEMO_SCRIPT.md`
- Evaluation page honesty + loading/empty states
- Env example cleanup; stale LangGraph/phase claims removed

### Acceptance criteria
- [x] No doc claims untested features as passed Docker E2E without daemon
- [x] Presentation path documented
- [x] V1 scope boundaries still hold
- [x] Evaluation numbers from artifacts
- [x] Full available validation executed

### Must NOT implement yet
V2 features (DNS, CI/CD, K8s, Redis, Postgres, remote deploy).

---

## Phase Dependency Graph

```
0 → 1
0 → 2 → 3 → (UI live)
2 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12
3 can proceed in parallel with 4–5 using simulated CNP/CEG events
```

---

## Conflict Check (Phase 0 validation)

- No phase requires Redis/Postgres/K8s/DNS/CI.
- CNP (6) and CEG (8–9) remain central research phases.
- Demo (3) does not block research implementation (4–9).
- Real E2E (10) comes after rollback (9).
- Ten logical agents map cleanly across phases 4–9.
