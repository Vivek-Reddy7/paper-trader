"""Strategy interface.

A strategy sees bars one at a time, oldest first, and may return a signal.
It is deliberately not allowed to see the future: `on_bar` receives only
the history up to and including the current bar. That constraint is the
whole reason backtests mean anything.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum

from paper_trader.datasource.base import Bar


class Signal(Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class Strategy(ABC):
    """Turns a stream of bars into signals."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier used in reports."""
        raise NotImplementedError

    @abstractmethod
    def on_bar(self, history: list[Bar]) -> Signal:
        """Decide what to do given all bars up to and including the latest.

        `history` is ascending by day; `history[-1]` is the current bar.
        Implementations must not look beyond it.
        """
        raise NotImplementedError
