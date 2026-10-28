"""Deterministic, evidence-backed product scores.

Four UI categories are scored independently from persisted artifacts:

- code_quality: static analysis findings plus build/lint/test evidence that was
  actually produced for this run. A check that never ran is ``not_assessed``,
  never a pass.
- security: scanner results (gitleaks/semgrep/trivy) and the container-config
  security check. A scanner that is missing or failed is unassessed; only a
  completed clean scan can pass.
- verification_confidence: the persisted verification checks. Required checks
  count fully; warnings count half; failures count zero. Skipped/pending checks
  do not count as assessed.
- deployment_readiness: target support, verification gate, build/runtime
  configuration, execution outcome and recorded health evidence. Pipeline
  completion alone does not imply readiness. When the run was blocked because
  the repository has no deployable application (framework/library/CLI-only),
  readiness is ``not_applicable`` (value ``None`` + ``applicable: false``)
  rather than a fabricated low score.

Every category returns ``None`` when no applicable check was actually assessed.
Scores are integers 0-100, higher is better, and deterministic for identical
inputs. ``score_impact`` is the documented deduction a failed/warning check
contributed. Critical findings cap the category score (see ``CAPS`` below).
"""

from __future__ import annotations

from typing import Any

VERSION = "scores-v4"

PASSED = "passed"
FAILED = "failed"
WARNING = "warning"
SKIPPED = "skipped"
NOT_ASSESSED = "not_assessed"
NOT_APPLICABLE = "not_applicable"

_ASSESSED = frozenset({PASSED, FAILED, WARNING})
_SEVERITY_RANK = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}

# Documented deduction weights (points off 100) per failed check severity.
_DEDUCTION = {"critical": 40, "high": 20, "medium": 8, "low": 2, "info": 0}
_WARNING_DEDUCTION = 5

# Upper bounds justified by deployment/security risk.
CAPS = {
    "secret_finding": (30, "a detected secret caps security posture"),
    "critical_security": (40, "a critical security finding caps security posture"),
    "high_security": (65, "high-severity security findings cap security posture"),
    "critical_code": (40, "a critical code-quality finding caps code quality"),
    "verification_failed": (40, "a failed verification gate caps readiness"),
    "unhealthy": (20, "a confirmed unhealthy application caps readiness"),
    "unsupported_target": (30, "an unsupported deployment target caps readiness"),
    "missing_health": (75, "health evidence is unavailable"),
    "missing_execution": (60, "execution evidence is unavailable"),
    "simulated_execution": (60, "simulated execution is not real deployment evidence"),
    "critical_blocker": (25, "a critical blocker caps readiness"),
    "no_security_scanner": (60, "no repository security scanner completed"),
    "partial_security_scanner": (85, "security scanner coverage is incomplete"),
    "no_static_analysis": (80, "no static-analysis coverage for code quality"),
}

# Support-gate codes meaning "this repository has no deployable application".
# For these, deployment readiness is not applicable (never a low score).
_NO_APP_TARGET_CODES = {
    "NO_DEPLOYABLE_APP": (
        "this repository has no deployable web application (framework, "
        "library, or CLI-only project), so deployment readiness is not applicable"
    ),
    "NO_TARGET_CANDIDATES": (
        "no deployable application candidates were discovered in this "
        "repository, so deployment readiness is not applicable"
    ),
}

