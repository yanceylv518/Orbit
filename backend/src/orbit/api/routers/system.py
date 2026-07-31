from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from orbit.api.dependencies import app_state, require_admin


router = APIRouter(prefix="/api", tags=["system"])


class LivePilotConfigureRequest(BaseModel):
    account_id: str = Field(min_length=1, max_length=128)

    class Config:
        extra = "forbid"


class LivePilotPrepareAccountRequest(LivePilotConfigureRequest):
    confirmation: str = Field(min_length=1, max_length=64)


class LivePilotActivateRequest(BaseModel):
    execution_epoch: str = Field(min_length=6, max_length=64)
    confirmation: str = Field(min_length=1, max_length=64)

    class Config:
        extra = "forbid"


def _live_action_response(app: Any, user: dict[str, Any], result: dict[str, Any], key: str):
    if not result.get("ok", result.get("passed", False)):
        return JSONResponse(
            {"ok": False, "error": result.get("error") or "操作未通过。", key: result},
            status_code=400,
        )
    snapshot = app.snapshot(user)
    snapshot[key] = result
    return snapshot


@router.get("/health")
def health(request: Request):
    result = app_state(request).health()
    if not result["ok"]:
        return JSONResponse(result, status_code=503)
    return result


@router.get("/live-execution/reports")
def live_execution_reports(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    _user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    items = app_state(request).live_execution_service.reports(limit)
    return {"items": items, "count": len(items), "limit": limit}


@router.post("/admin/live-pilot/configure")
def configure_live_pilot(
    request: Request,
    payload: LivePilotConfigureRequest,
    user: dict[str, Any] = Depends(require_admin),
):
    app = app_state(request)
    result = app.configure_live_pilot(
        actor=user["id"],
        account_id=payload.account_id,
    )
    return _live_action_response(app, user, result, "live_pilot_configure_result")


@router.post("/admin/live-pilot/prepare-account")
def prepare_live_pilot_account(
    request: Request,
    payload: LivePilotPrepareAccountRequest,
    user: dict[str, Any] = Depends(require_admin),
):
    app = app_state(request)
    result = app.prepare_live_pilot_account(
        actor=user["id"],
        account_id=payload.account_id,
        confirmation=payload.confirmation,
    )
    return _live_action_response(app, user, result, "live_pilot_account_result")


@router.post("/admin/live-pilot/initialize-forward")
def initialize_live_pilot_forward(
    request: Request,
    user: dict[str, Any] = Depends(require_admin),
):
    app = app_state(request)
    try:
        result = app.initialize_trend_forward(actor=user["id"])
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    return _live_action_response(app, user, result, "live_pilot_initialize_result")


@router.post("/admin/live-pilot/refresh-rules")
def refresh_live_pilot_rules(
    request: Request,
    user: dict[str, Any] = Depends(require_admin),
):
    app = app_state(request)
    try:
        result = app.refresh_live_exchange_rules(actor=user["id"])
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    return _live_action_response(app, user, result, "live_pilot_rules_result")


@router.post("/admin/live-pilot/preflight")
def run_live_pilot_preflight(
    request: Request,
    user: dict[str, Any] = Depends(require_admin),
):
    app = app_state(request)
    try:
        result = app.run_live_pilot_preflight(actor=user["id"])
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    return _live_action_response(app, user, result, "live_pilot_preflight_result")


@router.post("/admin/live-pilot/activate")
def activate_live_pilot(
    request: Request,
    payload: LivePilotActivateRequest,
    user: dict[str, Any] = Depends(require_admin),
):
    app = app_state(request)
    try:
        result = app.activate_live_pilot(
            actor=user["id"],
            execution_epoch=payload.execution_epoch,
            confirmation=payload.confirmation,
        )
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    return _live_action_response(app, user, result, "live_pilot_activation_result")


@router.post("/tick")
def tick(request: Request, user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    app = app_state(request)
    app.tick_once()
    return app.snapshot(user)


@router.post("/reset")
def reset(request: Request, user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    app = app_state(request)
    app.reset()
    return app.snapshot(user)


@router.post("/toggle")
def toggle(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    app = app_state(request)
    app.set_running(bool(payload.get("running", False)), actor=user["id"])
    return app.snapshot(user)


@router.post("/config/events")
def update_events(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    app = app_state(request)
    app.update_event_config(payload.get("event_config", {}), actor=user["id"])
    return app.snapshot(user)


@router.post("/report/daily")
def daily_report(request: Request, user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    app = app_state(request)
    generated = app.generate_daily_report(actor=user["id"])
    snapshot = app.snapshot(user)
    snapshot["generated_report"] = generated.get("generated_report")
    return snapshot


@router.post("/admin/emergency-stop")
def emergency_stop(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    app = app_state(request)
    app.admin_emergency_stop(actor=user["id"], reason=payload.get("reason"))
    return app.snapshot(user)


@router.post("/admin/live-execution/emergency-stop")
def live_execution_emergency_stop(
    request: Request,
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    app = app_state(request)
    result = app.emergency_stop_live_execution(
        actor=user["id"],
        reason=str(payload.get("reason") or ""),
    )
    if not result.get("ok"):
        return result
    snapshot = app.snapshot(user)
    snapshot["live_execution_stop_result"] = result
    return snapshot


@router.post("/admin/resume")
def resume(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    app = app_state(request)
    app.admin_resume(actor=user["id"], reason=payload.get("reason"))
    return app.snapshot(user)


@router.post("/admin/stopped-symbols/resume")
def resume_stopped_symbol(
    request: Request,
    payload: dict[str, Any],
    user: dict[str, Any] = Depends(require_admin),
) -> dict[str, Any]:
    app = app_state(request)
    result = app.resume_stopped_symbol(
        str(payload.get("account_id") or ""),
        str(payload.get("symbol") or ""),
        actor=user["id"],
        reason=str(payload.get("reason") or ""),
    )
    if not result.get("ok"):
        return result
    snapshot = app.snapshot(user)
    snapshot["recovered_symbol"] = result["recovered_symbol"]
    return snapshot
