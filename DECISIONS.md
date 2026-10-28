# DECISIONS.md — Architecture Decision Records

Status: living document. Initial ADRs recorded in Phase 0.

---

## ADR-001 — SQLite instead of PostgreSQL

- **Decision:** Use SQLite for V1 persistence.
- **Context:** College prototype on low-end laptops; single operator.
- **Consequences:** Simple file DB; no DB server. Not for multi-writer production scale.
- **Status:** Partially superseded by ADR-029 (SQLite remains the default; Postgres/Supabase is the opt-in main backend when `MEDHA_DATABASE_URL` is set).

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

## ADR-029 - Supabase Postgres as the main backend database (SQLite fallback)

- **Decision:** Support PostgreSQL (Supabase) as the primary MEDHA
  persistence backend, selected by `MEDHA_DATABASE_URL`. SQLite remains the
  default when the variable is unset, and an explicit file path argument to
  `get_connection`/`init_db` always means SQLite (keeps the offline test
  suite and Demo Mode working with no network).
- **Context:** The project now uses Supabase (`db.myukgjmhzmlzkxjszsdh.supabase.co`)
  as its main backend so run history survives redeploys (Render free-tier
  SQLite is ephemeral). This explicitly overrides the SQLite-only / "No
  PostgreSQL in V1" scope rules for persistence only.
- **Why psycopg 3:** stdlib-style DBAPI, binary wheels, `dict_row`
  cursors that match the existing `row.keys()` repository code. One small
  driver (`psycopg[binary]`), no ORM, no migration framework.
- **Compatibility design (repositories untouched):**
  - All repository SQL keeps `?` placeholders; the Postgres connection
    wrapper translates `?` to `%s` and `rowid` ordering to a `BIGSERIAL seq`
    column (`schema_pg.sql`). No `?` appears inside SQL string literals, so
    the translation is exact.
  - `is_demo` stays an INTEGER column on both drivers; repositories already
    pass `1`/`0` and read with `bool(...)`.
  - Supabase direct connections (port 5432) require TLS: `sslmode=require`
    is appended when the DSN has no explicit `sslmode`.
- **Secrets:** `MEDHA_DATABASE_URL` lives in local `.env` / host env only.
  Logs and health output carry a redacted label (scheme + user + host, never
  the password). Never paste the URL into issues, prompts, or the client
  bundle.
- **Consequences:** One extra dependency (`psycopg[binary]`); Postgres live
  tests are skip-guarded (`MEDHA_DATABASE_URL` absent = skipped); offline
  Demo Mode guarantee unchanged. `render.yaml` SQLite disk notes now apply
  to SQLite mode only.
- **Status:** Accepted

## ADR-030 — AI provider integration (Groq primary, Gemini fallback)

- **Decision:** Centralized `backend/app/ai/` service (Groq Chat Completions
  + Gemini generateContent over httpx; no vendor SDKs). Six advisory assists
  (change summary, repo interpretation, plan suggestion, agent explanation,
  critic assist, review brief), all schema-validated (Pydantic, extra=forbid),
  budget-capped (default 6 calls/run), cached per authorization context, with
  recorded outcomes (`ai_assisted`/`degraded`/`rule_based`/`unavailable`).
- **Context:** User-directed feature: AI where it adds value, deterministic
  pipeline untouched. Defaults verified Oct 2026: Groq `openai/gpt-oss-20b`,
  Gemini `gemini-3.8-flash`.
- **Rules:** Disabled/keyless → zero network I/O. Retry transient only
  (bounded, backoff+jitter); auth/config never retried. Fallback on eligible
  failures. Secrets redacted before prompts/logs/records. No Redis; in-process
  LRU cache. Model output never authorizes, executes, or bypasses gates.
- **Consequences:** No new dependencies (httpx already present). Automated
  tests use mocked transports; live provider behavior unverified without keys.
- **Status:** Accepted

## ADR-031 — Clerk backend verification + minimal ownership

