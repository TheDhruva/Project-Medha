# PROJECT_SCOPE.md — MEDHA V1

Status: **IMPLEMENTED** through Phase 12 polish (prototype scope frozen).

---

## 1. Product Goal

Ship a demonstrable, laptop-friendly prototype that proves:

1. Typed multi-agent **constraint negotiation** before deploy (CNP).
2. **Causal execution tracking** and **scoped rollback** (CEG).
3. Explainable Bright Mode UI over a single FastAPI backend + in-process workflow.

---

## 2. In Scope (V1)

| Area | Notes |
|------|--------|
| Bright Mode web dashboard | Next.js + TypeScript + Tailwind |
| Repository URL input | Real mode later; demo may use fixtures |
| Demo Mode | Deterministic offline scenarios |
| Host preflight | Docker/git/host checks |
| Git repository analysis | Shallow clone + manifests |
| Manifest-based stack inference | Compose/Dockerfile/package manifests |
| Specialist configuration generation | Docker / Nginx / Security proposals |
| Typed constraints | See `CNP_SPEC.md` |
| Constraint Negotiation Protocol | Max 3 rounds |
| Verification | Hard gate before execute |
| Critic | Quality score + structured findings |
| Docker execution | Local Docker SDK |
| Causal Execution Graph | Nodes + dependency edges |
| Scoped rollback | Dependency-aware; preserve independents |
| SQLite persistence | Single-file DB |
| REST API | Deployment lifecycle |
| SSE live events | Per-deployment stream |
| Local Docker host | Only target |
| Testing | Unit/integration/demo scenario tests |
| Evaluation | College-project metrics (later phase) |

---

## 3. Out of Scope (V1)

| Area | Rationale |
|------|-----------|
| DNS automation | Deferred (ADR-008) |
| CI/CD automation | Deferred (ADR-008) |
| Kubernetes / Helm | Overkill for laptop prototype |
| Terraform | Cloud IaC not needed |
| AWS / GCP / Azure deployment | Local-only V1 |
| Remote SSH deployment | Local Docker only (ADR-009) |
| Multi-host / multi-cloud | Complexity / demo risk |
| Multi-user concurrency | Single-operator prototype |
| PostgreSQL | SQLite sufficient (ADR-001) |
| Redis | In-process bus (ADR-002) |
| Kafka / RabbitMQ / Celery | No worker fleet |
| Unnecessary microservices | Monolith process preferred |
| Authentication / multi-tenant IAM | Not required for local demo |
| Sending entire repositories to LLMs | Manifest-focused analysis (ADR-006) |

Do **not** introduce these technologies unless an ADR explicitly changes V1 scope.

---

## 4. Research Must-Haves

These are not optional polish:

1. **CNP** — typed constraints + priority resolution + bounded mediation.
2. **CEG** — causal nodes for execution + dependency-aware rollback.
3. **Explainability** — UI shows decisions/events, not fake CoT.
4. **Demo Mode** — offline deterministic demonstration path.

---

## 5. Quality Bar

- Runnable after each implementation phase (or documented temporary blocker).
- Honest status labels: PLANNED / IN DEVELOPMENT / IMPLEMENTED / TESTED.
- Prefer simple deterministic code over clever abstractions.
- Suitable for low-end laptop demos.

---

## 6. Relationship to Sibling `cadre` Project

`Projects/cadre` overlaps thematically but **conflicts** with MEDHA V1 scope in several ways:

| cadre trait | MEDHA V1 stance |
|-------------|-----------------|
| Redis pub/sub | Forbidden |
| WebSocket events | Use SSE instead |
| DNS + CI agents | Out of scope |
| ~16 agents / more pipeline states | Cap at 10 logical agents |
| Auth / DI emphasis | Avoid premature auth |
| reactflow v11 | Prefer `@xyflow/react` per tech baseline |

**Conflict handling:** Do not rewrite or delete `cadre`. MEDHA lives in `Projects/Medha` as a clean V1 contract. Optional later reuse of ideas must be reimplemented under MEDHA rules, not imported wholesale.

---

## 7. Success Definition for V1 (end of Phase 12)

A reviewer can:

1. Run Demo Mode offline through all five scenarios.
2. See CNP conflict resolution explained in the UI.
3. See a CEG visualization and a scoped rollback on partial failure.
4. (If Docker available) run one real local deployment path.
5. Read specs that match the implemented behavior.
