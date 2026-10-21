"""Push-payload summaries + checkout-verified change intelligence."""

from __future__ import annotations

import shutil
import subprocess

import pytest

from app.changeintel.push_intel import analyze_push_checkout, summarize_push


def _payload(**overrides):
    body = {
        "repository": {"full_name": "octo/demo"},
        "ref": "refs/heads/main",
        "after": "a" * 40,
        "before": "b" * 40,
        "commits": [
            {"id": "a" * 40, "message": "add app",
             "added": ["app.py"], "removed": [], "modified": ["README.md"]},
            {"id": "c" * 40, "message": "drop legacy",
             "added": [], "removed": ["legacy.py"], "modified": []},
        ],
    }
    body.update(overrides)
    return body


def test_summarize_push_collects_union():
    push = summarize_push(_payload())
    assert push["deleted"] is False
    assert push["target_sha"] == "a" * 40
    assert push["base_sha"] == "b" * 40
    by_path = {f["path"]: f["change_type"] for f in push["files"]}
    assert by_path == {"app.py": "added", "README.md": "modified", "legacy.py": "deleted"}


def test_summarize_push_deleted_branch():
    push = summarize_push(_payload(after="0" * 40))
    assert push["deleted"] is True
    assert push["target_sha"] is None


def test_summarize_push_initial_push_has_no_base():
    push = summarize_push(_payload(before="0" * 40))
    assert push["base_sha"] is None
    assert push["target_sha"] == "a" * 40


def test_summarize_push_empty_and_malformed():
    push = summarize_push(_payload(commits=[]))
    assert push["files"] == [] and push["commit_count"] == 0
    push = summarize_push({"after": "a" * 40, "before": "b" * 40})
    assert push["files"] == []


def test_summarize_push_drops_traversal_and_bounds_lists():
    evil = {"id": "a" * 40, "message": "x" * 500,
            "added": ["../escape.py", "ok.py"], "removed": [], "modified": []}
    push = summarize_push(_payload(commits=[evil]))
    paths = [f["path"] for f in push["files"]]
    assert paths == ["ok.py"]
    assert len(push["commits"][0]["message"]) == 200


def test_analyze_push_checkout_verifies_tree(tmp_path):
    tree = tmp_path / "repo"
    tree.mkdir()
    (tree / "app.py").write_text("import os\nprint(os.name)\n", encoding="utf-8")
    (tree / "README.md").write_text("# demo\n", encoding="utf-8")
    push = summarize_push(_payload())
    info = analyze_push_checkout(
        repository_url="https://github.com/octo/demo.git",
        base_sha=push["base_sha"],
        target_sha=push["target_sha"],
        files=push["files"],
        checkout_path=tree,
        deployment_id="dep_test",
    )
    assert info.changeset.source_method == "webhook_push"
    assert info.changeset.target_sha == "a" * 40
    assert {f.path for f in info.changeset.files} == {"app.py", "README.md", "legacy.py"}
    assert info.risk.level.value in {"none", "low", "medium", "high"}
    assert isinstance(info.to_ui(), dict)


def test_analyze_push_checkout_reports_missing_files(tmp_path):
    tree = tmp_path / "repo"
    tree.mkdir()
    push = summarize_push(_payload())
    info = analyze_push_checkout(
        repository_url="https://github.com/octo/demo.git",
        base_sha=push["base_sha"],
        target_sha=push["target_sha"],
        files=push["files"],
        checkout_path=tree,
        deployment_id="dep_test",
    )
    # Nothing in the tree: added/modified files are unverified, deletions stand.
    assert {f.path for f in info.changeset.files} == {"legacy.py"}
    assert any("app.py" in note for note in info.changeset.unsupported_files)
    # An unreadable base is never silently treated as an empty baseline.
    assert any("base-revision" in note for note in info.changeset.unsupported_files)


pytestmark_git = pytest.mark.skipif(
    shutil.which("git") is None, reason="git executable not available"
)


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _commit(repo, message: str) -> str:
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _init_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    return repo


@pytestmark_git
def test_base_symbols_detect_removed_and_modified_functions(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "mod.py").write_text(
        "def keep():\n    return 1\n\n\ndef gone():\n    return 2\n", encoding="utf-8"
    )
    base = _commit(repo, "base")
    (repo / "mod.py").write_text(
        "def keep():\n    return 10\n\n\ndef added():\n    return 3\n", encoding="utf-8"
    )
    target = _commit(repo, "target")

    info = analyze_push_checkout(
        repository_url=str(repo), base_sha=base, target_sha=target,
        files=[{"path": "mod.py", "change_type": "modified"}], checkout_path=repo,
    )
    changed = {(cs.symbol.name, cs.change_type.value) for cs in info.changed_symbols}
    assert ("gone", "deleted") in changed  # only visible with a real base index
    assert ("keep", "modified") in changed
    assert ("added", "modified") in changed


@pytestmark_git
def test_base_symbols_for_deleted_module(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "legacy.py").write_text("def old_api():\n    return 1\n", encoding="utf-8")
    (repo / "keep.py").write_text("x = 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    (repo / "legacy.py").unlink()
    target = _commit(repo, "drop legacy")

    info = analyze_push_checkout(
        repository_url=str(repo), base_sha=base, target_sha=target,
        files=[{"path": "legacy.py", "change_type": "deleted"}], checkout_path=repo,
    )
    names = {(cs.symbol.name, cs.change_type.value) for cs in info.changed_symbols}
    assert ("old_api", "deleted") in names


@pytestmark_git
def test_renamed_module_symbols_remap_to_new_path(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "old_name.py").write_text("def handler():\n    return 1\n", encoding="utf-8")
    base = _commit(repo, "base")
    _git(repo, "mv", "old_name.py", "new_name.py")
    target = _commit(repo, "rename")

    info = analyze_push_checkout(
        repository_url=str(repo), base_sha=base, target_sha=target,
        files=[{"path": "new_name.py", "change_type": "added"}], checkout_path=repo,
    )
    renamed = [cs for cs in info.changed_symbols if cs.change_type.value == "renamed"]
    assert renamed, "rename must be detected from git, not just payload"
    assert all(cs.symbol.path == "new_name.py" for cs in renamed)
    assert any(cs.symbol.name == "handler" for cs in renamed)


@pytestmark_git
def test_unavailable_base_is_labelled_not_empty_baseline(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "mod.py").write_text("def keep():\n    return 1\n", encoding="utf-8")
    _commit(repo, "only")

    info = analyze_push_checkout(
        repository_url=str(repo), base_sha="d" * 40, target_sha="e" * 40,
        files=[{"path": "mod.py", "change_type": "modified"}], checkout_path=repo,
    )
    assert any("base-revision" in n and "unavailable" in n
               for n in info.changeset.unsupported_files)


@pytestmark_git
def test_initial_push_has_no_base_note(tmp_path):
    repo = _init_repo(tmp_path)
    (repo / "app.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    target = _commit(repo, "init")

    info = analyze_push_checkout(
        repository_url=str(repo), base_sha=None, target_sha=target,
        files=[{"path": "app.py", "change_type": "added"}], checkout_path=repo,
    )
    assert not any("base-revision" in n for n in info.changeset.unsupported_files)
