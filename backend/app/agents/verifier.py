"""Verifier agent — hard pre-execution checks (Phase 7)."""

from __future__ import annotations

import json
from typing import Any

from app.models.domain import ApplicationProfile, Constraint, ConstraintStatus, ConstraintType, NegotiationResult
from app.models.execution import (
    CheckSeverity,
    CheckStatus,
    VerificationCheck,
    VerificationResult,
)

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore


def run_verifier(
    *,
    deployment_id: str,
    profile: ApplicationProfile,
    constraints: list[Constraint],
    negotiation: NegotiationResult,
    config_fragments: dict[str, Any],
    replan_count: int = 0,
    force_fail_env: bool = False,
    is_demo: bool = False,
) -> VerificationResult:
    checks: list[VerificationCheck] = []

    checks.append(_schema_check(profile, constraints, negotiation, config_fragments))
    checks.append(_config_yaml_check(config_fragments))
    checks.append(_compose_check(config_fragments, profile))
    checks.append(_security_check(constraints, config_fragments))
    checks.append(_constraints_consistent(negotiation, constraints))
    checks.append(_exec_order_acyclic(constraints))
    checks.append(_env_required_check(constraints, config_fragments, force_fail_env=force_fail_env))
    checks.append(_target_local_check(profile))

    blocking = [
        c.message
        for c in checks
        if c.status == CheckStatus.FAIL
        and c.severity in {CheckSeverity.HIGH, CheckSeverity.CRITICAL, CheckSeverity.MEDIUM}
    ]
    warnings = [c.message for c in checks if c.status == CheckStatus.WARN]
    passed = len(blocking) == 0
    score = 100
    for c in checks:
        if c.status == CheckStatus.FAIL:
            score -= 20 if c.severity in {CheckSeverity.HIGH, CheckSeverity.CRITICAL} else 12
        elif c.status == CheckStatus.WARN:
            score -= 5
    score = max(0, score)

    return VerificationResult(
        deployment_id=deployment_id,
        passed=passed,
        checks=checks,
        blocking_failures=blocking,
        warnings=warnings,
        score=score,
        replan_count=replan_count,
        is_demo=is_demo,
    )


def _ok(check_id: str, name: str, category: str, rule: str, message: str, **kwargs) -> VerificationCheck:
    return VerificationCheck(
        id=check_id,
        name=name,
        category=category,
        rule=rule,
        status=CheckStatus.PASS,
        message=message,
        **kwargs,
    )


def _fail(
    check_id: str,
    name: str,
    category: str,
    rule: str,
    message: str,
    severity: CheckSeverity = CheckSeverity.HIGH,
    **kwargs,
) -> VerificationCheck:
    return VerificationCheck(
        id=check_id,
        name=name,
        category=category,
        rule=rule,
        status=CheckStatus.FAIL,
        severity=severity,
        message=message,
        **kwargs,
    )


def _schema_check(profile, constraints, negotiation, fragments) -> VerificationCheck:
    try:
        ApplicationProfile.model_validate(profile.model_dump())
        for c in constraints:
            Constraint.model_validate(c.model_dump())
        NegotiationResult.model_validate(negotiation.model_dump())
        if not isinstance(fragments, dict):
            raise ValueError("config_fragments must be an object")
        return _ok("schema", "Schema", "schema", "SCHEMA-001", "Configs match schema")
    except Exception as exc:  # noqa: BLE001
        return _fail(
            "schema",
            "Schema",
            "schema",
            "SCHEMA-001",
            f"Schema validation failed: {exc}",
            severity=CheckSeverity.CRITICAL,
        )


