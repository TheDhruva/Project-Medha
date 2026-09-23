"""Run all offline evaluation suites and print a combined report."""

from __future__ import annotations

import json
import sys

from app.evaluation.run_ceg import run_ceg_evaluation
from app.evaluation.run_cnp import run_cnp_evaluation
from app.evaluation.storage import save_run


def main() -> int:
    cnp = run_cnp_evaluation()
    ceg = run_ceg_evaluation()
    combined = {
        "cnp": {k: v for k, v in cnp.items() if k != "cases"},
        "ceg": {k: v for k, v in ceg.items() if k != "cases"},
        "fabricated": False,
        "note": "Numbers generated from actual runner execution.",
    }
    path = save_run("combined", combined)
    combined["artifact_path"] = str(path)
    print(json.dumps(combined, indent=2))
    failed = int(cnp.get("failed", 0)) + int(ceg.get("failed", 0))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
