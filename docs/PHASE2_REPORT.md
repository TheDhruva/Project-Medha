# PHASE 12/2 REPORT — Change Intelligence (CIG)

**Project:** MEDHA — Constraint-Negotiating Multi-Agent Architecture for Verifiable DevOps Automation
**Phase:** 12/2 (internal phase 2) — Final polish + documentation pass
**Scope doc:** `CIG_SPEC.md` · **Driving principles:** WORKING > CLEVER, DETERMINISTIC > UNNECESSARY LLM CALLS, EVIDENCE > INVENTION, LOCAL > CLOUD

---

## 1. Summary

MEDHA's Phase 2 adds a **Change Impact Graph (CIG)** — a deterministic,
evidence-based change-intelligence pipeline that turns a git revision pair
(`base_revision → target_revision`) into a ChangeSet (files, hunks, counts),
symbol-level diffs, dependency edges with concrete `file:line` evidence and
confidence, an impact traversal (direct/transitive, depth ≤ 3, cycle-safe), a
composite **risk**, and **verification requirements** mapped to the existing
verifier categories. Results are persisted on the deployment record (schema v2)
and surfaced to the UI as a **separate, visually distinct graph from the CEG**.
No LLM is used at any stage.

Verdict: **COMPLETE** (details in §13).

---

## 2. Goal

Provide deterministic, explainable *"what changed → what depends on it → what
must be re-verified"* analysis before a deployment executes, so MEDHA can flag
high-risk change sets with concrete evidence. The feature must:
- work **offline** on a low-end laptop against a **local git repository**;
- never fabricate dependency facts (unresolved imports are reported);
- keep the research claim **CIG ≠ CEG** explicit in data and UI;
- feed the existing verifier instead of replacing it.

---

## 3. Deliverables

| # | Deliverable | Status |
|---|-------------|--------|
| 3.1 | `backend/app/changeintel/` engine modules (models, git_extract, symbols, dep_index, cig, risk, requirements, engine) | IMPLEMENTED + TESTED |
| 3.2 | SQLite schema v2 (`change_intel_json`, `base_revision`, `target_revision`, `PRAGMA user_version=2`) | IMPLEMENTED + TESTED |
| 3.3 | API: `POST /api/change-impact/analyze`, `GET /api/deploy/{id}/change-impact`, `GET /api/change-impact/demo/fixture` | IMPLEMENTED + TESTED |
| 3.4 | Real pipeline hook: ANALYZE-stage `_run_change_intel` (SSE event carries `data.change_intel`) | IMPLEMENTED + TESTED |
| 3.5 | Demo fixture `change_intel_demo()` (canned, labelled DEMO/MOCK) | IMPLEMENTED + TESTED |
| 3.6 | 11 git fixture repos (`tests/fixtures/change_intel/_build.py`) | IMPLEMENTED + TESTED |
| 3.7 | Backend tests: 22 change-intel tests; full-chain integration; full regression **75 passed / 2 skipped** | TESTED |
| 3.8 | Frontend: CIG types, client fns, SSE mapper, `ChangeImpactPanel` (React Flow), layout util, research callout | IMPLEMENTED + TESTED |
| 3.9 | Frontend tests: **28 passed**; `tsc --noEmit`, `next lint`, `next build` green | TESTED |
| 3.10 | Docs: `CIG_SPEC.md`, API contract §9, ADR-018/019, READMEs, this report | COMPLETE |

---

## 4. Architecture

```
Local git repo (base…target ─ source of truth; the acquired shallow clone is NOT used)
   git diff / show ─────────────► extract_changeset()
                                          │ files, hunks, counts, unsupported, SHAs
   working tree scan ───────────► build_index()          symbols + imports (AST/regex/YAML/JSON)
   base-side blobs ─────────────► _build_base_side()     symbols for deleted/renamed/modified
                                          │
   detect_changed_symbols() ◄──── passed base_side (deleted MODULE/CLASS/FUNC/METHOD detection)
   build_cig()                  edges: import, api-consumer, schema-consumer,
                                          configuration-dependency, test-covers, inherits
   ImpactTraversal              direct/transitive dependents, cycles, depth ≤ 3
   assess_risk()                composite of evidence-based factors
   generate_requirements()      mapped to verifier categories (schema/config/compose/security/constraints/preflight)
   ChangeImpactAnalysis ──────► to_ui() ──► API / SSE / change_intel_json
```

