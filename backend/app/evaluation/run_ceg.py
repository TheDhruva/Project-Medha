"""CEG / scoped-rollback evaluation runner."""

from __future__ import annotations

import json
import sys
from typing import Any

from app.ceg.rollback import compute_rollback_scope
from app.evaluation.baseline import compare_rollback
from app.evaluation.datasets.ceg_cases import load_ceg_cases
from app.evaluation.metrics import summarize_ceg
from app.evaluation.storage import save_run
from app.models.execution import NodeStatus


def run_ceg_evaluation() -> dict[str, Any]:
    cases_out: list[dict[str, Any]] = []
    for case in load_ceg_cases():
        graph = case["graph"]
        fail = case["fail_node"]
        # Mark fail node failed, others success (pre-rollback snapshot)
        working = graph.model_copy(deep=True)
        for n in working.nodes:
            n.status = (
                NodeStatus.FAILED.value if n.node_id == fail else NodeStatus.SUCCESS.value
            )
        scope = compute_rollback_scope(working, fail, is_demo=False)
        comparison = compare_rollback(graph, fail)

        exp_rb = set(case.get("expected_rollback") or [])
        exp_pr = set(case.get("expected_preserved") or [])
        exp_not = set(case.get("expected_not_rollback") or [])
        actual_rb = set(scope.nodes_to_rollback)
        actual_pr = set(scope.nodes_preserved)
        passed = (
            actual_rb == exp_rb
            and exp_pr.issubset(actual_pr)
            and actual_rb.isdisjoint(exp_not)
        )
        cases_out.append(
            {
                "case_id": case["case_id"],
                "passed": passed,
                "failed_node": fail,
                "rollback_nodes": scope.nodes_to_rollback,
                "preserved_nodes": scope.nodes_preserved,
                "affected_nodes": scope.affected_nodes,
                "expected_rollback": sorted(exp_rb),
                "expected_preserved": sorted(exp_pr),
                "medha_rollback_count": comparison["medha"]["rollback_count"],
                "global_rollback_count": comparison["baseline"]["rollback_count"],
                "preserved_count": comparison["medha"]["preserved_count"],
                "services_saved_vs_global": comparison["services_saved_vs_global"],
                "scope_efficiency": comparison["scope_efficiency"],
                "comparison": comparison,
            }
        )
    summary = summarize_ceg(cases_out)
    report = {
        **summary,
        "cases": cases_out,
        "fabricated": False,
        "source": "app.evaluation.run_ceg",
        "baseline": "GLOBAL_ROLLBACK",
    }
    path = save_run("ceg", report)
    report["artifact_path"] = str(path)
    return report


def main() -> int:
    report = run_ceg_evaluation()
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
