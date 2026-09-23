# CNP_SPEC.md — Constraint Negotiation Protocol

Status: **IMPLEMENTED (Phase 6 deterministic engine)**. Optional LLM mediation remains available as a future enhancement; V1 uses deterministic_tiebreak when same-priority alternatives are exhausted.

CNP is a **core research contribution** of MEDHA. It runs **before** deployment execution.

---

## 1. Goal

Enable multiple logical agents to publish typed infrastructure constraints and resolve conflicts with:

1. Deterministic priority rules first
2. Alternative search second
3. Bounded LLM mediation only for same-priority deadlocks
4. Hard stop at **3** rounds

---

## 2. Constraint Types (V1)

| Type | Example payload fields |
|------|------------------------|
| `PORT_CLAIM` | `port`, `protocol`, `exclusive` |
| `ENV_VAR` | `key`, `value_policy`, `required` |
| `VOLUME_MOUNT` | `host_path`, `container_path`, `mode` |
| `NETWORK_POLICY` | `network`, `aliases`, `isolation` |
| `SECURITY_POLICY` | `rule`, `enforcement`, `severity` |
| `EXEC_ORDER` | `before`, `after`, `service` |

Each constraint carries a `priority` (see below), `source_agent`, and optional `alternatives`.

---

## 3. Priority Order

```
SECURITY
    >
RESOURCE
    >
DEPENDENCY
    >
PREFERENCE
```

| Priority | Typical use |
|----------|-------------|
| SECURITY | Non-negotiable security policies (no privileged mode, secret handling) |
| RESOURCE | Ports, volumes, CPU/memory-ish claims (ports are RESOURCE in V1) |
| DEPENDENCY | Exec order / startup dependencies |
| PREFERENCE | Nice-to-have naming, optional mounts, cosmetic config |

**Rule:** Higher priority wins over lower priority without LLM.

---

## 4. Negotiation Flow

```
COLLECT
  → VALIDATE
  → GROUP
  → DETECT CONFLICT
  → PRIORITY RESOLUTION
  → ALTERNATIVE SEARCH
  → SAME-PRIORITY LLM MEDIATION
  → VALIDATE DECISION
  → APPLY
  → RECHECK
```

### Stage definitions

1. **COLLECT** — Gather constraints from Docker, Nginx, Security (and others as applicable).
2. **VALIDATE** — Schema/type checks; drop/repair invalid entries with events.
3. **GROUP** — Cluster by resource key (e.g., same port, same env key, same mount target).
4. **DETECT CONFLICT** — Identify incompatible claims within a group.
5. **PRIORITY RESOLUTION** — If priorities differ, accept higher; mark lower rejected/superseded.
6. **ALTERNATIVE SEARCH** — If still conflicted, try declared `alternatives` (e.g., next free port).
7. **SAME-PRIORITY LLM MEDIATION** — Only if same priority and no deterministic alternative works. Structured output required. **No secrets in prompt.**
8. **VALIDATE DECISION** — Ensure decision still schema-valid and does not violate SECURITY constraints.
9. **APPLY** — Update `ConstraintSet` version; emit events.
10. **RECHECK** — Re-run detect on updated set; if clean → done; else next round.

---

## 5. Round Bound

| Parameter | Value |
|-----------|-------|
| `max_rounds` | **3** |
| On exhaustion | `NegotiationResult.status = exhausted` → pipeline fails closed (no execute) |

There must be **no infinite negotiation loop**. LangGraph/state must check `rounds_used < max_rounds` before another cycle.

---

## 6. Conflict Examples

### Port conflict (RESOURCE vs RESOURCE)

- Docker claims `8080`, Nginx claims `8080`.
- Alternative search assigns Nginx `8081` if listed/available.
- If no alternative and same priority → optional LLM mediation proposing a port remap (validated).

### Security vs preference

- Security forbids privileged container; Docker preference requests privileged.
- SECURITY wins immediately; no LLM.

### Exec order

- Backend must start before frontend (`EXEC_ORDER`).
- Conflicts with an opposite order from another agent → DEPENDENCY priority / deterministic topological resolution preferred over LLM.

---

## 7. LLM Mediation Contract

**When allowed:** same-priority conflict after alternatives exhausted, rounds remaining.

**Input (conceptual):** sanitized constraint pair/group, allowed alternative space, priority, non-secret metadata.

**Output (conceptual JSON):**

```json
{
  "decision": "accept_a" | "accept_b" | "compromise",
  "winning_constraint_ids": [],
  "updates": [],
  "rationale": "short observable reason"
}
```

Validate with Pydantic. On invalid output: retry once or fail the round deterministically (document choice in implementation ADR if needed). **Never** show private chain-of-thought in UI — only `rationale` / decision fields.

---

## 8. Events (observable)

Emit `SystemEvent`s such as:

- `constraint.collected`
- `constraint.conflict_detected`
- `constraint.resolved_priority`
- `constraint.resolved_alternative`
- `constraint.mediated_llm`
- `constraint.round_completed`
- `constraint.negotiation_exhausted`

All demo events set `is_demo=true`.

---

## 9. API / UI Surfaces

- `GET /api/deploy/{id}/constraints` returns constraints + negotiation summary.
- UI Constraint Negotiation panel shows IDs, types, priorities, rounds, resolution method (TECHNICAL mode).

---

## 10. Non-goals

- Distributed consensus protocols
- Redis-backed constraint bus
- Cross-host negotiation
- Unbounded multi-agent debate threads
