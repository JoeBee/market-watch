"""FastAPI application serving Market Watch API and static web UI."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from market_watch.analysis.company_detail import build_company_detail
from market_watch.config import APP_NAME, APP_VERSION, ROOT_DIR
from market_watch.data.ingest import DataIngestor
from market_watch.db.store import Database
from market_watch.scoring.engine import ScoringEngine
from market_watch.api.jobs import job_manager

WEB_DIR = ROOT_DIR / "web"

app = FastAPI(title=APP_NAME, version=APP_VERSION)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

db = Database()
ingestor = DataIngestor(db)
engine = ScoringEngine(db)


class RefreshRequest(BaseModel):
    universe_limit: int = Field(default=100, ge=20, le=503)


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
    return {
        "count": len(df),
        "last_sync": db.last_sync_time(),
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
        ingestor.refresh_all(progress=progress, universe_limit=body.universe_limit)
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
