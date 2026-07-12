from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from orbit.api.dependencies import app_state, require_account_access, require_user


router = APIRouter(prefix="/api/execution-plans", tags=["execution-plans"])


def result_status(result: dict[str, Any]) -> int:
    return 403 if result.get("status") == "forbidden" else 400


@router.post("/generate")
def generate(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user)):
    app = app_state(request)
    account_id = str(payload.get("account_id", "")).strip()
    if account_id:
        require_account_access(request, user, account_id)
    elif not app.is_admin_user_id(str(user["id"])):
        raise HTTPException(status_code=403, detail="当前用户没有权限执行此操作。")
    result = app.generate_execution_plans(account_id or None, actor=user["id"])
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    snapshot = app.snapshot(user)
    snapshot["execution_plan_result"] = result
    return snapshot


@router.post("/confirm")
def confirm(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user)):
    app = app_state(request)
    result = app.confirm_execution_plan(
        plan_id=str(payload.get("plan_id", "")),
        actor=user["id"],
        note=payload.get("note"),
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=result_status(result))
    snapshot = app.snapshot(user)
    snapshot["execution_plan_confirm_result"] = result
    return snapshot


@router.post("/export")
def export(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user)):
    app = app_state(request)
    result = app.record_execution_plan_export(
        plan_ids=payload.get("plan_ids", []),
        actor=user["id"],
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=result_status(result))
    snapshot = app.snapshot(user)
    snapshot["execution_plan_export_result"] = result
    return snapshot


@router.post("/execute")
def execute_live(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user)):
    """live 下单：全部闸门由 OrderExecutionService 逐一校验，默认全局关闭。"""
    app = app_state(request)
    result = app.execute_live_plan(
        plan_id=str(payload.get("plan_id", "")),
        actor=user["id"],
        confirm_phrase=str(payload.get("confirm_phrase", "")),
    )
    if not result.get("ok"):
        status = 403 if result.get("status") in ("forbidden", "disabled") else 400
        return JSONResponse(result, status_code=status)
    snapshot = app.snapshot(user)
    snapshot["execution_result"] = result
    return snapshot
