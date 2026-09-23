"""Phase 2 — Change Intelligence tests.

Coverage:
  * unit-level analysis of the 10 git fixture repositories (evidence edges,
    traversal, risk levels, verification requirements)
  * API: live analyze route, demo fixture (DEMO/MOCK labelled), deployment-
    linked persistence, GET /deploy/{id}/change-impact, error codes
  * one full-chain integration: git repo → diff → symbols → dependency edges →
    CIG → risk → verification requirement → stored → API
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.changeintel.engine import analyze_change_impact
from app.changeintel.git_extract import ChangeIntelError
from app.changeintel.models import (
    ChangeType,
    NodeType,
    RelationshipType,
    RiskLevel,
)

FIXTURES = Path(__file__).parent / "fixtures" / "change_intel"

requires_fixtures = pytest.mark.skipif(
    not (FIXTURES / "simple_import" / ".git").exists(),
    reason="git fixture repos have not been built (run tests/fixtures/change_intel/_build.py)",
)


def _analyze(name: str):
    return analyze_change_impact(
        repository_url=str(FIXTURES / name),
        base_revision="base",
        target_revision="target",
    )


def _edge_rel(analysis, rel: str) -> list:
    return [e for e in analysis.graph.edges if e.relationship.value == rel]


@requires_fixtures
class TestFixtureAnalysis:
    def test_simple_import(self):
        a = _analyze("simple_import")
        assert a.changeset.counts == {"modified": 1, "added": 1, "deleted": 0, "renamed": 0}
        mod_edge = next(e for e in a.graph.edges if e.source == "app.py")
        assert mod_edge.target == "mod.py"
        assert mod_edge.relationship == RelationshipType.IMPORT
        assert mod_edge.confidence.value == "high"
        assert mod_edge.evidence == "app.py:1 import mod"
        assert a.risk.level == RiskLevel.LOW

    def test_multi_level_transitive(self):
        a = _analyze("multi_level")
        assert a.changeset.counts["modified"] == 1
        assert a.traversal.direct_targets == ["b.py"]
        assert a.traversal.transitive_targets == ["a.py"]
        paths = {n.path for n in a.graph.nodes if n.node_type == NodeType.AFFECTED}
        assert {"a.py", "b.py"} <= paths

    def test_unrelated_file_no_dependents(self):
        a = _analyze("unrelated_file")
        assert a.changeset.counts == {"modified": 1, "added": 1, "deleted": 0, "renamed": 0}
        assert a.traversal.direct_targets == []
        assert a.traversal.transitive_targets == []
        assert a.risk.level == RiskLevel.LOW

    def test_deleted_symbol_is_high_risk(self):
        a = _analyze("deleted_symbol")
        deleted = {cs.symbol.fqn for cs in a.changed_symbols if cs.change_type == ChangeType.DELETED}
        assert "mod.helper" in deleted
        codes = {f.code for f in a.risk.factors}
        assert "deleted_artifacts_with_dependents" in codes
        assert a.risk.level == RiskLevel.HIGH

    def test_added_file_isolated(self):
        a = _analyze("added_file")
        assert a.changeset.counts["added"] == 1
        assert a.traversal.direct_targets == []
        assert a.risk.level == RiskLevel.LOW

    def test_rename_detected(self):
        a = _analyze("rename")
        renamed = [f for f in a.changeset.files if f.change_type == ChangeType.RENAMED]
        assert len(renamed) == 1
        assert renamed[0].old_path == "auth.py"
        assert renamed[0].path == "authentication.py"
        codes = {f.code for f in a.risk.factors}
        assert "renamed_artifacts" in codes
        assert a.risk.level == RiskLevel.MEDIUM

    def test_cycle_detected(self):
        a = _analyze("cycle")
        assert a.traversal.cycles_detected, "expected a detected import cycle"
        path_set = {pair[0] for pair in a.traversal.cycles_detected} | {
            pair[1] for pair in a.traversal.cycles_detected
        }
        assert {"a.py", "b.py"} <= path_set
        assert a.risk.level == RiskLevel.MEDIUM

    def test_dynamic_import_unresolved(self):
        a = _analyze("dynamic_import")
        targets = {u.target for u in a.unresolved}
        assert "plugin_catalog" in targets
        assert a.risk.level == RiskLevel.MEDIUM

    def test_api_consumer_edge(self):
        a = _analyze("api_consumer")
        api_edges = _edge_rel(a, RelationshipType.API_CONSUMER.value)
        assert api_edges, "expected an API_CONSUMER edge"
        assert api_edges[0].source == "clients/web_client.py"
        assert api_edges[0].target == "api/routes.py"
        assert "clients/web_client.py" in a.traversal.direct_targets
        assert a.risk.level == RiskLevel.MEDIUM

    def test_config_requires_verification(self):
        a = _analyze("verification_req")
        cfg_dep = _edge_rel(a, RelationshipType.CONFIGURATION_DEPENDENCY.value)
        assert cfg_dep, "expected configuration-dependency edge"
        assert cfg_dep[0].confidence.value == "medium"
        executable = [r for r in a.requirements if r.executable]
        assert executable, "expected an executable verification requirement"
        assert executable[0].check_category == "config"
        assert executable[0].status == "executable"

    def test_base_side_symbols_readable(self):
        # mod.py in deleted_symbol has base-side symbols parsed from git blobs.
        a = _analyze("deleted_symbol")
        target_fqns = {cs.symbol.fqn for cs in a.changed_symbols}
        assert "mod.helper" in target_fqns

    def test_error_non_git_repo(self):
        with pytest.raises(ChangeIntelError) as exc:
            analyze_change_impact(
                repository_url=str(FIXTURES.parent / "repos" / "compose_app"),
                base_revision="base",
                target_revision="target",
            )
        assert exc.value.code == "NOT_A_GIT_REPOSITORY"

    def test_error_missing_repo(self):
        with pytest.raises(ChangeIntelError) as exc:
            analyze_change_impact(
                repository_url=str(FIXTURES / "does_not_exist"),
                base_revision="base",
                target_revision="target",
            )
        assert exc.value.code == "REPO_NOT_FOUND"

    def test_error_identical_revisions(self):
        with pytest.raises(ChangeIntelError) as exc:
            analyze_change_impact(
                repository_url=str(FIXTURES / "simple_import"),
                base_revision="base",
                target_revision="base",
            )
        assert exc.value.code == "IDENTICAL_REVISIONS"

    def test_error_invalid_revision(self):
        with pytest.raises(ChangeIntelError) as exc:
            analyze_change_impact(
                repository_url=str(FIXTURES / "simple_import"),
                base_revision="definitely-not-a-rev",
                target_revision="target",
            )
        assert exc.value.code in {"REVISION_INVALID", "REVISION_NOT_FOUND"}


@requires_fixtures
class TestChangeIntelApi:
    def test_demo_fixture_labelled(self, client: TestClient):
        r = client.get("/api/change-impact/demo/fixture")
        assert r.status_code == 200
        body = r.json()
        assert body["is_demo"] is True
        assert body["label"] == "DEMO/MOCK"
        assert body["analysis"]["is_demo"] is True
        assert body["analysis"]["risk"]["level"] == "medium"
        assert body["analysis"]["graph"]["nodes"]

    def test_analyze_live(self, client: TestClient):
        r = client.post(
            "/api/change-impact/analyze",
            json={
                "repository_url": str(FIXTURES / "multi_level"),
                "base_revision": "base",
                "target_revision": "target",
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["is_demo"] is False
        assert body["label"] is None
        assert "a.py" in body["analysis"]["traversal"]["transitive_targets"]
        assert body["analysis"]["graph"]["edges"]

    def test_analyze_linked_to_deployment_persists(self, client: TestClient):
        deploy = client.post(
            "/api/deploy",
            json={
                "repository_url": "https://github.com/example/app",
                "mode": "demo",
                "scenario": "SUCCESSFUL_DEPLOYMENT",
                "target": {"host": "localhost", "port": 8080},
            },
        )
        assert deploy.status_code == 202, deploy.text
        dep_id = deploy.json()["deployment_id"]

        r = client.post(
            "/api/change-impact/analyze",
            json={
                "repository_url": str(FIXTURES / "verification_req"),
                "base_revision": "base",
                "target_revision": "target",
                "deployment_id": dep_id,
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["deployment_id"] == dep_id

        got = client.get(f"/api/deploy/{dep_id}/change-impact")
        assert got.status_code == 200, got.text
        payload = got.json()
        assert payload["is_demo"] is False
        assert payload["label"] is None
        assert payload["analysis"]["risk"]["level"] in {"low", "medium", "high"}

    def test_get_change_impact_missing(self, client: TestClient):
        r = client.get("/api/deploy/nope/change-impact")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "NOT_FOUND"

    def test_analyze_remote_rejected(self, client: TestClient):
        r = client.post(
            "/api/change-impact/analyze",
            json={
                "repository_url": "https://github.com/example/app.git",
                "base_revision": "a",
                "target_revision": "b",
            },
        )
        assert r.status_code == 400
        assert r.json()["error"]["code"] == "NOT_LOCAL_REPOSITORY"

    def test_analyze_validation_error(self, client: TestClient):
        r = client.post("/api/change-impact/analyze", json={"repository_url": "x"})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "VALIDATION_ERROR"


@requires_fixtures
class TestFullChainIntegration:
    """git → diff → symbols → dependency edges → CIG → risk → requirements →
    persisted → API, end to end on a real local git fixture."""

    def test_full_chain(self, client: TestClient):
        repo = str(FIXTURES / "delete_import_chain")

        r = client.post(
            "/api/change-impact/analyze",
            json={
                "repository_url": repo,
                "base_revision": "base",
                "target_revision": "target",
                "deployment_id": None,
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        analysis = body["analysis"]

        # diff: a single deleted module with a live (now broken) importer
        assert analysis["changeset"]["counts"] == {
            "modified": 0,
            "added": 0,
            "deleted": 1,
            "renamed": 0,
        }
        assert analysis["changeset"]["base_sha"] != analysis["changeset"]["target_sha"]

        # unresolved deleted-import surfaced, not fabricated
        targets = [u["target"] for u in analysis["unresolved"]]
        assert "helpers.residual" in targets
        kinds = {u["kind"] for u in analysis["unresolved"]}
        assert "deleted-import" in kinds

        # risk is high for a deleted module still referenced by a live file
        assert analysis["risk"]["level"] == "high"

        # verification requirement recorded honestly as non-executable
        non_exec = [r for r in analysis["requirements"] if not r["executable"]]
        assert non_exec
        assert all(r["status"] != "executable" for r in non_exec)