def _config_yaml_check(fragments: dict[str, Any]) -> VerificationCheck:
    compose = fragments.get("docker", {}).get("compose_fragment") or fragments.get("compose")
    if compose is None:
        return _ok("yaml", "YAML", "config", "YAML-001", "No compose fragment to validate")
    if yaml is None:
        # Fallback: ensure JSON-serializable structure
        try:
            json.dumps(compose)
            return _ok("yaml", "YAML", "config", "YAML-001", "Compose structure is serializable")
        except TypeError as exc:
            return _fail("yaml", "YAML", "config", "YAML-001", f"Invalid config structure: {exc}")
    try:
        dumped = yaml.safe_dump(compose)
        yaml.safe_load(dumped)
        return _ok("yaml", "YAML", "config", "YAML-001", "YAML parses cleanly")
    except Exception as exc:  # noqa: BLE001
        return _fail("yaml", "YAML", "config", "YAML-001", f"YAML invalid: {exc}")


def _compose_check(fragments: dict[str, Any], profile: ApplicationProfile) -> VerificationCheck:
    compose = fragments.get("docker", {}).get("compose_fragment") or {}
    services = compose.get("services") or {}
    if not services:
        # Accept profile-only plans
        if profile.inferred_stack.services:
            return _ok(
                "compose",
                "Compose",
                "compose",
                "COMPOSE-001",
                "Compose graph valid (profile services present)",
            )
        return _fail(
            "compose",
            "Compose",
            "compose",
            "COMPOSE-001",
            "No services defined in compose or profile",
            severity=CheckSeverity.HIGH,
        )

    names = set(services.keys())
    for name, svc in services.items():
        if not isinstance(svc, dict):
            return _fail("compose", "Compose", "compose", "COMPOSE-002", f"Service '{name}' is not an object")
        if not (svc.get("image") or svc.get("build")):
            return _fail(
                "compose",
                "Compose",
                "compose",
                "COMPOSE-003",
                f"Service '{name}' missing image/build",
            )
        ports = svc.get("ports") or []
        for p in ports:
            if isinstance(p, str) and ":" in p:
                host = p.split(":")[0]
                if not host.isdigit():
                    return _fail("compose", "Compose", "compose", "COMPOSE-004", f"Invalid port '{p}'")
        depends = svc.get("depends_on") or []
        if isinstance(depends, dict):
            depends = list(depends.keys())
        for dep in depends:
            if dep not in names:
                return _fail(
                    "compose",
                    "Compose",
                    "compose",
                    "COMPOSE-005",
                    f"Service '{name}' depends on unknown '{dep}'",
                )
    return _ok("compose", "Compose", "compose", "COMPOSE-001", "Compose graph valid")


def _security_check(constraints: list[Constraint], fragments: dict[str, Any]) -> VerificationCheck:
    active = [
        c
        for c in constraints
        if c.status in {ConstraintStatus.ACCEPTED, ConstraintStatus.PROPOSED, ConstraintStatus.SUPERSEDED}
    ]
    # Privileged forbidden
    compose = fragments.get("docker", {}).get("compose_fragment") or {}
    for name, svc in (compose.get("services") or {}).items():
        if isinstance(svc, dict) and svc.get("privileged") is True:
            return _fail(
                "security",
                "Security",
                "security",
                "SEC-001",
                f"Container '{name}' must not require privileged=true",
                severity=CheckSeverity.CRITICAL,
                affected_service=name,
            )
        caps = (svc.get("cap_add") or []) if isinstance(svc, dict) else []
        if "SYS_ADMIN" in caps:
            return _fail(
                "security",
                "Security",
                "security",
                "SEC-002",
                f"Service '{name}' adds unsafe capability SYS_ADMIN",
                severity=CheckSeverity.HIGH,
                affected_service=name,
            )

    has_security = any(
        c.type == ConstraintType.SECURITY_POLICY and c.status == ConstraintStatus.ACCEPTED for c in active
    )
    if not has_security:
        return VerificationCheck(
            id="security",
            name="Security",
            category="security",
            rule="SEC-010",
            status=CheckStatus.WARN,
            severity=CheckSeverity.MEDIUM,
            message="No accepted SECURITY_POLICY constraints present",
        )

    # Rejected unrestricted access should stay rejected
    for c in constraints:
        if (
            c.type in {ConstraintType.NETWORK_POLICY, ConstraintType.SECURITY_POLICY}
            and c.payload.get("mode") == "unrestricted"
            and c.status == ConstraintStatus.ACCEPTED
        ):
            return _fail(
                "security",
                "Security",
                "security",
                "SEC-003",
                "Unrestricted external access must not remain accepted",
                severity=CheckSeverity.CRITICAL,
            )

    return _ok("security", "Security", "security", "SEC-001", "Security floor intact")


