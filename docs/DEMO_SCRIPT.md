# DEMO_SCRIPT.md — 5–10 Minute Presentation

**Goal:** Show the research story, not every implementation detail.

**Prep (2 minutes before):**

1. Backend: `uvicorn app.main:app --reload --host 127.0.0.1 --port 8000`
2. Frontend: `npm run dev` → `http://localhost:3000`
3. Optional: pre-run `python -m app.evaluation.run_all` so `/evaluation` has numbers
4. UI: **Simple** mode for talk track; flip to **Technical** once per conflict

---

## PART 1 — Introduction (30–45s)

> “DevOps multi-agent systems often collide on ports and security, execute unverified plans, and roll back everything when one service fails. MEDHA negotiates typed constraints, verifies before execute, tracks causality in a graph, and rolls back only the affected branch.”

Point at header: **LOCAL HOST** · **DEMO MODE**.

---

## PART 2 — Successful deployment (~1.5 min)

1. Mode: **Demo**
2. Scenario: **SUCCESSFUL_DEPLOYMENT**
3. Start Deployment

Show briefly: pipeline stages → agents → constraints → verification PASS → critic → execution SUCCESS → result.

**Say:** “Happy path: negotiate, verify, execute, no rollback.”

---

## PART 3 — Port conflict (~1.5 min)

Scenario: **PORT_CONFLICT**

Show: two port claims → conflict → resolution (priority/alternative) → verification → success.

Toggle **Technical** once: constraint IDs / method.

**Say:** “Conflict is resolved *before* execution—not discovered after containers start.”

---

## PART 4 — Verification failure (~1.5 min)

Scenario: **VERIFICATION_FAILURE**

Show: verification FAIL → bounded replan → verification PASS → execute.

**Say:** “We never execute an unverified plan; replan is capped so it cannot loop forever.”

---

## PART 5 — Core research demo (~3 min) — PARTIAL_FAILURE

Scenario: **PARTIAL_FAILURE**

Watch CEG:

| Service | Status |
|---------|--------|
| Network | ✓ preserved |
| Database | ✓ preserved |
| Backend | ✕ failed |
| Frontend | ↶ rolled back |
| Analytics | ✓ preserved |

Narrate panel sequence:

1. **FAILURE DETECTED** — Backend failed  
2. **DEPENDENCY ANALYSIS** — Frontend depends on Backend  
3. **ROLLBACK SCOPE** — Frontend  
4. **PRESERVED** — Network, Database, Analytics  
5. **SCOPED ROLLBACK COMPLETE**

**Say:** “Traditional automation would tear down the whole stack. MEDHA preserves independent success.”

---

## PART 6 — Evaluation (~1 min)

Open **Evaluation** (`/evaluation`).

Show measured CNP / CEG panels (from API artifacts).

**Say carefully:**

> “On these seeded cases, CNP resolved the expected conflicts, and scoped rollback rolled back fewer nodes than a global-rollback baseline. These are project-defined measures—not a claim that MEDHA is universally superior.”

---

## If asked about Real Mode / Docker

- Real Mode runs analysis → CNP → verify → execute.
- Docker mutate requires `MEDHA_DOCKER_EXECUTE=true` and a local daemon.
- If Docker was unavailable during development: **say so**—do not claim E2E Docker passed.

---

## Close (15s)

> “Prototype: typed CNP, pre-execution verification, CEG, scoped rollback, and measured evaluation—local, deterministic, and honest about limits.”