- **Decision:** `MEDHA_AUTH_MODE=off` (default, legacy single-operator) vs
  `clerk` (FastAPI verifies RS256 session JWTs via JWKS: signature, issuer,
  expiry, `sub`; ownership enforced on runs/proposals via `owner_sub`).
  New deps `PyJWT` + `cryptography` (justified: token verification).
- **Context:** Frontend middleware never protects FastAPI. Clerk is identity
  only; no Supabase Auth alongside it. Minimal model (subject column + users
  audit table), no enterprise RBAC.
- **Rules:** Production clerk-mode without JWKS config fails closed (503).
  Cross-user reads return 404 (no oracle); foreign-owner approve/reject 403.
  Webhook auth stays GitHub-secret based, independent of Clerk.
- **Consequences:** Legacy rows (`local-operator`) are invisible to Clerk
  users by design. Old DBs heal via schema v5 migration.
- **Status:** Accepted

## ADR-032 — GitHub webhook + approval-gated execution

- **Decision:** `POST /api/webhooks/github` (HMAC-SHA256, delivery-ID
  idempotency, branch/repo allowlists) creates proposals; plan-only analysis
  persists a canonical plan + SHA-256 hash; `POST /api/proposals/{id}/approve`
  re-runs the deterministic pipeline and revalidates the exact hash before
  executing. Stale/superseded/replayed approvals cannot execute.
- **Context:** Completes the push → review → approve loop without touching
  the operator-invoked `POST /api/deploy` path (the human pressing deploy
  remains the approval for manual runs).
- **Rules:** Webhook secret unset → 503. Empty repo allowlist fails closed in
  production. Hosted execution stays simulator-pinned. Newer pushes supersede
  older pending proposals.
- **Consequences:** Approval e2e covered by tests on the local fixture repo;
  real-GitHub delivery unverified until a public endpoint exists.
- **Status:** Accepted

## ADR-033 — Project-scoped, multi-user repository connections

- **Decision:** `projects` table (`owner_sub`, `owner/name`, `branch`,
  `canonical_url`, `visibility`, `connection_status`) replaces the founder
  allowlist as the routing source of truth. Runs/proposals carry `project_id`;
  reads, mutations, approvals, and webhook routing are owner-scoped
  (cross-owner → 404/403, no existence oracle). The global
  `MEDHA_WEBHOOK_ALLOWED_REPOS` remains a server-level guard only.
- **Context:** MEDHA must serve many users × many repositories without manual
  founder edits per project. A repository string in a form is configuration,
  never proof of access: readability is proven by `git ls-remote` (verify)
  and exact-SHA checkout at analysis time.
- **Rules:** No credentials accepted or stored (PATs in URLs already
  rejected). Duplicate `(owner, repository)` → 409. Disconnect/delete stops
  all future routing; history is preserved. Supersede is scoped per project.
- **Consequences:** Same public repo may be connected by different owners
  independently; each gets isolated proposals/runs.
- **Status:** Accepted

## ADR-034 — Exact pushed-SHA checkout + payload-derived change intel

- **Decision:** Webhook/project runs with a full 40-hex `target_revision`
  fetch + detach-checkout that exact commit and assert `HEAD == SHA` before
  analysis (`SHA_MISMATCH` fails closed). `commits[]` file lists become
  `source_method=webhook_push` change intelligence verified against the
  checkout; unverified files are reported, never trusted. Branch deletions
  (null SHA) are recorded and ignored.
- **Context:** Cloning the default-branch tip can analyze a different commit
  than the push event attests to.
- **Rules:** Non-SHA revisions keep legacy behavior. Approval revalidates
  project linkage (connected, same repo/branch/URL) in addition to SHA +
  plan hash.
- **Status:** Accepted

## ADR-035 — Startup recovery without new infrastructure

