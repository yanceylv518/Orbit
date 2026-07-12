from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

from orbit.application.app_state import AppState


def app_state(request: Request) -> AppState:
    return request.app.state.orbit


def session_cookie_name(app: AppState) -> str:
    return app.config.get("auth", {}).get("session_cookie_name", "orbit_session")


def session_token(request: Request, app: AppState) -> str | None:
    return request.cookies.get(session_cookie_name(app))


def optional_user(request: Request) -> dict[str, Any] | None:
    app = app_state(request)
    return app.current_user(session_token(request, app))


def require_user(request: Request) -> dict[str, Any]:
    user = optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录。")
    return user


def require_admin(request: Request) -> dict[str, Any]:
    user = require_user(request)
    if not app_state(request).is_admin_user_id(str(user["id"])):
        raise HTTPException(status_code=403, detail="当前用户没有权限执行此操作。")
    return user


def require_account_access(request: Request, user: dict[str, Any], account_id: str) -> None:
    if not app_state(request).user_can_access_account(user, account_id):
        raise HTTPException(status_code=403, detail="当前用户没有权限访问此账户。")


def require_account_operation(request: Request, user: dict[str, Any], account_id: str) -> None:
    if not app_state(request).user_can_operate_account(user, account_id):
        raise HTTPException(status_code=403, detail="Binance 同步只能由账户所属用户或管理员执行。")
