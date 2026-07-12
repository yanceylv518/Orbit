from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from orbit.api.dependencies import app_state, require_account_access, require_account_operation, require_user


router = APIRouter(prefix="/api/binance", tags=["binance"])


@router.post("/sync")
def sync_account(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    app = app_state(request)
    account_id = str(payload.get("account_id", ""))
    require_account_operation(request, user, account_id)
    result = app.sync_binance_account(account_id, actor=user["id"])
    snapshot = app.snapshot(user)
    snapshot["binance_sync_result"] = result
    return snapshot


@router.post("/credentials")
def credentials(request: Request, payload: dict[str, Any], user: dict[str, Any] = Depends(require_user)):
    app = app_state(request)
    account_id = str(payload.get("account_id", ""))
    if not app.account_by_id(account_id):
        raise HTTPException(status_code=403, detail="API Key/Secret 只能由账户所属用户或管理员维护。")
    require_account_access(request, user, account_id)
    result = app.update_binance_credentials(
        account_id=account_id,
        actor=user["id"],
        api_key=str(payload.get("api_key", "")),
        api_secret=str(payload.get("api_secret", "")),
    )
    if not result.get("ok"):
        return JSONResponse(result, status_code=400)
    snapshot = app.snapshot(user)
    snapshot["credential_update_result"] = result
    return snapshot