- **Decision:** At boot, `reconcile_interrupted()` fails orphaned
  `queued/started/running` deployments and pre-`ready`
  (`pending/analyzing/approved/executing`) proposals closed with an honest
  reason + terminal event. `ready` proposals and persisted plans survive
  restarts and stay approvable. Conditional SQL makes recovery idempotent;
  nothing auto-executes.
- **Context:** In-process pipeline tasks do not survive restarts; previously
  orphaned rows never resolved.
- **Rules:** No Redis/workers. Recovery never invents success and never
  approves or executes.
- **Status:** Accepted

## ADR-036 — Private repositories stay unsupported pending a GitHub App

- **Decision:** Private-repository access is explicitly **not implemented**:
  `verify` reports unreachable/private honestly (`failed`/`unverified`),
  acquisition fails closed, and no PAT/App-token flow exists. The secure
  path forward is a GitHub App (installation tokens, per-installation
  secrets, permission grants) — code + dashboard steps to be added with an
  explicit founder action, never fabricated credentials.
- **Status:** Accepted

## ADR-037 — No simulated production success (real-execution hardening)

- **Decision:** (a) The demo engine is disabled by default
  (`MEDHA_ENABLE_DEMO=false`; `POST /api/deploy` with `mode=demo` returns
  `403 DEMO_DISABLED`). It remains for isolated automated tests only and must
  never be reachable as a successful production run. (b) The simulator runs
  only with `MEDHA_EXECUTOR_MODE=simulator` set explicitly; results are
  labelled test-only (`execution_mode: simulator`, health `test_only`) and can
  never be reported healthy. Unconfigured or hosted execution fails closed
  (`EXECUTION_NOT_CONFIGURED` / `EXECUTION_DISABLED_HOSTED`). (c) The legacy
  controlled-test Docker path no longer substitutes BusyBox for placeholder
  plan images — unapproved images fail the service honestly
  (`UNSUPPORTED_IMAGE`). (d) Every remote real run resolves exactly one commit
  SHA (explicit revision or remote HEAD) before analysis and records it
  (`resolved_sha`, `target_sha`, `plan_hash` binding). (e) `Healthy` requires
  observed runtime evidence: stored results distinguish `healthy` (real +
  readiness passed) from `test_only`/`demo`/`unknown`, and
  `GET /api/deploy/{id}/health` live-probes the recorded container; unknown
  runtimes report `unknown`, never a retained healthy label. (f) Low-confidence
  manifest analysis requires explicit review (`PLAN_REQUIRES_REVIEW` below
  0.5); ambiguous multi-application repositories are rejected
  (`MULTIPLE_APPS_REQUIRE_TARGET`).
- **Why:** The readiness audit (F-001–F-013) showed invalid URLs reaching
  `Healthy` via demo-default creation, workflow completion equated with health,
  and silent simulator substitution. Each is a false-success vector.
- **Consequences:** Local runs without an isolated builder end at a verified
  plan with an honest configuration error instead of a fake deployment. The
  full backend suite declares its test-only execution explicitly
  (`tests/conftest.py` autouse fixture). Production refuses execution outright.
- **Status:** Accepted

## ADR-038 — Demo execution removed from the product (supersedes ADR-007)

- **Decision:** `POST /api/deploy` with `mode=demo` returns `410 DEMO_REMOVED`;
  `GET /api/demo/scenarios` and `GET /api/change-impact/demo/fixture` return
  404. `backend/app/demo/*` remains as isolated test fixtures only, unreachable
  from any product route. Synthetic canonical-service expansion is removed
  from both `workflow/planning.py` and `execution/plan_builder.py`: real plans
  contain exactly the discovered topology. Hosted execution is
  explicitly disabled (`MEDHA_EXECUTOR_MODE=disabled`), not simulator-pinned.
- **Why:** Product demo behavior and synthetic topology are false-success
  vectors: they can be mistaken for real analysis, scores, and health.
  Historical DEMO/MOCK records keep their labels; nothing is relabelled.
