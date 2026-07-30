from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from orbit.api.dependencies import app_state, require_user


router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("")
def list_strategies(
    request: Request,
    _user: dict = Depends(require_user),
) -> dict:
    items = app_state(request).strategy_catalog_service.strategies()
    return {"items": items, "count": len(items)}


@router.get("/{strategy_id}")
def get_strategy(
    strategy_id: str,
    request: Request,
    _user: dict = Depends(require_user),
) -> dict:
    try:
        return app_state(request).strategy_catalog_service.strategy(strategy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="策略不存在。") from exc
