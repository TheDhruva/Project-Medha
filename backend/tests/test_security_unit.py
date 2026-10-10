"""Repository URL + git revision + workspace hardening tests (no network)."""

from __future__ import annotations

import pytest

from app.changeintel.git_extract import ChangeIntelError, _validate_revision
from app.core.repo_url import RepositoryUrlError, validate_repository_url
from app.services import workspace


def test_repository_url_accepts_github_https():
    assert (
        validate_repository_url("https://github.com/example/app")
        == "https://github.com/example/app"
    )
    assert validate_repository_url("https://github.com/example/app.git")
    assert validate_repository_url("git@github.com:org/repo.git")


def test_repository_url_accepts_local_paths(tmp_path):
    assert validate_repository_url(str(tmp_path)) == str(tmp_path)
    assert validate_repository_url(f"file://{tmp_path}") == f"file://{tmp_path}"


def test_repository_url_rejects_garbage():
    for bad in ("", "   ", "x", "not a url", "a" * 2001):
        with pytest.raises(RepositoryUrlError):
            validate_repository_url(bad)


def test_repository_url_rejects_dangerous_schemes():
    for bad in (
        "javascript:alert(1)",
        "data:text/plain,hi",
        "ftp://example.com/repo.git",
        "file:etc/passwd",
    ):
        with pytest.raises(RepositoryUrlError):
            validate_repository_url(bad)


def test_repository_url_blocks_metadata_and_private_ips():
    for bad in (
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/x.git",
        "https://10.0.0.5/repo.git",
        "https://192.168.1.10/repo.git",
        "https://172.16.0.9/repo.git",
        "http://0.0.0.0/repo.git",
    ):
        with pytest.raises(RepositoryUrlError) as exc:
            validate_repository_url(bad)
        assert exc.value.code == "REPOSITORY_URL_BLOCKED"


def test_repository_url_allows_loopback_dev_and_public_ips():
    assert validate_repository_url("http://127.0.0.1:8080/repo.git")
    assert validate_repository_url("https://93.184.216.34/repo.git")


def test_repository_url_rejects_embedded_credentials():
    with pytest.raises(RepositoryUrlError) as exc:
        validate_repository_url("https://user:secret@github.com/org/repo.git")
    assert exc.value.code == "REPOSITORY_URL_BLOCKED"


def test_validate_revision_accepts_normal_revisions():
    for good in (
        "main",
        "master",
        "develop",
        "feature/test",
        "v1.0.0",
        "abc123",
        "HEAD",
        "HEAD~1",
        "abc123^",
        "main@{1}",
    ):
        assert _validate_revision(good) == good


def test_validate_revision_rejects_flag_injection():
    for bad in ("", "-h", "--help", "--upload-pack=x", "a b", "a;b", "a$(b)", "a`b`", "a|b"):
        with pytest.raises(ChangeIntelError) as exc:
            _validate_revision(bad)
        assert exc.value.code == "REVISION_INVALID"


def test_deployment_workspace_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PROJECT_ROOT", tmp_path)
    for bad in ("", "../evil", "..", "a/b", "a\\b", ".", " dep_x "):
        with pytest.raises(ValueError):
            workspace.deployment_workspace(bad)


def test_cleanup_workspace_confined_to_root(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PROJECT_ROOT", tmp_path)
    root = workspace.workspaces_root()
    victim = tmp_path / "victim.txt"
    victim.write_text("keep")
    # A symlink escape must not delete outside the workspaces root.
    link = root / "dep_escape"
    try:
        link.symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    workspace.cleanup_workspace("dep_escape")
    assert victim.exists()
    assert root.exists()


def test_cleanup_workspace_parent_reference_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "PROJECT_ROOT", tmp_path)
    root = workspace.workspaces_root()
    sentinel = root.parent / "sentinel.txt"
    sentinel.write_text("keep")
    workspace.cleanup_workspace("..")
    assert sentinel.exists()
    assert sentinel.read_text() == "keep"


def test_prune_stale_workspaces_removes_old_only(tmp_path, monkeypatch):
    import os
    import time

    monkeypatch.setattr(workspace, "PROJECT_ROOT", tmp_path)
    workspace.deployment_workspace("dep_recent")
    old = workspace.deployment_workspace("dep_old123")
    ancient = time.time() - 48 * 3600
    os.utime(old, (ancient, ancient))
    removed = workspace.prune_stale_workspaces(max_age_hours=24)
    assert removed == 1
    assert (workspace.workspaces_root() / "dep_recent").exists()
    assert not (workspace.workspaces_root() / "dep_old123").exists()