# Verifier checks that must pass before execution. Anything else is optional.
_REQUIRED_VERIFICATION_IDS = frozenset(
    {"schema", "yaml", "compose", "security", "constraints", "ports", "order", "env", "target"}
)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _severity(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in _SEVERITY_RANK:
        return text
    return {"error": "high", "warning": "medium", "info": "low"}.get(text, "medium")


def _check(
    check_id: str,
    category: str,
    title: str,
    status: str,
    *,
    severity: str | None = None,
    finding: str = "",
    evidence_source: str,
    reference: str | None = None,
    required: bool = True,
    score_impact: float = 0,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "category": category,
        "title": title,
        "status": status,
        "severity": severity,
        "finding": finding,
        "evidence_source": evidence_source,
        "reference": reference,
        "required": required,
        "score_impact": score_impact,
        "findings": findings or [],
    }


def _coverage(checks: list[dict[str, Any]]) -> dict[str, Any]:
    applicable = [c for c in checks if c["status"] != NOT_APPLICABLE]
    assessed = [c for c in applicable if c["status"] in _ASSESSED]
    counts = {
        "passed": sum(1 for c in applicable if c["status"] == PASSED),
        "failed": sum(1 for c in applicable if c["status"] == FAILED),
        "warnings": sum(1 for c in applicable if c["status"] == WARNING),
        "skipped": sum(1 for c in applicable if c["status"] == SKIPPED),
        "not_assessed": sum(1 for c in applicable if c["status"] == NOT_ASSESSED),
        "not_applicable": sum(1 for c in checks if c["status"] == NOT_APPLICABLE),
    }
    return {
        "assessed": len(assessed),
        "applicable": len(applicable),
        "ratio": round(len(assessed) / len(applicable), 4) if applicable else 0.0,
        **counts,
    }


def _top_finding(checks: list[dict[str, Any]]) -> str | None:
    def rank(c: dict[str, Any]) -> tuple[int, int]:
        priority = 3 if c["status"] == FAILED else 2 if c["status"] == WARNING else 1
        return (priority, _SEVERITY_RANK.get(c.get("severity") or "", 0))

    for check in sorted(checks, key=rank, reverse=True):
        if check["status"] in {FAILED, WARNING} and check.get("finding"):
            return check["finding"]
    return None


def _evidence(
    checks: list[dict[str, Any]],
    *,
    caps: list[tuple[int, str, str]] | None = None,
    reason: str | None = None,
    assessed_at: str | None = None,
    revision: str | None = None,
) -> tuple[int | None, dict[str, Any]]:
    coverage = _coverage(checks)
    evidence: dict[str, Any] = {
        "category": checks[0]["category"] if checks else None,
        "checks": checks,
        "coverage": coverage,
        "top_finding": _top_finding(checks),
        "assessed_at": assessed_at,
        "revision": revision,
    }
    if coverage["assessed"] == 0:
        evidence["reason"] = reason or "no applicable check produced evidence"
        return None, evidence

    score = 100.0
    for check in checks:
        if check["status"] in {FAILED, WARNING}:
            score -= float(check.get("score_impact") or 0)
    score = max(0.0, min(100.0, score))

    applied: list[dict[str, Any]] = []
    for cap, cap_reason, trigger in caps or []:
        if score > cap:
            score = float(cap)
            applied.append({"cap": cap, "reason": cap_reason, "trigger": trigger})
    if applied:
        evidence["caps_applied"] = applied
        if not evidence.get("top_finding"):
            # A capped score must explain itself even without a failed check.
            evidence["top_finding"] = (
                f"{applied[0]['reason']}; "
                f"{coverage['assessed']}/{coverage['applicable']} checks assessed"
            )
    return int(round(score)), evidence


def _repo_findings(repository_analysis: dict | None, scanner: str) -> list[dict[str, Any]]:
    analysis = _as_dict(repository_analysis)
    out: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for item in analysis.get("findings", []) if isinstance(analysis.get("findings"), list) else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("scanner") or str(item.get("source") or "").replace("scanner:", ""))
        if name != scanner:
            continue
        key = (
            str(item.get("rule_id") or ""),
            str(item.get("path") or ""),
            item.get("line"),
            str(item.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _scanner_status(repository_analysis: dict | None, scanner: str) -> str | None:
    analysis = _as_dict(repository_analysis)
    for item in analysis.get("scanners", []) if isinstance(analysis.get("scanners"), list) else []:
        if isinstance(item, dict) and item.get("name") == scanner:
            return str(item.get("status") or "")
    return None


def _scanner_check(
    repository_analysis: dict | None,
    scanner: str,
    *,
    check_id: str,
    title: str,
    category: str,
) -> dict[str, Any]:
    findings = _repo_findings(repository_analysis, scanner)
    status = _scanner_status(repository_analysis, scanner)
    source = f"scanner:{scanner}"
    if findings:
        severities = [_severity(f.get("severity")) for f in findings]
        highest = max(severities, key=lambda s: _SEVERITY_RANK.get(s, 0))
        impact = sum(_DEDUCTION.get(s, 8) for s in severities)
        return _check(
            check_id,
            category,
            title,
            FAILED,
            severity=highest,
            finding=f"{len(findings)} {scanner} finding(s); highest severity {highest}",
            evidence_source=source,
            reference=scanner,
            score_impact=min(100, impact),
            findings=[
                {
                    "severity": _severity(f.get("severity")),
                    "rule_id": f.get("rule_id"),
                    "path": f.get("path"),
                    "line": f.get("line"),
                    "message": f.get("message"),
                }
                for f in findings
            ],
        )
    if status in {"succeeded", "clean"}:
        return _check(
            check_id, category, title, PASSED,
            finding=f"{scanner} completed with no findings",
            evidence_source=source, reference=scanner,
        )
    if status in {"completed_with_findings", "findings"}:
        # Findings were reported but could not be normalized into this bucket.
        return _check(
            check_id, category, title, NOT_ASSESSED,
            finding=f"{scanner} reported findings that could not be attributed",
            evidence_source=source, reference=scanner,
        )
    reason = {
        "unavailable": f"{scanner} is not installed; this check did not run",
        "failed": f"{scanner} errored; results are unknown",
        "timed_out": f"{scanner} timed out; results are unknown",
        "partial": f"{scanner} only partially completed",
    }.get(status or "", f"no {scanner} result was recorded for this run")
    return _check(
        check_id, category, title, NOT_ASSESSED,
        finding=reason, evidence_source=source, reference=scanner,
        severity="medium",
    )


def _build_check(result: dict | None) -> dict[str, Any]:
    result = _as_dict(result)
    build = _as_dict(result.get("build"))
    code = str(result.get("code") or "")
    if build:
        return _check(
            "build", "code_quality", "Build validation", FAILED,
            severity="high",
            finding=f"Build failed at {build.get('stage') or 'build'}"
            + (f" (exit {build.get('exit_code')})" if build.get("exit_code") is not None else ""),
            evidence_source="execution.result.build",
            reference=build.get("error_code") or build.get("command"),
            score_impact=_DEDUCTION["high"],
        )
    if code == "BUILD_FAILED":
        return _check(
            "build", "code_quality", "Build validation", FAILED,
            severity="high", finding="Build failed before the application started",
            evidence_source="execution.result.code", reference=code,
            score_impact=_DEDUCTION["high"],
        )
    if result.get("kind") == "success" and result.get("execution_mode") == "real":
        return _check(
            "build", "code_quality", "Build validation", PASSED,
            finding="Real build completed",
            evidence_source="execution.result", reference="real",
        )
    return _check(
        "build", "code_quality", "Build validation", NOT_ASSESSED,
        finding="No build result was produced for this run",
        evidence_source="execution.result",
    )


def _verification_check(verification: dict | None) -> dict[str, Any]:
    """Container security configuration assessed by the verifier."""
    checks = _as_dict(verification).get("checks")
    for item in checks if isinstance(checks, list) else []:
        if not isinstance(item, dict) or item.get("category") != "security":
            continue
        raw = str(item.get("status") or "").lower()
        severity = _severity(item.get("severity"))
        if raw == "pass":
            status = PASSED
        elif raw == "fail":
            status = FAILED
        elif raw == "warning":
            status = WARNING
        else:
            status = NOT_ASSESSED
        impact = 0 if status == PASSED else (
            _WARNING_DEDUCTION if status == WARNING else _DEDUCTION.get(severity, 8)
        )
        return _check(
            "container_security", "security", "Container security config", status,
            severity=severity,
            finding=str(item.get("message") or ""),
            evidence_source="verification.checks",
            reference=str(item.get("rule") or item.get("id") or "security"),
            score_impact=impact,
        )
    return _check(
        "container_security", "security", "Container security config", NOT_ASSESSED,
        finding="No container security check was recorded for this run",
        evidence_source="verification.checks",
    )


def compute_code_quality(*, repository_analysis: dict | None = None,
                         verification: dict | None = None,
                         result: dict | None = None,
                         assessed_at: str | None = None,
                         revision: str | None = None) -> tuple[int | None, dict]:
    checks = [
        _scanner_check(
            repository_analysis, "semgrep",
            check_id="static_analysis", title="Static analysis",
            category="code_quality",
        ),
        _build_check(result),
    ]

    # Lint/typecheck/tests are only counted when a real artifact exists. MEDHA
    # does not currently execute them, so the default is an honest unassessed.
    verification_checks = _as_dict(verification).get("checks")
    for check_id, category, title in (
        ("lint", "lint", "Lint results"),
        ("typecheck", "typecheck", "Type-check results"),
        ("tests", "test", "Test results"),
    ):
        found = None
        for item in verification_checks if isinstance(verification_checks, list) else []:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "") == check_id or str(item.get("category") or "") == category:
                found = item
                break
        if found is None:
            checks.append(_check(
                check_id, "code_quality", title, NOT_ASSESSED,
                finding=f"No {title.lower()} artifact was produced for this run",
                evidence_source="verification.checks",
            ))
            continue
        raw = str(found.get("status") or "").lower()
        status = PASSED if raw == "pass" else WARNING if raw == "warning" else (
            FAILED if raw == "fail" else NOT_ASSESSED
        )
        severity = _severity(found.get("severity"))
        checks.append(_check(
            check_id, "code_quality", title, status,
            severity=severity,
            finding=str(found.get("message") or ""),
            evidence_source="verification.checks",
            reference=str(found.get("rule") or check_id),
            score_impact=_WARNING_DEDUCTION if status == WARNING else (
                _DEDUCTION.get(severity, 8) if status == FAILED else 0
            ),
        ))

    caps: list[tuple[int, str, str]] = []
    if any(c["severity"] == "critical" and c["status"] == FAILED for c in checks):
        caps.append((*CAPS["critical_code"], "critical_code"))
    if not any(c["id"] == "static_analysis" and c["status"] in _ASSESSED for c in checks):
        caps.append((*CAPS["no_static_analysis"], "static_analysis"))
    value, evidence = _evidence(
        checks, caps=caps,
        reason="no code-quality check produced evidence for this run",
        assessed_at=assessed_at, revision=revision,
    )
    evidence["code_quality_failures"] = sum(
        1 for c in checks if c["status"] == FAILED
    )
    return value, evidence


def compute_security(*, repository_analysis: dict | None = None,
                     verification: dict | None = None,
                     change_intel: dict | None = None,
                     assessed_at: str | None = None,
                     revision: str | None = None) -> tuple[int | None, dict]:
    checks = [
        _scanner_check(
            repository_analysis, "gitleaks",
            check_id="secret_scan", title="Secret scan",
            category="security",
        ),
        _scanner_check(
            repository_analysis, "trivy",
            check_id="dependency_scan", title="Dependency vulnerabilities",
            category="security",
        ),
        _scanner_check(
            repository_analysis, "semgrep",
            check_id="static_security", title="Static security analysis",
            category="security",
        ),
        _scanner_check(
            repository_analysis, "builtin",
            check_id="policy_checks", title="Configuration & code policy checks",
            category="security",
        ),
        _verification_check(verification),
    ]

    risk = _as_dict(_as_dict(change_intel).get("risk"))
    if risk.get("level") == "high":
        checks.append(_check(
            "change_risk", "security", "Change security risk", WARNING,
            severity="medium", finding="Dependency change impact was rated high risk",
            evidence_source="change_intel.risk", reference="risk.level",
            score_impact=_WARNING_DEDUCTION,
        ))

    caps: list[tuple[int, str, str]] = []
    secret_failure = next(
        (c for c in checks if c["id"] == "secret_scan" and c["status"] == FAILED), None)
    if secret_failure:
        caps.append((*CAPS["secret_finding"], "secret_scan"))
    if any(c["severity"] == "critical" and c["status"] == FAILED for c in checks):
        caps.append((*CAPS["critical_security"], "critical_security"))
    if any(c["severity"] == "high" and c["status"] == FAILED for c in checks):
        caps.append((*CAPS["high_security"], "high_security"))
    scanner_checks = [c for c in checks if c["id"] in {"secret_scan", "dependency_scan", "static_security"}]
    assessed_scanners = [c for c in scanner_checks if c["status"] in _ASSESSED]
    if not assessed_scanners:
        caps.append((*CAPS["no_security_scanner"], "scanner_coverage"))
    elif len(assessed_scanners) < len(scanner_checks):
        caps.append((*CAPS["partial_security_scanner"], "scanner_coverage"))

    value, evidence = _evidence(
        checks, caps=caps,
        reason="no security scanner completed; security coverage is unknown",
        assessed_at=assessed_at, revision=revision,
    )
    # Honest roll-up fields consumed by the dashboard: how many security
    # checks actually failed, and how complete the scan coverage was.
    analysis = _as_dict(repository_analysis)
    coverage = _as_dict(analysis.get("coverage"))
    gaps = coverage.get("gaps")
    evidence["security_failures"] = sum(1 for c in checks if c["status"] == FAILED)
    evidence["scan_completeness"] = {
        "analysis_status": analysis.get("analysis_status"),
        "security_scan": coverage.get("security_scan"),
        "gaps": [str(g) for g in gaps] if isinstance(gaps, list) else [],
    }
    return value, evidence


def compute_verification_confidence(*, verification: dict | None,
                                    assessed_at: str | None = None,
                                    revision: str | None = None) -> tuple[int | None, dict]:
    raw_checks = _as_dict(verification).get("checks")
    if not isinstance(raw_checks, list) or not raw_checks:
        return _evidence(
            [], reason="no verification checks were recorded for this run",
            assessed_at=assessed_at, revision=revision,
        )

    checks: list[dict[str, Any]] = []
    points = 0.0
    present: set[str] = set()
    required_assessed = 0
    for item in raw_checks:
        if not isinstance(item, dict):
            continue
        check_id = str(item.get("id") or item.get("rule") or "check")
        raw = str(item.get("status") or "").lower()
        required = check_id in _REQUIRED_VERIFICATION_IDS
        if required:
            present.add(check_id)
        if raw in {"pass", "passed", "ok"}:
            status = PASSED
            if required:
                points += 1.0
                required_assessed += 1
        elif raw in {"warning", "warn"}:
            status = WARNING
            if required:
                points += 0.5
                required_assessed += 1
        elif raw in {"fail", "failed", "error"}:
            status = FAILED
            if required:
                required_assessed += 1
        elif raw in {"skipped", "not_applicable"}:
            status = SKIPPED
        else:
            status = NOT_ASSESSED
        checks.append(_check(
            check_id,
            "verification",
            str(item.get("name") or check_id),
            status,
            severity=_severity(item.get("severity")),
            finding=str(item.get("message") or ""),
            evidence_source="verification.checks",
            reference=str(item.get("rule") or check_id),
            required=required,
        ))

    for missing in sorted(_REQUIRED_VERIFICATION_IDS - present):
        checks.append(_check(
            missing, "verification", missing.replace("_", " ").title(), NOT_ASSESSED,
            finding="Required verification check was not recorded",
            evidence_source="verification.checks", reference=missing,
        ))

    if required_assessed == 0:
        evidence = _evidence_meta(
            checks, reason="no required verification check actually ran",
            assessed_at=assessed_at, revision=revision,
        )
        return None, evidence
    value = int(round(100.0 * points / len(_REQUIRED_VERIFICATION_IDS)))
    return value, _evidence_meta(
        checks, reason=None, assessed_at=assessed_at, revision=revision,
    )


def _evidence_meta(checks: list[dict[str, Any]], *, reason: str | None,
                   assessed_at: str | None, revision: str | None) -> dict[str, Any]:
    coverage = _coverage(checks)
    return {
        "category": "verification",
        "checks": checks,
        "coverage": coverage,
        "top_finding": _top_finding(checks),
        "assessed_at": assessed_at,
        "revision": revision,
        **({"reason": reason} if reason else {}),
    }


def compute_deployment_readiness(*, verification: dict | None,
                                 repository_analysis: dict | None = None,
                                 result: dict | None = None,
                                 support_code: str | None = None,
                                 health_status: str | None = None,
                                 execution_mode: str | None = None,
                                 profile_confidence: float | None = None,
                                 health_hints: list | None = None,
                                 assessed_at: str | None = None,
                                 revision: str | None = None) -> tuple[int | None, dict]:
    result = _as_dict(result)
    checks: list[dict[str, Any]] = []

    # Deployment ineligibility is not a deployment-readiness defect. A
    # repository with no deployable application (framework, library, CLI-only
    # project) is not applicable for this score — never a low number with
    # fabricated "critical findings".
    support = str(support_code or "").upper()
    if support in _NO_APP_TARGET_CODES:
        reason = _NO_APP_TARGET_CODES[support]
        na_checks = [
            _check(
                "target_support", "deployment", "Deployment target support",
                NOT_APPLICABLE, finding=reason,
                evidence_source="execution.result.code", reference=support,
            )
        ]
        return None, {
            "category": "deployment",
            "checks": na_checks,
            "coverage": _coverage(na_checks),
            "top_finding": None,
            "assessed_at": assessed_at,
            "revision": revision,
            "applicable": False,
            "reason": reason,
        }

    verification = _as_dict(verification) if verification is not None else None
    if verification is not None and isinstance(verification.get("passed"), bool):
        passed = bool(verification["passed"])
        checks.append(_check(
            "verification_gate", "deployment", "Verification gate",
            PASSED if passed else FAILED,
            severity="critical" if not passed else "low",
            finding="Verification gate passed" if passed else "Verification gate failed",
            evidence_source="verification.passed",
            reference="verification",
            score_impact=0 if passed else _DEDUCTION["critical"],
        ))
    else:
        checks.append(_check(
            "verification_gate", "deployment", "Verification gate", NOT_ASSESSED,
            finding="No verification outcome was recorded",
            evidence_source="verification.passed",
        ))

    if support_code:
        supported = str(support_code).upper() in {"SUPPORTED", "OK"}
        checks.append(_check(
            "target_support", "deployment", "Deployment target support",
            PASSED if supported else FAILED,
            severity="critical" if not supported else "low",
            finding=("Deployment target is supported" if supported
                     else f"Deployment target is unsupported ({support_code})"),
            evidence_source="execution.result.code",
            reference=str(support_code),
            score_impact=0 if supported else _DEDUCTION["critical"],
        ))
    else:
        checks.append(_check(
            "target_support", "deployment", "Deployment target support", NOT_ASSESSED,
            finding="Supported target has not been established",
            evidence_source="execution.result.code",
        ))

    analysis = _as_dict(repository_analysis)
    apps = analysis.get("applications") if isinstance(analysis.get("applications"), list) else []
    if analysis:
        if apps:
            checks.append(_check(
                "deployment_config", "deployment", "Deployment configuration",
                PASSED, finding=f"{len(apps)} deployable application root(s) detected",
                evidence_source="repository_analysis.applications",
                reference="applications",
            ))
        else:
            checks.append(_check(
                "deployment_config", "deployment", "Deployment configuration",
                FAILED, severity="high",
                finding="No deployable application root was detected",
                evidence_source="repository_analysis.applications",
                reference="applications",
                score_impact=_DEDUCTION["high"],
            ))
    else:
        checks.append(_check(
            "deployment_config", "deployment", "Deployment configuration", NOT_ASSESSED,
            finding="No repository analysis was recorded for this run",
            evidence_source="repository_analysis.applications",
        ))

    build = _as_dict(result.get("build"))
    code = str(result.get("code") or "")
    if build or code in {"BUILD_FAILED", "START_FAILED", "READINESS_FAILED"}:
        checks.append(_check(
            "execution", "deployment", "Execution result", FAILED,
            severity="high",
            finding=str(build.get("error_code") or code or "Execution failed"),
            evidence_source="execution.result",
            reference=build.get("stage") or code or "execution",
            score_impact=_DEDUCTION["high"],
        ))
    elif result.get("kind") == "success" and (execution_mode or result.get("execution_mode")) == "real":
        checks.append(_check(
            "execution", "deployment", "Execution result", PASSED,
            finding="Real execution completed",
            evidence_source="execution.result", reference="real",
        ))
    elif execution_mode in {"simulator", "simulator_fallback", "demo", "controlled_test"}:
        checks.append(_check(
            "execution", "deployment", "Execution result", NOT_ASSESSED,
            finding="Simulated/controlled execution is not real deployment evidence",
            evidence_source="execution.result.execution_mode",
            reference=str(execution_mode),
        ))
    else:
        checks.append(_check(
            "execution", "deployment", "Execution result", NOT_ASSESSED,
            finding="No execution outcome was recorded",
            evidence_source="execution.result",
        ))

    health = (health_status or "").lower()
    if health == "healthy":
        checks.append(_check(
            "health", "deployment", "Application health", PASSED,
            finding="Application health was confirmed",
            evidence_source="deploy/health", reference="healthy",
        ))
    elif health == "unhealthy":
        checks.append(_check(
            "health", "deployment", "Application health", FAILED,
            severity="critical",
            finding="Application health check failed",
            evidence_source="deploy/health", reference="unhealthy",
            score_impact=_DEDUCTION["critical"],
        ))
    else:
        checks.append(_check(
            "health", "deployment", "Application health", NOT_ASSESSED,
            finding=("Health evidence is unavailable"
                     if health in {"", "unknown"} else
                     f"Health state '{health}' is not verified application health"),
            evidence_source="deploy/health", reference=health or None,
        ))

    caps: list[tuple[int, str, str]] = []
    if any(c["id"] in {"verification_gate", "target_support", "health", "execution"}
           and c["status"] == FAILED and c["severity"] == "critical" for c in checks):
        caps.append((*CAPS["critical_blocker"], "critical_blocker"))
    if any(c["id"] == "verification_gate" and c["status"] == FAILED for c in checks):
        caps.append((*CAPS["verification_failed"], "verification_gate"))
    if any(c["id"] == "health" and c["status"] == FAILED for c in checks):
        caps.append((*CAPS["unhealthy"], "health"))
    if any(c["id"] == "target_support" and c["status"] == FAILED for c in checks):
        caps.append((*CAPS["unsupported_target"], "target_support"))
    if any(c["id"] == "health" and c["status"] == NOT_ASSESSED for c in checks):
        caps.append((*CAPS["missing_health"], "health"))
    if health == "demo" or execution_mode in {
        "simulator", "simulator_fallback", "demo", "controlled_test",
    }:
        caps.append((*CAPS["simulated_execution"], "execution"))
    elif any(c["id"] == "execution" and c["status"] == NOT_ASSESSED for c in checks):
        caps.append((*CAPS["missing_execution"], "execution"))

    return _evidence(
        checks, caps=caps,
        reason="no deployment-readiness check produced evidence",
        assessed_at=assessed_at, revision=revision,
    )


def compute_performance(*, change_intel: dict | None,
                        runtime_measured: dict | None) -> tuple[float | None, dict]:
    """Static estimate from change-risk evidence, or a measured benchmark.

    Returns ``None`` when neither exists: an unmeasured system is never
    assigned a default score, because a number without evidence would
    misrepresent unassessed areas as healthy.
    """
    evidence: dict[str, Any] = {"measured": bool(runtime_measured)}
    if not change_intel and not runtime_measured:
        evidence.update({
            "reason": "no performance evidence was recorded for this run",
            "benchmark": "not-measured",
            "static_deductions": 0,
        })
        return None, evidence
    risk = _as_dict((change_intel or {}).get("risk"))
    factors = risk.get("factors", []) if isinstance(risk, dict) else []
    score: float = 80
    deductions = 0
    for factor in factors if isinstance(factors, list) else []:
        code = str(factor.get("code", ""))
        if "blast" in code or "large" in code or "perf" in code:
            if factor.get("level") == "high":
                deductions += 15
            elif factor.get("level") == "medium":
                deductions += 7
    score -= deductions
    evidence["static_deductions"] = deductions
    evidence["benchmark"] = runtime_measured or "not-measured"
    return max(0, score), evidence


def compute_optimization(*, change_intel: dict | None,
                         verification: dict | None) -> tuple[float | None, dict]:
    """Optimization headroom from observed verification warnings.

    Returns ``None`` when no signal exists at all: warnings and open
    requirements are the only observed inputs, so an empty evidence set
    scored at 100 would claim "nothing to optimize" without ever looking.
    """
    if verification is None and change_intel is None:
        return None, {
            "reason": "verification evidence missing; optimization was not assessed",
        }
    evidence: dict[str, Any] = {}
    score = 100
    requirements = (change_intel or {}).get("requirements", []) if isinstance(change_intel, dict) else []
    open_reqs = [r for r in requirements if isinstance(r, dict) and r.get("status") != "done"]
    checks = verification.get("checks", []) if isinstance(verification, dict) else []
    if not checks and not requirements:
        return None, {
            "reason": (
                "no verification checks or change requirements were recorded;"
                " optimization was not assessed"
            ),
        }
    score -= min(30, len(open_reqs) * 3)
    evidence["open_requirements"] = len(open_reqs)
    warnings = [c for c in checks if isinstance(c, dict) and str(c.get("status", "")).lower() == "warning"]
    score -= min(20, len(warnings) * 2)
    evidence["warnings"] = len(warnings)
    return max(0, score), evidence


def compute_all(*, verification: dict | None, critic: dict | None,
                change_intel: dict | None, support_code: str | None = None,
                profile_confidence: float | None = None,
                health_hints: list | None = None,
                runtime_measured: dict | None = None,
                repository_analysis: dict | None = None,
                result: dict | None = None,
                health_status: str | None = None,
                execution_mode: str | None = None,
                assessed_at: str | None = None,
                revision: str | None = None) -> dict[str, dict]:
    """Compute all scores. Returns {name: {value, version, evidence}}.

    ``critic`` no longer contributes numeric scores: LLM/critic output may
    describe findings but is never treated as authoritative measurement.
    """
    _ = critic
    readiness, ev_r = compute_deployment_readiness(
        verification=verification, repository_analysis=repository_analysis,
        result=result, support_code=support_code, health_status=health_status,
        execution_mode=execution_mode, profile_confidence=profile_confidence,
        health_hints=health_hints or [], assessed_at=assessed_at, revision=revision)
    code, ev_c = compute_code_quality(
        repository_analysis=repository_analysis, verification=verification,
        result=result, assessed_at=assessed_at, revision=revision)
    verification_confidence, ev_v = compute_verification_confidence(
        verification=verification, assessed_at=assessed_at, revision=revision)
    sec, ev_s = compute_security(
        repository_analysis=repository_analysis, verification=verification,
        change_intel=change_intel, assessed_at=assessed_at, revision=revision)
    perf, ev_p = compute_performance(
        change_intel=change_intel, runtime_measured=runtime_measured)
    opt, ev_o = compute_optimization(
        change_intel=change_intel, verification=verification)
    return {
        "code_quality": {"value": code, "version": VERSION, "evidence": ev_c},
        "security": {"value": sec, "version": VERSION, "evidence": ev_s},
        "verification_confidence": {
            "value": verification_confidence, "version": VERSION, "evidence": ev_v},
        "deployment_readiness": {"value": readiness, "version": VERSION, "evidence": ev_r},
        "performance": {"value": perf, "version": VERSION, "evidence": ev_p},
        "optimization": {"value": opt, "version": VERSION, "evidence": ev_o},
    }
