"""Evidence-backed score engine: category independence and honesty.

Fixtures are synthetic and exist only to exercise scoring rules; they are not
production measurements. Every category must be derived from its own persisted
evidence and must return None when nothing was actually assessed.
"""
from __future__ import annotations

from app.api.scores import _readiness_health
from app.scores.compute import (
    VERSION,
    compute_all,
    compute_code_quality,
    compute_deployment_readiness,
    compute_security,
    compute_verification_confidence,
)

REQUIRED = ["schema", "yaml", "compose", "security", "constraints", "ports", "order", "env", "target"]


def test_score_snapshots_are_isolated_by_run_and_project(tmp_path):
    from app.database.connection import init_db
    from app.database.repositories import ScoreRepository

    db = tmp_path / "scores.db"
    init_db(db)
    repo = ScoreRepository(db)
    for run_id, project_id, value in (
        ("run_a", "prj_a", 42.0),
        ("run_b", "prj_b", None),
    ):
        repo.save(
            run_id=run_id, score_name="security", value=value,
            version=VERSION, computed_at="2026-01-01T00:00:00Z",
            inputs_hash=f"hash-{run_id}", target_sha="a" * 40,
            project_id=project_id, evidence={"checks": [], "coverage": {}},
        )
    a = repo.history(run_id="run_a")
    b = repo.history(project_id="prj_b")
    assert a[0]["value"] == 42.0 and a[0]["project_id"] == "prj_a"
    assert b[0]["run_id"] == "run_b" and b[0]["value"] is None


def _finding(scanner: str, severity: str, *, rule: str = "R1", path: str = "app.py",
             line: int = 1, message: str = "finding") -> dict:
    return {
        "source": f"scanner:{scanner}",
        "scanner": scanner,
        "rule_id": rule,
        "severity": severity,
        "path": path,
        "line": line,
        "message": message,
    }


def _analysis(*, scanners: dict[str, str] | None = None,
              findings: list[dict] | None = None,
              applications: list[dict] | None = None) -> dict:
    return {
        "schema": "repository-analysis/v1",
        "analysis_status": "completed",
        "commit_sha": "a" * 40,
        "applications": applications if applications is not None else [{"path": "."}],
        "findings": findings or [],
        "scanners": [
            {"name": name, "status": status, "error": None, "duration_ms": 1.0}
            for name, status in (scanners or {}).items()
        ],
    }


def _checks(*, failing: set[str] | None = None, warning: set[str] | None = None,
            statuses: dict[str, str] | None = None) -> list[dict]:
    failing = failing or set()
    warning = warning or set()
    out = []
    for check_id in REQUIRED:
        status = "fail" if check_id in failing else "warn" if check_id in warning else "pass"
        if statuses and check_id in statuses:
            status = statuses[check_id]
        out.append({
            "id": check_id,
            "name": check_id,
            "category": "security" if check_id == "security" else "config",
            "severity": "CRITICAL" if status == "fail" and check_id == "security" else "MEDIUM",
            "status": status,
            "rule": check_id.upper(),
            "message": f"{check_id} {status}",
        })
    return out


def _verification(*, passed: bool = True, checks: list[dict] | None = None) -> dict:
    return {"passed": passed, "checks": checks if checks is not None else _checks()}


def test_version_and_missing_evidence_is_none():
    assert VERSION == "scores-v2"
    out = compute_all(verification={"checks": []}, critic=None, change_intel=None)
    assert out["code_quality"]["value"] is None
    assert out["security"]["value"] is None
    assert out["verification_confidence"]["value"] is None
    assert out["deployment_readiness"]["value"] is None


def test_identical_evidence_is_deterministic():
    kwargs = dict(
        verification=_verification(),
        critic=None,
        change_intel=None,
        repository_analysis=_analysis(
            scanners={"gitleaks": "succeeded", "semgrep": "succeeded", "trivy": "succeeded"}
        ),
        result={"kind": "success", "execution_mode": "real", "profile": {}},
        support_code="SUPPORTED",
        health_status="healthy",
    )
    assert compute_all(**kwargs) == compute_all(**kwargs)


def test_code_quality_uses_its_own_findings():
    clean, _ = compute_code_quality(
        repository_analysis=_analysis(scanners={"semgrep": "succeeded"}),
        result={"kind": "success", "execution_mode": "real"},
    )
    dirty, evidence = compute_code_quality(
        repository_analysis=_analysis(
            scanners={"semgrep": "completed_with_findings"},
            findings=[_finding("semgrep", "high", rule="CQ1", message="complex function")],
        ),
        result={"kind": "success", "execution_mode": "real"},
    )
    assert clean == 100
    assert dirty is not None and dirty < clean
    assert evidence["top_finding"]
    assert any(c["status"] == "failed" for c in evidence["checks"])


def test_code_quality_missing_evidence_is_not_assessed():
    value, evidence = compute_code_quality(repository_analysis=None, result=None)
    assert value is None
    assert evidence["reason"]


def test_security_missing_scanner_is_not_clean():
    value, evidence = compute_security(
        repository_analysis=_analysis(scanners={}, findings=[]),
        verification=_verification(),
        change_intel=None,
    )
    assert value is not None
    assert value <= 60
    coverage = evidence["coverage"]
    assert coverage["assessed"] < coverage["applicable"]


def test_security_completed_clean_scan_can_pass():
    value, evidence = compute_security(
        repository_analysis=_analysis(
            scanners={"gitleaks": "succeeded", "semgrep": "succeeded", "trivy": "succeeded"}
        ),
        verification=_verification(),
        change_intel=None,
    )
    assert value == 100
    assert evidence["coverage"]["failed"] == 0


