"""Load investable universe (S&P 500 constituents via public sources)."""
from __future__ import annotations

import io
import logging
from typing import Callable

import pandas as pd
import requests

from market_watch.config import SEC_USER_AGENT

logger = logging.getLogger(__name__)

WIKI_SP500_URL = (
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
)
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def fetch_sp500(progress: Callable[[str], None] | None = None) -> pd.DataFrame:
    """Return tickers, names, sectors from Wikipedia S&P 500 table."""
    if progress:
        progress("Loading S&P 500 universe from Wikipedia…")
    headers = {
        "User-Agent": SEC_USER_AGENT,
    }
    resp = requests.get(WIKI_SP500_URL, headers=headers, timeout=60)
    resp.raise_for_status()
    tables = pd.read_html(io.StringIO(resp.text))
    df = tables[0]
    df = df.rename(
        columns={
            "Symbol": "ticker",
            "Security": "name",
            "GICS Sector": "sector",
        }
    )
    df["ticker"] = df["ticker"].str.replace(".", "-", regex=False)
    return df[["ticker", "name", "sector"]].drop_duplicates(subset=["ticker"])


def fetch_sec_cik_map(progress: Callable[[str], None] | None = None) -> dict[str, str]:
    """Map ticker -> zero-padded CIK from SEC."""
    if progress:
        progress("Loading SEC CIK ticker map…")
    headers = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
    resp = requests.get(SEC_TICKERS_URL, headers=headers, timeout=60)
    resp.raise_for_status()
    raw = resp.json()
    mapping: dict[str, str] = {}
    for entry in raw.values():
        ticker = str(entry.get("ticker", "")).upper()
        cik = str(entry.get("cik_str", ""))
        if ticker and cik:
            mapping[ticker] = cik.zfill(10)
    return mapping


def build_universe_rows(
    universe_df: pd.DataFrame,
    cik_map: dict[str, str] | None = None,
) -> list[dict]:
    rows = []
    for _, row in universe_df.iterrows():
        ticker = str(row["ticker"]).upper()
        rows.append(
            {
                "ticker": ticker,
                "name": str(row.get("name", "")),
                "sector": str(row.get("sector", "")),
                "cik": (cik_map or {}).get(ticker.replace("-", ""), None)
                or (cik_map or {}).get(ticker, None),
            }
        )
    return rows
