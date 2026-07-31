from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from orbit.api.dependencies import app_state, require_admin


router = APIRouter(prefix="/api", tags=["system"])


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
