"""Deterministic CNP conflict dataset (seeded / fixed cases — no random generation)."""

from __future__ import annotations

from app.models.domain import Constraint, ConstraintStatus, ConstraintType, Priority


def _c(
    cid: str,
    ctype: ConstraintType,
    priority: Priority,
    agent: str,
    payload: dict,
) -> dict:
    return {
        "constraint_id": cid,
        "type": ctype.value,
        "priority": priority.value,
        "source_agent": agent,
        "payload": payload,
        "status": ConstraintStatus.PROPOSED.value,
    }


def load_cnp_cases() -> list[dict]:
    """Fixed evaluation cases. expected_* fields drive assertions."""
    return [
        {
            "case_id": "cnp_none_01",
            "description": "No conflicts",
            "constraints": [
                _c("a1", ConstraintType.PORT_CLAIM, Priority.RESOURCE, "Docker Agent", {"port": 8080, "service": "backend"}),
                _c("a2", ConstraintType.SECURITY_POLICY, Priority.SECURITY, "Security Agent", {"rule": "no_privileged"}),
            ],
            "expected_conflict": False,
            "expected_status": "resolved",
            "expected_min_rounds": 1,
        },
        {
            "case_id": "cnp_port_01",
            "description": "Port conflict between Docker and Nginx",
            "constraints": [
                _c("d1", ConstraintType.PORT_CLAIM, Priority.RESOURCE, "Docker Agent", {"port": 8080, "service": "backend", "alternatives": [8081]}),
                _c("n1", ConstraintType.PORT_CLAIM, Priority.RESOURCE, "Nginx Agent", {"port": 8080, "service": "proxy", "alternatives": [8082]}),
            ],
            "expected_conflict": True,
            "expected_status": "resolved",
            "expected_methods_any": ["priority", "alternative", "deterministic_tiebreak"],
        },
        {
            "case_id": "cnp_sec_01",
            "description": "Security vs preference on same policy rule",
            "constraints": [
                _c("s1", ConstraintType.SECURITY_POLICY, Priority.SECURITY, "Security Agent", {"rule": "external_access", "mode": "restricted"}),
                _c("p1", ConstraintType.NETWORK_POLICY, Priority.PREFERENCE, "Docker Agent", {"rule": "external_access", "mode": "unrestricted"}),
            ],
            "expected_conflict": True,
            "expected_status": "resolved",
            "expected_methods_any": ["priority"],
        },
        {
            "case_id": "cnp_env_01",
            "description": "Conflicting ENV_VAR values",
            "constraints": [
                _c("e1", ConstraintType.ENV_VAR, Priority.RESOURCE, "Docker Agent", {"key": "DATABASE_URL", "value": "postgres://a"}),
                _c("e2", ConstraintType.ENV_VAR, Priority.RESOURCE, "Nginx Agent", {"key": "DATABASE_URL", "value": "postgres://b", "alternatives": [{"key": "DATABASE_URL", "value": "postgres://a"}]}),
            ],
            "expected_conflict": True,
            "expected_status": "resolved",
        },
        {
            "case_id": "cnp_vol_01",
            "description": "Conflicting volume mounts",
            "constraints": [
                _c("v1", ConstraintType.VOLUME_MOUNT, Priority.RESOURCE, "Docker Agent", {"host": "/data", "container_path": "/var/lib"}),
                _c("v2", ConstraintType.VOLUME_MOUNT, Priority.RESOURCE, "Security Agent", {"host": "/data", "container_path": "/unsafe"}),
            ],
            "expected_conflict": True,
            "expected_status": "resolved",
        },
        {
            "case_id": "cnp_dep_01",
            "description": "EXEC_ORDER dependency pair (compatible)",
            "constraints": [
                _c("o1", ConstraintType.EXEC_ORDER, Priority.DEPENDENCY, "Docker Agent", {"before": "database", "after": "backend"}),
                _c("o2", ConstraintType.EXEC_ORDER, Priority.DEPENDENCY, "Docker Agent", {"before": "backend", "after": "frontend"}),
            ],
            "expected_conflict": False,
            "expected_status": "resolved",
        },
        {
            "case_id": "cnp_same_pri_01",
            "description": "Same-priority port conflict → tiebreak/alternative",
            "constraints": [
                _c("r1", ConstraintType.PORT_CLAIM, Priority.RESOURCE, "Docker Agent", {"port": 3000, "service": "a", "alternatives": [3001]}),
                _c("r2", ConstraintType.PORT_CLAIM, Priority.RESOURCE, "Nginx Agent", {"port": 3000, "service": "b", "alternatives": [3002]}),
            ],
            "expected_conflict": True,
            "expected_status": "resolved",
        },
        {
            "case_id": "cnp_multi_01",
            "description": "Port + security multi-conflict",
            "constraints": [
                _c("m1", ConstraintType.PORT_CLAIM, Priority.RESOURCE, "Docker Agent", {"port": 80, "service": "web", "alternatives": [8080]}),
                _c("m2", ConstraintType.PORT_CLAIM, Priority.RESOURCE, "Nginx Agent", {"port": 80, "service": "proxy", "alternatives": [8081]}),
                _c("m3", ConstraintType.SECURITY_POLICY, Priority.SECURITY, "Security Agent", {"rule": "external_access", "mode": "restricted"}),
                _c("m4", ConstraintType.NETWORK_POLICY, Priority.PREFERENCE, "Docker Agent", {"rule": "external_access", "mode": "unrestricted"}),
            ],
            "expected_conflict": True,
            "expected_status": "resolved",
        },
    ]


def constraints_from_case(case: dict) -> list[Constraint]:
    out: list[Constraint] = []
    for raw in case["constraints"]:
        out.append(
            Constraint(
                constraint_id=raw["constraint_id"],
                type=ConstraintType(raw["type"]),
                priority=Priority(raw["priority"]),
                source_agent=raw["source_agent"],
                payload=raw["payload"],
                status=ConstraintStatus(raw.get("status", "proposed")),
            )
        )
    return out
