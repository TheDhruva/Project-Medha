"""Constraint Negotiation Protocol engine (Phase 6)."""

from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from uuid import uuid4

from app.core.logging import get_logger
from app.models.domain import (
    PRIORITY_RANK,
    ConflictRecord,
    Constraint,
    ConstraintStatus,
    ConstraintType,
    DecisionRecord,
    NegotiationResult,
    Priority,
)

logger = get_logger(__name__)

MAX_ROUNDS = 3


def run_cnp(
    deployment_id: str,
    constraints: list[Constraint],
    *,
    max_rounds: int = MAX_ROUNDS,
    is_demo: bool = False,
) -> NegotiationResult:
    """
    Deterministic CNP:
    collect → validate → group → detect → priority → alternative → tiebreak → apply → recheck

    LLM mediation is optional and not required for V1; same-priority deadlocks use
    deterministic_tiebreak so the laptop/demo path stays ₹0 and offline-capable.
    """
    working = _validate([deepcopy(c) for c in constraints])
    all_conflicts: list[ConflictRecord] = []
    decisions: list[DecisionRecord] = []
    rounds_used = 0

    for round_idx in range(1, max_rounds + 1):
        rounds_used = round_idx
        conflicts = detect_conflicts(working)
        if not conflicts:
            for c in working:
                if c.status == ConstraintStatus.PROPOSED:
                    c.status = ConstraintStatus.ACCEPTED
            return NegotiationResult(
                deployment_id=deployment_id,
                status="resolved",
                rounds_used=rounds_used if decisions else 1,
                max_rounds=max_rounds,
                conflicts=all_conflicts,
                decisions=decisions,
                final_constraints=working,
                is_demo=is_demo,
            )

        all_conflicts.extend(conflicts)
        for conflict in conflicts:
            decision = resolve_conflict(working, conflict)
            decisions.append(decision)
            apply_decision(working, decision)

        remaining = detect_conflicts(working)
        if not remaining:
            for c in working:
                if c.status in {ConstraintStatus.PROPOSED, ConstraintStatus.CONFLICT}:
                    c.status = ConstraintStatus.ACCEPTED
            return NegotiationResult(
                deployment_id=deployment_id,
                status="resolved",
                rounds_used=rounds_used,
                max_rounds=max_rounds,
                conflicts=all_conflicts,
                decisions=decisions,
                final_constraints=working,
                is_demo=is_demo,
            )

    return NegotiationResult(
        deployment_id=deployment_id,
        status="exhausted",
        rounds_used=rounds_used,
        max_rounds=max_rounds,
        conflicts=all_conflicts,
        decisions=decisions,
        final_constraints=working,
        is_demo=is_demo,
    )


def _validate(constraints: list[Constraint]) -> list[Constraint]:
    valid: list[Constraint] = []
    for c in constraints:
        if c.type == ConstraintType.PORT_CLAIM and "port" not in c.payload:
            logger.warning("Dropping invalid PORT_CLAIM %s", c.constraint_id)
            continue
        if c.type == ConstraintType.ENV_VAR and "key" not in c.payload:
            logger.warning("Dropping invalid ENV_VAR %s", c.constraint_id)
            continue
        valid.append(c)
    return valid


def detect_conflicts(constraints: list[Constraint]) -> list[ConflictRecord]:
    active = [
        c
        for c in constraints
        if c.status
        in {ConstraintStatus.PROPOSED, ConstraintStatus.ACCEPTED, ConstraintStatus.CONFLICT}
    ]
    groups: dict[str, list[Constraint]] = defaultdict(list)
    for c in active:
        groups[c.resource_key()].append(c)

    conflicts: list[ConflictRecord] = []
    for key, group in groups.items():
        if len(group) < 2:
            continue
        if not _group_incompatible(group):
            continue
        for c in group:
            if c.status != ConstraintStatus.REJECTED:
                c.status = ConstraintStatus.CONFLICT
        conflicts.append(
            ConflictRecord(
                conflict_id=f"cf_{uuid4().hex[:10]}",
                constraint_ids=[c.constraint_id for c in group],
                reason=_conflict_reason(key, group),
                priority_span=sorted({c.priority.value for c in group}),
                resource_key=key,
            )
        )
    return conflicts


def _group_incompatible(group: list[Constraint]) -> bool:
    types = {c.type for c in group}
    if ConstraintType.PORT_CLAIM in types:
        port_claims = [c for c in group if c.type == ConstraintType.PORT_CLAIM]
        ports = {c.payload.get("port") for c in port_claims}
        exclusive = any(c.payload.get("exclusive", True) for c in port_claims)
        return exclusive and len(ports) == 1 and len(port_claims) > 1

    policyish = [
        c
        for c in group
        if c.type in {ConstraintType.SECURITY_POLICY, ConstraintType.NETWORK_POLICY}
    ]
    if len(policyish) >= 2:
        rules = {c.payload.get("rule") for c in policyish}
        if len(rules) == 1:
            modes = {c.payload.get("mode") for c in policyish if c.payload.get("mode") is not None}
            if len(modes) > 1:
                return True
            priorities = {c.priority for c in policyish}
            if Priority.SECURITY in priorities and Priority.PREFERENCE in priorities:
                return True

    if ConstraintType.EXEC_ORDER in types:
        pairs = {
            (c.payload.get("before"), c.payload.get("after"))
            for c in group
            if c.type == ConstraintType.EXEC_ORDER
        }
        reversed_pairs = {(b, a) for a, b in pairs if a and b}
        return bool(pairs & reversed_pairs)

    if ConstraintType.ENV_VAR in types:
        env = [c for c in group if c.type == ConstraintType.ENV_VAR]
        keys = {c.payload.get("key") for c in env}
        values = {c.payload.get("value") for c in env if "value" in c.payload}
        return len(keys) == 1 and len(env) > 1 and len(values) > 1

    if ConstraintType.VOLUME_MOUNT in types:
        vols = [c for c in group if c.type == ConstraintType.VOLUME_MOUNT]
        hosts = {c.payload.get("host_path") or c.payload.get("host") for c in vols}
        containers = {
            c.payload.get("container_path") or c.payload.get("container") for c in vols
        }
        return len(vols) > 1 and len(hosts) == 1 and len(containers) > 1

    return False