def test_security_findings_penalize_and_cap_secrets():
    finding = _finding("gitleaks", "high", rule="secret")
    value, evidence = compute_security(
        repository_analysis=_analysis(
            scanners={
                "gitleaks": "completed_with_findings",
                "semgrep": "succeeded",
                "trivy": "succeeded",
            },
            findings=[finding],
        ),
        verification=_verification(),
        change_intel=None,
    )
    assert value is not None and value <= 30
    assert evidence["top_finding"]
    # Raw secret material is never part of the evidence payload.
    assert "secret_value" not in str(evidence)


def test_duplicate_findings_do_not_double_penalize():
    one = _finding("semgrep", "high", rule="DUP", path="x.py", line=7, message="dup")
    single, _ = compute_security(
        repository_analysis=_analysis(
            scanners={"semgrep": "completed_with_findings", "gitleaks": "succeeded",
                      "trivy": "succeeded"},
            findings=[one],
        ),
        verification=_verification(), change_intel=None,
    )
    duplicate, _ = compute_security(
        repository_analysis=_analysis(
            scanners={"semgrep": "completed_with_findings", "gitleaks": "succeeded",
                      "trivy": "succeeded"},
            findings=[one, dict(one)],
        ),
        verification=_verification(), change_intel=None,
    )
    assert single == duplicate


def test_verification_confidence_counts_required_checks_only():
    passing, _ = compute_verification_confidence(verification=_verification())
    failing, evidence = compute_verification_confidence(
        verification=_verification(passed=False, checks=_checks(failing={"compose"}))
    )
    assert passing == 100
    assert failing is not None and failing < passing
    assert any(c["status"] == "failed" for c in evidence["checks"])


def test_verification_skipped_or_missing_is_not_success():
    skipped, _ = compute_verification_confidence(
        verification={"passed": True, "checks": _checks(statuses={k: "skipped" for k in REQUIRED})}
    )
    missing, evidence = compute_verification_confidence(
        verification={"passed": True, "checks": _checks()[:2]}
    )
    assert skipped is None
    assert missing is not None and missing < 100
    assert evidence["coverage"]["not_assessed"] > 0


def test_readiness_healthy_real_deployment_can_score_high():
    value, _ = compute_deployment_readiness(
        verification=_verification(),
        repository_analysis=_analysis(),
        result={"kind": "success", "execution_mode": "real"},
        support_code="SUPPORTED",
        health_status="healthy",
        execution_mode="real",
    )
    assert value == 100


def test_readiness_unhealthy_application_is_penalized():
    value, evidence = compute_deployment_readiness(
        verification=_verification(),
        repository_analysis=_analysis(),
        result={"kind": "failed", "execution_mode": "real", "code": "READINESS_FAILED"},
        support_code="SUPPORTED",
        health_status="unhealthy",
        execution_mode="real",
    )
    assert value is not None and value <= 20
    assert evidence["top_finding"]


def test_readiness_missing_health_is_not_perfect():
    value, _ = compute_deployment_readiness(
        verification=_verification(),
        repository_analysis=_analysis(),
        result={"kind": "success", "execution_mode": "real"},
        support_code="SUPPORTED",
        health_status="unknown",
        execution_mode="real",
    )
    assert value is not None and value < 100


def test_readiness_simulated_completion_is_not_high():
    value, _ = compute_deployment_readiness(
        verification=_verification(),
        repository_analysis=_analysis(),
        result={"kind": "success", "execution_mode": "simulator"},
        support_code="SUPPORTED",
        health_status="test_only",
        execution_mode="simulator",
    )
    assert value is not None and value <= 60


def test_readiness_unsupported_target_is_blocked():
    value, evidence = compute_deployment_readiness(
        verification=_verification(),
        repository_analysis=_analysis(applications=[]),
        result={"kind": "failed", "code": "DEPLOYMENT_UNSUPPORTED"},
        support_code="DEPLOYMENT_UNSUPPORTED",
        health_status="unknown",
        execution_mode=None,
    )
    assert value is not None and value <= 30
    assert any(c["status"] == "failed" for c in evidence["checks"])


def test_categories_are_independent():
    out = compute_all(
        verification=_verification(passed=False, checks=_checks(failing={"compose"})),
        critic=None,
        change_intel=None,
        repository_analysis=_analysis(scanners={"semgrep": "succeeded",
                                                "gitleaks": "succeeded",
                                                "trivy": "succeeded"}),
        result={"kind": "failed", "execution_mode": "real", "code": "VERIFICATION_FAILED"},
        support_code="SUPPORTED",
        health_status="unknown",
        execution_mode="real",
    )
    assert out["verification_confidence"]["value"] < 100
    assert out["security"]["value"] == 100
    assert out["deployment_readiness"]["value"] < out["security"]["value"]


def test_readiness_without_execution_evidence_is_capped():
    value, evidence = compute_deployment_readiness(
        verification=_verification(),
        repository_analysis=_analysis(),
        result={"kind": "failed", "code": "VERIFICATION_FAILED"},
        support_code="SUPPORTED",
        health_status="unknown",
        execution_mode=None,
    )
    assert value is not None and value <= 60
    assert any(cap["trigger"] == "execution" for cap in evidence.get("caps_applied", []))


def test_pre_execution_failure_is_not_confirmed_unhealthy():
    class Record:
        is_demo = False

    assert _readiness_health(Record(), {"kind": "failed", "code": "VERIFICATION_FAILED"}) == "unknown"
    assert _readiness_health(Record(), {"kind": "failed", "code": "BUILD_FAILED"}) == "unknown"
    assert _readiness_health(
        Record(),
        {"kind": "failed", "code": "READINESS_FAILED", "execution_mode": "real"},
    ) == "unhealthy"