- **Consequences:** Empty workspaces render no seeded projects. Docs
  `DEMO_MODE.md` retired; presenter script archived at
  `docs/archive/DEMO_SCRIPT.md`. Isolated demo-engine unit tests remain.
- **Status:** Accepted

## ADR-039 — Durable commit-aware jobs, incremental tiers, versioned scores

- **Decision:** (a) `jobs` table (v8 schema) is the source of truth for
  push-triggered analysis; a single in-process worker claims jobs with bounded
  retries (exponential backoff) and `dead_letter` terminal state. Older queued
  jobs are superseded by newer pushes; branch `seq` guards ordering. (b)
  Three-tier incremental analysis (`changeintel/tiers.py`): Tier 1
  deterministic with 0 LLM calls (docs-only), Tier 2 targeted (≤2 calls),
  Tier 3 expanded (≤6 calls, existing AI budget). Tier 1 skips `_ai_assist`
  entirely. Cache keys hash all inputs (`inputs_hash`). (c) Four versioned
  scores (`scores-v1`: deployment_readiness, performance, optimization,
  security) computed deterministically from stored evidence; missing evidence
  yields `null`, never success. Snapshots persist in `scores` table with
  history API. (d) Real Git history service (`history_service.py`, bounded
  `git log`) backs `GET /projects/{id}/history` + commit detail; frontend
  `CommitGraph.tsx` renders actual ancestry, distinct from CIG/CEG.
- **Why:** The readiness audit required durable push processing, no repeated
  full analysis per small commit, evidence-backed scores, and a genuine
  commit graph — without new infrastructure (no Redis/workers).
- **Consequences:** V1 remains single-process (one backend replica for
  webhook analysis). Postgres compatibility is best-effort for job claiming
  (`strftime` backoff is SQLite-dialect). Score history and commit metadata
  persist in `scores`/`commits` tables.
- **Status:** Accepted

## ADR-040 - Versioned runtime spec + staged real-execution readiness contract

- **Decision:** (a) `backend/app/execution/runtime.py` defines the validated
  `runtime-spec/v1` Pydantic contract (profile/version, pinned commit SHA,
  app root, language/framework/package-manager, evidence + confidence,
  internal/host ports, build/start/bind config, readiness deadline, env
  names only, resource limits, base image). Detection returns
  supported/unsupported/ambiguous — never a silent guess
  (`AMBIGUOUS_TARGET` for multi-app roots without a target). (b) The
  profile registry (`profiles.py`) extends the existing system with
  `nextjs` (lockfile-aware npm/pnpm/yarn install + required `build` step +
  glibc `node:22-slim` base) and `python-asgi` alongside unchanged
  `node`/`python`/`static` behavior; bun fails closed (no V1 toolchain).
  (c) `RealExecutor.deploy` enforces staged fail-closed evidence:
  detection → build → start → published-port verification → bounded
  readiness probes, recording probe URL, host→container mapping, attempts,
  container state/exit code, and a bounded log tail. Post-start failures
  keep code `READINESS_FAILED` with a machine-readable `stage`
  (`connection_refused` / `timeout` / `http_error` / `container_exited`);
  a missing published binding fails fast as `PORT_MAPPING_FAILED` and an
  immediately-exited container as `START_FAILED` with its exit code.
  Success requires a passed probe.
- **Why:** Real Docker readiness repeatedly failed with `connection refused`
  at the published port because the node template installed with npm
  (ignoring pnpm lockfiles) and never ran the production build, so
  `next start` had no `.next` output; failures were undiagnosable (no port
  binding/state evidence). Verified against pinned Lead_Website
  `ad51b8b3` (pnpm + `next build`): real build + readiness passed.
- **Consequences:** `RealDeployResult`/`run result` gain optional
  `runtime_spec` evidence (old runs without it stay readable). Pipeline
  passes the analyzed commit SHA into the executor; CNP/verifier/CEG/
  rollback/simulator paths are untouched.
- **Status:** Accepted

