from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from orbit.api.dependencies import app_state, require_admin
from orbit.application.data_summary import DataSummaryError


router = APIRouter(prefix="/api/data", tags=["data"])


@router.get("/summary")
def summary(request: Request, _user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    try:
        result = app_state(request).data_summary.summary()
    except DataSummaryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="research dataset summary is not available")
    return result


@router.get("/quality")
def quality(
    request: Request,
    kind: Literal["halts", "missing", "duplicates"] = Query(default="halts"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    try:
        result = app_state(request).data_summary.quality_page(
            kind,
            page=page,
            page_size=page_size,
        )
    except DataSummaryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="research dataset quality is not available")
    return result
