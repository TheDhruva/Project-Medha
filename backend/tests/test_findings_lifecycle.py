"""Cross-run finding ledger: stable identity, dedup, explicit lifecycle.

The ledger is the single source of truth for a finding's state across runs.
A finding never resolves merely because a file changed: absence is marked
``fixed_unverified`` only when the originating check actually re-ran, and
verified conclusions always require evidence references.
"""
from __future__ import annotations

import pytest

from app.database.connection import init_db
from app.database.repositories import (
    FINDING_STATUSES,
    FindingRepository,
    finding_fingerprint,
)


def _repo(tmp_path) -> FindingRepository:
    db = tmp_path / "findings.db"
    init_db(db)
    return FindingRepository(db_path=db)


def _finding(**over) -> dict:
    base = {
        "source": "scanner:gitleaks",
        "scanner": "gitleaks",
        "rule_id": "generic-api-key",
        "path": "app/settings.py",
        "line": 10,
        "message": "potential secret",
        "severity": "high",
    }
    base.update(over)
    return base


def _sync(repo: FindingRepository, findings: list, *, active=(), commit="sha1",
          dep="dep1"):
    return repo.sync_scan(
        project_id="p1",
        repository="https://example.invalid/r.git",
        deployment_id=dep,
        commit_sha=commit,
        findings=findings,
        active_sources=set(active),
        scanned_at="2026-01-01T00:00:00Z",
    )


# --- identity ---------------------------------------------------------------


def test_fingerprint_is_line_independent_and_input_scoped():
    a = finding_fingerprint("scanner:gitleaks", "rule", "a.py", "msg")
    b = finding_fingerprint("scanner:gitleaks", "rule", "a.py", "msg")
    assert a == b  # deterministic
    # Line drift (reformatted code) never changes identity.
    assert a == finding_fingerprint("scanner:gitleaks", "rule", "a.py", "msg")
    assert a != finding_fingerprint("scanner:semgrep", "rule", "a.py", "msg")
    assert a != finding_fingerprint("scanner:gitleaks", "other", "a.py", "msg")
    assert a != finding_fingerprint("scanner:gitleaks", "rule", "b.py", "msg")
    assert a != finding_fingerprint("scanner:gitleaks", "rule", "a.py", "other")


def test_scan_inserts_once_then_updates_same_row(tmp_path):
    repo = _repo(tmp_path)
    first = _sync(repo, [_finding()])
    assert first["inserted"] == 1

    second = _sync(repo, [_finding(line=999)], dep="dep2", commit="sha2")
    assert second["inserted"] == 0 and second["updated"] == 1

    items = repo.list(project_id="p1")
    assert len(items) == 1  # dedup across scans
    assert items[0]["status"] == "detected"
    assert items[0]["first_seen_sha"] == "sha1"
    assert items[0]["last_seen_sha"] == "sha2"


# --- absence marking --------------------------------------------------------


def test_absence_marked_only_when_source_actually_ran(tmp_path):
    repo = _repo(tmp_path)
    _sync(repo, [_finding()])

    # The originating check did not run this scan: state is untouched.
    _sync(repo, [], active=set())
    assert repo.list(project_id="p1")[0]["status"] == "detected"

    # A different scanner ran: still untouched (absence is per-source).
    _sync(repo, [], active={"scanner:semgrep"})
    assert repo.list(project_id="p1")[0]["status"] == "detected"

    # gitleaks re-ran clean: fixed_unverified — never "resolved" without
    # anyone verifying the fix.
    _sync(repo, [], active={"scanner:gitleaks"})
    item = repo.list(project_id="p1")[0]
    assert item["status"] == "fixed_unverified"
    assert item["verification_status"] != "verified"


def test_reopen_when_condition_is_redetected(tmp_path):
    repo = _repo(tmp_path)
    _sync(repo, [_finding()])
    _sync(repo, [], active={"scanner:gitleaks"})          # fixed_unverified
    _sync(repo, [_finding()], dep="dep3", commit="sha3")  # present again
    item = repo.list(project_id="p1")[0]
    assert item["status"] == "reopened"
    transitions = [h["to"] for h in item["history"]]
    assert "reopened" in transitions


def test_builtin_absence_follows_same_rule(tmp_path):
    repo = _repo(tmp_path)
    _sync(repo, [_finding(source="builtin", scanner="builtin", rule_id="SEC-101")])
    _sync(repo, [], active={"scanner:gitleaks"})  # builtin did not run
    assert repo.list(project_id="p1")[0]["status"] == "detected"
    _sync(repo, [], active={"builtin"})
    assert repo.list(project_id="p1")[0]["status"] == "fixed_unverified"