**Static analysis only.** Repository code is never executed; git commands run
via `git_extract` with hard timeouts. No network in the analysis path.

---

## 5. Key decisions

| Decision | Why |
|----------|-----|
| No LLM authority; deterministic everywhere | Evidence must not be hallucinated; AGENTS.md rule 7 |
| Every edge carries `relationship + evidence + confidence` | Observable decision reasons (rule 29) |
| Local git only; remote → `NOT_LOCAL_REPOSITORY` | V1 scope; remote analysis is a Phase 3 item |
| CIG row on `deployments` (schema v2), no ORM | SQLite-only invariant; deployment→analysis linkage |
| Stdlib imports not flagged unresolved | `sys.stdlib_module_names` — known dep, not a breakage signal |
| Deleted module still imported → `deleted-import` + HIGH risk | High-signal breakage surfaced, not hidden by synthetic re-indexing |
| Synthetic re-indexing of deleted files removed | It created fabricated edges (bug found in full-chain testing) |
| `file:line` terminal evidence for all edges | Traceability across report/UI/viva |

**Contracts not emitted in V1** (must be stated): `call`, `reference`,
`extends`, `implements`, `unknown` exist in the enum but no path emits them —
`inherits` is emitted for class-base relations; JS/TS is heuristic-only.

---

## 6. Graph & evidence model

- **Nodes:** `path` (file) or `symbol_id` (symbol); roles `changed` / `affected`
  / `context` / `test` / `config`.
- **Edges:** source depends on target. Confidence = `high` (Python AST resolved
  to a repo file), `medium` (config/YAML/JSON reference), `heuristic` (JS/TS regex).
- **Unresolved:** `import`, `require`, `deleted-import`, each with `path:line`,
  `target`, and an honest `reason`.
- **CIG ≠ CEG guarantee:** separate storage (`change_intel_json`), separate
  graph shape, separate React Flow renderer with a distinct palette, edge
  labels, and title. A CIG node is never inserted into the CEG and vice versa.

---

## 7. Risk model

Composite of factors; overall = highest factor. `deleted_artifacts_with_dependents`
HIGH · `renamed_artifacts` MEDIUM · `large_blast_radius` MEDIUM(≥5)/HIGH(≥10) ·
`api_contract_exposure` MEDIUM · `schema_consumers` MEDIUM ·
`configuration_dependencies` MEDIUM · `unresolved_dependencies` MEDIUM ·
`dependency_cycle` MEDIUM · `inheritance_base_modified` MEDIUM ·
`test_coverage_gap` LOW · `sizeable_changeset` LOW(>10 files). Example: a
deleted module still imported by a live file yields HIGH.

---

## 8. Verification requirements

Each requirement maps to an existing verifier check category and records
`executable` honestly: only config changes get `executable=True` / status
`executable` (the verifier can truly run them); source-level checks are
`executable=False` / `identified`. The UI renders
"source-level check (not faked)" — a deliberate anti-overclaiming feature.

---

## 9. API & persistence

- **POST** `/api/change-impact/analyze` — deterministic live analysis; optional
  `deployment_id` persists onto the deployment. Errors: `NOT_A_GIT_REPOSITORY`,
  `NOT_LOCAL_REPOSITORY`, `REPO_NOT_FOUND`, `REVISION_INVALID`,
  `REVISION_NOT_FOUND`, `IDENTICAL_REVISIONS` → 400; `GIT_*` → 500.
- **GET** `/api/deploy/{id}/change-impact` — persisted analysis (`NOT_FOUND` /
  `CHANGE_INTEL_NOT_FOUND` as 404).
- **GET** `/api/change-impact/demo/fixture` — canned fixture, `is_demo: true`,
  `label: "DEMO/MOCK"`.
- Pipeline hook `_run_change_intel` (ANALYZE stage): runs only when
  base/target revisions exist AND the repo URL is local; anything else emits an
  honest skip event (`change_intel=not_computed`). Results are stored via
  `save_artifacts(change_intel=...)` and streamed to the UI in `data.change_intel`.

---

## 10. UI

