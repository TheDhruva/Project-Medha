"""Deterministic built-in policy checks (offline, no external tools).

Every result is a POTENTIAL issue with ``verification_status="unverified"`` —
a pattern match is evidence to investigate, never a confirmed exploit. The
checks are bounded (hit caps) and never read secret values into output.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.analysis.policy import run_policy_checks


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _rules(result) -> set[str]:
    return {f["rule_id"] for f in result.findings}


def test_clean_repository_is_succeeded_without_findings(tmp_path):
    _write(tmp_path / "app.py", "print('hello')\n")
    res = run_policy_checks(tmp_path)
    assert res.task == "security:builtin"
    assert res.findings == []
    assert res.status == "succeeded"
    assert res.evidence["auth_boundary_detected"] is True


def test_known_rules_fire_and_are_all_unverified(tmp_path):
    _write(
        tmp_path / "app.py",
        "import subprocess, yaml, pickle, hashlib, requests\n"
        "subprocess.run(cmd, shell=True)\n"
        "yaml.load(data)\n"
        "pickle.loads(blob)\n"
        'cur.execute(f"SELECT * FROM t WHERE id={i}")\n'
        "hashlib.md5(b'x')\n"
        "debug = True\n"
        "requests.get(url, verify=False)\n",
    )
    res = run_policy_checks(tmp_path)
    assert {
        "SEC-101", "SEC-102", "SEC-103", "SEC-104", "SEC-105",
        "CFG-003", "CFG-004",
    } <= _rules(res)
    assert res.status == "completed_with_findings"
    # Pattern matches are evidence, never confirmed defects.
    assert all(f["verification_status"] == "unverified" for f in res.findings)
    assert all(f["source"] == "builtin" for f in res.findings)


def test_committed_env_reported_by_path_only(tmp_path):
    _write(tmp_path / ".env", "API_SECRET=hunter2hunter2\n")
    res = run_policy_checks(tmp_path)
    finding = next(f for f in res.findings if f["rule_id"] == "CFG-001")
    assert finding["path"] == ".env"
    # Secret values are never read into the output.
    assert "hunter2" not in json.dumps(res.findings)


def test_cors_wildcard_detected(tmp_path):
    _write(
        tmp_path / "main.py",
        'app.add_middleware(CORSMiddleware, allow_origins=["*"])\n',
    )
    res = run_policy_checks(tmp_path)
    assert "CFG-002" in _rules(res)


def test_auth_boundary_observation_is_conditional(tmp_path):
    _write(tmp_path / "server.py", "@app.get('/x')\ndef x():\n    return 1\n")
    res = run_policy_checks(tmp_path)
    assert "AUTH-001" in _rules(res)

    # With an auth boundary present anywhere in scope, no absence is claimed.
    _write(
        tmp_path / "server2.py",
        "@app.get('/y')\ndef y(u=Depends(get_current_user)):\n    return 1\n",
    )
    res2 = run_policy_checks(tmp_path)
    assert "AUTH-001" not in _rules(res2)


def test_rule_hits_are_capped(tmp_path):
    _write(
        tmp_path / "app.py",
        "\n".join("subprocess.run(c, shell=True)" for _ in range(25)) + "\n",
    )
    res = run_policy_checks(tmp_path)
    hits = sum(1 for f in res.findings if f["rule_id"] == "SEC-101")
    assert hits == 20  # bounded work, no finding storms


def test_debug_mode_variable_variant_is_detected(tmp_path):
    # CFG-003 must catch DEBUG_MODE=/debug_mode= as well as debug=, but only
    # when the flag is explicitly True.
    _write(
        tmp_path / "settings.py",
        "DEBUG_MODE = True\n"
        "debug_mode=True\n"
        "debug_settings = True\n"   # different identifier: must NOT match
        "debug_mode = False\n",     # disabled: must NOT match
    )
    res = run_policy_checks(tmp_path)
    hits = [f for f in res.findings if f["rule_id"] == "CFG-003"]
    lines = {f["line"] for f in hits}
    assert lines == {1, 2}  # only the two genuinely-enabled debug flags


def test_truncated_walk_is_partial_and_never_claims_missing_auth(tmp_path):
    # More files than the safety cap, all declaring endpoints and none with
    # an auth boundary. The walk is truncated, so silence past the cap is not
    # evidence of a missing boundary: no AUTH-001, and status is PARTIAL.
    for i in range(810):
        _write(tmp_path / f"svc_{i:04d}.py", "@app.get('/x')\ndef x():\n    return 1\n")
    res = run_policy_checks(tmp_path)
    assert res.evidence["truncated"] is True
    assert res.status == "partial"
    assert "AUTH-001" not in _rules(res)