## ADR-041 - Analyzed-commit summaries + declaration-aware package managers

- **Decision:** (a) The analysis pipeline records commit metadata
  (SHA/message/author/timestamps) plus a deterministic, evidence-based
  summary (headline + changed-file paths + diff stats) for the analyzed
  revision, read from the already-acquired checkout — no extra clone, no
  LLM, no paid APIs. New `commits` columns (`summary`, `files_json`,
  `added`, `deleted`, `deployment_id`; schema v10 with migration) extend
  the existing table; missing summaries render as unavailable, never
  fabricated. (b) The history API serves persisted commits first
  (`?refresh=1` forces a live re-acquire), so opening the overview causes
  no new analysis or clone. (c) Package-manager selection honors a valid
  `packageManager` declaration when consistent with lockfile evidence,
  pins the declared version via Corepack (non-interactive bootstrap), and
  fails closed with an explicit diagnostic on conflicting lockfiles or
  declaration/lockfile mismatch. Repository intelligence reports the
  selected manager + evidence from the same shared selector.
- **Why:** The Latest-commit card was empty because the pipeline never
  persisted commit metadata (only the history endpoint's live re-clone
  wrote rows), and the overview reported npm for a pnpm repo because the
  analyzer hardcoded npm while the executor used lockfile priority.
- **Consequences:** Future analyses self-record; the existing Lead run was
  backfilled from its pinned SHA. Bulk ancestry upserts never overwrite a
  recorded summary. Bun and conflicting-managers still fail closed before
  any Docker work; the Next.js build/readiness path is unchanged.
- **Status:** Accepted

## ADR-042 - Authoritative port contract (internal vs host) + bounded host renegotiation

- **Decision:** The final validated execution plan owns one port contract
  (`internal_port` from repository evidence, `host_port` from the CNP app
  PORT_CLAIM). Only the host side is availability-checked/probed; a busy
  host port triggers one bounded CNP `alternative` renegotiation
  (`apply_decision` + verifier/critic revalidation), never a silent remap.
  The contract binds the RuntimeSpec (`with_host_port` keeps PORT/HOSTNAME
  and python `--port` on the internal port), Docker publish/probe mapping,
  compose app-service entry, canonical plan hash, and every terminal result
  payload (which also carry `target_sha`, `requested_ref`, and an explicit
  `execution_mode`: `real` | `simulator` | `unconfigured`). Remote runs
  without a pinned SHA fail closed (`NO_PINNED_REVISION`) before real
  execution; simulator runs skip host availability claims entirely.
- **Why:** Every repeat run failed with `Negotiated target port 8080 is no
  longer available` because (a) the CNP host alternative was never
  propagated past negotiation (plan, runtime, publish, and probe all reused
  the stale requested port), (b) a busy *host* socket was treated as proof
  the *container-internal* port was unusable, and (c) pre-execution failure
  payloads omitted `target_sha`/`execution_mode`, so the UI fell back to
  `Revision Unknown` / `Mode Simulated` for runs that never simulated.
- **Consequences:** No CNP bypass (renegotiation reuses `apply_decision`
  and the verifier/critic gate; max 3 CNP rounds unchanged). New verifier
  rule `PORT-001/002` rejects unresolved/duplicate host claims. Old
  approvals hash-mismatch closed (`STALE_PLAN`) since the plan identity now
  includes the contracted mapping. Successful-container lifecycle, CEG,
  rollback, and security checks are untouched.
- **Status:** Accepted

## ADR-043 - Evidence-backed project scorecards (`scores-v2`)

