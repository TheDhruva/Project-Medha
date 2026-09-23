# VERIFICATION_SPEC.md — Verification + Critic Gate

Status: **TESTED** (Phases 7–9). Runs after CNP and **before** any executor mutate.

Principle: **NEVER EXECUTE AN UNVERIFIED PLAN.**

---

## 1. Roles

| Agent | Job |
|-------|-----|
| Verifier | Hard, mostly deterministic checks. Failures **block** execution. |
| Critic | Structured quality scores + `PASS` / `REPLAN` / `ESCALATE`. |

---

## 2. Pipeline

```
Negotiated plan
  → Schema validation (Pydantic)
  → YAML / configuration validation (PyYAML)
  → Compose structure validation (static; optional `docker compose config`)
  → Security validation (deterministic rules)
  → Optional health validation (off by default / DEMO simulated)
  → Critic scoring
  → PASS | REPLAN | ESCALATE
  → Executor (only if allowed)
```

Bounded replan: maximum **3** verify/plan rounds (`MEDHA_MAX_VERIFY_ROUNDS`). Exceeding the bound → `ESCALATE`.

---

## 3. Verifier checks (V1)

| Category | Examples |
|----------|----------|
| Schema | `ApplicationProfile`, constraints, negotiated / execution plan shapes |
| Config / YAML | Generated compose / nginx fragments parse |
| Compose | Services exist; image/build present; ports/deps structurally valid |
| Security | `SEC-001` privileged=false; host mounts; unsafe caps; public ports |
| Consistency | CNP unresolved conflicts; EXEC_ORDER DAG; required env; local target |

Each check is a `VerificationCheck` (`id`, `category`, `severity`, `rule`, `status`, `message`, …).

`VerificationResult`: `passed`, `checks`, `blocking_failures`, `warnings`, `score`, `replan_count`.

**Gate:** any blocking failure → do not execute.

Docker is **not** required for unit tests; compose validation has a deterministic static fallback.

---

## 4. Critic

### Inputs

- VerificationResult
- Agreed constraints / plan fragments
- Structured profile data only (no invented facts)

### Outputs (`CriticResult`)

- `overall_score`, `security_score`, `completeness_score`, `constraint_score`, `intent_alignment_score` (0–100)
- `recommendation`: `PASS` | `REPLAN` | `ESCALATE` (UI may map REPLAN→WARN, ESCALATE→BLOCK)
- `findings[]`, `summary`

### Deterministic scoring (prototype, not scientific)

Start at 100; deduct for failed checks, warnings, security problems, missing required config, constraint issues. Documented in `backend/app/agents/critic.py`. Works **without** an API key. Optional LLM critic may exist behind an interface later; V1 default is offline.

---

## 5. Implementation map

| Piece | Location |
|-------|----------|
| Verifier | `backend/app/agents/verifier.py` |
| Critic | `backend/app/agents/critic.py` |
| Models | `backend/app/models/execution.py` |
| Workflow gate + replan | `backend/app/workflow/planning.py` |
| API | `GET /api/deploy/{id}/verification` |

---

## 6. Demo

- `VERIFICATION_FAILURE`: force fail → bounded replan → pass → execute (DEMO labelled)
- Real mode intents: `"force verification failure"` / `"missing env"` exercise replan

---

## 7. Limitations

- Not a full container security scanner
- Scores are explainable heuristics for the prototype
- Health checks optional; not required for CI
- No claim of production-grade verification completeness
