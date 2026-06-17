"""Orchestrates universe, price, and fundamental data ingestion."""
from __future__ import annotations

import logging
from typing import Callable

from market_watch.config import (
    DEFAULT_UNIVERSE_LIMIT,
    PRICE_BATCH_SIZE,
    USE_SEC_ENRICHMENT,
)
from market_watch.data.fundamentals import fetch_fundamentals_batch
from market_watch.data.prices import fetch_prices_with_fallback
from market_watch.data.universe import build_universe_rows, fetch_sec_cik_map, fetch_sp500
from market_watch.db.store import Database

logger = logging.getLogger(__name__)


class DataIngestor:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()
        self._cik_map: dict[str, str] = {}

    def refresh_universe(
        self,
        progress: Callable[[str], None] | None = None,
        limit: int | None = None,
    ) -> list[str]:
        log_id = self.db.log_sync_start("universe")
        try:
            universe_df = fetch_sp500(progress=progress)
            if limit:
                universe_df = universe_df.head(limit)
            self._cik_map = fetch_sec_cik_map(progress=progress)
            rows = build_universe_rows(universe_df, self._cik_map)
            self.db.upsert_universe(rows)
            tickers = [r["ticker"] for r in rows]
            self.db.log_sync_finish(log_id, "ok", f"{len(tickers)} tickers")
            return tickers
        except Exception as exc:
            self.db.log_sync_finish(log_id, "error", str(exc))
            raise

    def refresh_prices(
        self,
        tickers: list[str] | None = None,
        progress: Callable[[str], None] | None = None,
        batch_size: int | None = None,
    ) -> int:
        log_id = self.db.log_sync_start("prices")
        try:
            tickers = tickers or self.db.get_universe_tickers()
            if not tickers:
                raise ValueError("Universe is empty. Refresh universe first.")
            batch_size = batch_size or PRICE_BATCH_SIZE
            total_rows = 0
            batches = (len(tickers) + batch_size - 1) // batch_size
            for i in range(0, len(tickers), batch_size):
                batch = tickers[i : i + batch_size]
                if progress:
                    progress(f"Price batch {i // batch_size + 1}/{batches}…")
                df, _ = fetch_prices_with_fallback(batch, progress=progress)
                total_rows += self.db.upsert_prices(df, "mixed")
            self.db.log_sync_finish(log_id, "ok", f"{total_rows} rows")
            return total_rows
        except Exception as exc:
            self.db.log_sync_finish(log_id, "error", str(exc))
            raise

    def refresh_fundamentals(
        self,
        tickers: list[str] | None = None,
        progress: Callable[[str], None] | None = None,
        use_sec: bool | None = None,
        cik_map: dict[str, str] | None = None,
    ) -> int:
        log_id = self.db.log_sync_start("fundamentals")
        try:
            tickers = tickers or self.db.get_universe_tickers()
            cik_map = cik_map or self._cik_map or fetch_sec_cik_map()
            data = fetch_fundamentals_batch(
                tickers,
                cik_map=cik_map,
                use_sec=use_sec,
                progress=progress,
            )
            universe_meta = {
                row["ticker"]: row
                for row in self.db.get_universe_rows()
            }
            for ticker, payload in data.items():
                meta = universe_meta.get(ticker, {})
                if not payload.get("name"):
                    payload["name"] = meta.get("name")
                if not payload.get("sector"):
                    payload["sector"] = meta.get("sector")
                self.db.upsert_fundamentals(
                    ticker, payload, payload.get("fundamentals_source", "yfinance")
                )
            self.db.log_sync_finish(log_id, "ok", f"{len(data)} tickers")
            return len(data)
        except Exception as exc:
            self.db.log_sync_finish(log_id, "error", str(exc))
            raise

    def refresh_all(
        self,
        progress: Callable[[str], None] | None = None,
        universe_limit: int | None = None,
        use_sec: bool | None = None,
    ) -> None:
        limit = universe_limit if universe_limit is not None else DEFAULT_UNIVERSE_LIMIT
        tickers = self.refresh_universe(progress=progress, limit=limit)
        self.refresh_prices(tickers, progress=progress)
        self.refresh_fundamentals(
            tickers,
            progress=progress,
            use_sec=use_sec if use_sec is not None else USE_SEC_ENRICHMENT,
            cik_map=self._cik_map,
        )
