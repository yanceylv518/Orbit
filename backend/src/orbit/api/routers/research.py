from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from orbit.api.dependencies import app_state, require_admin


router = APIRouter(prefix="/api/research", tags=["research"])


class CandidateCreateRequest(BaseModel):
    id: str = Field(min_length=1, max_length=32)
    name: str = Field(default="", max_length=120)
    protocol: str = Field(min_length=1, max_length=16)
    dataset_ids: list[str] = Field(min_length=1)


class RunCreateRequest(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=32)
    open_lockbox: bool = False


class DatasetFetchRequest(BaseModel):
    symbol: str = Field(min_length=3, max_length=20)
    kind: Literal["ohlc", "funding"]
    interval: str = Field(default="15m", max_length=4)
    days: int = Field(default=180, ge=1, le=2000)


def workflow_error(exc: Exception) -> HTTPException:
    status = 409 if isinstance(exc, RuntimeError) else 400
    return HTTPException(status_code=status, detail=str(exc))


@router.get("/datasets")
def datasets(request: Request, _user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = app_state(request).research_catalog.datasets()
    return {"items": items, "count": len(items)}


@router.post("/datasets/fetch", status_code=202)
def fetch_dataset(
    payload: DatasetFetchRequest,
    request: Request,
    _user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return app_state(request).research_workflow.create_dataset_fetch(payload.model_dump())
    except (ValueError, RuntimeError) as exc:
        raise workflow_error(exc) from exc


@router.get("/candidates")
def candidates(request: Request, _user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = app_state(request).research_catalog.candidates()
    return {"items": items, "count": len(items)}


@router.get("/templates")
def templates(request: Request, _user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = app_state(request).research_workflow.templates()
    return {"items": items, "count": len(items)}


@router.post("/candidates", status_code=201)
def create_candidate(
    payload: CandidateCreateRequest,
    request: Request,
    _user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return app_state(request).research_workflow.create_candidate(payload.model_dump())
    except (ValueError, RuntimeError) as exc:
        raise workflow_error(exc) from exc


@router.get("/runs")
def runs(request: Request, _user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    items = app_state(request).research_workflow.runs()
    return {"items": items, "count": len(items)}


@router.post("/runs", status_code=202)
def create_run(
    payload: RunCreateRequest,
    request: Request,
    _user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    try:
        return app_state(request).research_workflow.create_run(
            payload.candidate_id,
            open_lockbox=payload.open_lockbox,
        )
    except (ValueError, RuntimeError) as exc:
        raise workflow_error(exc) from exc


@router.get("/runs/{run_id}")
def run(run_id: str, request: Request, _user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    item = app_state(request).research_workflow.run(run_id)
    if not item:
        raise HTTPException(status_code=404, detail="research run not found")
    return item


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
