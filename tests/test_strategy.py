"""Strategy tests.

Hand-built price series so the expected signal is verifiable on paper.
That is the reason for picking a strategy this simple: if the test needs
a spreadsheet to justify, the test isn't testing the code any more.
"""

from datetime import date, timedelta

import pytest

from paper_trader.datasource.base import Bar
from paper_trader.strategy.base import Signal
from paper_trader.strategy.sma_crossover import SmaCrossover, sma


def series(closes: list[float], symbol: str = "TEST") -> list[Bar]:
    """Build bars from a list of closes, one per consecutive day."""
    start = date(2026, 1, 1)
    return [
        Bar(
            symbol=symbol,
            day=start + timedelta(days=i),
            open=c,
            high=c + 1,
            low=c - 1,
            close=c,
            volume=1_000,
        )
        for i, c in enumerate(closes)
    ]


def test_sma_averages_last_n():
    assert sma([1, 2, 3, 4, 5], 5) == 3.0
    assert sma([1, 2, 3, 4, 5], 2) == 4.5


def test_sma_returns_none_when_history_too_short():
    assert sma([1, 2], 5) is None


def test_sma_rejects_non_positive_window():
    with pytest.raises(ValueError):
        sma([1, 2, 3], 0)


def test_fast_must_be_below_slow():
    with pytest.raises(ValueError, match="fast"):
        SmaCrossover(fast=50, slow=20)


def test_holds_until_enough_history():
    strat = SmaCrossover(fast=2, slow=3)
    # Needs slow + 1 = 4 bars before it will commit to anything.
    for n in range(1, 4):
        assert strat.on_bar(series([10.0] * n)) is Signal.HOLD


def test_buys_on_upward_cross():
    strat = SmaCrossover(fast=2, slow=3)
    # Flat, then a jump that drags the fast average above the slow one.
    bars = series([10.0, 10.0, 10.0, 20.0])
    assert strat.on_bar(bars) is Signal.BUY


def test_sells_on_downward_cross():
    strat = SmaCrossover(fast=2, slow=3)
    # Rising, then a collapse that drags fast back below slow.
    bars = series([10.0, 20.0, 30.0, 1.0])
    assert strat.on_bar(bars) is Signal.SELL


def test_no_repeat_signal_while_trend_persists():
    """The signal must fire on the crossing bar only, not every bar after.

    Otherwise the backtester receives a BUY it has already acted on, every
    single day the trend holds.
    """
    strat = SmaCrossover(fast=2, slow=3)

    crossing = series([10.0, 10.0, 10.0, 20.0])
    assert strat.on_bar(crossing) is Signal.BUY

    # One more bar in the same direction: still above, but no new crossing.
    still_rising = series([10.0, 10.0, 10.0, 20.0, 25.0])
    assert strat.on_bar(still_rising) is Signal.HOLD


def test_flat_market_never_signals():
    strat = SmaCrossover(fast=2, slow=3)
    assert strat.on_bar(series([10.0] * 30)) is Signal.HOLD


def test_strategy_name_encodes_windows():
    assert SmaCrossover(fast=20, slow=50).name == "sma_20_50"
