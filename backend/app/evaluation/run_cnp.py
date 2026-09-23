"""CNP evaluation runner — results come from actual CNP execution only."""

from __future__ import annotations

import json
import sys
from collections import Counter
from typing import Any

from app.cnp.engine import detect_conflicts, run_cnp
from app.evaluation.datasets.cnp_cases import constraints_from_case, load_cnp_cases
from app.evaluation.metrics import summarize_cnp
from app.evaluation.storage import save_run


def run_cnp_evaluation() -> dict[str, Any]:
    cases_out: list[dict[str, Any]] = []
    for case in load_cnp_cases():
        constraints = constraints_from_case(case)
        detected = detect_conflicts(constraints)
        result = run_cnp(f"eval_{case['case_id']}", constraints, max_rounds=3, is_demo=False)
        methods = Counter(d.method for d in result.decisions)
        expected_conflict = bool(case.get("expected_conflict"))
        had_conflict = len(detected) > 0 or len(result.conflicts) > 0
        status_ok = result.status == case.get("expected_status", "resolved")
        conflict_ok = had_conflict == expected_conflict
        methods_ok = True
        if case.get("expected_methods_any"):
            methods_ok = any(m in methods for m in case["expected_methods_any"])
        passed = status_ok and conflict_ok and methods_ok
        cases_out.append(
            {
                "case_id": case["case_id"],
                "description": case.get("description"),
                "passed": passed,
                "conflicts_detected": len(result.conflicts) or len(detected),
                "conflicts_resolved": len(result.decisions),
                "rounds_used": result.rounds_used,
                "status": result.status,
                "resolution_methods": dict(methods),
                "expected_conflict": expected_conflict,
                "expected_status": case.get("expected_status"),
            }
        )
    summary = summarize_cnp(cases_out)
    report = {
        **summary,
        "cases": cases_out,
        "fabricated": False,
        "source": "app.evaluation.run_cnp",
    }
    path = save_run("cnp", report)
    report["artifact_path"] = str(path)
    return report


def main() -> int:
    report = run_cnp_evaluation()
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    print(f"cases_detail={len(report['cases'])} artifact={report.get('artifact_path')}")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
