"""Fundamental data via Yahoo Finance (batch) with optional SEC enrichment."""
from __future__ import annotations

import logging
from typing import Any, Callable

import yfinance as yf

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
    cik_map: dict[str, str],
    use_sec: bool = True,
    progress: Callable[[str], None] | None = None,
    sec_every_n: int = 5,
) -> dict[str, dict[str, Any]]:
    """Fetch fundamentals; SEC enrichment on a subset to respect rate limits."""
    results: dict[str, dict[str, Any]] = {}
    total = len(tickers)
    for i, ticker in enumerate(tickers):
        if progress and i % 10 == 0:
            progress(f"Fundamentals {i + 1}/{total}: {ticker}…")
        data = fetch_yfinance_fundamentals(ticker)
        cik = cik_map.get(ticker.replace("-", "")) or cik_map.get(ticker)
        if use_sec and cik and (i % sec_every_n == 0):
            data = enrich_with_sec(ticker, cik, data)
        results[ticker.upper()] = data
    return results
