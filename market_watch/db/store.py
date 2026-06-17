"""SQLite persistence for prices, fundamentals, and sync metadata."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pandas as pd

from market_watch.config import DB_PATH


class Database:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT,
                    message TEXT
                );

                CREATE TABLE IF NOT EXISTS universe (
                    ticker TEXT PRIMARY KEY,
                    name TEXT,
                    sector TEXT,
                    cik TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS prices (
                    ticker TEXT NOT NULL,
                    date TEXT NOT NULL,
                    open REAL,
                    high REAL,
                    low REAL,
                    close REAL,
                    volume REAL,
                    source TEXT,
                    PRIMARY KEY (ticker, date)
                );

                CREATE TABLE IF NOT EXISTS fundamentals (
                    ticker TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    source TEXT,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS picks (
                    run_id TEXT NOT NULL,
                    ticker TEXT NOT NULL,
                    rank INTEGER,
                    composite REAL,
                    momentum_12_1 REAL,
                    momentum_6m REAL,
                    value_score REAL,
                    quality_score REAL,
                    vol_60d REAL,
                    ret_12_1 REAL,
                    ret_6m REAL,
                    earnings_yield REAL,
                    roe REAL,
                    market_cap REAL,
                    sector TEXT,
                    name TEXT,
                    PRIMARY KEY (run_id, ticker)
                );

                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    message TEXT,
                    result TEXT,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );
                """
            )

    def log_sync_start(self, source: str) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO sync_log (source, started_at, status) VALUES (?, ?, ?)",
                (source, now, "running"),
            )
            return int(cur.lastrowid)

    def log_sync_finish(self, log_id: int, status: str, message: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                "UPDATE sync_log SET finished_at=?, status=?, message=? WHERE id=?",
                (now, status, message, log_id),
            )

    def upsert_universe(self, rows: list[dict[str, Any]]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.executemany(
                """
                INSERT INTO universe (ticker, name, sector, cik, updated_at)
                VALUES (:ticker, :name, :sector, :cik, :updated_at)
                ON CONFLICT(ticker) DO UPDATE SET
                    name=excluded.name,
                    sector=excluded.sector,
                    cik=COALESCE(excluded.cik, universe.cik),
                    updated_at=excluded.updated_at
                """,
                [{**r, "updated_at": now} for r in rows],
            )

    def get_universe_tickers(self) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT ticker FROM universe ORDER BY ticker"
            ).fetchall()
        return [r["ticker"] for r in rows]

    def get_universe_rows(self) -> list[dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT ticker, name, sector, cik FROM universe ORDER BY ticker"
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_prices(self, df: pd.DataFrame, source: str) -> int:
        if df.empty:
            return 0
        records = df.reset_index().to_dict(orient="records")
        with self._conn() as conn:
            conn.executemany(
                """
                INSERT INTO prices (ticker, date, open, high, low, close, volume, source)
                VALUES (:ticker, :date, :open, :high, :low, :close, :volume, :source)
                ON CONFLICT(ticker, date) DO UPDATE SET
                    open=excluded.open, high=excluded.high, low=excluded.low,
                    close=excluded.close, volume=excluded.volume, source=excluded.source
                """,
                [{**r, "source": source} for r in records],
            )
        return len(records)

    def load_prices(self, tickers: list[str] | None = None) -> pd.DataFrame:
        query = "SELECT ticker, date, open, high, low, close, volume FROM prices"
        params: tuple[Any, ...] = ()
        if tickers:
            placeholders = ",".join("?" * len(tickers))
            query += f" WHERE ticker IN ({placeholders})"
            params = tuple(tickers)
        with self._conn() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"])
        return df

    def upsert_fundamentals(self, ticker: str, data: dict[str, Any], source: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO fundamentals (ticker, payload, source, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(ticker) DO UPDATE SET
                    payload=excluded.payload, source=excluded.source, updated_at=excluded.updated_at
                """,
                (ticker, json.dumps(data), source, now),
            )

    def load_fundamentals(self) -> dict[str, dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT ticker, payload FROM fundamentals").fetchall()
        return {r["ticker"]: json.loads(r["payload"]) for r in rows}

    def save_picks(self, run_id: str, picks: pd.DataFrame) -> None:
        with self._conn() as conn:
            conn.execute("DELETE FROM picks WHERE run_id=?", (run_id,))
            picks = picks.copy()
            picks["run_id"] = run_id
            picks.to_sql("picks", conn, if_exists="append", index=False)

    def load_latest_picks(self) -> pd.DataFrame:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT run_id FROM picks ORDER BY run_id DESC LIMIT 1"
            ).fetchone()
            if not row:
                return pd.DataFrame()
            return pd.read_sql_query(
                "SELECT * FROM picks WHERE run_id=? ORDER BY rank",
                conn,
                params=(row["run_id"],),
            )

    def last_sync_time(self, source: str | None = None) -> str | None:
        query = (
            "SELECT finished_at FROM sync_log WHERE status='ok'"
        )
        params: tuple[Any, ...] = ()
        if source:
            query += " AND source=?"
            params = (source,)
        query += " ORDER BY id DESC LIMIT 1"
        with self._conn() as conn:
            row = conn.execute(query, params).fetchone()
        return row["finished_at"] if row else None

    def save_job(
        self,
        job_id: str,
        status: str,
        message: str = "",
        result: str | None = None,
        error: str | None = None,
        created_at: str | None = None,
        finished_at: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO jobs (id, status, message, result, error, created_at, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    message=excluded.message,
                    result=excluded.result,
                    error=excluded.error,
                    finished_at=excluded.finished_at
                """,
                (
                    job_id,
                    status,
                    message,
                    result,
                    error,
                    created_at or now,
                    finished_at,
                ),
            )

    def load_job(self, job_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            return None
        return dict(row)
