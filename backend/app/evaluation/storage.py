"""Persist evaluation run artifacts as JSON under data/evaluation/."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.core.config import PROJECT_ROOT

EVAL_DIR = PROJECT_ROOT / "data" / "evaluation"


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def save_run(kind: str, report: dict[str, Any]) -> Path:
    EVAL_DIR.mkdir(parents=True, exist_ok=True)
    run_id = report.get("run_id") or f"eval_{uuid4().hex[:12]}"
    report = {**report, "run_id": run_id, "kind": kind, "saved_at": _now()}
    path = EVAL_DIR / f"{kind}_{run_id}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    latest = EVAL_DIR / f"{kind}_latest.json"
    latest.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path


def load_latest(kind: str) -> dict[str, Any] | None:
    path = EVAL_DIR / f"{kind}_latest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    if not EVAL_DIR.exists():
        return []
    files = sorted(EVAL_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    out: list[dict[str, Any]] = []
    for path in files:
        if path.name.endswith("_latest.json"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            out.append(
                {
                    "path": str(path),
                    "run_id": data.get("run_id"),
                    "kind": data.get("kind"),
                    "saved_at": data.get("saved_at"),
                    "summary": {
                        k: data.get(k)
                        for k in (
                            "total_cases",
                            "passed",
                            "failed",
                            "conflicts_detected",
                            "conflicts_resolved",
                            "average_rounds",
                        )
                        if k in data
                    },
                }
            )
        except (OSError, json.JSONDecodeError):
            continue
        if len(out) >= limit:
            break
    return out
