# CIG_SPEC.md — Change Intelligence (Phase 12/2)

The **Change Impact Graph (CIG)** is MEDHA's Phase 2 research contribution: a
deterministic, evidence-based map of *repository dependency impact* produced by
a git change set (`base_revision → target_revision`).

> **CIG ≠ CEG.** The Causal Execution Graph (CEG, `CEG_SPEC.md`) describes
> *runtime execution causality* between deployed services (who depends on whom
> at container level, used for rollback). The CIG describes *source dependency
> impact* between repository artifacts (which files changed → which files are
> affected → what must be reverified). The two never share node/edge storage and
> render in the UI as separate, visually distinct graphs.

## 1. Pipeline

```
git base_revision … target_revision
  → ChangeSet (files, hunks, counts, unsupported)
  → file symbols + imports  (AST for Python; regex for JS/TS; parsers for YAML/JSON)
  → base-side symbols from git blobs (deleted/renamed detection)
  → changed symbols (ADDED / MODIFIED / DELETED at symbol level)
  → CIG nodes + edges (every edge carries evidence + confidence)
  → impact traversal (direct / transitive dependents, cycles, depth ≤ 3)
  → risk assessment (composite of evidence-based factors)
  → verification requirements (mapped to existing verifier check categories)
  → persisted artifact (deployments.change_intel_json) + UI display
```

No LLM is used at any stage. Every edge is backed by a concrete repository
reference (`file:line import x`). Unresolved dependencies are reported as
**unresolved** — never invented.

## 2. Graph semantics

- **Node** = a repository file (`path`) or a symbol (`symbol_id`) inside one.
  Roles: `changed` (touched by the change set), `affected` (depends on a
  changed artifact), `context` (depends on an affected artifact), `test`
  (test file covering changed/affected), `config` (config whose meaning depends
  on changed artifacts).
- **Edge direction** = *source depends on target*.
- **Impact** = reverse reachability: from a changed node, walk its dependents.
  Bounded to `max_depth = 3`, cycle-safe.
- **Edge relationship types emitted in V1**: `import`, `api-consumer`,
  `schema-consumer`, `configuration-dependency`, `test-covers`, `inherits`.
  (`call`/`reference`/`extends`/`implements`/`unknown` exist in the enum but are
  NOT emitted in V1 — this report must state that explicitly.)
- **Confidence**: `HIGH` = Python AST import resolved to a repo file; `MEDIUM`
  = config/JSON/YAML reference; `HEURISTIC` = JS/TS regex.

## 3. Unresolved dependencies

| `kind` | Meaning |
|--------|---------|
| `import` | bare/relative import that could not be mapped to a repo file |
| `require` | JS/TS require that could not be resolved |
| `deleted-import` | import target was deleted by the change set (high-signal breakage) |

Stdlib imports are recognized via `sys.stdlib_module_names` and are **not**
flagged as unresolved (a known dependency, not a breakage signal).

## 4. Risk assessment

Composite of evidence-based factors; overall level = highest factor:

| code | level |
|------|-------|
| `deleted_artifacts_with_dependents` | HIGH |
| `renamed_artifacts` | MEDIUM |
| `large_blast_radius` | MEDIUM (≥5 dependents) / HIGH (≥10) |
| `api_contract_exposure` | MEDIUM |
| `schema_consumers` | MEDIUM |
| `configuration_dependencies` | MEDIUM |
| `unresolved_dependencies` | MEDIUM |
| `dependency_cycle` | MEDIUM |
| `inheritance_base_modified` | MEDIUM |
| `test_coverage_gap` | LOW |
| `sizeable_changeset` | LOW (>10 files) |

## 5. Verification requirements

Each requirement maps to an existing verifier check category (`schema`, `config`,
`compose`, `security`, `constraints`, `preflight`). `executable=True` (status
`executable`) only for config changes the existing verifier can actually run;
source-level checks are recorded as `executable=False` / `identified` — never
faked as already-verified.

## 6. Scope (Phase 12/2)

- **Supported:** local git repositories only (`file://` or a local path).
  Remote URLs are rejected with `NOT_LOCAL_REPOSITORY` (analysed in Phase 3).
- **Languages:** Python (AST, structural), JS/TS (regex, heuristic), YAML/JSON
  (config references). Everything else is `unsupported` and reported.
- Static analysis only. Repository code is never executed.
- Source of truth is the **original local repo path** (the acquired deployment
  workspace strips history via shallow clone).

## 7. API (summary; contract in `API_CONTRACT.md`)

- `POST /api/change-impact/analyze` — live deterministic analysis.
- `GET /api/deploy/{id}/change-impact` — persisted analysis on a deployment.
- `GET /api/change-impact/demo/fixture` — canned, clearly DEMO/MOCK fixture.

Demo results are always labelled `DEMO/MOCK` in JSON and UI.