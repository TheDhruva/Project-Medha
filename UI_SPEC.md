# UI_SPEC.md — Bright Mode Dashboard

Status: **IMPLEMENTED** (Phase 1 UI with DEMO/MOCK data). Backend wiring is Phase 2–3.

---

## 1. Design direction

Bright Mode should feel:

- bright, modern, technical, premium, clean, minimal
- high information clarity
- **not** generic corporate SaaS
- **not** dark hacker / gaming UI

Typography: expressive, purposeful (avoid default Inter/Roboto/Arial-only stacks when building the real UI).

Atmosphere: subtle gradients or light patterns — not a flat empty white void, and not purple-glow clichés.

---

## 2. Main dashboard regions

The eventual dashboard contains:

1. **MEDHA header** — brand as a strong first-viewport signal
2. **Demo Mode indicator** — unmistakable when active
3. **Repository input**
4. **Target configuration** (host/port; V1 local)
5. **Scenario selector** (demo)
6. **Start Deployment** CTA
7. **Pipeline view** — stage progress
8. **"What MEDHA Is Doing" panel** — plain-language current action
9. **Agent Activity** — which logical agent is active / last result summary
10. **Constraint Negotiation** — conflicts, rounds, resolutions
11. **Verification** — check list
12. **Critic score** — score + findings
13. **Causal Execution Graph** — `@xyflow/react`
14. **Deployment Result**
15. **Rollback Summary**
16. **Live System Trace** — SSE event feed

Phase 1 may lay these out with mock data; wiring comes later.

---

## 3. SIMPLE / TECHNICAL toggle

| Mode | Shows |
|------|-------|
| **SIMPLE** | Plain-language explanations of decisions and current state |
| **TECHNICAL** | Constraint IDs, types, priorities, negotiation rounds, resolution method, verification check ids, CEG dependencies, rollback scope node ids |

Default: SIMPLE for demos; remember toggle in local UI state (no Redux/Zustand required unless necessity appears).

---

## 4. Explainability rules

- Display **observable system events** and **decision reasons**.
- Do **not** display private/internal LLM chain-of-thought.
- Do **not** invent reasoning text that did not come from structured agent/CNP outputs.
- Demo content must remain labelled DEMO/MOCK.

---

## 5. Interaction flow

1. User sets mode (demo/real), scenario (if demo), repo URL, target, intent.
2. Start Deployment → receive `deployment_id`.
3. Subscribe to SSE `/api/deploy/{id}/events`.
4. Poll or fetch snapshots for constraints/graph/result as stages complete.
5. On terminal state, freeze live indicators and show result/rollback.

---

## 6. Visual hierarchy (first viewport)

Prefer one composition:

- Brand (MEDHA)
- Short supporting line of what it does
- Primary controls (repo / mode / start)
- Demo badge if applicable

Avoid dumping all 16 panels into the first viewport with equal weight — progressive disclosure as the run progresses is preferred.

---

## 7. CEG visualization

- Use `@xyflow/react`
- Node states color-coded (success / fail / rolled back / running)
- TECHNICAL mode reveals ids and parent links
- Clicking a node may show metadata + reversible_action summary (no secrets)

---

## 8. Accessibility & responsiveness

- Usable on laptop widths used for viva demos
- Keyboard-focusable primary controls
- Do not rely on color alone for success/fail

---

## 9. Non-goals

- Dark theme as default
- Fake terminal matrix aesthetics
- Heavy dashboard card grids with vanity metrics
- Auth screens in V1