- **Decision:** Replace the 100-minus-runtime-deductions scorecard with four
  independently computed categories: `code_quality`, `security`,
  `verification_confidence`, `deployment_readiness` (plus the existing
  `performance`/`optimization`). Inputs are stored repository analysis
  (inventory, scanner findings, change intelligence) and stored run artifacts
  (verification, execution, health). Every check records `status`
  (`passed`/`failed`/`warning`/`not_assessed`), severity, finding, evidence
  source, reference, and score impact; unavailable scanners and unrun health
  probes are `not_assessed`, never passes. Coverage caps (no static analysis
  80, missing security scanners 60, missing health 75, unverified execution
  60, critical blocker 25) stop unknown areas from scoring full. The frontend
  renders backend values only (no local recomputation) and labels coverage,
  source revision, stale snapshots, in-progress assessments, and demo data.
- **Why:** The old cards were indistinguishable from a perfect 100 on every
  project because they only deducted for generated-plan/runtime problems and
  never consumed repository analysis. Security/health were reported green
  even when no scanner or health probe ran.
- **Consequences:** Score version bumps to `scores-v2`; snapshots remain in
  the existing `scores` table (no migration). Repeated requests with the same
  inputs/version reuse the stored snapshot. Simulator/demo results are capped
  and labelled; missing evidence shows `Not assessed` instead of a perfect
  score. Verification confidence uses the 9 required verifier checks; the
  optional `change_impact` check does not affect it.
- **Status:** Accepted

## ADR-044 — Analysis outcome is authoritative and separate from deployment (`scores-v3`)

- **Context:** A successfully analyzed framework/library repository (e.g.
  FastAPI) was shown as an overall `Failed` run with a fabricated
  `25/100` "Critical findings" Deployment Readiness score. The 25 came from
  scoring deployment *ineligibility* (`NO_DEPLOYABLE_APP`) against
  readiness criteria: the target-support check failed critically, the caps
  fired (critical blocker → 25), and the frontend mapped <60 → "Critical".
- **Decision:**
  1. Run summaries expose additive backend-persisted `analysis_status`
     (`completed`/`partial`/`failed`) and `deployment_status` (e.g.
     `blocked`) fields; `run.status` keeps its existing values (a blocked
     run stays `failed`) so older clients and records are unaffected.
  2. `deployment_readiness` is **not applicable** (value `null`,
     `evidence.applicable=false`, plain-English `reason`) when the support
     gate reports no deployable application (`NO_DEPLOYABLE_APP`,
     `NO_TARGET_CANDIDATES`). Deployment ineligibility is never scored as a
     defect. Other blocked-target codes keep the documented capped formula.
  3. The frontend derives run outcomes from those fields (falling back to
     the structured `error_code` semantics for older runs): primary status
     describes analysis (`Analysis complete/partially complete/failed`),
     deployment is a separate secondary label (`Deployment not
     applicable/blocked/completed/...`). Scorecard states add
     `not_applicable` and `partial` ("Partially assessed").
- **Why:** Analysis completion and deployment eligibility are independent
  facts. The backend already persists both; the missing piece was exposing
  them and refusing to fabricate a score when the criteria do not apply.
- **Consequences:** Score version bumps to `scores-v3`, which invalidates
  stale stored `scores-v2` snapshots (they recompute on next fetch). No
  schema migration. Run rows remain backward compatible; older records
  without the new fields render honest fallbacks (`Run failed`,
  `Not assessed`) instead of invented outcomes.
- **Status:** Accepted

## ADR-045 — Baseline policy checks + cross-run finding ledger

- **Context:** External scanners (semgrep/gitleaks/trivy) are optional and
  frequently absent on a low-end/local machine, so repositories could get no
  security coverage at all — or worse, a scan where semgrep was invoked
  without `--config`, i.e. with no ruleset. Nothing persisted findings across
  runs: identity was re-derived per analysis, and there was no lifecycle
  (triage, confirmation, re-detection) anywhere in the system. Scanner
  finding messages were stored as-is, so a secret echoed by a tool could land
  in the database.
