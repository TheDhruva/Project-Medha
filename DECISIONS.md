# DECISIONS.md — Architecture Decision Records

Status: living document. Initial ADRs recorded in Phase 0.

---

## ADR-001 — SQLite instead of PostgreSQL

- **Decision:** Use SQLite for V1 persistence.
- **Context:** College prototype on low-end laptops; single operator.
- **Consequences:** Simple file DB; no DB server. Not for multi-writer production scale.
- **Status:** Accepted

## ADR-002 — In-process constraint bus instead of Redis

- **Decision:** Coordinate constraints/events in-process (with optional SQLite persistence). No Redis.
- **Context:** V1 forbids unnecessary infrastructure; Redis appears in sibling `cadre` but conflicts with MEDHA scope.
- **Consequences:** Simpler ops; no cross-process bus. Multi-instance horizontal scale out of scope.
- **Status:** Accepted

## ADR-003 — LangGraph as lightweight workflow/state layer

- **Decision (Phase 0 intent):** Prefer a lightweight graph/state layer for logical agent nodes.
- **V1 outcome:** **Superseded by ADR-017.** Runtime uses in-process `PlanningPipeline` / `DemoRunner` without a LangGraph dependency.
- **Context:** Avoid spawning many independent AI processes/services.
- **Consequences:** Do not claim LangGraph as the V1 execution engine.
- **Context:** Need clear pipeline state without microservice sprawl.
- **Consequences:** Single backend process; agents are functions/classes/nodes.
- **Status:** Accepted

## ADR-004 — Deterministic logic first; LLM only where useful

- **Decision:** Prefer rules, schemas, and deterministic CNP resolution. LLM only for bounded cases (e.g., same-priority mediation) with structured validation.
- **Context:** Cost, reliability, demo-without-API-key, academic clarity.
- **Consequences:** Fewer LLM calls; mediation path must be optional.
- **Status:** Accepted

## ADR-005 — SSE instead of WebSockets

- **Decision:** Stream deployment events with Server-Sent Events.
- **Context:** One-way live updates fit the UI; simpler than full-duplex sockets (cadre used WebSockets).
- **Consequences:** Client→server still REST; SSE for server→client live trace.
- **Status:** Accepted

## ADR-006 — Manifest-focused repository analysis

- **Decision:** Analyze Docker/compose/package manifests via shallow clone; do not send entire repositories to an LLM.
- **Context:** Token limits, secret risk, laptop performance.
- **Consequences:** Stack inference may miss exotic layouts; acceptable for V1.
- **Status:** Accepted

## ADR-007 — Demo Mode is mandatory

- **Decision:** Ship deterministic Demo Mode that runs offline without GitHub/Docker/LLM/internet/cloud.
- **Context:** Reliable viva/demo; dependency flakiness.
- **Consequences:** Dual paths (demo/real) must stay labelled; extra fixture maintenance.
- **Status:** Accepted

## ADR-008 — DNS and CI/CD deferred from V1

- **Decision:** No DNS automation and no CI/CD automation in V1.
- **Context:** Scope control; sibling cadre includes these; MEDHA focuses on CNP+CEG.
- **Consequences:** Clear non-goals; avoid agent sprawl.
- **Status:** Accepted

## ADR-009 — Local Docker host is the V1 deployment target

- **Decision:** Execute only against local Docker. No remote SSH/multi-host/cloud deploy.
- **Context:** Demonstrability and safety on student machines.
- **Consequences:** Real-mode demos need Docker Desktop/Engine locally.
- **Status:** Accepted

## ADR-010 — CNP and CEG are the primary research contributions

- **Decision:** Treat Constraint Negotiation Protocol and Causal Execution Graph as first-class research pillars; do not demote them to optional plugins.
- **Context:** Project thesis identity.
- **Consequences:** Phases 6–9 are critical path; UI must expose both.
- **Status:** Accepted

---

## Conflict log (Phase 0)

| Conflict | Resolution |
|----------|------------|
| Workspace is multi-project; no existing Medha app | Create new `Medha/` project root |
| Sibling `cadre` uses Redis, WebSockets, DNS, CI | Do not import those into MEDHA V1; document as non-goals |
| cadre agent count (~16) vs MEDHA (10 logical) | Stick to MEDHA’s ten; no DNS/CI/monitor/intent sprawl in V1 |
| Empty `frontend/`/`backend/` vs “don’t rewrite working code” | N/A — no MEDHA runtime code yet |

No contradictory requirements found inside the MEDHA V1 contract set after cross-check of scope, CNP bounds, CEG rollback rules, and phase plan.

---

## Phase 3 notes

