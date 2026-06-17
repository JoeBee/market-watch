"""Historical price ingestion via yfinance (primary) and Stooq (fallback)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable

import pandas as pd
import yfinance as yf

from market_watch.config import PRICE_HISTORY_CALENDAR_DAYS, STOOQ_SUFFIX, USE_STOOQ_FALLBACK
from market_watch.data.stooq import fetch_stooq_daily

logger = logging.getLogger(__name__)


def _normalize_price_df(df: pd.DataFrame, ticker: str) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    df = df.rename(
        columns={
            date_col: "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }
    )
    keep = ["date", "open", "high", "low", "close", "volume"]
    df = df[[c for c in keep if c in df.columns]]
    df["ticker"] = ticker.upper()
    df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
    return df.dropna(subset=["close"])


def _price_window() -> tuple[str, str]:
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=PRICE_HISTORY_CALENDAR_DAYS)
    return start.isoformat(), end.isoformat()


def fetch_prices_yfinance(
    tickers: list[str],
    progress: Callable[[str], None] | None = None,
) -> pd.DataFrame:
    if progress:
        progress(f"Downloading prices for {len(tickers)} symbols (Yahoo Finance)…")
    if not tickers:
        return pd.DataFrame()

    start, end = _price_window()
    yf_tickers = " ".join(tickers)
    raw = yf.download(
        yf_tickers,
        start=start,
        end=end,
        interval="1d",
        group_by="ticker",
        auto_adjust=True,
        threads=True,
        progress=False,
    )
    frames: list[pd.DataFrame] = []

    if len(tickers) == 1:
        t = tickers[0].upper()
        frames.append(_normalize_price_df(raw, t))
    elif isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            tu = t.upper()
            try:
                sub = raw[tu] if tu in raw.columns.get_level_values(0) else raw[t]
                frames.append(_normalize_price_df(sub, tu))
            except (KeyError, TypeError):
                logger.warning("No Yahoo data for %s", t)
    else:
        frames.append(_normalize_price_df(raw, tickers[0].upper()))

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def fetch_prices_with_fallback(
    tickers: list[str],
    progress: Callable[[str], None] | None = None,
) -> tuple[pd.DataFrame, dict[str, str]]:
    """Returns combined price DataFrame and per-ticker source map."""
    df = fetch_prices_yfinance(tickers, progress=progress)
    sources: dict[str, str] = {}
    if not df.empty:
        for t in df["ticker"].unique():
            sources[str(t)] = "yfinance"

    # Stooq fallback only when Yahoo returned no rows (optional; slow per ticker).
    need_fallback: list[str] = []
    if USE_STOOQ_FALLBACK:
        if df.empty:
            need_fallback = list(tickers)
        else:
            present = set(df["ticker"].astype(str).str.upper())
            need_fallback = [t for t in tickers if t.upper() not in present]

    for t in need_fallback:
        if progress:
            progress(f"Stooq fallback for {t}…")
        stooq_sym = f"{t.lower()}{STOOQ_SUFFIX}"
        stooq_df = fetch_stooq_daily(stooq_sym)
        norm = _normalize_price_df(stooq_df, t.upper())
        if norm.empty:
            continue
        sources[t.upper()] = "stooq"
        df = pd.concat([df[df["ticker"] != t.upper()], norm], ignore_index=True)

    return df, sources


def prices_to_db_records(df: pd.DataFrame) -> pd.DataFrame:
    return df