`ChangeImpactPanel` renders the CIG as its own React Flow graph (distinct
palette, edge labels with relationship + confidence, dashed heuristic edges), a
risk badge, change counts, changed files, direct/transitive impact + cycles,
unresolved deps, **edge evidence list**, and verification requirements with
executable status. Idle state offers a labelled **"Load demo fixture"** button.
The research callout row adds a CIG card, and the SSE mapper routes
`data.change_intel` into `snapshot.changeIntel`. DEMO/MOCK is always labelled.

---

## 11. Test evidence

Backend: `cd backend && pytest -q` → **75 passed, 2 skipped (Docker)**
(after `_build.py` regenerates the 11 fixture repos). Frontend:
`npm test` → **28 passed**; `tsc --noEmit`, `npm run lint`, `npm run build` green.

**Fixture-based expectations (each verified end-to-end via the engine):**

| Fixture | Expected | Verified |
|---------|----------|----------|
| simple_import | LOW risk; import edge with HIGH confidence | ✓ |
| multi_level | LOW; transitive c.py via a.py→b.py | ✓ |
| unrelated_file | LOW; no edges | ✓ |
| deleted_symbol | HIGH; symbol DELETED inside MODIFIED file | ✓ |
| added_file | LOW | ✓ |
| rename | MEDIUM; `renamed_artifacts` factor | ✓ |
| cycle | MEDIUM; `dependency_cycle` a.py↔b.py | ✓ |
| dynamic_import | MEDIUM; unresolved `plugin_catalog` | ✓ |
| api_consumer | MEDIUM; `api-consumer` edge evidence | ✓ |
| verification_req | LOW; config edge + executable requirement | ✓ |
| delete_import_chain | HIGH; `deleted-import` surfaced, not fabricated | ✓ |

**Full-chain integration test** (`TestFullChainIntegration`): builds the
`delete_import_chain` repo → POST `/api/change-impact/analyze` → asserts counts
(`deleted: 1`), unfabricated `deleted-import` unresolved, risk HIGH, honest
non-executable requirements → persists → GET reads the same record.

This suite is exactly what caught the two real bugs shipped this phase
(§5: synthetic re-indexing and the `deleted-import` fall-through).

---

## 12. Limitations — Phase 2 vs Phase 3

**Phase 2 (this deliverable) accepts:** local git only; revisions required;
Python structural, JS/TS heuristic, YAML/JSON config refs; static analysis only;
`call`/`reference`/`extends`/`implements`/`unknown` not emitted; no auto-remediation
— MEDHA reports risk and requirements but does not self-modify the plan from CIG.

**Deferred to Phase 3 (not in scope now):** remote/HTTPS/GitHub analysis ·
webhook/PR triggers · branch-aware shadowing of unpushed commits · deeper
in-symbol references (call graphs, full AST type flow) · Maven/npm/Go ecosystem
resolution · CIG feedback into the verifier gate (e.g., blocking HIGH-risk
deploys) · merge-request comments · historical trend/risk telemetry.

Phase 2 results are honest about everything it cannot resolve — that is a
feature, not a stub.

---

## 13. Final verdict

**COMPLETE.** All acceptance criteria implemented and tested: deterministic
engine, schema v2 migration, typed API with uniform error shape, demo fixture
labelled DEMO/MOCK, pipeline integration with honest skips, 11 fixture repos,
22 backend tests + full-chain integration, 28 frontend tests, green regression
(backend 75/2-skipped; frontend test/tsc/lint/build), and synchronized
documentation (`CIG_SPEC.md`, API contract §9, ADRs 018–019, READMEs, this
report). No durability blockers remain.

**Files touched (new):** `backend/app/changeintel/*`, `backend/app/api/change_impact.py`,
`backend/app/demo/fixtures.py` (`change_intel_demo`), `backend/app/workflow/planning.py`
(`_run_change_intel`), `backend/app/database/schema.sql` + `connection.py` +
`repositories.py`, `backend/app/models/deployment.py`, `backend/tests/test_change_intel.py`,
`backend/tests/fixtures/change_intel/_build.py` (+ 11 built repos), frontend
`ChangeImpactPanel.tsx` + `test`, `lib/changeintel/layout.ts`, `lib/api/client.ts`
+ `client.test.ts`, `lib/api/eventMapper.ts` (+ test), `lib/demo/types.ts`,
`ResearchCallouts.tsx`, `Dashboard.tsx`, `CIG_SPEC.md`, `docs/PHASE2_REPORT.md`.