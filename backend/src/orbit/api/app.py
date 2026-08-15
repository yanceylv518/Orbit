from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from threading import Event, Thread
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from orbit.api.routers import accounts, auth, binance, data, execution_plans, messages, research, signals, strategies, strategy_control, system
from orbit.bootstrap import create_app_state


ROOT = Path(__file__).resolve().parents[4]
WEB = ROOT / "frontend" / "dist"
REPORTS = ROOT / "reports"


def create_api(app_state: Any | None = None) -> FastAPI:
    app = FastAPI(title="Orbit", docs_url="/api/docs", redoc_url=None)
    app.state.orbit = app_state or create_app_state()
    scheduler_stop = Event()

    def scheduler_loop() -> None:
        while not scheduler_stop.wait(60):
            scheduler = getattr(app.state.orbit, "data_update_scheduler", None)
            if scheduler is not None:
                scheduler.run_due(datetime.now(timezone.utc))

    @app.on_event("startup")
    def start_scheduler() -> None:
        scheduler = getattr(app.state.orbit, "data_update_scheduler", None)
        if scheduler is not None:
            scheduler.run_due(datetime.now(timezone.utc))
            app.state.data_scheduler_thread = Thread(target=scheduler_loop, daemon=True, name="orbit-data-update")
            app.state.data_scheduler_thread.start()

    @app.on_event("shutdown")
    def stop_scheduler() -> None:
        scheduler_stop.set()

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            {"ok": False, "error": str(exc.detail)},
            status_code=exc.status_code,
            headers=exc.headers,
        )

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    app.include_router(auth.router)
    app.include_router(system.router)
    app.include_router(accounts.router)
    app.include_router(binance.router)
    app.include_router(execution_plans.router)
    app.include_router(data.router)
    app.include_router(messages.router)
    app.include_router(research.router)
    app.include_router(signals.router)
    app.include_router(strategies.router)
    app.include_router(strategy_control.router)
    app.mount("/reports", StaticFiles(directory=REPORTS, check_dir=False), name="reports")
    app.mount("/", StaticFiles(directory=WEB, html=True, check_dir=False), name="frontend")
    return app
