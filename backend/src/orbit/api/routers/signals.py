from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from typing import Any, Literal

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


class PushoverConfigurationRequest(BaseModel):
    api_token: str = Field(min_length=1, max_length=128)
    user_key: str = Field(min_length=1, max_length=128)
    enabled: bool = True


class SignalServiceControlRequest(BaseModel):
    enabled: bool


class SignalFamilyControlRequest(BaseModel):
    family_id: Literal["BREAKOUT_MOMENTUM", "OVERSOLD_REBOUND", "SUSTAINED_STRENGTH"]
    enabled: bool
    reason: str | None = Field(default=None, max_length=200)


class SignalConfigurationRequest(BaseModel):
    values: dict[str, Any]
    note: str | None = Field(default=None, max_length=200)


class SignalAccountBindingRequest(BaseModel):
    account_id: str | None = Field(default=None, max_length=64)


class DisciplineChangeRequest(BaseModel):
    setting: Literal["daily_loss_limit_r", "consecutive_loss_limit"]
    value: float


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


@router.post("/pushover")
def configure_pushover(request: Request, payload: PushoverConfigurationRequest, user: dict = Depends(require_admin)) -> dict:
    try:
        return app_state(request).signal_desk.configure_pushover(**payload.model_dump(), actor=str(user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/pushover/test")
def test_pushover(request: Request, user: dict = Depends(require_admin)) -> dict:
    try:
        return app_state(request).signal_desk.test_pushover(actor=str(user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/service")
def control_signal_service(request: Request, payload: SignalServiceControlRequest, user: dict = Depends(require_admin)) -> dict:
    return app_state(request).signal_desk.set_service_enabled(enabled=payload.enabled, actor=str(user["id"]))


@router.post("/families/control")
def control_signal_family(request: Request, payload: SignalFamilyControlRequest, user: dict = Depends(require_admin)) -> dict:
    try:
        return app_state(request).signal_desk.set_family_enabled(**payload.model_dump(), actor=str(user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/configuration")
def update_signal_configuration(request: Request, payload: SignalConfigurationRequest, user: dict = Depends(require_admin)) -> dict:
    try:
        return app_state(request).signal_desk.update_configuration(**payload.model_dump(), actor=str(user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/binding")
def bind_signal_account(request: Request, payload: SignalAccountBindingRequest, user: dict = Depends(require_admin)) -> dict:
    try:
        return app_state(request).signal_desk.bind_account(account_id=payload.account_id, actor=str(user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/discipline/changes")
def request_discipline_change(request: Request, payload: DisciplineChangeRequest, user: dict = Depends(require_admin)) -> dict:
    try:
        return app_state(request).signal_desk.request_discipline_change(**payload.model_dump(), actor=str(user["id"]))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
