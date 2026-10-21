"""Run an allowlisted local security scanner and normalise its JSON output.

Design rules (Phase D):
- Honest status: "clean" is only returned when the scanner actually ran and
  produced parsable output with zero findings. A missing binary is
  "unavailable"; a timeout, non-zero exit without parsable findings, or
  unparseable output is "failed". Callers must not treat either as "no issues".
- No shell: argv is passed as a list with ``shell=False`` (no injection).
- No secret exfiltration: gitleaks match/secret fields are dropped from
  findings, so raw secrets never leave this module.
- Stdlib only: no new runtime dependency is introduced.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

DEFAULT_TIMEOUT_S = 120.0

# statuses
CLEAN = "clean"
FINDINGS = "findings"
UNAVAILABLE = "unavailable"
FAILED = "failed"


@dataclass
class ScannerFinding:
    rule_id: str
    severity: str
    path: str
    message: str
    line: int | None = None


@dataclass
class ScannerResult:
    scanner: str
    status: str
    findings: list[ScannerFinding] = field(default_factory=list)
    exit_code: int | None = None
    message: str = ""
    duration_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def _norm_gitleaks(data: Any) -> list[ScannerFinding]:
    out: list[ScannerFinding] = []
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        out.append(
            ScannerFinding(
                rule_id=str(item.get("RuleID") or "gitleaks"),
                severity="high",
                path=str(item.get("File") or ""),
                message=str(item.get("Description") or "secret detected"),
                line=_as_int(item.get("StartLine")),
            )
        )
    return out


def _norm_semgrep(data: Any) -> list[ScannerFinding]:
    out: list[ScannerFinding] = []
    results = data.get("results") if isinstance(data, dict) else None
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        start = item.get("start") if isinstance(item.get("start"), dict) else {}
        out.append(
            ScannerFinding(
                rule_id=str(item.get("check_id") or "semgrep"),
                severity=str(extra.get("severity") or "warning").lower(),
                path=str(item.get("path") or ""),
                message=str(extra.get("message") or "rule match"),
                line=_as_int(start.get("line")),
            )
        )
    return out


def _norm_trivy(data: Any) -> list[ScannerFinding]:
    out: list[ScannerFinding] = []
    results = data.get("Results") if isinstance(data, dict) else None
    for section in results if isinstance(results, list) else []:
        if not isinstance(section, dict):
            continue
        target = str(section.get("Target") or "")
        vulns = section.get("Vulnerabilities")
        for vuln in vulns if isinstance(vulns, list) else []:
            if not isinstance(vuln, dict):
                continue
            out.append(
                ScannerFinding(
                    rule_id=str(vuln.get("VulnerabilityID") or "trivy"),
                    severity=str(vuln.get("Severity") or "unknown").lower(),
                    path=target,
                    message=str(vuln.get("Title") or vuln.get("PkgName") or "vulnerability"),
                )
            )
    return out


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class _Spec:
    executable: str
    argv: Callable[[str, str], list[str]]
    normalize: Callable[[Any], list[ScannerFinding]]


_SCANNERS: dict[str, _Spec] = {
    "gitleaks": _Spec(
        "gitleaks",
        lambda exe, target: [
            exe, "detect", "--no-banner", "--report-format", "json",
            "--source", target,
        ],
        _norm_gitleaks,
    ),
    "semgrep": _Spec(
        "semgrep",
        lambda exe, target: [exe, "--json", "--quiet", target],
        _norm_semgrep,
    ),
    "trivy": _Spec(
        "trivy",
        lambda exe, target: [exe, "fs", "--format", "json", "--quiet", target],
        _norm_trivy,
    ),
}


def supported_scanners() -> list[str]:
    return sorted(_SCANNERS)


def available_scanners() -> list[str]:
    return [name for name, spec in _SCANNERS.items() if shutil.which(spec.executable)]


def run_scanner(
    name: str,
    target: str | Path,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> ScannerResult:
    """Run one allowlisted scanner against ``target`` and report honestly."""
    spec = _SCANNERS.get(name)
    if spec is None:
        return ScannerResult(
            scanner=name,
            status=UNAVAILABLE,
            message=f"unsupported scanner '{name}'",
        )
    target_path = Path(target)
    if not target_path.exists():
        return ScannerResult(
            scanner=name, status=UNAVAILABLE, message=f"target missing: {target_path}"
        )
    exe = shutil.which(spec.executable)
    if not exe:
        return ScannerResult(
            scanner=name,
            status=UNAVAILABLE,
            message=f"{spec.executable} not installed",
        )

    argv = spec.argv(exe, str(target_path))
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(  # noqa: S603 - allowlisted argv, shell=False
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ScannerResult(
            scanner=name,
            status=FAILED,
            message=f"timeout after {timeout_s:g}s",
            duration_s=round(time.perf_counter() - t0, 3),
        )
    except (OSError, ValueError) as exc:
        return ScannerResult(
            scanner=name,
            status=FAILED,
            message=f"could not run {spec.executable}: {exc}",
            duration_s=round(time.perf_counter() - t0, 3),
        )

    duration = round(time.perf_counter() - t0, 3)
    try:
        parsed = json.loads(proc.stdout or "")
        findings = spec.normalize(parsed)
    except (ValueError, TypeError) as exc:
        return ScannerResult(
            scanner=name,
            status=FAILED,
            exit_code=proc.returncode,
            message=f"unparseable output: {exc}",
            duration_s=duration,
        )

    if findings:
        return ScannerResult(
            scanner=name,
            status=FINDINGS,
            findings=findings,
            exit_code=proc.returncode,
            message=f"{len(findings)} finding(s)",
            duration_s=duration,
        )
    if proc.returncode != 0:
        return ScannerResult(
            scanner=name,
            status=FAILED,
            exit_code=proc.returncode,
            message=f"exit {proc.returncode} without parsable findings",
            duration_s=duration,
        )
    return ScannerResult(
        scanner=name,
        status=CLEAN,
        exit_code=0,
        message="no findings",
        duration_s=duration,
    )
