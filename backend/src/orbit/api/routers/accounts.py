from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from orbit.api.dependencies import app_state, require_account_access, require_admin, require_user


router = APIRouter(prefix="/api", tags=["accounts"])


@router.post("/users/upsert")
def upsert_user(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_admin)):
    app = app_state(request)
    result = app.upsert_business_user(payload, actor=user["id"])
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    snapshot = app.snapshot(user)
    snapshot["user_update_result"] = result
    return snapshot


@router.post("/accounts/upsert")
def upsert_account(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_admin)):
    app = app_state(request)
    result = app.upsert_exchange_account(payload, actor=user["id"])
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    snapshot = app.snapshot(user)
    snapshot["account_update_result"] = result
    return snapshot


@router.post("/account-run-config")
def update_run_config(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user)):
    app = app_state(request)
    account_id = str(payload.get("account_id", ""))
    require_account_access(request, user, account_id)
    result = app.update_account_run_config(
        account_id=account_id,
        incoming=payload.get("run_config", {}),
        actor=user["id"],
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    snapshot = app.snapshot(user)
    snapshot["account_run_config_result"] = result
    return snapshot
