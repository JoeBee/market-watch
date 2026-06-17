"""Factor scoring for 6–12 month stock selection."""
from __future__ import annotations

from datetime import datetime, timezone

import numpy as np
import pandas as pd

from market_watch.config import (
    WEIGHT_LOW_VOL,
    WEIGHT_MOMENTUM_12_1,
    WEIGHT_MOMENTUM_6M,
    WEIGHT_QUALITY,
    WEIGHT_VALUE,
)
from market_watch.db.store import Database


def _zscore(series: pd.Series) -> pd.Series:
    s = series.astype(float)
    std = s.std()
    if std == 0 or np.isnan(std):
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def _trading_day_return(close: pd.Series, days_back: int) -> float | None:
    if len(close) < days_back + 1:
        return None
    end = close.iloc[-1]
    start = close.iloc[-1 - days_back]
    if start == 0 or pd.isna(start) or pd.isna(end):
        return None
    return float(end / start - 1.0)


def _apply_factor_scores(df: pd.DataFrame) -> pd.DataFrame:
    """Apply factor z-scores and composite rank to a metrics dataframe."""
    if df.empty:
        return df

    df["z_mom_12_1"] = _zscore(df["ret_12_1"].fillna(df["ret_12_1"].median()))
    df["z_mom_6m"] = _zscore(df["ret_6m"].fillna(df["ret_6m"].median()))
    df["z_value"] = _zscore(
        (
            df["earnings_yield"].fillna(df["earnings_yield"].median())
            + df["book_yield"].fillna(df["book_yield"].median())
        )
        / 2.0
    )
    quality_raw = (
        df["roe"].fillna(df["roe"].median()).fillna(0)
        + df["profit_margins"].fillna(df["profit_margins"].median()).fillna(0)
    ) / 2.0
    df["z_quality"] = _zscore(quality_raw)
    if df["debt_to_equity"].notna().any():
        df["z_quality"] = df["z_quality"] + _zscore(
            -df["debt_to_equity"].fillna(df["debt_to_equity"].median())
        ) * 0.3

    df["z_low_vol"] = _zscore(-df["vol_60d"].fillna(df["vol_60d"].median()))

    df["momentum_12_1"] = df["z_mom_12_1"]
    df["momentum_6m"] = df["z_mom_6m"]
    df["value_score"] = df["z_value"]
    df["quality_score"] = df["z_quality"]

    df["composite"] = (
        WEIGHT_MOMENTUM_12_1 * df["z_mom_12_1"]
        + WEIGHT_MOMENTUM_6M * df["z_mom_6m"]
        + WEIGHT_VALUE * df["z_value"]
        + WEIGHT_QUALITY * df["z_quality"]
        + WEIGHT_LOW_VOL * df["z_low_vol"]
    )

    df = df.sort_values("composite", ascending=False).reset_index(drop=True)
    df["rank"] = np.arange(1, len(df) + 1)
    return df


def _annualized_vol(close: pd.Series, window: int = 60) -> float | None:
    if len(close) < window + 1:
        return None
    rets = close.pct_change().dropna().tail(window)
    if rets.empty:
        return None
    return float(rets.std() * np.sqrt(252))


class ScoringEngine:
    """
    Composite factor ranker aligned to 6–12 month horizon:
    - Momentum: 12-1 month and 6-month price strength
    - Value: earnings yield, low P/B
    - Quality: ROE, margins, conservative leverage
    - Low vol: slight preference for lower 60-day volatility
    """

    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def compute(self, min_market_cap: float = 2e9) -> pd.DataFrame:
        prices = self.db.load_prices()
        fundamentals = self.db.load_fundamentals()
        if prices.empty:
            raise ValueError("No price data. Run data refresh first.")

        prices["date"] = pd.to_datetime(prices["date"])
        rows: list[dict] = []

        for ticker, grp in prices.groupby("ticker"):
            grp = grp.sort_values("date")
            close = grp["close"].astype(float)
            if close.empty:
                continue

            ret_12_1 = _trading_day_return(close, 252)
            ret_1m = _trading_day_return(close, 21)
            if ret_12_1 is not None and ret_1m is not None:
                mom_12_1 = ret_12_1 - ret_1m
            else:
                mom_12_1 = None

            ret_6m = _trading_day_return(close, 126)
            vol_60 = _annualized_vol(close, 60)

            fund = fundamentals.get(str(ticker), {})
            market_cap = fund.get("market_cap")
            if market_cap is not None and market_cap < min_market_cap:
                continue

            trailing_pe = fund.get("trailing_pe")
            earnings_yield = fund.get("earnings_yield")
            if earnings_yield is None and trailing_pe and trailing_pe > 0:
                earnings_yield = 1.0 / trailing_pe

            ptb = fund.get("price_to_book")
            book_yield = (1.0 / ptb) if ptb and ptb > 0 else None

            roe = fund.get("return_on_equity")
            margins = fund.get("profit_margins")
            dte = fund.get("debt_to_equity")

            rows.append(
                {
                    "ticker": ticker,
                    "name": fund.get("name", ""),
                    "sector": fund.get("sector", ""),
                    "market_cap": market_cap,
                    "ret_12_1": mom_12_1,
                    "ret_6m": ret_6m,
                    "vol_60d": vol_60,
                    "earnings_yield": earnings_yield,
                    "book_yield": book_yield,
                    "roe": roe,
                    "profit_margins": margins,
                    "debt_to_equity": dte,
                }
            )

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        return _apply_factor_scores(df)

    def compute_for_sector(
        self, sector: str, min_market_cap: float = 2e9
    ) -> pd.DataFrame:
        """Re-score and rank stocks within a single sector (z-scores vs sector peers)."""
        full = self.compute(min_market_cap=min_market_cap)
        if full.empty:
            return full
        sector_norm = str(sector).strip()
        subset = full[full["sector"].astype(str).str.strip() == sector_norm]
        if subset.empty:
            raise ValueError(f"No stocks found in sector: {sector}")
        return _apply_factor_scores(subset.copy())

    def run_and_save(self, min_market_cap: float = 2e9) -> pd.DataFrame:
        picks = self.compute(min_market_cap=min_market_cap)
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_cols = [
            "rank",
            "ticker",
            "composite",
            "momentum_12_1",
            "momentum_6m",
            "value_score",
            "quality_score",
            "vol_60d",
            "ret_12_1",
            "ret_6m",
            "earnings_yield",
            "roe",
            "market_cap",
            "sector",
            "name",
        ]
        save_df = picks[[c for c in out_cols if c in picks.columns]]
        self.db.save_picks(run_id, save_df)
        return picks
