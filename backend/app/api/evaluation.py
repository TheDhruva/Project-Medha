"""Evaluation API — returns measured artifacts only (never fabricated)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.evaluation.run_ceg import run_ceg_evaluation
from app.evaluation.run_cnp import run_cnp_evaluation
from app.evaluation.storage import list_runs, load_latest

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


@router.get("")
async def evaluation_summary():
    return JSONResponse(
        {
            "cnp": load_latest("cnp"),
            "ceg": load_latest("ceg"),
            "combined": load_latest("combined"),
            "runs": list_runs(10),
            "note": (
                "Results appear after running evaluation runners. "
                "Null fields mean experiments have not been executed yet — not fabricated zeros."
            ),
            "commands": {
                "cnp": "python -m app.evaluation.run_cnp",
                "ceg": "python -m app.evaluation.run_ceg",
                "all": "python -m app.evaluation.run_all",
            },
        }
    )


@router.post("/run/cnp")
async def run_cnp():
    report = run_cnp_evaluation()
    return JSONResponse(report)


@router.post("/run/ceg")
async def run_ceg():
    report = run_ceg_evaluation()
    return JSONResponse(report)


@router.get("/latest/{kind}")
async def latest(kind: str):
    data = load_latest(kind)
    if data is None:
        return JSONResponse(
            {
                "error": {
                    "code": "NOT_FOUND",
                    "message": f"No evaluation artifact for kind={kind}",
                    "details": {},
                }
            },
            status_code=404,
        )
    return JSONResponse(data)
