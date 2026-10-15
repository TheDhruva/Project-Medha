"""Focused tests: commit metadata extraction, summary persistence, API shape.

No daemon, no network: local git fixture repos + tmp SQLite databases.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def _git(cwd: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    return (out.stdout or "").strip()


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t.t")
    _git(repo, "config", "user.name", "Test Author")
    (repo / "a.txt").write_text("one", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add a")
    (repo / "sub").mkdir()
    (repo / "sub" / "b.txt").write_text("two\nthree", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "add b\n\nSecond line of body.")
    return repo


def _head(repo: Path) -> str:
    return _git(repo, "rev-parse", "HEAD").lower()


def test_commit_metadata_and_diff_summary(git_repo: Path):
    from app.services import history_service as hs

    sha = _head(git_repo)
    entry = hs.commit_metadata(git_repo, sha)
    assert entry.sha == sha
    assert entry.author == "Test Author"
    assert entry.committed_at
    assert entry.message and entry.message.startswith("add b")
    assert entry.parents and len(entry.parents[0]) == 40

    diff = hs.changed_files_summary(git_repo, sha)
    assert diff["sha"] == sha
    assert [f["path"] for f in diff["files"]] == ["sub/b.txt"]
    assert diff["added"] == 2 and diff["deleted"] == 0

    summary = hs.build_commit_summary(entry, diff)
    assert summary.startswith("add b")
    assert "+2/-0" in summary
    assert "sub/b.txt" in summary
    assert len(summary) <= 500

    with pytest.raises(hs.HistoryError):
        hs.commit_metadata(git_repo, "short")


def test_summary_without_diff_is_metadata_only(git_repo: Path):
    from app.services import history_service as hs

    entry = hs.commit_metadata(git_repo, _head(git_repo))
    summary = hs.build_commit_summary(entry, None)
    assert "add b" in summary
    assert "unavailable" in summary
    # Never fabricates file claims.
    assert "sub/b.txt" not in summary


def test_commit_repository_round_trip_with_summary(tmp_path: Path):
    from app.database.connection import init_db
    from app.database.repositories import CommitRepository

    db = tmp_path / "c.db"
    init_db(db)
    repo = CommitRepository(db_path=db)
    repo.upsert(
        project_id="prj_1", sha="a" * 40, parents=[], author="A",
        committed_at="2026-01-01T00:00:00Z", message="add b",
        branch="main", recorded_at="2026-01-02T00:00:00Z",
        summary="add b — +2/-0 across 1 file(s)", files=[{"path": "b", "added": 2, "deleted": 0}],
        added=2, deleted=0, deployment_id="dep_1",
    )
    row = repo.get(project_id="prj_1", sha="a" * 40)
    assert row is not None
    assert row["summary"].startswith("add b")
    assert row["files"] == [{"path": "b", "added": 2, "deleted": 0}]
    assert row["added"] == 2 and row["deployment_id"] == "dep_1"

    # Bulk ancestry upsert without diff evidence keeps the analyzed summary.
    repo.upsert(
        project_id="prj_1", sha="a" * 40, parents=[], author="A",
        committed_at="2026-01-01T00:00:00Z", message="add b",
        branch="main", recorded_at="2026-01-03T00:00:00Z",
    )
    kept = repo.get(project_id="prj_1", sha="a" * 40)
    assert kept is not None and kept["summary"].startswith("add b")
    assert kept["files"] == [{"path": "b", "added": 2, "deleted": 0}]

    assert repo.get(project_id="prj_1", sha="b" * 40) is None
    assert repo.history(project_id="prj_nobody") == []


def test_migration_adds_summary_columns_to_legacy_db(tmp_path: Path):
    import sqlite3

    from app.database.connection import init_db
    from app.database.repositories import CommitRepository

    db = tmp_path / "legacy.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE commits (project_id TEXT NOT NULL, sha TEXT NOT NULL,"
            " parents_json TEXT NOT NULL DEFAULT '[]', author TEXT,"
            " committed_at TEXT, message TEXT, branch TEXT,"
            " recorded_at TEXT NOT NULL, PRIMARY KEY (project_id, sha))"
        )
        conn.execute(
            "INSERT INTO commits VALUES ('prj_old', ?, '[]', 'A',"
            " '2026-01-01T00:00:00Z', 'old msg', 'main', '2026-01-02T00:00:00Z')",
            ("c" * 40,),
        )
        conn.commit()
    init_db(db)
    with sqlite3.connect(db) as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(commits)")}
    assert {"summary", "files_json", "added", "deleted", "deployment_id"} <= cols
    row = CommitRepository(db_path=db).get(project_id="prj_old", sha="c" * 40)
    assert row is not None and row["message"] == "old msg"
    assert row["summary"] is None  # unavailable, never fabricated


def test_history_api_serves_persisted_without_reacquire(client, monkeypatch):
    import app.api.history as history_api
    from app.core.events import utc_now_iso
    from app.database.repositories import CommitRepository, ProjectRepository
    from app.models.deployment import ProjectRecord

    now = utc_now_iso()
    project = ProjectRecord(
        project_id="prj_hist1", owner_sub="local-operator", name="demo",
        provider="github", repo_owner="o", repo_name="r", repository="o/r",
        canonical_url="https://github.com/o/r.git", branch="main",
        visibility="unverified", connection_status="pending",
        created_at=now, updated_at=now,
    )
    ProjectRepository().create(project)
    CommitRepository().upsert(
        project_id="prj_hist1", sha="d" * 40, parents=["e" * 40],
        author="Dev", committed_at="2026-02-01T00:00:00Z",
        message="ship it", branch="main", recorded_at=now,
        summary="ship it — +10/-2 across 3 file(s)",
        files=[{"path": "x.py", "added": 10, "deleted": 2}],
        added=10, deleted=2, deployment_id="dep_x",
    )

    def _boom(*args, **kwargs):
        raise AssertionError("must not re-acquire when persisted rows exist")

    monkeypatch.setattr(history_api, "acquire_repository", _boom)
    r = client.get("/api/projects/prj_hist1/history")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "persisted"
    assert body["commits"][0]["sha"] == "d" * 40
    assert body["commits"][0]["summary"].startswith("ship it")
    assert body["commits"][0]["author"] == "Dev"
    assert body["commits"][0]["github_url"].endswith(f"/commit/{'d' * 40}")

    d = client.get(f"/api/projects/prj_hist1/history/{'d' * 40}")
    assert d.status_code == 200, d.text
    detail = d.json()
    assert detail["source"] == "persisted"
    assert detail["files"] == [{"path": "x.py", "added": 10, "deleted": 2}]
    assert detail["summary"].startswith("ship it")

    assert client.get("/api/projects/prj_hist1/history/short").status_code == 400
    assert client.get("/api/projects/prj_missing/history").status_code == 404


def test_pipeline_records_analyzed_commit(tmp_path: Path, monkeypatch):
    import asyncio

    from app.core.enums import DeploymentStatus
    from app.core.events import utc_now_iso
    from app.database.connection import init_db
    from app.database.repositories import (
        CommitRepository,
        DeploymentRepository,
        ProjectRepository,
    )
    from app.models.deployment import DeploymentRecord, ProjectRecord
    from app.workflow.planning import PlanningPipeline

    src = tmp_path / "src"
    src.mkdir()
    (src / "package.json").write_text(
        '{"scripts": {"start": "node server.js"}}', encoding="utf-8")
    (src / "server.js").write_text("console.log(1)", encoding="utf-8")
    _git(src, "init", "-b", "main")
    _git(src, "config", "user.email", "t@t.t")
    _git(src, "config", "user.name", "t")
    _git(src, "add", ".")
    _git(src, "commit", "-m", "initial app")
    head = _head(src)

    db = tmp_path / "t.db"
    init_db(db)
    repo = DeploymentRepository(db_path=db)
    now = utc_now_iso()
    ProjectRepository(db_path=db).create(ProjectRecord(
        project_id="prj_pipe1", owner_sub="local-operator", name="app",
        provider="github", repo_owner="o", repo_name="app", repository="o/app",
        canonical_url=str(src), branch="main", visibility="unverified",
        connection_status="pending", created_at=now, updated_at=now,
    ))
    repo.create(DeploymentRecord(
        deployment_id="dep_pipe1", repository_url=str(src),
        mode="real", scenario=None, target_host="localhost", target_port=8080,
        intent=None, base_revision=None, target_revision=head,
        status=DeploymentStatus.STARTED, current_stage=None,
        project_id="prj_pipe1",
        created_at=now, updated_at=now, is_demo=False,
    ))
    asyncio.run(PlanningPipeline(repo=repo).run("dep_pipe1", plan_only=True))
    row = CommitRepository(db_path=db).get(project_id="prj_pipe1", sha=head)
    assert row is not None
    assert row["message"] and row["message"].startswith("initial app")
    assert row["summary"] and row["summary"].startswith("initial app")
    assert any(f["path"] == "package.json" for f in row["files"])
    assert row["deployment_id"] == "dep_pipe1"
    assert row["branch"] == "main"
