"""Focused tests: versioned runtime spec + extensible profile detection.

Pure detection/Dockerfile rendering — no daemon required. Covers the four
supported profiles (nextjs / node / static / python-asgi), lockfile-aware
package managers, monorepo ambiguity, and fail-closed unsupported cases.
"""

from __future__ import annotations

import json

import pytest

from app.execution.profiles import (
    UnsupportedStack,
    detect_profile,
    render_dockerfile,
)
from app.execution.runtime import RUNTIME_SCHEMA, detect_runtime


def _write_pkg(root, pkg: dict) -> None:
    (root / "package.json").write_text(json.dumps(pkg), encoding="utf-8")


NEXT_PKG = {
    "name": "site",
    "packageManager": "pnpm@10.12.4",
    "scripts": {"build": "next build", "start": "next start"},
    "dependencies": {"next": "16.2.12", "react": "19.2.4"},
}


def test_nextjs_pnpm_spec_with_build(tmp_path):
    _write_pkg(tmp_path, NEXT_PKG)
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n", encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080, commit_sha="a" * 40)
    assert spec.profile == "nextjs"
    assert spec.outcome.value == "supported"
    assert spec.package_manager == "pnpm"
    assert spec.framework == "next"
    assert spec.build.required is True
    assert spec.build.command == ["pnpm", "run", "build"]
    assert spec.start.command == ["pnpm", "start"]
    assert spec.start.bind_host == "0.0.0.0"
    assert spec.env_defaults == {"PORT": "8080", "HOSTNAME": "0.0.0.0"}
    assert spec.internal_port == 8080 and spec.host_port == 8080
    assert spec.base_image == "node:22-slim"
    assert spec.commit_sha == "a" * 40
    assert spec.runtime_schema == RUNTIME_SCHEMA

    profile = spec.to_build_profile()
    assert profile.name == "nextjs"
    assert profile.build_command == ["pnpm", "run", "build"]
    text = render_dockerfile(profile, checkout=tmp_path)
    assert "corepack enable" in text
    assert "pnpm install --frozen-lockfile" in text
    assert "RUN pnpm run build" in text
    assert "node:22-slim" in text
    assert "USER node" in text


def test_nextjs_npm_lockfile_uses_ci(tmp_path):
    pkg = dict(NEXT_PKG)
    pkg.pop("packageManager")
    _write_pkg(tmp_path, pkg)
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 3}\n', encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.package_manager == "npm"
    assert spec.build.command == ["npm", "run", "build"]
    text = render_dockerfile(spec.to_build_profile(), checkout=tmp_path)
    assert "npm ci" in text


def test_nextjs_explicit_script_port_honored(tmp_path):
    pkg = dict(NEXT_PKG)
    pkg["scripts"] = {"build": "next build", "start": "next start -p 3000"}
    _write_pkg(tmp_path, pkg)
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.internal_port == 3000
    assert spec.host_port == 8080
    assert spec.env_defaults["PORT"] == "3000"


def test_nextjs_without_build_or_output_unsupported(tmp_path):
    _write_pkg(tmp_path, {
        "scripts": {"start": "next start"},
        "dependencies": {"next": "15.0.0"},
    })
    with pytest.raises(UnsupportedStack) as exc:
        detect_runtime(tmp_path)
    assert "production build" in exc.value.message


def test_nextjs_committed_output_skips_build(tmp_path):
    _write_pkg(tmp_path, {
        "scripts": {"start": "next start"},
        "dependencies": {"next": "15.0.0"},
    })
    out = tmp_path / ".next"
    out.mkdir()
    (out / "BUILD_ID").write_text("abc", encoding="utf-8")
    spec = detect_runtime(tmp_path)
    assert spec.profile == "nextjs"
    assert spec.build.required is False