# --- lifecycle state machine ------------------------------------------------


def test_illegal_transitions_and_missing_reason_raise(tmp_path):
    repo = _repo(tmp_path)
    _sync(repo, [_finding()])
    fid = repo.list(project_id="p1")[0]["finding_id"]

    with pytest.raises(ValueError, match="reason"):
        repo.transition(fid, "under_investigation", reason="  ",
                        at="2026-01-02T00:00:00Z")
    # detected -> resolved skips every verification step: refused.
    with pytest.raises(ValueError, match="invalid transition"):
        repo.transition(fid, "resolved", reason="file changed",
                        at="2026-01-02T00:00:00Z", evidence=["run:x"])
    with pytest.raises(ValueError, match="unknown finding status"):
        repo.transition(fid, "banana", reason="x", at="2026-01-02T00:00:00Z")


def test_verified_conclusions_require_evidence(tmp_path):
    repo = _repo(tmp_path)
    _sync(repo, [_finding()])
    fid = repo.list(project_id="p1")[0]["finding_id"]

    with pytest.raises(ValueError, match="evidence"):
        repo.transition(fid, "confirmed", reason="triaged",
                        at="2026-01-02T00:00:00Z")
    ok = repo.transition(
        fid, "under_investigation", reason="triage queue",
        at="2026-01-02T00:00:00Z",
    )
    assert ok["status"] == "under_investigation"
    confirmed = repo.transition(
        fid, "confirmed", reason="reproduced against the live endpoint",
        at="2026-01-03T00:00:00Z",
        evidence=["run:dep1#verify"],
    )
    assert confirmed["status"] == "confirmed"
    assert confirmed["verification_status"] == "verified"


def test_statuses_match_documented_contract():
    assert FINDING_STATUSES == (
        "detected", "under_investigation", "confirmed", "rejected",
        "accepted_risk", "fixed_unverified", "resolved", "reopened",
    )


# --- API contract -----------------------------------------------------------


def test_findings_endpoints_enforce_lifecycle(client):
    import json

    from app.database.repositories import DeploymentRepository, FindingRepository

    created = client.post("/api/deploy", json={
        "repository_url": "https://example.invalid/r.git",
        "mode": "real",
        "intent": "Deploy securely",
        "target": {"host": "localhost", "port": 8080},
    }).json()
    dep_id = created["deployment_id"]
    record = DeploymentRepository().get(dep_id)
    assert record is not None

    FindingRepository().sync_scan(
        project_id=record.project_id or "",
        repository=record.repository_url,
        deployment_id=dep_id,
        commit_sha="a" * 40,
        findings=[_finding()],
        active_sources=set(),
        scanned_at="2026-01-01T00:00:00Z",
    )
    rows = FindingRepository().list(
        project_id=record.project_id or "", repository=record.repository_url,
    )
    assert len(rows) == 1
    fid = rows[0]["finding_id"]

    body = client.get(f"/api/deploy/{dep_id}/findings").json()
    assert body["status_counts"] == {"detected": 1}
    assert body["lifecycle_states"] == list(FINDING_STATUSES)

    bad = client.get(f"/api/deploy/{dep_id}/findings", params={"status": "banana"})
    assert bad.status_code == 400

    # Verified conclusion without evidence: refused by the API too.
    r = client.post(
        f"/api/deploy/{dep_id}/findings/{fid}",
        json={"status": "confirmed", "reason": "looks bad to me"},
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "FINDING_TRANSITION_INVALID"

    ok = client.post(
        f"/api/deploy/{dep_id}/findings/{fid}",
        json={"status": "under_investigation", "reason": "queued for triage"},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["finding"]["status"] == "under_investigation"

    missing = client.post(
        f"/api/deploy/{dep_id}/findings/fnd_missing",
        json={"status": "rejected", "reason": "n", "evidence": ["e"]},
    )
    assert missing.status_code == 404

    # The stored history survives serialization end to end.
    persisted = client.get(f"/api/deploy/{dep_id}/findings").json()["findings"][0]
    assert [h["to"] for h in persisted["history"]] == [
        "detected", "under_investigation",
    ]
    assert json.dumps(persisted)  # fully JSON-serializable
