"""SQLite bar store.

Two things matter here and they are the whole reason this file exists:

1. Writes are idempotent. Re-running an ingest for a range you already
   have must not duplicate or double-count bars. The PRIMARY KEY on
   (symbol, day) plus INSERT ... ON CONFLICT gives us that for free, and
   it is the same problem as not double-posting a payment.

2. Gaps are visible. `missing_days` tells you what a range should have
   had versus what it does have, so a silently short backtest is
   detectable instead of quietly wrong.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from paper_trader.datasource.base import Bar

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars (
    symbol  TEXT    NOT NULL,
    day     TEXT    NOT NULL,          -- ISO date, sorts lexicographically
    open    REAL    NOT NULL,
    high    REAL    NOT NULL,
    low     REAL    NOT NULL,
    close   REAL    NOT NULL,
    volume  INTEGER NOT NULL,
    PRIMARY KEY (symbol, day)
);

CREATE INDEX IF NOT EXISTS idx_bars_symbol_day ON bars (symbol, day);
"""


class BarStore:
    def __init__(self, db_path: str | Path = "market.db") -> None:
        self.db_path = str(db_path)
        with closing(self._connect()) as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, bars: list[Bar]) -> int:
        """Insert or replace bars. Returns the number of rows written.

        Idempotent: calling this twice with the same bars leaves the table
        in the same state as calling it once.
        """
        if not bars:
            return 0
        rows = [
            (b.symbol, b.day.isoformat(), b.open, b.high, b.low, b.close, b.volume)
            for b in bars
        ]
        with closing(self._connect()) as conn:
            conn.executemany(
                """
                INSERT INTO bars (symbol, day, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (symbol, day) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    volume = excluded.volume
                """,
                rows,
            )
            conn.commit()
        return len(rows)

    def load(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Return stored bars for `symbol` in [start, end], ascending by day."""
        with closing(self._connect()) as conn:
            cur = conn.execute(
                """
                SELECT symbol, day, open, high, low, close, volume
                FROM bars
                WHERE symbol = ? AND day BETWEEN ? AND ?
                ORDER BY day ASC
                """,
                (symbol, start.isoformat(), end.isoformat()),
            )
            return [
                Bar(
                    symbol=r["symbol"],
                    day=date.fromisoformat(r["day"]),
                    open=r["open"],
                    high=r["high"],
                    low=r["low"],
                    close=r["close"],
                    volume=r["volume"],
                )
                for r in cur.fetchall()
            ]

    def count(self, symbol: str) -> int:
        with closing(self._connect()) as conn:
            cur = conn.execute("SELECT COUNT(*) AS n FROM bars WHERE symbol = ?", (symbol,))
            return int(cur.fetchone()["n"])

    def missing_weekdays(self, symbol: str, start: date, end: date) -> list[date]:
        """Weekdays in [start, end] with no stored bar.

        Weekday absence is not proof of a data gap -- exchange holidays are
        weekdays too. This is a signal to look, not an error. Filtering real
        holidays needs an exchange calendar, which is a documented extension
        point rather than something to guess at.
        """
        have = {b.day for b in self.load(symbol, start, end)}
        missing: list[date] = []
        cursor = start
        while cursor <= end:
            if cursor.weekday() < 5 and cursor not in have:
                missing.append(cursor)
            cursor += timedelta(days=1)
        return missing
