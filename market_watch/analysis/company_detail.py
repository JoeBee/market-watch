"""Build company detail view and factor-based narrative summary."""
from __future__ import annotations

from typing import Any

import pandas as pd

from market_watch.db.store import Database
from market_watch.scoring.engine import ScoringEngine


def _fmt_pct(val: float | None) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    return f"{float(val) * 100:.2f}%"


def _fmt_money(val: float | None) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    v = float(val)
    if abs(v) >= 1e12:
        return f"${v / 1e12:.2f}T"
    if abs(v) >= 1e9:
        return f"${v / 1e9:.2f}B"
    if abs(v) >= 1e6:
        return f"${v / 1e6:.1f}M"
    return f"${v:,.0f}"


def _fmt_float(val: float | None, decimals: int = 2) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return "—"
    return f"{float(val):.{decimals}f}"


def _z_label(z: float | None) -> str:
    if z is None or (isinstance(z, float) and pd.isna(z)):
        return "n/a"
    z = float(z)
    if z >= 1.0:
        return "strong"
    if z >= 0.25:
        return "above average"
    if z > -0.25:
        return "average"
    if z > -1.0:
        return "below average"
    return "weak"


def _generate_summary(
    ticker: str,
    row: pd.Series,
    fund: dict[str, Any],
    universe_rank: int,
    universe_total: int,
    sector_rank: int | None,
    sector_total: int | None,
) -> str:
    composite = float(row.get("composite", 0))
    mom_z = float(row.get("momentum_12_1", 0) or 0)
    val_z = float(row.get("value_score", 0) or 0)
    qual_z = float(row.get("quality_score", 0) or 0)
    vol = row.get("vol_60d")

    pros: list[str] = []
    cons: list[str] = []

    if mom_z >= 0.25:
        pros.append(
            f"Momentum is {_z_label(mom_z)} (12–1M return {_fmt_pct(row.get('ret_12_1'))}), "
            "which historically supports 6–12 month relative strength."
        )
    elif mom_z <= -0.25:
        cons.append(
            f"Momentum is {_z_label(mom_z)}—recent trend lags peers in your universe."
        )

    if val_z >= 0.25:
        pros.append(
            f"Valuation looks relatively attractive (value score {_z_label(val_z)}; "
            f"earnings yield {_fmt_pct(row.get('earnings_yield'))})."
        )
    elif val_z <= -0.25:
        cons.append(
            f"Stock screens expensive vs peers (value score {_z_label(val_z)})."
        )

    if qual_z >= 0.25:
        pros.append(
            f"Business quality is {_z_label(qual_z)} (ROE {_fmt_pct(fund.get('return_on_equity'))}, "
            f"margins {_fmt_pct(fund.get('profit_margins'))})."
        )
    elif qual_z <= -0.25:
        cons.append(f"Quality metrics are {_z_label(qual_z)}—weaker profitability or balance sheet vs peers.")

    dte = fund.get("debt_to_equity")
    if dte is not None and float(dte) > 150:
        cons.append(f"Elevated debt-to-equity ({_fmt_float(dte, 0)}) adds financial risk.")

    if vol is not None and not pd.isna(vol) and float(vol) > 0.45:
        cons.append(f"Higher 60-day volatility ({_fmt_float(vol, 2)})—larger short-term swings likely.")

    pct_top = (universe_rank / universe_total) * 100 if universe_total else 100
    if universe_rank <= max(3, universe_total * 0.1):
        pros.append(
            f"Ranks #{universe_rank} of {universe_total} overall on the composite 6–12 month score."
        )
    elif universe_rank > universe_total * 0.75:
        cons.append(
            f"Ranks #{universe_rank} of {universe_total} overall—below most names in the current screen."
        )

    if sector_rank is not None and sector_total and sector_rank <= max(2, sector_total * 0.25):
        pros.append(f"Top-tier within its sector (#{sector_rank} of {sector_total} in-sector).")

  # Verdict
    if composite >= 0.75 and len(pros) >= 2 and len(cons) <= 1:
        verdict = (
            f"<b>Summary:</b> <span class='verdict-favorable'>Favorable</span> for a 6–12 month "
            f"factor-tilted watchlist—strengths outweigh weaknesses on this model."
        )
    elif composite >= 0.0 and len(cons) <= len(pros):
        verdict = (
            f"<b>Summary:</b> <span class='verdict-neutral'>Mixed / neutral</span>—some factors support "
            f"a hold or further research, but there are notable offsets."
        )
    else:
        verdict = (
            f"<b>Summary:</b> <span class='verdict-caution'>Caution</span>—on this screener, weaknesses "
            f"dominate; not a top candidate unless you have a separate thesis."
        )

    pros_html = "".join(f"<li>{p}</li>" for p in pros) or "<li>No major factor strengths flagged.</li>"
    cons_html = "".join(f"<li>{c}</li>" for c in cons) or "<li>No major factor weaknesses flagged.</li>"

    return (
        f"{verdict}<br><br>"
        f"<b>Why it could work (6–12 months)</b><ul>{pros_html}</ul>"
        f"<b>Why to be careful</b><ul>{cons_html}</ul>"
        "<i>This is model commentary from historical data—not a buy/sell recommendation.</i>"
    )


