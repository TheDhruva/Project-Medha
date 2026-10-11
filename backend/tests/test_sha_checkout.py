"""Exact-SHA acquisition: checkout, mismatch, and missing-commit behavior.

Local git fixtures exercise the real code path offline. Remote checkout is
covered by unit-testing the SHA gate (no network in CI).
"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.services import git_service
from app.services.git_service import (
    GitAcquireError,
    acquire_repository,
    checkout_commit,
    local_rev_parse,
    ls_remote_sha,
    normalize_commit_sha,
)

git = shutil.which("git")
needs_git = pytest.mark.skipif(git is None, reason="git executable unavailable")


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True, timeout=60)


@pytest.fixture()
def local_repo(tmp_path):
    if git is None:
        pytest.skip("git executable unavailable")
    repo = tmp_path / "src"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "-c", "user.email=t@t.t", "-c", "user.name=t", "commit", "--allow-empty", "-m", "one")
    (repo / "app.py").write_text("print('one')\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.email=t@t.t", "-c", "user.name=t", "commit", "-m", "two")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo), check=True,
                         capture_output=True, text=True, timeout=60).stdout.strip()
    return repo, sha


def test_normalize_commit_sha_gate():
    assert normalize_commit_sha("A" * 40) == "a" * 40
    for bad in [None, "", "0" * 40, "abc123", "z" * 40, "main", "HEAD~1"]:
        with pytest.raises(GitAcquireError):
            normalize_commit_sha(bad)


def test_local_rev_parse_accepts_exact_sha(local_repo):
    repo, sha = local_repo
    assert local_rev_parse(repo, sha) == sha


def test_local_rev_parse_rejects_unknown_sha(local_repo):
    repo, _ = local_repo
    with pytest.raises(GitAcquireError) as exc_info:
        local_rev_parse(repo, "b" * 40)
    assert exc_info.value.code == "SHA_NOT_FOUND"


@needs_git
def test_acquire_local_archive_materializes_exact_commit(local_repo, tmp_path):
    from app.services.workspace import cleanup_workspace

    repo, sha = local_repo
    try:
        acquisition = acquire_repository("dep_sha_archive", str(repo), ref_sha=sha)
        assert acquisition.method == "local_archive"
        assert acquisition.checked_sha == sha
        assert (acquisition.path / "app.py").is_file()
    finally:
        cleanup_workspace("dep_sha_archive")


@needs_git
def test_acquire_local_rejects_missing_sha(local_repo):
    from app.services.workspace import cleanup_workspace

    repo, _ = local_repo
    try:
        with pytest.raises(GitAcquireError):
            acquire_repository("dep_sha_missing", str(repo), ref_sha="c" * 40)
    finally:
        cleanup_workspace("dep_sha_missing")


@needs_git
def test_checkout_commit_rejects_garbage_sha(tmp_path):
    with pytest.raises(GitAcquireError):
        checkout_commit(tmp_path, "not-a-sha")


def test_ls_remote_returns_none_for_unreachable():
    # Local paths are never remotes; unresolvable hosts fail fast to None.
    assert ls_remote_sha(str("C:/definitely/not/a/repo")) is None
    assert ls_remote_sha("not a url at all") is None


def test_acquire_rejects_short_sha_without_network(tmp_path):
    with pytest.raises(GitAcquireError) as exc_info:
        acquire_repository("dep_short", str(tmp_path), ref_sha="abc123")
    assert exc_info.value.code == "INVALID_SHA"
