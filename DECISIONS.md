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

## ADR-020 — Repository URL validation at the API boundary (V1 completion)

- **Decision:** Validate `repository_url` in `DeploymentRequest` and
  `ChangeImpactRequest` via `app/core/repo_url.py`: scheme allowlist
  (`https/http/git/ssh/git+https/git+ssh`, scp-like `user@host:path`),
  rejection of embedded credentials on http(s), and blocking of
  metadata/internal hostnames plus non-public literal IPs. Local paths and
  `file://` URIs remain accepted for the single-operator workflow.
- **Why:** The URL reaches server-side `git clone`; baseline SSRF protection
  without an overengineered framework.
- **Consequences / limitation:** Hostname checks are static (no DNS
  resolution), so DNS-rebinding is not detected — documented in the module.
  Acceptable for a 127.0.0.1 single-operator prototype; a beyond-loopback
  deployment must pin resolved IPs.

## ADR-021 — Git revision validation (V1 completion)

- **Decision:** `git_extract._validate_revision` allowlists revision charset
  and rejects leading-`-` values before they reach git argv.
- **Why:** Eliminates flag-injection via `base_revision`/`target_revision`.
- **Consequences:** Exotic-but-valid rev syntax outside the charset is rejected
  with `REVISION_INVALID`; normal branches/tags/SHAs/HEAD/reflogs pass.

## ADR-022 — Canonical research-graph expansion is labelled, not silent

- **Decision:** Keep expanding thin profiles to the canonical
  `network/database/backend/frontend/analytics` graph (needed for CEG demo
  quality), but record `expanded_to_canonical` + `synthetic_services` in the
  `ceg.created` event metadata and the persisted result message.
- **Why:** A one-file repository must never appear to have contained five
  services. The detected profile itself is unchanged (notes record the
  expansion).
- **Consequences:** UI/viva can quote the synthetic list directly from events.

## ADR-023 — Docker CLI (not SDK) is the V1 Docker interface

- **Decision:** Remove the unused `docker>=7` PyPI dependency; the runtime
  uses allowlisted Docker CLI verbs via `docker_ops.py` only.
- **Why:** AGENTS.md rule 17 (every dependency needs a V1 reason); the SDK was
  never imported.
- **Consequences:** `PROJECT_SCOPE.md` corrected from "SDK" to "CLI".

## ADR-024 — Advisory HTTP readiness + CIG→verification link (V1 completion)

- **Decision:** (a) `docker_ops.probe_http_readiness` performs a bounded (3s)
  loopback HTTP probe for host-mapped service ports; results are recorded in
  node metadata and never fail the deployment (busybox/simulator record
  `skipped`). (b) `run_verifier` gains an advisory, never-blocking
  `change_impact` check summarising CIG risk + requirement counts so the gate
  states "these changes require verification of these properties".
- **Why:** Strengthens "verifiable" without cloud infra or scope creep.
- **Consequences:** One extra WARN-level check on deployments carrying
  change-intel; zero behavior change for deployments without it.

## ADR-025 — `is_git_repository` confined to owned git metadata

- **Decision:** Check `<path>/.git` first, else require
  `rev-parse --absolute-git-dir` to equal `<path>/.git` — parent worktree
  discovery no longer counts.
- **Why:** A plain directory inside the MEDHA worktree was misdetected as a
  git repository (pre-existing `test_error_non_git_repo` failure on a clean
  tree).

## ADR-026 — Single Render Web Service (Next.js + FastAPI, one origin)

- **Decision:** Host V1 as one Web Service from a root `Dockerfile`
  (`runtime: docker`, see `render.yaml`). The image runs uvicorn on loopback
  `:8000` and `next start` on `$PORT` under stdlib-only
  `scripts/run_service.py`; Next.js `rewrites()` proxy `/api/*` and `/health`
  to FastAPI so the browser uses a single public origin with same-origin
  relative URLs (`frontend/src/lib/api/client.ts` falls back to `""`).
- **Why:** One service preserves the V1 shape (one FastAPI process + one
  Next.js app, AGENTS.md rule 18) with no new runtime, queue, or database.
  Rewrites need no extra proxy dependency (rule 17); the supervisor is stdlib
  and unit-tested (`scripts/test_run_service.py`).
- **Consequences:**
  - SSE streams through the rewrite unbuffered (backend already sends
    `X-Accel-Buffering: no`); verify with `curl --no-buffer` after deploy.
  - Rewrite destinations are baked at `next build` time (verified: a
    runtime-only backend URL is ignored), so the internal backend port is
    fixed at `127.0.0.1:8000` in `next.config.js`, `run_service.py`, and the
    `Dockerfile` — keep the three in sync. Only `NEXT_PUBLIC_*` would need a
    rebuild per environment, and none is required now that URLs are relative.
  - Either child exiting terminates the other and exits non-zero, so Render
    restarts instead of serving half a system.
  - Free tier has no persistent disk: SQLite at `/var/medha-data/medha.db`
    is ephemeral (fresh DB per redeploy). Paid disk at the same mount path
    persists history with no config change.

## ADR-027 — Server-side API token for mutating routes (hosting)

- **Decision:** `POST /api/deploy`, `POST /api/change-impact/analyze`, and
  `POST /api/evaluation/run/*` require `X-Medha-Token`
  (`backend/app/core/api_token.py`, `MEDHA_API_TOKEN`). Next.js
  `middleware.ts` injects it server-side from process env on mutating
  `/api/*` calls, so browsers carry nothing and the bundle holds no secret.
  Missing/wrong token → 401; production without any token → 503 fail-closed;
  local non-production without a token → allowed (unchanged laptop DX).
- **Why:** Public exposure of unauthenticated clone/pipeline/compute
  endpoints is an abuse magnet (bandwidth/CPU burn, server-path probing via
  change-impact). Loopback-binding alone does not help once a public proxy
  forwards to the backend.
- **Consequences:** `render.yaml` generates the token (`generateValue`).
  GETs and `/health` stay open (read-only demo data). Token rotation =
  Render env change + restart; no rebuild needed.

## ADR-028 — Frontend and test fixtures tracked as regular directories

- **Decision:** Remove the 12 bare gitlinks (`frontend/` + 11
  `backend/tests/fixtures/change_intel/*/` repos, which had no `.gitmodules`
  entries and, for `frontend/`, no remote at all) and track their working
  files as normal directories. Fixture `.git` histories are regenerable via
  `backend/tests/fixtures/change_intel/_build.py` (tests skip cleanly when
  absent); the nested frontend history (2 local commits, no remote) is
  superseded by the monorepo history.
- **Why:** A fresh clone (and therefore any Render build) received empty
  `frontend/` and fixture directories — the service could not build. A
  submodule without a URL cannot be initialized by anyone but the original
  author.
- **Consequences:** Slightly larger monorepo; fixture `.git` dirs stay
  untracked build outputs (regenerate with `_build.py`). If a separate
  frontend history is ever needed, extract with `git subtree split`.