- **Decision:**
  1. A deterministic, bounded, read-only policy module (`security:builtin`)
     always runs with scanning: `SEC-*` (shell=True, yaml.load, pickle,
     f-string SQL, weak hash), `CFG-*` (committed `.env` reported by path
     only, CORS wildcard, debug=True, verify=False) and the aggregate
     `AUTH-001` observation. Every result is `verification_status="unverified"`
     with confidence stated — a pattern match is evidence to investigate,
     never a confirmed exploit.
  2. A `findings` table (schema v11) is the cross-run ledger. Identity is
     `sha256(source|rule_id|path|normalized message)` — line numbers excluded
     so reformatting never duplicates a condition. The lifecycle state machine
     (`detected → under_investigation → confirmed|rejected|accepted_risk`,
     `fixed_unverified → resolved`, `reopened` on re-detection) is enforced
     server-side, and `confirmed`/`rejected`/`resolved` require evidence
     references.
  3. A disappearing finding becomes `fixed_unverified` — never `resolved` —
     and only when its originating check actually re-ran in that scan.
     Checks that did not run leave state untouched.
  4. `GET/POST /api/deploy/{id}/findings[/{finding_id}]` expose the ledger
     (§20 API_CONTRACT). semgrep now runs with `--config auto`, and all
     scanner finding messages pass through the existing redaction helper
     before storage.
  5. The builtin task is excluded from the external `security_scan` coverage
     calculation: baseline coverage must never soften the honest
     "no external security scanner executed" gap.
- **Why:** Coverage that always exists (offline-safe) plus a durable,
  deduplicated lifecycle is what makes findings actionable across commits;
  and the honesty rules are what keep it from becoming decorative.
- **Consequences:** One idempotent schema migration (SQLite `user_version`
  11 + `_V11_TABLES_SQL`, mirrored in `schema_pg.sql`). `semgrep --config
  auto` needs registry access — offline it fails honestly (`failed` status),
  which is surfaced as a coverage gap rather than a silent clean scan. The
  builtin checks are advisory input to scoring, never auto-confirmed findings.
- **Status:** Accepted

## ADR-046 — Honest scoring (`scores-v4`) + revision-keyed inventory reuse

- **Context:** `performance` defaulted to 80 and `optimization` to 100 even
  when no performance or optimization evidence existed at all — a number
  without evidence misrepresents unassessed areas as healthy. Runs whose
  clone failed still reported `target_support = SUPPORTED`. The
  `analysis_cache` table existed but was never written. A task-level
  cancellation (`asyncio.CancelledError`) bypassed every failure handler, so
  a run could stay `running` forever — a false active dashboard state.
- **Decision:**
  1. `performance` returns `null` (+ reason) unless change-risk evidence or a
     measured benchmark exists; `optimization` returns `null` unless
     verification checks or change requirements were actually recorded.
  2. Security evidence always carries `security_failures` (failed security
     check count) and `scan_completeness` (`analysis_status`,
     `security_scan`, `gaps`), so "scan ran without coverage" is never read
     as a pass.
  3. `target_support = SUPPORTED` requires a successful repository analysis
     (or a previously analyzed revision with a supported mode); a failed
     clone yields `not_assessed`.
  4. Repository inventories are reused via `analysis_cache` keyed on
     `commit + selected target + scanner configuration + installed-tool
     binary signature` (path/mtime/size). Results without an immutable commit
     are never cached; failed payloads are never stored; any cache problem
     degrades to a fresh analysis, never to a failed run.
  5. `CancelledError` in the planning pipeline persists a terminal
     `PIPELINE_CANCELLED` failure (dropped when the cancel endpoint already
     recorded `CANCELLED` — cancellation always wins) and re-raises.
- **Why:** Every one of these was a path where the system claimed knowledge
  it did not have, or claimed activity that was not happening.
- **Consequences:** Score version bumps to `scores-v4`, invalidating stale
  `scores-v3` snapshots (recompute on next fetch). No schema migration beyond
  v11's `findings` (ADR-045); `analysis_cache` was already present. The
  frontend already renders `value: null` as "not assessed", so no UI contract
  changed.
- **Status:** Accepted
