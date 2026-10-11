"""Push-payload summaries + checkout-verified change intelligence."""

from __future__ import annotations

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
