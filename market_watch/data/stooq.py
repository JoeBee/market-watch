"""Stooq daily CSV download (free, no API key)."""
from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from market_watch.config import SEC_USER_AGENT

logger = logging.getLogger(__name__)

STOOQ_DAILY_URL = "https://stooq.com/q/d/l/"


def fetch_stooq_daily(symbol: str) -> pd.DataFrame:
    """
    Download daily OHLCV from Stooq.
    symbol example: 'aapl.us'
    """
    params = {"s": symbol, "i": "d"}
    headers = {"User-Agent": SEC_USER_AGENT}
    resp = requests.get(STOOQ_DAILY_URL, params=params, headers=headers, timeout=60)
    resp.raise_for_status()
    if "Exceeded" in resp.text[:200]:
        logger.warning("Stooq rate limit for %s", symbol)
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(resp.text))
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()
    df = df.rename(
        columns={
            "Date": "Date",
            "Open": "Open",
            "High": "High",
            "Low": "Low",
            "Close": "Close",
            "Volume": "Volume",
        }
    )
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date")
    return df.set_index("Date")