def _constraints_consistent(negotiation: NegotiationResult, constraints: list[Constraint]) -> VerificationCheck:
    if negotiation.status != "resolved":
        return _fail(
            "constraints",
            "Constraints",
            "constraints",
            "CNP-001",
            f"Negotiation status is {negotiation.status}",
            severity=CheckSeverity.CRITICAL,
        )
    if any(c.status == ConstraintStatus.CONFLICT for c in constraints):
        return _fail(
            "constraints",
            "Constraints",
            "constraints",
            "CNP-002",
            "Unresolved CONFLICT constraints remain",
            severity=CheckSeverity.HIGH,
        )
    return _ok("constraints", "Constraints", "constraints", "CNP-001", "Agreed set consistent")


def _exec_order_acyclic(constraints: list[Constraint]) -> VerificationCheck:
    edges: list[tuple[str, str]] = []
    for c in constraints:
        if c.type != ConstraintType.EXEC_ORDER:
            continue
        if c.status in {ConstraintStatus.REJECTED}:
            continue
        before = c.payload.get("before")
        after = c.payload.get("after")
        if before and after:
            edges.append((str(before), str(after)))
    # Detect simple cycles via DFS
    graph: dict[str, list[str]] = {}
    for a, b in edges:
        graph.setdefault(a, []).append(b)
        graph.setdefault(b, [])
    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(n: str) -> bool:
        if n in visiting:
            return True
        if n in visited:
            return False
        visiting.add(n)
        for nxt in graph.get(n, []):
            if dfs(nxt):
                return True
        visiting.remove(n)
        visited.add(n)
        return False

    for node in list(graph):
        if dfs(node):
            return _fail(
                "order",
                "Exec order",
                "constraints",
                "ORDER-001",
                "EXEC_ORDER constraints contain a cycle",
                severity=CheckSeverity.HIGH,
            )
    return _ok("order", "Exec order", "constraints", "ORDER-001", "Exec order forms a valid DAG")


def _env_required_check(
    constraints: list[Constraint],
    fragments: dict[str, Any],
    *,
    force_fail_env: bool,
) -> VerificationCheck:
    if force_fail_env:
        return _fail(
            "env",
            "Environment",
            "config",
            "ENV-001",
            "Required environment variable DATABASE_URL missing",
            severity=CheckSeverity.HIGH,
        )
    required = [
        c
        for c in constraints
        if c.type == ConstraintType.ENV_VAR
        and c.payload.get("required")
        and c.status != ConstraintStatus.REJECTED
    ]
    compose = fragments.get("docker", {}).get("compose_fragment") or {}
    services = compose.get("services") or {}
    for c in required:
        key = c.payload.get("key")
        found = False
        for svc in services.values():
            if not isinstance(svc, dict):
                continue
            env = svc.get("environment") or {}
            if isinstance(env, dict) and key in env:
                found = True
            if isinstance(env, list) and any(str(item).startswith(f"{key}=") for item in env):
                found = True
        if key and not found:
            if fragments.get("env_present", {}).get(key):
                found = True
        if key and not found:
            return _fail(
                "env",
                "Environment",
                "config",
                "ENV-001",
                f"Required environment variable {key} missing",
                severity=CheckSeverity.HIGH,
            )
    return _ok("env", "Environment", "config", "ENV-001", "Required environment variables present")


def _target_local_check(profile: ApplicationProfile) -> VerificationCheck:
    host = (profile.target_host or "").lower()
    if host not in {"localhost", "127.0.0.1", "::1"}:
        return _fail(
            "target",
            "Target",
            "preflight",
            "TARGET-001",
            f"Non-local target '{profile.target_host}' is not allowed in V1",
            severity=CheckSeverity.CRITICAL,
        )
    return _ok("target", "Target", "preflight", "TARGET-001", "Target host is local")
