# VIVA_GUIDE.md — MEDHA Oral Examination Notes

Concise answers aligned with the **actual** implementation. Do not invent capabilities.

---

## 1. What is MEDHA?

A local prototype for **constraint-aware, verifiable DevOps automation**: negotiate typed constraints, verify before execute, track causality in a graph, and roll back only the affected branch.

## 2. What problem does it solve?

Agent/LLM DevOps systems often conflict on resources, execute unverified plans, and roll back too broadly. MEDHA makes negotiation, verification, and scoped recovery explicit and demonstrable.

## 3. Why multi-agent?

Different concerns (Docker, proxy, security) produce different constraints. Separating specialists makes conflicts visible as typed objects rather than one opaque blob of text.

## 4. Why not one LLM?

Infrastructure rules must be **reproducible**. Port conflicts and priority order are handled by deterministic logic. An LLM is optional for ambiguous same-priority cases—not the default for every decision.

## 5. What is CNP?

**Constraint Negotiation Protocol** — collect typed constraints → detect conflicts by resource key → resolve by priority / alternative / deterministic tiebreak → max 3 rounds.

## 6. Why are constraints typed?

So conflicts are machine-checkable (`PORT_CLAIM` vs free-form prose) and explainable in the UI (IDs, priorities, methods).

## 7. How are conflicts detected?

Constraints share a `resource_key` (e.g. `port:8080`, `env:DATABASE_URL`, `policy:external_access`). Incompatible groups become conflicts.

## 8. Why does SECURITY have highest priority?

Unsafe exposure (e.g. unrestricted network) must outrank convenience preferences. Rank: `SECURITY > RESOURCE > DEPENDENCY > PREFERENCE`.

## 9. Equal priority?

Try alternatives (e.g. alternate ports), then **deterministic_tiebreak**. LLM mediation is optional and not required for V1 demos.

## 10. Why is LLM optional?

₹0 / offline demos, reproducibility, and laptop constraints. Core CNP/CEG/verification/rollback work without an API key.

## 11. What is CEG?

**Causal Execution Graph** — nodes = meaningful actions; edges = depends-on. Source of truth for execution order and rollback scope.

## 12. Why a graph?

Linear logs cannot distinguish “depends on failed service” from “independent success.” The graph encodes that distinction.

## 13. Why not rollback everything?

Global cleanup destroys healthy independent work (e.g. analytics). Scoped rollback is the research claim under test.

## 14. How does scoped rollback work?

Failed node → traverse **downstream** dependents → rollback reversible dependents in reverse topo order → preserve ancestors and independents.

## 15. How is verification performed?

Deterministic checks: schema, YAML/compose structure, security rules, CNP consistency, required env, local target. Failure blocks execution.

## 16. What does the Critic do?

Scores the plan (security/completeness/constraints/intent) and recommends `PASS` / `REPLAN` / `ESCALATE`. Prototype heuristics—not a scientific metric.

## 17. Why verification before execution?

**Never execute an unverified plan.** Mistakes are cheaper to catch before Docker mutate.

## 18. How does MEDHA handle failure?

Mark failed CEG node → stop dependents → compute `RollbackScope` → roll back affected branch → report preserved services. Docker path only touches MEDHA-labeled resources.

## 19. What is Demo Mode?

Deterministic offline fixtures for five scenarios; labelled `DEMO/MOCK`. No GitHub/Docker/LLM required.

## 20. What is Real Mode?

Local analysis → CNP → verify → execute. Default executor is simulator; set `MEDHA_DOCKER_EXECUTE=true` for local Docker mutate of controlled plans.

## 21. Limitations?

Opt-in Docker; one real deploy at a time; no K8s/cloud/SSH/DNS/CI; not arbitrary GitHub auto-deploy; evaluation is project-defined; Demo is simulated.

## 22. What did evaluation measure?

Seeded CNP cases (conflict detection/resolution/rounds) and CEG cases (rollback scope vs `GLOBAL_ROLLBACK` baseline, preserved nodes).

## 23. What is the baseline?

**GLOBAL_ROLLBACK** — on failure, roll back all other deployment nodes. Compared to **MEDHA_SCOPED_ROLLBACK**.

## 24. Measured results?

Use **current** `backend/data/evaluation/*_latest.json` after running runners. Do not recite stale numbers from memory. Typical recent run: CNP 8/8, CEG 5/5 with fewer MEDHA rollback nodes than global baseline on those fixtures.

## 25. Future work?

Phase-12 scope stops here. Reasonable future (not implemented): deeper Docker health/HTTP checks, larger evaluation corpora, optional structured LLM mediation—still local-first.

---

## Key differentiation (30 seconds)

**Traditional:** plan → execute → failure → broad cleanup  

**MEDHA:** plan → negotiate constraints → verify → execute → CEG → failure → trace affected branch → scoped rollback → preserve independents

## LLM is not everything

MEDHA does not delegate every decision to an LLM. Deterministic infrastructure constraints such as port conflicts and priority rules use explicit logic because these decisions must be reproducible and verifiable. LLM mediation is optional for ambiguous same-priority conflicts.
