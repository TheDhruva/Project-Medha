"""Phase D: honest local scanner wrapper (offline, subprocess mocked)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.security import scanners


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def target(tmp_path: Path) -> Path:
    d = tmp_path / "checkout"
    d.mkdir()
    return d


def _which_found(monkeypatch) -> None:
    monkeypatch.setattr(scanners.shutil, "which", lambda exe: f"/usr/bin/{exe}")


def test_missing_binary_is_unavailable_not_clean(monkeypatch, target):
    monkeypatch.setattr(scanners.shutil, "which", lambda exe: None)
    res = scanners.run_scanner("gitleaks", target)
    assert res.status == scanners.UNAVAILABLE
    assert res.findings == []


def test_missing_target_is_unavailable(monkeypatch, tmp_path):
    _which_found(monkeypatch)
    res = scanners.run_scanner("gitleaks", tmp_path / "nope")
    assert res.status == scanners.UNAVAILABLE


def test_unsupported_scanner_rejected(target):
    res = scanners.run_scanner("rm-rf", target)
    assert res.status == scanners.UNAVAILABLE
    assert "unsupported" in res.message


def test_clean_when_ran_and_no_findings(monkeypatch, target):
    _which_found(monkeypatch)
    monkeypatch.setattr(scanners.subprocess, "run", lambda *a, **k: _Proc(0, "[]"))
    res = scanners.run_scanner("gitleaks", target)
    assert res.status == scanners.CLEAN
    assert res.exit_code == 0


def test_findings_mapped_and_secret_redacted(monkeypatch, target):
    _which_found(monkeypatch)
    payload = json.dumps(
        [
            {
                "RuleID": "aws-access-token",
                "Description": "AWS Access Token",
                "File": "config/app.py",
                "StartLine": 12,
                "Match": "AKIAIOSFODNN7EXAMPLE",
                "Secret": "AKIAIOSFODNN7EXAMPLE",
            }
        ]
    )
    monkeypatch.setattr(
        scanners.subprocess, "run", lambda *a, **k: _Proc(1, payload)
    )
    res = scanners.run_scanner("gitleaks", target)
    assert res.status == scanners.FINDINGS
    assert len(res.findings) == 1
    f = res.findings[0]
    assert f.rule_id == "aws-access-token"
    assert f.path == "config/app.py"
    assert f.line == 12
    # Raw secret must never be carried into findings.
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(res.to_dict())


def test_timeout_is_failed(monkeypatch, target):
    _which_found(monkeypatch)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="gitleaks", timeout=1)

    monkeypatch.setattr(scanners.subprocess, "run", boom)
    res = scanners.run_scanner("gitleaks", target, timeout_s=1)
    assert res.status == scanners.FAILED
    assert "timeout" in res.message


def test_unparseable_output_is_failed_not_clean(monkeypatch, target):
    _which_found(monkeypatch)
    monkeypatch.setattr(
        scanners.subprocess, "run", lambda *a, **k: _Proc(1, "not json")
    )
    res = scanners.run_scanner("gitleaks", target)
    assert res.status == scanners.FAILED


def test_nonzero_exit_without_findings_is_failed(monkeypatch, target):
    _which_found(monkeypatch)
    monkeypatch.setattr(scanners.subprocess, "run", lambda *a, **k: _Proc(2, "[]"))
    res = scanners.run_scanner("gitleaks", target)
    assert res.status == scanners.FAILED
    assert res.exit_code == 2


def test_semgrep_findings_normalized(monkeypatch, target):
    _which_found(monkeypatch)
    payload = json.dumps(
        {
            "results": [
                {
                    "check_id": "python.lang.security.audit",
                    "path": "app/main.py",
                    "start": {"line": 7},
                    "extra": {"message": "eval() used", "severity": "ERROR"},
                }
            ]
        }
    )
    monkeypatch.setattr(scanners.subprocess, "run", lambda *a, **k: _Proc(1, payload))
    res = scanners.run_scanner("semgrep", target)
    assert res.status == scanners.FINDINGS
    assert res.findings[0].severity == "error"
    assert res.findings[0].line == 7


def test_semgrep_invokes_config_auto(monkeypatch, target):
    """semgrep must actually receive a ruleset: --config auto, or it scans nothing."""
    _which_found(monkeypatch)
    captured: dict = {}

    def spy(argv, **kwargs):
        captured["argv"] = argv
        return _Proc(0, json.dumps({"results": []}))

    monkeypatch.setattr(scanners.subprocess, "run", spy)
    scanners.run_scanner("semgrep", target)
    argv = captured["argv"]
    assert "--config" in argv
    assert argv[argv.index("--config") + 1] == "auto"


def test_scanner_message_is_redacted(monkeypatch, target):
    """Finding messages are scrubbed of token-like material before storage."""
    _which_found(monkeypatch)
    payload = json.dumps(
        {
            "results": [
                {
                    "check_id": "python.lang.security.audit",
                    "path": "conf.py",
                    "start": {"line": 3},
                    "extra": {
                        "message": "hardcoded key sk-abcdef123456 in config",
                        "severity": "WARNING",
                    },
                }
            ]
        }
    )
    monkeypatch.setattr(scanners.subprocess, "run", lambda *a, **k: _Proc(1, payload))
    res = scanners.run_scanner("semgrep", target)
    assert res.findings[0].message
    assert "sk-abcdef123456" not in json.dumps(res.to_dict())


def test_trivy_findings_normalized(monkeypatch, target):
    _which_found(monkeypatch)
    payload = json.dumps(
        {
            "Results": [
                {
                    "Target": "requirements.txt",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2024-0001",
                            "Severity": "HIGH",
                            "Title": "bad package",
                        }
                    ],
                }
            ]
        }
    )
    monkeypatch.setattr(scanners.subprocess, "run", lambda *a, **k: _Proc(0, payload))
    res = scanners.run_scanner("trivy", target)
    assert res.status == scanners.FINDINGS
    assert res.findings[0].rule_id == "CVE-2024-0001"
    assert res.findings[0].path == "requirements.txt"


def test_run_uses_argv_list_without_shell(monkeypatch, target):
    _which_found(monkeypatch)
    captured: dict = {}

    def spy(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _Proc(0, "[]")

    monkeypatch.setattr(scanners.subprocess, "run", spy)
    scanners.run_scanner("trivy", target)
    assert isinstance(captured["argv"], list)
    assert captured["kwargs"].get("shell", False) is False
    assert captured["kwargs"].get("check") is False
