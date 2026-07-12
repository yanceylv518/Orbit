from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from orbit.api.dependencies import app_state, optional_user, session_cookie_name, session_token


router = APIRouter(prefix="/api", tags=["auth"])


@router.get("/state")
def state(request: Request) -> dict[str, Any]:
    app = app_state(request)
    user = optional_user(request)
    return app.snapshot(user) if user else app.public_snapshot()


@router.post("/login")
def login(request: Request, payload: dict[str, Any]) -> Response:
    app = app_state(request)
    result = app.authenticate(str(payload.get("login", "")), str(payload.get("password", "")))
    if not result.get("ok"):
        return JSONResponse(
            {"ok": False, "error": result.get("error", "登录失败。")},
            status_code=401,
        )
    token = result.pop("session_token")
    response = JSONResponse({"ok": True, "user": result["user"]})
    response.set_cookie(
        session_cookie_name(app),
        token,
        httponly=True,
        samesite="strict",
        path="/",
    )
    return response


@router.post("/logout")
def logout(request: Request) -> Response:
    app = app_state(request)
    app.logout(session_token(request, app))
    response = JSONResponse({"ok": True})
    response.delete_cookie(session_cookie_name(app), path="/", httponly=True, samesite="strict")
    return response