def _conflict_reason(key: str, group: list[Constraint]) -> str:
    agents = ", ".join(sorted({c.source_agent for c in group}))
    if key.startswith("port:"):
        port = group[0].payload.get("port")
        return f"Port {port} claimed by {agents}"
    if key.startswith("policy:"):
        return f"Policy conflict on {key} between {agents}"
    return f"Constraint conflict on {key} between {agents}"


def resolve_conflict(constraints: list[Constraint], conflict: ConflictRecord) -> DecisionRecord:
    by_id = {c.constraint_id: c for c in constraints}
    group = [by_id[cid] for cid in conflict.constraint_ids if cid in by_id]

    ranks = [(PRIORITY_RANK[c.priority], c) for c in group]
    max_rank = max(r for r, _ in ranks)
    winners = [c for r, c in ranks if r == max_rank]
    losers = [c for r, c in ranks if r < max_rank]
    if losers:
        return DecisionRecord(
            conflict_id=conflict.conflict_id,
            method="priority",
            winner_ids=[c.constraint_id for c in winners],
            loser_ids=[c.constraint_id for c in losers],
            rationale=(
                f"{winners[0].priority.value} outranks {losers[0].priority.value}; "
                "higher-priority constraint kept."
            ),
        )

    if all(c.type == ConstraintType.PORT_CLAIM for c in group):
        ordered = sorted(group, key=lambda c: c.constraint_id)
        keeper = ordered[0]
        updates: list[dict] = []
        loser_ids: list[str] = []
        for other in ordered[1:]:
            new_port = _pick_alternative_port(other, keeper.payload.get("port"), constraints)
            if new_port is None:
                continue
            updates.append(
                {
                    "constraint_id": other.constraint_id,
                    "old_value": other.payload.get("port"),
                    "new_value": new_port,
                    "field": "port",
                }
            )
            loser_ids.append(other.constraint_id)
        if updates:
            return DecisionRecord(
                conflict_id=conflict.conflict_id,
                method="alternative",
                winner_ids=[keeper.constraint_id],
                loser_ids=loser_ids,
                rationale=(
                    "Same-priority port conflict; remapped via declared alternatives "
                    f"({updates[0]['old_value']} → {updates[0]['new_value']})."
                ),
                updates=updates,
            )

    ordered = sorted(group, key=lambda c: c.constraint_id)
    keeper = ordered[0]
    return DecisionRecord(
        conflict_id=conflict.conflict_id,
        method="deterministic_tiebreak",
        winner_ids=[keeper.constraint_id],
        loser_ids=[c.constraint_id for c in ordered[1:]],
        rationale=(
            "Same-priority deadlock after alternatives; deterministic tiebreak kept "
            f"{keeper.constraint_id} (lexicographically first). LLM mediation skipped "
            "(not configured / not required)."
        ),
    )


def _pick_alternative_port(
    constraint: Constraint,
    conflicting_port: int | None,
    all_constraints: list[Constraint],
) -> int | None:
    used = {
        c.payload.get("port")
        for c in all_constraints
        if c.type == ConstraintType.PORT_CLAIM and c.status != ConstraintStatus.REJECTED
    }
    for alt in constraint.alternatives:
        port = alt.get("port")
        if isinstance(port, int) and port not in used and port != conflicting_port:
            return port
    base = constraint.payload.get("port") or conflicting_port or 8080
    for delta in range(1, 20):
        candidate = int(base) + delta
        if candidate not in used:
            return candidate
    return None


def apply_decision(constraints: list[Constraint], decision: DecisionRecord) -> None:
    by_id = {c.constraint_id: c for c in constraints}
    for cid in decision.winner_ids:
        if cid in by_id:
            by_id[cid].status = ConstraintStatus.ACCEPTED
    for cid in decision.loser_ids:
        if cid not in by_id:
            continue
        c = by_id[cid]
        update = next((u for u in decision.updates if u.get("constraint_id") == cid), None)
        if update and decision.method == "alternative":
            old = update["old_value"]
            new = update["new_value"]
            c.payload["port"] = new
            c.payload["key"] = f"host:{new}"
            c.payload["previous_port"] = old
            c.payload["summary"] = f"{c.source_agent} remapped to {new}"
            c.payload["detail"] = f"Alternative port selected after conflict ({old} → {new})"
            c.status = ConstraintStatus.SUPERSEDED
        else:
            c.status = ConstraintStatus.REJECTED
