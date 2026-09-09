"""Data source interface.

Everything that fetches market data implements this. The point of the
interface is that the rest of the system never knows or cares where bars
came from, so swapping yfinance for a broker API (Zerodha Kite, Upstox)
means writing one new class and changing one line in the CLI.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Bar:
    """One daily OHLCV bar for one symbol.

    Frozen because a bar is a historical fact. Nothing downstream should
    be able to mutate it.
    """

    symbol: str
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: int

    def __post_init__(self) -> None:
        # Cheap sanity checks. Bad data from an upstream API is the normal
        # case, not the exceptional one, so it gets rejected at the boundary
        # rather than corrupting the store.
        if self.high < self.low:
            raise ValueError(f"{self.symbol} {self.day}: high {self.high} < low {self.low}")
        if not (self.low <= self.open <= self.high):
            raise ValueError(f"{self.symbol} {self.day}: open {self.open} outside [{self.low}, {self.high}]")
        if not (self.low <= self.close <= self.high):
            raise ValueError(f"{self.symbol} {self.day}: close {self.close} outside [{self.low}, {self.high}]")
        if self.volume < 0:
            raise ValueError(f"{self.symbol} {self.day}: negative volume {self.volume}")


class DataSource(ABC):
    """Fetches daily bars for a symbol over a date range."""

    @abstractmethod
    def fetch(self, symbol: str, start: date, end: date) -> list[Bar]:
        """Return bars for `symbol` between `start` and `end` inclusive.

        Implementations must:
          - return bars sorted ascending by day
          - skip (not fabricate) non-trading days
          - raise on transport or auth failure rather than returning []
        """
        raise NotImplementedError
