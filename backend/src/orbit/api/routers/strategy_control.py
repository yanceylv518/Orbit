from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from orbit.api.dependencies import app_state, require_admin


router = APIRouter(prefix="/api/strategy-control", tags=["strategy-control"])


@router.get("")
def overview(request: Request, _user: dict = Depends(require_admin)) -> dict:
    return app_state(request).strategy_control_plane_service.overview()


@router.get("/definitions")
def definitions(request: Request, _user: dict = Depends(require_admin)) -> dict:
    items = app_state(request).strategy_control_plane_service.definitions()
    return {"items": items, "count": len(items)}


@router.get("/evidence-bundles")
def evidence_bundles(request: Request, _user: dict = Depends(require_admin)) -> dict:
    items = app_state(request).strategy_control_plane_service.evidence_bundles()
    return {"items": items, "count": len(items)}


@router.get("/instances")
def instances(request: Request, _user: dict = Depends(require_admin)) -> dict:
    items = app_state(request).strategy_control_plane_service.instances()
    return {"items": items, "count": len(items)}


@router.get("/bindings")
def bindings(request: Request, _user: dict = Depends(require_admin)) -> dict:
    items = app_state(request).strategy_control_plane_service.bindings()
    return {"items": items, "count": len(items)}


@router.get("/risk-policies")
def risk_policies(request: Request, _user: dict = Depends(require_admin)) -> dict:
    items = app_state(request).strategy_control_plane_service.risk_policies()
    return {"items": items, "count": len(items)}


@router.get("/runner-leases")
def runner_leases(request: Request, _user: dict = Depends(require_admin)) -> dict:
    items = app_state(request).strategy_control_plane_service.runner_leases()
    return {"items": items, "count": len(items)}
