"""Repository summary generation, validation, and API exposure."""

from __future__ import annotations

import time
from pathlib import Path

from app.analysis.inventory import build_repository_inventory
from app.analysis.summary import (
    build_repository_summary,
    present_repository_summary,
    read_readme_excerpt,
)
from tests.conftest import _deploy_payload


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _inventory(root: Path, sha: str | None = None) -> dict:
    _write(root / "package.json", '{"name": "demo", "scripts": {"start": "node index.js"}}')
    _write(root / "index.js", "console.log('demo')")
    return build_repository_inventory(root, commit_sha=sha, scanner_names=[])


def test_readme_excerpt_skips_badges_and_headings(tmp_path):
    _write(
        tmp_path / "README.md",
        "# Demo\n\n"
        "[![Build](https://img.shields.io/badge/build-passing-green)](https://example.com)\n\n"
        "Demo is a small FastAPI service that manages tasks and exposes a JSON API for clients.\n\n"
        "## Install\n\nrun pip install demo\n",
    )
    excerpt = read_readme_excerpt(tmp_path)
    assert excerpt.startswith("Demo is a small FastAPI service")
    assert "img.shields" not in excerpt


def test_deterministic_summary_uses_readme_and_revision(tmp_path):
    sha = "a" * 40
    analysis = _inventory(tmp_path, sha)
    _write(
        tmp_path / "README.md",
        "Demo is a small FastAPI service that manages tasks and exposes a JSON API for clients.",
    )
    summary = build_repository_summary(tmp_path, analysis)
    assert summary["schema"] == "repository-summary/v1"
    assert summary["source"] == "deterministic"
    assert summary["commit_sha"] == sha
    assert "FastAPI" in summary["text"]
    assert "node" in summary["technologies"]


def test_no_readme_falls_back_to_manifest_evidence(tmp_path):
    analysis = _inventory(tmp_path)
    summary = build_repository_summary(tmp_path, analysis)
    assert summary["source"] == "deterministic"
    assert "no README description" in summary["text"]
    assert "demo" not in summary["text"].lower()  # no project name repetition


def test_unsafe_readme_claim_is_not_repeated(tmp_path):
    _write(tmp_path / "README.md", "This project is production-ready and fully secure.")
    analysis = _inventory(tmp_path)
    summary = build_repository_summary(tmp_path, analysis)
    assert "production-ready" not in summary["text"].lower()
    assert "fully secure" not in summary["text"].lower()


def test_valid_ai_summary_is_preferred_and_unsafe_is_rejected(tmp_path):
    analysis = _inventory(tmp_path)
    good = build_repository_summary(
        tmp_path,
        analysis,
        ai_summary="A task API that appears to use FastAPI and serves JSON clients.",
        ai_meta={"outcome": "ai_assisted", "provider": "groq", "model": "m"},
    )
    assert good["source"] == "ai"
    assert good["ai"]["provider"] == "groq"
    assert "task API" in good["text"]

    for bad in ("", "   ", "Production-ready and fully secure.", "x " * 100):
        summary = build_repository_summary(tmp_path, analysis, ai_summary=bad)
        assert summary["source"] == "deterministic"
        assert summary["ai"] is None


def test_present_summary_validates_and_marks_stale_revision():
    stored = {
        "schema": "repository-summary/v1",
        "text": "A repository summary.",
        "source": "deterministic",
        "commit_sha": "a" * 40,
        "generated_at": "2026-01-01T00:00:00Z",
        "technologies": ["python"],
        "ai": None,
    }
    present = present_repository_summary(
        {"repository_analysis": {"summary": stored}}, "b" * 40
    )
    assert present["status"] == "stale"
    assert present["text"] == "A repository summary."
    same = present_repository_summary(
        {"repository_analysis": {"summary": stored}}, "a" * 40
    )
    assert same["status"] == "available"


def test_present_summary_is_unavailable_when_missing_or_malformed():
    missing = present_repository_summary({"repository_analysis": {}}, None)
    assert missing["status"] == "unavailable" and missing["text"] is None

    malformed = present_repository_summary(
        {"repository_analysis": {"summary": {"schema": "repository-summary/v1", "text": 3}}}, None
    )
    assert malformed["status"] == "unavailable"

    assert present_repository_summary(
        {"repository_analysis": {"summary": {"schema": "other", "text": "x", "source": "ai", "generated_at": "t"}}},
        None,
    )["status"] == "unavailable"


def _wait_terminal(client, deployment_id: str, timeout: float = 60.0) -> dict:
    deadline = time.time() + timeout
    body: dict = {}
    while time.time() < deadline:
        body = client.get(f"/api/deploy/{deployment_id}").json()
        if body.get("status") in {
            "completed", "failed", "partial_recovery", "cancelled", "awaiting_approval",
        }:
            return body
        time.sleep(0.05)
    raise AssertionError(f"Deployment did not finish: {body}")


def test_run_persists_summary_and_runs_api_exposes_it(client, tmp_path, monkeypatch):
    # Summary persistence does not depend on Docker; isolate from an operator
    # .env that requests real execution.
    from app.core.config import get_settings

    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "false")
    get_settings.cache_clear()

    repo = tmp_path / "demo-app"
    _write(repo / "package.json", '{"name": "demo", "scripts": {"start": "node index.js"}}')
    _write(repo / "index.js", "console.log('demo')")
    _write(
        repo / "README.md",
        "Demo is a small Node service that exposes a JSON API for task tracking.",
    )

    response = client.post("/api/deploy", json=_deploy_payload(repository_url=str(repo)))
    assert response.status_code == 202, response.text
    deployment_id = response.json()["deployment_id"]
    final = _wait_terminal(client, deployment_id)

    summary = final["result"].get("repository_analysis", {}).get("summary")
    assert summary, sorted(final["result"])
    assert summary["schema"] == "repository-summary/v1"
    assert summary["source"] == "deterministic"
    assert "Node service" in summary["text"]

    runs = client.get("/api/deploys").json()["runs"]
    row = next(r for r in runs if r["deployment_id"] == deployment_id)
    assert row["repository_summary"]["status"] in {"available", "stale"}
    assert row["repository_summary"]["text"] == summary["text"]
    # Additive change: existing run fields are still present.
    assert row["deployment_id"] == deployment_id
    assert "repository_url" in row