def build_company_detail(
    ticker: str,
    db: Database,
    engine: ScoringEngine,
    min_market_cap: float = 0.0,
) -> dict[str, Any]:
    """Assemble metrics and HTML content for the company detail tab."""
    ticker = ticker.upper().strip()
    full = engine.compute(min_market_cap=min_market_cap)
    if full.empty:
        raise ValueError("No scored data. Run Refresh first.")

    match = full[full["ticker"].astype(str).str.upper() == ticker]
    if match.empty:
        raise ValueError(f"{ticker} is not in the current screen (try Refresh Data).")

    row = match.iloc[0]
    fund = db.load_fundamentals().get(ticker, {})

    universe_rank = int(row.get("rank", 0))
    universe_total = len(full)

    sector = str(row.get("sector", "") or fund.get("sector", "")).strip()
    sector_rank = None
    sector_total = None
    if sector:
        try:
            in_sector = engine.compute_for_sector(sector, min_market_cap=min_market_cap)
            sec_match = in_sector[in_sector["ticker"].astype(str).str.upper() == ticker]
            if not sec_match.empty:
                sector_rank = int(sec_match.iloc[0]["rank"])
                sector_total = len(in_sector)
        except ValueError:
            pass

    name = str(row.get("name") or fund.get("name") or ticker)
    summary_html = _generate_summary(
        ticker, row, fund, universe_rank, universe_total, sector_rank, sector_total
    )

    metrics_html = (
        "<table cellspacing='6'>"
        f"<tr><td><b>Ticker</b></td><td>{ticker}</td></tr>"
        f"<tr><td><b>Company</b></td><td>{name}</td></tr>"
        f"<tr><td><b>Sector</b></td><td>{sector or '—'}</td></tr>"
        f"<tr><td><b>Market cap</b></td><td>{_fmt_money(row.get('market_cap') or fund.get('market_cap'))}</td></tr>"
        f"<tr><td><b>Overall rank</b></td><td>#{universe_rank} of {universe_total}</td></tr>"
        f"<tr><td><b>Sector rank</b></td><td>"
        f"{'#' + str(sector_rank) + ' of ' + str(sector_total) if sector_rank else '—'}"
        f"</td></tr>"
        f"<tr><td><b>Composite score</b></td><td>{_fmt_float(row.get('composite'), 3)}</td></tr>"
        f"<tr><td><b>12–1 month return</b></td><td>{_fmt_pct(row.get('ret_12_1'))}</td></tr>"
        f"<tr><td><b>6 month return</b></td><td>{_fmt_pct(row.get('ret_6m'))}</td></tr>"
        f"<tr><td><b>Momentum (Z)</b></td><td>{_fmt_float(row.get('momentum_12_1'), 3)} ({_z_label(row.get('momentum_12_1'))})</td></tr>"
        f"<tr><td><b>Value (Z)</b></td><td>{_fmt_float(row.get('value_score'), 3)} ({_z_label(row.get('value_score'))})</td></tr>"
        f"<tr><td><b>Quality (Z)</b></td><td>{_fmt_float(row.get('quality_score'), 3)} ({_z_label(row.get('quality_score'))})</td></tr>"
        f"<tr><td><b>60-day volatility (ann.)</b></td><td>{_fmt_float(row.get('vol_60d'), 3)}</td></tr>"
        f"<tr><td><b>Trailing P/E</b></td><td>{_fmt_float(fund.get('trailing_pe'))}</td></tr>"
        f"<tr><td><b>Forward P/E</b></td><td>{_fmt_float(fund.get('forward_pe'))}</td></tr>"
        f"<tr><td><b>Price / book</b></td><td>{_fmt_float(fund.get('price_to_book'))}</td></tr>"
        f"<tr><td><b>Earnings yield (E/P)</b></td><td>{_fmt_pct(row.get('earnings_yield'))}</td></tr>"
        f"<tr><td><b>ROE</b></td><td>{_fmt_pct(fund.get('return_on_equity'))}</td></tr>"
        f"<tr><td><b>Profit margin</b></td><td>{_fmt_pct(fund.get('profit_margins'))}</td></tr>"
        f"<tr><td><b>Debt / equity</b></td><td>{_fmt_float(fund.get('debt_to_equity'))}</td></tr>"
        f"<tr><td><b>Free cash flow</b></td><td>{_fmt_money(fund.get('free_cashflow'))}</td></tr>"
        f"<tr><td><b>Revenue</b></td><td>{_fmt_money(fund.get('total_revenue'))}</td></tr>"
        f"<tr><td><b>Data source</b></td><td>{fund.get('fundamentals_source', '—')}</td></tr>"
        "</table>"
    )

    return {
        "ticker": ticker,
        "name": name,
        "title_html": f"<h2 style='margin:0'>{ticker} — {name}</h2>",
        "metrics_html": metrics_html,
        "summary_html": summary_html,
    }
