"""Evaluation API — returns measured artifacts only (never fabricated)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.core.api_token import require_mutation_token
from app.core.clerk_auth import RequireSubject
from app.evaluation.run_ceg import run_ceg_evaluation
from app.evaluation.run_cnp import run_cnp_evaluation
from app.evaluation.storage import list_runs, load_latest

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])


def _load_summary() -> tuple:
    """Blocking file reads (sync JSON) — always called via to_thread."""
    return load_latest("cnp"), load_latest("ceg"), load_latest("combined"), list_runs(10)


@router.get("")
async def evaluation_summary(subject: str = RequireSubject):
    import asyncio

    cnp, ceg, combined, runs = await asyncio.to_thread(_load_summary)
    return JSONResponse(
        {
            "cnp": cnp,
            "ceg": ceg,
            "combined": combined,
            "runs": runs,
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


@router.post("/run/cnp", dependencies=[Depends(require_mutation_token)])
async def run_cnp(request: Request, subject: str = RequireSubject):
    import asyncio

    from app.core.config import get_settings
    from app.core.rate_limit import check_rate_limit, client_ip

    ip = client_ip(request, trusted_proxy=get_settings().trusted_proxy)
    if not check_rate_limit(
        f"eval:{ip}", limit_per_minute=max(5, get_settings().rate_limit_per_minute // 4)
    ):
        return JSONResponse(
            {"error": {"code": "RATE_LIMITED", "message": "Too many evaluation runs.",
                       "details": {}}},
            status_code=429,
        )
    # CPU/file-bound eval runs off the event loop; request stays open but
    # no longer head-of-line blocks health/SSE. Bounded with a 300s timeout
    # so a stuck run returns 503 instead of hanging the client forever.
    try:
        async with asyncio.timeout(300):
            report = await asyncio.to_thread(run_cnp_evaluation)
    except TimeoutError:
        return JSONResponse(
            {"error": {"code": "EVAL_TIMEOUT", "message": "Evaluation run timed out.",
                       "details": {}}},
            status_code=503,
        )
    return JSONResponse(report)


@router.post("/run/ceg", dependencies=[Depends(require_mutation_token)])
async def run_ceg(request: Request, subject: str = RequireSubject):
    import asyncio

    from app.core.config import get_settings
    from app.core.rate_limit import check_rate_limit, client_ip

    ip = client_ip(request, trusted_proxy=get_settings().trusted_proxy)
    if not check_rate_limit(
        f"eval:{ip}", limit_per_minute=max(5, get_settings().rate_limit_per_minute // 4)
    ):
        return JSONResponse(
            {"error": {"code": "RATE_LIMITED", "message": "Too many evaluation runs.",
                       "details": {}}},
            status_code=429,
        )
    try:
        async with asyncio.timeout(300):
            report = await asyncio.to_thread(run_ceg_evaluation)
    except TimeoutError:
        return JSONResponse(
            {"error": {"code": "EVAL_TIMEOUT", "message": "Evaluation run timed out.",
                       "details": {}}},
            status_code=503,
        )
    return JSONResponse(report)


@router.get("/latest/{kind}")
async def latest(kind: str, subject: str = RequireSubject):
    import asyncio

    data = await asyncio.to_thread(load_latest, kind)
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
