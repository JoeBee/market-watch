"""SEC EDGAR company facts (structured fundamentals)."""
from __future__ import annotations

import logging
from typing import Any

import requests

from market_watch.config import SEC_USER_AGENT

logger = logging.getLogger(__name__)

COMPANY_FACTS_URL = (
    "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
)


def _latest_annual_value(us_gaap: dict, tag: str) -> float | None:
    """Extract most recent annual value from SEC company facts tree."""
    try:
        if tag not in us_gaap:
            return None
        node = us_gaap[tag]
        units = node.get("units", {})
        # Prefer USD for monetary, pure for ratios
        for unit_key in ("USD", "USD/shares", "pure", "shares"):
            if unit_key not in units:
                continue
            entries = units[unit_key]
            annual = [e for e in entries if e.get("form") in ("10-K", "20-F", "40-F")]
            if not annual:
                annual = entries
            if not annual:
                continue
            annual.sort(key=lambda e: e.get("end", ""), reverse=True)
            val = annual[0].get("val")
            if val is not None:
                return float(val)
    except (KeyError, TypeError, ValueError):
        return None
    return None


def fetch_sec_company_facts(
    cik: str,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    cik_padded = str(cik).zfill(10)
    url = COMPANY_FACTS_URL.format(cik=cik_padded)
    headers = {"User-Agent": SEC_USER_AGENT, "Accept": "application/json"}
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 404:
        return {}
    resp.raise_for_status()
    data = resp.json()
    us_gaap = data.get("facts", {}).get("us-gaap", {})

    net_income = _latest_annual_value(us_gaap, "NetIncomeLoss")
    if net_income is None:
        for tag in ("ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"):
            net_income = _latest_annual_value(us_gaap, tag)
            if net_income is not None:
                break

    total_equity = None
    for tag in (
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
    ):
        total_equity = _latest_annual_value(us_gaap, tag)
        if total_equity is not None:
            break

    total_assets = _latest_annual_value(us_gaap, "Assets")
    long_term_debt = None
    for tag in ("LongTermDebt", "LongTermDebtNoncurrent"):
        long_term_debt = _latest_annual_value(us_gaap, tag)
        if long_term_debt is not None:
            break

    revenues = None
    for tag in ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"):
        revenues = _latest_annual_value(us_gaap, tag)
        if revenues is not None:
            break

    return {
        "sec_net_income": net_income,
        "sec_total_equity": total_equity,
        "sec_total_assets": total_assets,
        "sec_long_term_debt": long_term_debt,
        "sec_revenues": revenues,
    }


def enrich_with_sec(
    ticker: str,
    cik: str | None,
    existing: dict[str, Any],
) -> dict[str, Any]:
    if not cik:
        return existing
    try:
        sec_data = fetch_sec_company_facts(cik)
        merged = {**existing, **{k: v for k, v in sec_data.items() if v is not None}}
        if sec_data:
            merged["fundamentals_source"] = (
                merged.get("fundamentals_source", "") + "+sec"
            ).strip("+") or "sec"
        return merged
    except Exception as exc:
        logger.warning("SEC fetch failed for %s: %s", ticker, exc)
        return existing
