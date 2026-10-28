"""Inventory cache: input-sensitive keys and honest storage.

The key commits to everything that can change the result (commit, target,
scanner configuration, tool binaries). Failed analyses are never stored;
every cache operation degrades to a miss instead of raising.
"""
from __future__ import annotations

from app.analysis.cache import inventory_cache_key, load_inventory, store_inventory


def _key(**over) -> str | None:
    base = dict(
        commit_sha="a" * 40,
        selected_target=None,
        scan_security=True,
        scanner_names=None,
        scanner_timeout_s=120.0,
    )
    base.update(over)
    return inventory_cache_key(**base)


def test_key_requires_an_immutable_commit():
    assert _key(commit_sha=None) is None
    assert _key(commit_sha="") is None


def test_key_is_deterministic_and_input_sensitive(monkeypatch):
    from app.security import scanners

    assert _key() == _key()  # identical inputs -> identical key
    assert _key() != _key(commit_sha="b" * 40)
    assert _key() != _key(selected_target="backend")
    assert _key() != _key(scanner_timeout_s=60.0)
    assert _key() != _key(scan_security=False)

    # A tool upgrade (different installed binaries) invalidates the key.
    monkeypatch.setattr(scanners, "supported_scanners", lambda: ["gitleaks"])
    one_tool = _key()
    monkeypatch.setattr(
        scanners, "supported_scanners", lambda: ["gitleaks", "semgrep"]
    )
    assert _key() != one_tool


def test_store_load_roundtrip_and_honest_skips(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.database.connection import init_db

    db = tmp_path / "cache.db"
    monkeypatch.setenv("MEDHA_DATABASE_PATH", str(db))
    monkeypatch.setenv("MEDHA_DATABASE_URL", "")
    get_settings.cache_clear()
    init_db(db)

    payload = {
        "schema": "repository-analysis/v1",
        "analysis_status": "completed",
        "commit_sha": "a" * 40,
    }
    key = _key()
    store_inventory(key, payload, project_id=None, target_sha="a" * 40)
    assert load_inventory(key) == payload

    # A failed analysis is never reusable as a clean result.
    store_inventory(
        "inv:failed",
        {"schema": "repository-analysis/v1", "analysis_status": "failed"},
        project_id=None,
        target_sha="b" * 40,
    )
    assert load_inventory("inv:failed") is None

    # Missing key / unknown key / no key all degrade to a miss.
    assert load_inventory(None) is None
    assert load_inventory("inv:unknown") is None
    store_inventory(None, payload, project_id=None, target_sha="")

    # A foreign schema is never trusted.
    store_inventory("inv:foreign", {"schema": "other/v1"}, project_id=None,
                    target_sha="c" * 40)
    assert load_inventory("inv:foreign") is None
