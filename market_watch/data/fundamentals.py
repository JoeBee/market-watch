"""Fundamental data via Yahoo Finance (parallel) with optional SEC enrichment."""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

import yfinance as yf

from market_watch.config import FUNDAMENTALS_MAX_WORKERS, USE_SEC_ENRICHMENT
from market_watch.data.sec import enrich_with_sec

logger = logging.getLogger(__name__)


def _safe_float(val: Any) -> float | None:
    try:
        if val is None:
            return None
        f = float(val)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def fetch_yfinance_fundamentals(ticker: str) -> dict[str, Any]:
    t = yf.Ticker(ticker)
    info = {}
    try:
        info = t.info or {}
    except Exception as exc:
        logger.warning("yfinance info failed for %s: %s", ticker, exc)

    return {
        "name": info.get("shortName") or info.get("longName"),
        "sector": info.get("sector"),
        "market_cap": _safe_float(info.get("marketCap")),
        "trailing_pe": _safe_float(info.get("trailingPE")),
        "forward_pe": _safe_float(info.get("forwardPE")),
        "price_to_book": _safe_float(info.get("priceToBook")),
        "return_on_equity": _safe_float(info.get("returnOnEquity")),
        "profit_margins": _safe_float(info.get("profitMargins")),
        "debt_to_equity": _safe_float(info.get("debtToEquity")),
        "earnings_yield": (
            1.0 / _safe_float(info.get("trailingPE"))
            if _safe_float(info.get("trailingPE"))
            else None
        ),
        "free_cashflow": _safe_float(info.get("freeCashflow")),
        "total_revenue": _safe_float(info.get("totalRevenue")),
        "fundamentals_source": "yfinance",
    }


def fetch_fundamentals_batch(
    tickers: list[str],
    cik_map: dict[str, str] | None = None,
    use_sec: bool | None = None,
    progress: Callable[[str], None] | None = None,
    max_workers: int | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch fundamentals in parallel; SEC enrichment is off by default (slow)."""
    if not tickers:
        return {}

    use_sec = USE_SEC_ENRICHMENT if use_sec is None else use_sec
    workers = max_workers or FUNDAMENTALS_MAX_WORKERS
    cik_map = cik_map or {}
    total = len(tickers)
    results: dict[str, dict[str, Any]] = {}
    completed = 0

    def fetch_one(ticker: str) -> tuple[str, dict[str, Any]]:
        data = fetch_yfinance_fundamentals(ticker)
        if use_sec:
            cik = cik_map.get(ticker.replace("-", "")) or cik_map.get(ticker)
            if cik:
                data = enrich_with_sec(ticker, cik, data)
        return ticker.upper(), data

    with ThreadPoolExecutor(max_workers=min(workers, total)) as executor:
        futures = {executor.submit(fetch_one, t): t for t in tickers}
        for future in as_completed(futures):
            ticker, data = future.result()
            results[ticker] = data
            completed += 1
            if progress and (completed == 1 or completed % 10 == 0 or completed == total):
                progress(f"Fundamentals {completed}/{total}: {ticker}…")

    return results
