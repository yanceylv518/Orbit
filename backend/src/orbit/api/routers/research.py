from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from orbit.api.dependencies import app_state, require_admin


router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("/datasets")
def datasets(request: Request, _user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = app_state(request).research_catalog.datasets()
    return {"items": items, "count": len(items)}


@router.get("/candidates")
def candidates(request: Request, _user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = app_state(request).research_catalog.candidates()
    return {"items": items, "count": len(items)}


@router.get("/candidates/{candidate_id}")
def candidate(
    candidate_id: str,
    request: Request,
    _user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    item = app_state(request).research_catalog.candidate(candidate_id)
    if not item:
        raise HTTPException(status_code=404, detail="research candidate not found")
    return item


@router.get("/results/{result_id}")
def result(
    result_id: str,
    request: Request,
    _user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    item = app_state(request).research_catalog.result(result_id)
    if not item:
        raise HTTPException(status_code=404, detail="research result not found")
    return item
