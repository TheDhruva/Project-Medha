# EVALUATION.md — MEDHA Experiment Design (Phase 11–12)

Status: **IMPLEMENTED**. Results below are verified against `backend/data/evaluation/*_latest.json` when last refreshed. **Re-run runners before viva** and prefer artifact values over this snapshot.

Academic honesty: distinguish **implemented capability**, **measured result**, and **not supported**.

---

## 1. Goals

Measure (prototype / **project-defined**):

1. Constraint conflict detection & resolution (CNP)
2. Negotiation rounds
3. CEG rollback scope vs global baseline
4. Preservation of independent nodes
5. Verification / replan / execution outcomes (pytest + planning tests)

These are **not** established academic benchmarks and do **not** prove universal superiority.

---

## 2. How to run

```powershell
cd backend
.\.venv\Scripts\python.exe -m app.evaluation.run_cnp
.\.venv\Scripts\python.exe -m app.evaluation.run_ceg
.\.venv\Scripts\python.exe -m app.evaluation.run_all
.\.venv\Scripts\python.exe -m pytest tests -q
```

Artifacts: `backend/data/evaluation/{cnp,ceg,combined}_latest.json`  
UI: `http://localhost:3000/evaluation`

---

## 3. CNP dataset

**8** fixed cases in `backend/app/evaluation/datasets/cnp_cases.py`:

| Category | Examples |
|----------|----------|
| No conflict | Compatible port + security |
| Port conflict | Docker vs Nginx same port |
| Security vs preference | Same policy rule, different modes |
| Environment conflict | Same `ENV_VAR` key, different values |
| Volume conflict | Same host path, different container paths |
| Dependency | Compatible `EXEC_ORDER` |
| Same-priority | Two RESOURCE port claims |
| Multi-conflict | Port + security together |

Each case declares `expected_conflict` and `expected_status`.

---

## 4. CEG dataset + baseline

**5** graphs in `backend/app/evaluation/datasets/ceg_cases.py` (e.g. `A→B→C` + independent `D`; network→db→backend→frontend + analytics).

**Baseline `GLOBAL_ROLLBACK`:** on failure, roll back all other deployment nodes.  
**MEDHA `SCOPED_ROLLBACK`:** downstream dependents only.

Project-defined `scope_efficiency = rollback_nodes / active_nodes` — **not** an established academic metric.

---

## 5. Measured results (artifact snapshot)

Verified from latest JSON on the development machine (refresh if you re-run):

### CNP (`cnp_latest.json`)

| Metric | Value |
|--------|------:|
| total_cases | 8 |
| passed | 8 |
| failed | 0 |
| conflicts_detected | 7 |
| conflicts_resolved | 7 |
| conflict_resolution_rate | 1.0 |
| average_rounds | 1.0 |

**Interpretation:** The implemented CNP correctly handled these seeded cases (detection + resolution within round limits). Not a claim about all real-world conflicts.

### CEG (`ceg_latest.json`)

| Metric | Value |
|--------|------:|
| total_cases | 5 |
| passed | 5 |
| failed | 0 |
| medha_rollback_nodes_total | 5 |
| global_rollback_nodes_total | 17 |
| preserved_nodes_total | 12 |
| mean_scope_efficiency | 0.24 |

**Interpretation:** On these fixtures, scoped rollback used fewer rollback nodes than the global baseline and preserved independent branches as expected. Not proof of optimality.

### Backend pytest (last full suite)

Report from Phase 12 validation run — see final report for exact counts. Docker-marked tests skip when the daemon is missing.

### Docker E2E

If Docker is unavailable: **SKIPPED — Docker unavailable.** Do not claim pass.

---

## 6. Limitations

- Seeded, small datasets
- Project-defined rates
- Simulator covers CEG logic without Docker
- Docker mutate path is opt-in and host-dependent
