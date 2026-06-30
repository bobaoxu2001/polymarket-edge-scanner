"""FastAPI application entrypoint.

Wires up the database, the REST API, a background scan scheduler, and serves the
static dashboard. Run with::

    uvicorn backend.main:app --reload

or simply ``./run.sh`` from the project root.
"""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.config import ROOT_DIR, settings
from backend.db import init_db, session_scope
from backend.routes import (
    arbitrage,
    markets,
    metrics,
    opportunities,
    paper_trades,
    settings as settings_routes,
)
from backend.services.scanner import run_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("scanner")

_scheduler: BackgroundScheduler | None = None


def _scheduled_scan() -> None:
    """Run a scan inside its own DB transaction; never raise into the scheduler."""
    try:
        with session_scope() as session:
            result = run_scan(session)
        logger.info("scan complete: %s", result.message)
    except Exception:  # noqa: BLE001 — keep the scheduler alive
        logger.exception("scheduled scan failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB + scheduler on startup; shut the scheduler down on exit."""
    global _scheduler
    init_db()
    logger.info("database initialized at %s", settings.database_url)

    _scheduler = BackgroundScheduler(daemon=True)
    _scheduler.add_job(
        _scheduled_scan,
        "interval",
        seconds=max(30, settings.scan_interval_seconds),
        id="periodic_scan",
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("scheduler started (every %ss)", settings.scan_interval_seconds)

    if settings.scan_on_startup:
        # Run the first scan off-thread so startup isn't blocked by network I/O.
        threading.Thread(target=_scheduled_scan, daemon=True).start()

    try:
        yield
    finally:
        if _scheduler:
            _scheduler.shutdown(wait=False)
            logger.info("scheduler stopped")


app = FastAPI(
    title="Polymarket Edge Scanner",
    version="0.1.0",
    summary="Research + paper-trading scanner for Polymarket. No real trading.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # local-only tool; tighten if ever exposed
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API
app.include_router(markets.router)
app.include_router(opportunities.router)
app.include_router(paper_trades.router)
app.include_router(metrics.router)
app.include_router(arbitrage.router)
app.include_router(settings_routes.router)
app.include_router(settings_routes.scan_router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Liveness probe + key safety flags (paper-only by design)."""
    return {
        "status": "ok",
        "paper_trading_enabled": settings.paper_trading_enabled,
        "live_trading_enabled": False,  # hard-disabled in the MVP
        "scan_interval_seconds": settings.scan_interval_seconds,
    }


# Static dashboard (mounted last so it doesn't shadow /api routes).
_frontend_dir = ROOT_DIR / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")