| Topic | Decision |
|-------|----------|
| Demo engine location | `backend/app/demo/` (models, fixtures, scenarios, runner) |
| Foundation workflow | Replaced for demo deploys by `DemoRunner` (Phase 2 placeholder no longer scheduled) |
| VERIFICATION_FAILURE | Bounded replan (max 1) then success — aligns with Phase 3 brief (not terminal fail-only) |
| CNP/CEG | Fixture-compatible shapes only; full engines remain Phases 6–9 |
| Persistence | SQLite artifact JSON columns on `deployments` (`result_json`, `constraints_json`, …) |

---

## Phase 4–6 notes

| Topic | Decision |
|-------|----------|
| Real mode | Enabled for planning (`analyze → specialists → CNP`); extended in Phases 7–9 |
| Repo acquire | Local path / `file://` preferred for offline tests; remote uses `git clone --depth 1` |
| CNP LLM | Not required in V1; `deterministic_tiebreak` after alternatives exhausted (₹0 / offline) |
| Port conflict | Docker + Nginx both claim `target.port` as RESOURCE so CNP alternatives are exercised |
| Security conflict | Intent containing `unrestricted`/`privileged` publishes PREFERENCE; SECURITY wins |

---

## ADR-011 — Simulator default; Docker mutate opt-in

- **Decision:** Real-mode execution uses `SimulatorExecutor` unless `MEDHA_DOCKER_EXECUTE=true`. `DockerExecutor` remains local-host only.
- **Why:** Low-end laptop safety, deterministic CI without Docker, clear DEMO vs REAL distinction.
- **Consequences:** CEG/rollback logic is fully exercised without pulling images; optional fixture under `backend/tests/fixtures/docker/`.

## ADR-012 — Downstream-only scoped rollback

- **Decision:** On failure, rollback only reversible **dependents** of the failed node (plus mark failure). Preserve successful ancestors and independent branches.
- **Why:** Matches the research claim of dependency-aware recovery without cascading unnecessary undo.
- **Consequences:** Ancestors of a failed node are never rolled back merely because the failed node depended on them.

## ADR-014 — One real deployment at a time

- **Decision:** Serialize real-mode deployments with an in-process lock; return `409 DEPLOYMENT_BUSY` if busy.
- **Why:** SQLite + local Docker safety on a low-end laptop; V1 is single-operator.
- **Consequences:** Demo Mode remains concurrent with UI fixtures; only one real pipeline mutates host state.

## ADR-015 — Controlled images for Docker mutate

- **Decision:** Real Docker mutate uses allowlisted images (default `busybox:1.36`) from verified plans; does not build/run arbitrary repository Dockerfiles automatically.
- **Why:** Prevent arbitrary code execution via `npm`/`make`/untrusted builds.
- **Consequences:** “Real Docker” validates ordering, labels, health, and rollback — not universal auto-deploy of any GitHub app.

## ADR-017 — In-process workflow (not LangGraph runtime in V1)

- **Decision:** V1 orchestration is `PlanningPipeline` / `DemoRunner` inside FastAPI. LangGraph was considered in Phase 0 docs but is not a runtime dependency.
- **Why:** Fewer packages, simpler debugging on a low-end laptop, sufficient for the prototype.
- **Consequences:** Docs must not claim a LangGraph execution engine until an ADR adds it.

## ADR-018 — Change Intelligence (CIG) as a third research contribution

- **Decision:** Phase 12 (internal phase 2) adds a deterministic **Change Impact
  Graph (CIG)** — git revisions → ChangeSet → symbols → dependency edges →
  traversal → risk → verification requirements — as a persistent, UI-visible
  artifact (`deployments.change_intel_json`, schema v2). CIG is formally
  distinct from the CEG (runtime execution causality). No LLM; every edge has
  concrete `file:line` evidence and a confidence (HIGH/MEDIUM/HEURISTIC).
- **Why:** Change-intelligence answers "what depends on what and what must be
  re-verified" before deployment, complementing CEG's runtime recovery. It is
  verifiable offline, keeps the deterministic-first rule (ADR-004), and avoids
  the opacity and hallucination risk of LLM-only impact analysis.
- **Consequences:**
  - V1 analyses **local git repositories only**; remote URLs stay
    `NOT_LOCAL_REPOSITORY` (ADR-008 scope — a later phase may add remotes).
  - Unresolved/deleted imports are reported as evidence, never invented
    (`deleted-import` is a high-signal breakage).
  - CIG and CEG never share storage or UI graph; observe Claim: "CIG ≠ CEG".

## ADR-019 — Schema v2 migration for change-intel artifacts

- **Decision:** `deployments` gains `change_intel_json`, `base_revision`,
  `target_revision` via the existing `PRAGMA user_version` migration pattern
  (`_SCHEMA_VERSION = 2`). No ORM introduced.
- **Why:** Keeps the SQLite-only, no-ORM invariant (AGENTS.md rules 6/19/20) and
  lets a deployment carry its analysis for the GET endpoint and reconciling UI.
- **Consequences:** Schema v1 databases auto-upgrade on startup; tests cover the
  migration path when run on a fresh DB.
