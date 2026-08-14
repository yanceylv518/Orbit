from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from typing import Literal

from orbit.api.dependencies import app_state, require_admin


router = APIRouter(prefix="/api/signals", tags=["signals"])


class SignalDecisionRequest(BaseModel):
    signal_id: str = Field(min_length=1, max_length=64)
    decision: str
    reason: str | None = Field(default=None, max_length=120)
    entry_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, gt=0)


class ManualExecutionRequest(BaseModel):
    signal_id: str = Field(min_length=1, max_length=64)
    entry_price: float = Field(gt=0)
    exit_price: float = Field(gt=0)
    exited_at_ms: int = Field(gt=0)
    exit_reason: Literal["MANUAL", "STOP", "TIME_EXIT"]


@router.get("")
def signal_desk(
    request: Request,
    day: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    limit: int = Query(default=200, ge=1, le=1000),
    _user: dict = Depends(require_admin),
) -> dict:
    return app_state(request).signal_desk.snapshot(day=day, limit=limit)


@router.post("/decisions")
def record_signal_decision(
    request: Request, payload: SignalDecisionRequest, user: dict = Depends(require_admin)
) -> dict:
    try:
        return app_state(request).signal_desk.record_decision(
            **payload.model_dump(), actor=str(user["id"])
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/executions")
def record_manual_execution(
    request: Request, payload: ManualExecutionRequest, user: dict = Depends(require_admin)
) -> dict:
    try:
        return app_state(request).signal_desk.record_execution(
            **payload.model_dump(), actor=str(user["id"])
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
