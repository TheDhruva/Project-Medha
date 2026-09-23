# AGENTS.md — MEDHA Permanent Development Rulebook

Read this file before making any changes to MEDHA.

MEDHA is a college major-project prototype:

> Constraint-Negotiating Multi-Agent Architecture for Verifiable DevOps Automation

Priority order: **WORKING > CLEVER**, **SIMPLE > OVER-ENGINEERED**, **DETERMINISTIC > UNNECESSARY LLM CALLS**, **LOCAL > CLOUD**, **DEMONSTRABLE > THEORETICALLY COMPLETE**.

---

## Permanent Rules

1. **Read AGENTS.md before making changes.**
2. **Inspect existing code before modifying it.**
3. **Never rewrite working code without justification.** Document conflicts instead of silently replacing behavior.
4. **Implement only the requested phase.** Do not pull work from later phases into the current one.
5. **Do not implement future phases prematurely.** Scaffolding and contracts are fine; runtime features wait for their phase.
6. **Keep MEDHA suitable for a low-end laptop.** Prefer SQLite, in-process orchestration, local Docker, and modest resource use.
7. **Prefer deterministic logic over unnecessary LLM calls.** Use LLMs only where structured reasoning adds clear value (e.g., same-priority CNP mediation).
8. **LLM outputs must be structured and validated** (Pydantic / JSON schema). Reject or retry invalid outputs; never trust free-form text as executable truth.
9. **Never expose secrets/API keys to LLM prompts.** Redact tokens, env secrets, and credentials from any model context.
10. **Never fabricate execution results.** Real Docker/git/network outcomes must reflect reality. Simulated outcomes are allowed only in Demo Mode and must be labelled.
11. **Demo results must be explicitly labelled DEMO/MOCK** in API payloads, SSE events, and UI.
12. **CNP is a core research component.** Do not dilute, bypass, or stub it out of the real pipeline without an ADR.
13. **CEG is a core research component.** Every meaningful execution action must eventually become a CEG node.
14. **Negotiation must have bounded rounds.** V1 maximum is **3** rounds. No infinite negotiation loops.
15. **Rollback must be dependency-aware** using CEG causal/dependency edges.
16. **Preserve independent successful services** during rollback when they are causally independent of the failure.
17. **Avoid unnecessary dependencies.** Every new package needs a concrete V1 reason.
18. **Avoid unnecessary infrastructure.** One FastAPI process + one Next.js app + local Docker is enough for V1.
19. **No Redis in V1.** Use in-process structures / SQLite for coordination and events.
20. **No PostgreSQL in V1.** SQLite only.
21. **No Kubernetes in V1.**
22. **No DNS automation in V1.**
23. **No CI/CD automation in V1.**
24. **No remote deployment in V1.** Local Docker host only.
25. **Run relevant tests after implementation.**
26. **Never claim functionality has been implemented unless it has actually been tested.**
27. **Keep architecture documentation synchronized with implementation.**
28. **Do not expose fake LLM chain-of-thought in the UI.** Show observable system events and decision reasons only.
29. **UI should display observable system events and decision reasons** (constraint IDs, priorities, resolution method, verification outcomes, CEG edges, rollback scope).
30. **Every implementation phase must leave the project runnable** (or clearly document temporary blockers).

---

## Logical Agents (not separate services)

V1 logical agents are lightweight Python classes/functions (optionally modelable as graph nodes):

1. Preflight Agent  
2. Code Analyzer Agent  
3. Docker Agent  
4. Nginx Agent  
5. Security Agent  
6. Mediator / Constraint Negotiator  
7. Verifier Agent  
8. Critic Agent  
9. Executor Agent  
10. Rollback Agent  

Do **not** create ten processes, workers, queues, or microservices for these.

---

## Phase Discipline

| Status meaning | Definition |
|----------------|------------|
| PLANNED | Documented only |
| IN DEVELOPMENT | Partially coded, not ready to claim done |
| IMPLEMENTED | Code exists and runs |
| TESTED | Covered by automated or documented manual tests |

Current status: **PHASE 12 — FINAL POLISH + DOCUMENTATION + VIVA PACKAGING** (TESTED).

When starting a phase:

1. Re-read this file and the phase section in `DEVELOPMENT_PLAN.md`.
2. Confirm out-of-scope items for that phase.
3. Implement only listed acceptance criteria.
4. Update status labels honestly in `README.md` / `DECISIONS.md` if needed.

---

## Sibling Project Note

A related project (`cadre`) exists under `Projects/`. It explores overlapping DevOps multi-agent ideas but **is not MEDHA**. Do not copy Redis, DNS, CI, WebSocket, or multi-service patterns from it into MEDHA V1 without an explicit ADR that overrides the V1 scope.
