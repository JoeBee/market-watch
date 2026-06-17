"""FastAPI application serving Market Watch API and static web UI."""
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from market_watch.analysis.company_detail import build_company_detail
from market_watch.config import APP_NAME, APP_VERSION, DEFAULT_UNIVERSE_LIMIT, ROOT_DIR
from market_watch.data.ingest import DataIngestor
from market_watch.db.store import Database
from market_watch.scoring.engine import ScoringEngine
from market_watch.api.jobs import job_manager

logger = logging.getLogger(__name__)

WEB_DIR = ROOT_DIR / "web"

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def disable_cache_for_ui(request: Request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-cache"
    return response

db = Database()
ingestor = DataIngestor(db)
engine = ScoringEngine(db)
job_manager.db = db


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        raise exc
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


class RefreshRequest(BaseModel):
    universe_limit: int = Field(default=DEFAULT_UNIVERSE_LIMIT, ge=20, le=503)
    use_sec: bool = Field(
        default=False,
        description="Enrich fundamentals from SEC EDGAR (slower; off by default).",
    )


class ScreenRequest(BaseModel):
    min_market_cap: float = Field(default=2_000_000_000, ge=0)


def _sanitize_value(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
        return None
    if isinstance(val, pd.Timestamp):
        return val.isoformat()
    return val


def _df_to_records(df: pd.DataFrame) -> list[dict[str, Any]]:
    if df.empty:
        return []
    records = df.to_dict(orient="records")
    return [{k: _sanitize_value(v) for k, v in row.items()} for row in records]


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


@app.get("/api/status")
def status() -> dict[str, Any]:
    return {
        "last_sync": db.last_sync_time(),
        "universe_size": len(db.get_universe_tickers()),
        "cached_picks": len(db.load_latest_picks()),
    }


@app.get("/api/picks")
def get_picks() -> dict[str, Any]:
    df = db.load_latest_picks()
    count = len(df)
    universe_size = len(db.get_universe_tickers())
    hint = None
    if count == 0:
        if universe_size == 0:
            hint = "No market data yet. Click Refresh Data to download, then Refresh to rank stocks."
        else:
            hint = (
                f"Data loaded ({universe_size} stocks) but not ranked yet. "
                "Click Refresh to compute scores."
            )
    return {
        "count": count,
        "last_sync": db.last_sync_time(),
        "universe_size": universe_size,
        "hint": hint,
        "rows": _df_to_records(df),
    }


@app.post("/api/screen")
def run_screen(body: ScreenRequest) -> dict[str, Any]:
    try:
        picks = engine.run_and_save(min_market_cap=body.min_market_cap)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "count": len(picks),
        "last_sync": db.last_sync_time(),
        "top_pick": picks.iloc[0]["ticker"] if len(picks) else None,
        "rows": _df_to_records(picks),
    }


@app.post("/api/refresh")
def start_refresh(body: RefreshRequest) -> dict[str, str]:
    def task(progress) -> str:
        ingestor.refresh_all(
            progress=progress,
            universe_limit=body.universe_limit,
            use_sec=body.use_sec,
        )
        return "Data refresh complete."

    job_id = job_manager.submit(task, label="data refresh")
    return {"job_id": job_id}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = job_manager.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "id": job.id,
        "status": job.status,
        "message": job.message,
        "error": job.error,
        "result": job.result,
        "created_at": job.created_at,
        "finished_at": job.finished_at,
    }


@app.get("/api/sectors/{sector}")
def get_sector(
    sector: str,
    min_market_cap: float = Query(default=2_000_000_000, ge=0),
) -> dict[str, Any]:
    try:
        ranked = engine.compute_for_sector(sector, min_market_cap=min_market_cap)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    top = ranked.iloc[0]["ticker"] if len(ranked) else None
    return {
        "sector": sector,
        "count": len(ranked),
        "top_pick": top,
        "rows": _df_to_records(ranked),
    }


@app.get("/api/companies/{ticker}")
def get_company(
    ticker: str,
    min_market_cap: float = Query(default=0, ge=0),
) -> dict[str, Any]:
    try:
        detail = build_company_detail(ticker, db, engine, min_market_cap=min_market_cap)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return detail


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> FileResponse:
    return FileResponse(WEB_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
