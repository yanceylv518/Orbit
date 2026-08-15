from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from orbit.api.dependencies import app_state, require_admin

router = APIRouter(prefix="/api/messages", tags=["messages"])

@router.get("")
def list_messages(request: Request, kind: str = "", level: str = "", limit: int = Query(100, ge=1, le=500), _user: dict[str, Any] = Depends(require_admin)):
    return app_state(request).message_center.list(kind=kind, level=level, limit=limit)

@router.post("/{message_id}/read")
def read_message(message_id: str, request: Request, _user: dict[str, Any] = Depends(require_admin)):
    try:
        app_state(request).message_center.mark_read(message_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="message not found") from exc
    return app_state(request).message_center.list(limit=20)

@router.post("/read-all")
def read_all(request: Request, _user: dict[str, Any] = Depends(require_admin)):
    app_state(request).message_center.mark_all_read()
    return app_state(request).message_center.list(limit=20)
