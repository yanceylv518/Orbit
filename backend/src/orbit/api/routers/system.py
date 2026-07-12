from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from orbit.api.dependencies import app_state, require_admin


router = APIRouter(prefix="/api", tags=["system"])


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


@router.post("/admin/resume")
def resume(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_admin)) -> dict[str, Any]:
    app = app_state(request)
    app.admin_resume(actor=user["id"], reason=payload.get("reason"))
    return app.snapshot(user)