def test_generic_node_yarn(tmp_path):
    _write_pkg(tmp_path, {
        "scripts": {"start": "node server.js --port 8080"},
        "dependencies": {"express": "^4.19.0"},
    })
    (tmp_path / "yarn.lock").write_text("# yarn\n", encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.profile == "node"
    assert spec.package_manager == "yarn"
    assert spec.framework == "express"
    assert spec.build.required is False
    assert spec.start.command == ["yarn", "start"]
    text = render_dockerfile(spec.to_build_profile(), checkout=tmp_path)
    assert "yarn install" in text
    assert "node:22-alpine" in text


def test_generic_node_legacy_npm_path_unchanged(tmp_path):
    # No lockfile → npm default, legacy slim install without a build step.
    _write_pkg(tmp_path, {"scripts": {"start": "node server.js"}})
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.profile == "node"
    assert spec.package_manager == "npm"
    text = render_dockerfile(spec.to_build_profile(), checkout=tmp_path)
    assert "--omit=dev" in text
    assert "RUN npm run build" not in text


def test_bun_lockfile_fails_clearly(tmp_path):
    _write_pkg(tmp_path, {"scripts": {"start": "bun run index.ts"}})
    (tmp_path / "bun.lockb").write_text("bun", encoding="utf-8")
    with pytest.raises(UnsupportedStack) as exc:
        detect_runtime(tmp_path)
    assert exc.value.code == "UNSUPPORTED_STACK"
    assert "bun" in exc.value.message.lower()


def test_static_profile(tmp_path):
    (tmp_path / "index.html").write_text("<h1>hi</h1>", encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.profile == "static"
    assert spec.base_image == "nginx:1.27-alpine"
    assert detect_profile(tmp_path).name == "static"


def test_python_fastapi_profile(tmp_path):
    (tmp_path / "requirements.txt").write_text("fastapi\nuvicorn\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("app = 1", encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.profile == "python-asgi"
    assert spec.framework == "fastapi"
    assert spec.start.command[0] == "uvicorn"
    assert "--host" in spec.start.command and "0.0.0.0" in spec.start.command
    assert detect_profile(tmp_path).name == "python"


def test_empty_checkout_unsupported(tmp_path):
    with pytest.raises(UnsupportedStack) as exc:
        detect_runtime(tmp_path)
    assert exc.value.code == "UNSUPPORTED_STACK"


def test_monorepo_root_ambiguous(tmp_path):
    for app in ("web", "api"):
        sub = tmp_path / app
        sub.mkdir()
        _write_pkg(sub, {"scripts": {"start": "node i.js"}})
    with pytest.raises(UnsupportedStack) as exc:
        detect_runtime(tmp_path)
    assert exc.value.code == "AMBIGUOUS_TARGET"
    assert "target" in exc.value.message.lower()


def test_spec_validation_rejects_bad_sha_port_root(tmp_path):
    _write_pkg(tmp_path, {"scripts": {"start": "node i.js"}})
    with pytest.raises(UnsupportedStack):
        detect_runtime(tmp_path, target_port=99999)
    spec = detect_runtime(tmp_path, target_port=8080)
    base = spec.model_dump()
    with pytest.raises(Exception):
        type(spec)(**{**base, "commit_sha": "not-a-sha"})
    with pytest.raises(Exception):
        type(spec)(**{**base, "internal_port": 0})
    with pytest.raises(Exception):
        type(spec)(**{**base, "app_root": "../escape"})


def test_env_example_contributes_names_only(tmp_path):
    _write_pkg(tmp_path, {"scripts": {"start": "node i.js"}})
    (tmp_path / ".env.example").write_text(
        "RESEND_API_KEY=\nNEXT_PUBLIC_SITE_URL=https://x.example\n"
        "# comment\nnot a var\n",
        encoding="utf-8",
    )
    spec = detect_runtime(tmp_path)
    assert "RESEND_API_KEY" in spec.required_env_names
    assert "NEXT_PUBLIC_SITE_URL" in spec.required_env_names
    evidence = spec.to_evidence()
    assert "RESEND_API_KEY" in evidence["env_names"]
    # Names only — no values ever carried.
    assert "https://x.example" not in json.dumps(evidence)


def test_legacy_detect_profile_names_preserved(tmp_path):
    node = tmp_path / "n"
    node.mkdir()
    _write_pkg(node, {"scripts": {"start": "node i.js"}})
    assert detect_profile(node).name == "node"
    nxt = tmp_path / "j"
    nxt.mkdir()
    _write_pkg(nxt, NEXT_PKG)
    assert detect_profile(nxt).name == "nextjs"


# --- Package-manager selection: declaration + lockfile evidence -------------

from app.execution.runtime import select_package_manager


def test_selector_respects_declared_pnpm_without_lockfile(tmp_path):
    pm, pinned, evidence, found, conflict = select_package_manager(
        tmp_path, {"packageManager": "pnpm@10.12.4"})
    assert conflict is None
    assert pm == "pnpm" and pinned == "10.12.4"
    assert any("declared" in line for line in evidence)


def test_selector_conflicting_lockfiles_fail_closed(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("x", encoding="utf-8")
    pm, _v, _e, found, conflict = select_package_manager(tmp_path, {})
    assert pm is None and conflict is not None
    assert "pnpm-lock.yaml" in conflict and "yarn.lock" in conflict
    assert set(found) == {"pnpm", "yarn"}


def test_selector_declaration_resolves_conflict(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("x", encoding="utf-8")
    pm, pinned, _e, _f, conflict = select_package_manager(
        tmp_path, {"packageManager": "pnpm@9.0.0"})
    assert conflict is None and pm == "pnpm" and pinned == "9.0.0"


def test_selector_declaration_contradicting_lockfile_fails(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("x", encoding="utf-8")
    _pm, _v, _e, _f, conflict = select_package_manager(
        tmp_path, {"packageManager": "yarn@1.22.22"})
    assert conflict is not None and "yarn" in conflict


def test_selector_unparseable_declaration_falls_back_to_lockfile(tmp_path):
    (tmp_path / "yarn.lock").write_text("x", encoding="utf-8")
    pm, _v, evidence, _f, conflict = select_package_manager(
        tmp_path, {"packageManager": "not-a-version"})
    assert conflict is None and pm == "yarn"
    assert any("unparseable" in line for line in evidence)


def test_detect_runtime_conflict_is_diagnostic(tmp_path):
    _write_pkg(tmp_path, {"scripts": {"start": "node i.js"}})
    (tmp_path / "pnpm-lock.yaml").write_text("x", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}", encoding="utf-8")
    with pytest.raises(UnsupportedStack) as exc:
        detect_runtime(tmp_path)
    assert exc.value.code == "UNSUPPORTED_STACK"
    assert "pnpm-lock.yaml" in exc.value.message
    assert "package-lock.json" in exc.value.message


def test_detect_runtime_pins_declared_pnpm(tmp_path):
    _write_pkg(tmp_path, NEXT_PKG)
    (tmp_path / "pnpm-lock.yaml").write_text("x", encoding="utf-8")
    spec = detect_runtime(tmp_path, target_port=8080)
    assert spec.package_manager == "pnpm"
    assert spec.package_manager_version == "10.12.4"
    assert any("10.12.4" in line for line in spec.evidence)


def test_analyzer_reports_selected_package_manager(tmp_path):
    from app.agents.analyzer import analyze_repository

    site = tmp_path / "site"
    site.mkdir()
    _write_pkg(site, NEXT_PKG)
    (site / "pnpm-lock.yaml").write_text("x", encoding="utf-8")
    profile, _result = analyze_repository(
        deployment_id="dep_pm", repository_url=str(site),
        workspace_path=site, target_host="localhost", target_port=8080,
    )
    assert "pnpm" in profile.inferred_stack.package_managers
    assert "npm" not in profile.inferred_stack.package_managers
    assert any("pnpm" in note for note in profile.inferred_stack.notes)


def test_analyzer_conflict_is_recorded_not_crashed(tmp_path):
    from app.agents.analyzer import analyze_repository

    site = tmp_path / "site"
    site.mkdir()
    _write_pkg(site, {"scripts": {"start": "node i.js"}})
    (site / "pnpm-lock.yaml").write_text("x", encoding="utf-8")
    (site / "yarn.lock").write_text("x", encoding="utf-8")
    profile, result = analyze_repository(
        deployment_id="dep_pm2", repository_url=str(site),
        workspace_path=site, target_host="localhost", target_port=8080,
    )
    assert result.ok
    assert any("conflict" in note.lower() for note in profile.inferred_stack.notes)
