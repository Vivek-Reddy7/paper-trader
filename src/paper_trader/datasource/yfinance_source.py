"""yfinance-backed data source.

Free, no API key, no account. Good enough to build against and easy to
replace: implement DataSource with a broker client (Zerodha Kite, Upstox)
and nothing downstream changes.

Everything upstream gets validated on the way in. yfinance returns a
pandas DataFrame whose exact column shape varies with version and with
whether one or many symbols were requested, so this module's job is to
normalise that mess into Bar objects and reject anything malformed.
"""

from __future__ import annotations

from datetime import date, timedelta

from paper_trader.datasource.base import Bar, DataSource


class YFinanceSource(DataSource):
    def fetch(self, symbol: str, start: date, end: date) -> list[Bar]:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "yfinance is not installed. Run: pip install -r requirements.txt"
            ) from exc

        # yfinance treats `end` as exclusive; we want inclusive.
        frame = yf.download(
            symbol,
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            progress=False,
            auto_adjust=False,
        )

        if frame is None or frame.empty:
            return []

        # With a single ticker yfinance may still return MultiIndex columns
        # depending on version. Flatten to the first level either way.
        if hasattr(frame.columns, "nlevels") and frame.columns.nlevels > 1:
            frame.columns = frame.columns.get_level_values(0)

        required = {"Open", "High", "Low", "Close", "Volume"}
        missing = required - set(frame.columns)
        if missing:
            raise RuntimeError(f"{symbol}: yfinance response missing columns {sorted(missing)}")

        bars: list[Bar] = []
        for index, row in frame.iterrows():
            # A row with any NaN in the OHLCV fields is unusable. Skipping
            # is right; imputing a price would invent data.
            values = [row["Open"], row["High"], row["Low"], row["Close"], row["Volume"]]
            if any(v != v for v in values):  # NaN != NaN
                continue

            bars.append(
                Bar(
                    symbol=symbol,
                    day=index.date() if hasattr(index, "date") else date.fromisoformat(str(index)[:10]),
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    volume=int(row["Volume"]),
                )
            )

        bars.sort(key=lambda b: b.day)
        return bars
