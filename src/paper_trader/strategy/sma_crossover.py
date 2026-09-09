"""Moving-average crossover.

Chosen because it is boring and easy to verify by hand. The interesting
engineering in this project is the pipeline around the strategy, not the
strategy itself, and a strategy you can check on paper makes the
backtester's correctness testable.

Rule: buy when the fast SMA crosses above the slow SMA, sell when it
crosses back below. Signal fires only on the crossing bar, not on every
bar where fast > slow, so the backtester isn't handed a buy signal it
already acted on.
"""

from __future__ import annotations

from paper_trader.datasource.base import Bar
from paper_trader.strategy.base import Signal, Strategy


def sma(values: list[float], window: int) -> float | None:
    """Simple moving average of the last `window` values, or None if short."""
    if window <= 0:
        raise ValueError("window must be positive")
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


class SmaCrossover(Strategy):
    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        if fast >= slow:
            raise ValueError(f"fast ({fast}) must be less than slow ({slow})")
        self.fast = fast
        self.slow = slow

    @property
    def name(self) -> str:
        return f"sma_{self.fast}_{self.slow}"

    def on_bar(self, history: list[Bar]) -> Signal:
        # Need one extra bar so we can compare this bar's relationship to
        # the previous bar's and detect a crossing rather than a state.
        if len(history) < self.slow + 1:
            return Signal.HOLD

        closes = [b.close for b in history]

        fast_now = sma(closes, self.fast)
        slow_now = sma(closes, self.slow)
        fast_prev = sma(closes[:-1], self.fast)
        slow_prev = sma(closes[:-1], self.slow)

        if None in (fast_now, slow_now, fast_prev, slow_prev):
            return Signal.HOLD

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        if crossed_up:
            return Signal.BUY
        if crossed_down:
            return Signal.SELL
        return Signal.HOLD
