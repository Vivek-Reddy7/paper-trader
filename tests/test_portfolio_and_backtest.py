"""Portfolio accounting and backtest correctness.

The two tests that matter most:

  test_fills_at_next_open_not_current_close -- guards against the most
  common way a backtest lies, which is acting on a price you couldn't
  have traded at.

  test_reconcile_catches_tampering -- proves the ledger check works, so
  it's worth something when the engine calls it.
"""

from datetime import date, timedelta

import pytest

from paper_trader.backtest import engine
from paper_trader.datasource.base import Bar
from paper_trader.portfolio import Portfolio, ReconciliationError
from paper_trader.strategy.base import Signal, Strategy


# ---------------------------------------------------------------- portfolio

def test_buy_reduces_cash_and_adds_position():
    p = Portfolio(starting_cash=1_000.0)
    p.buy(date(2026, 1, 5), "TEST", 10, 50.0)

    assert p.cash == 500.0
    assert p.positions == {"TEST": 10}
    p.reconcile()


def test_sell_restores_cash_and_clears_position():
    p = Portfolio(starting_cash=1_000.0)
    p.buy(date(2026, 1, 5), "TEST", 10, 50.0)
    p.sell(date(2026, 1, 6), "TEST", 10, 60.0)

    assert p.cash == 1_100.0
    assert p.positions == {}
    p.reconcile()


def test_cannot_overspend():
    p = Portfolio(starting_cash=100.0)
    with pytest.raises(ValueError, match="insufficient cash"):
        p.buy(date(2026, 1, 5), "TEST", 10, 50.0)


def test_cannot_sell_what_is_not_held():
    p = Portfolio(starting_cash=1_000.0)
    with pytest.raises(ValueError, match="cannot sell"):
        p.sell(date(2026, 1, 5), "TEST", 1, 50.0)


def test_market_value_includes_open_position():
    p = Portfolio(starting_cash=1_000.0)
    p.buy(date(2026, 1, 5), "TEST", 10, 50.0)

    assert p.market_value({"TEST": 70.0}) == 500.0 + 700.0


def test_reconcile_catches_tampering():
    """If cash drifts from the fill log, reconcile must notice."""
    p = Portfolio(starting_cash=1_000.0)
    p.buy(date(2026, 1, 5), "TEST", 10, 50.0)
    p.reconcile()  # clean

    p.cash += 1.0  # simulate an accounting bug
    with pytest.raises(ReconciliationError, match="cash mismatch"):
        p.reconcile()


def test_reconcile_catches_position_drift():
    p = Portfolio(starting_cash=1_000.0)
    p.buy(date(2026, 1, 5), "TEST", 10, 50.0)

    p.positions["TEST"] = 99  # simulate a bug
    with pytest.raises(ReconciliationError, match="position mismatch"):
        p.reconcile()


# ---------------------------------------------------------------- backtest

class BuyOnBar(Strategy):
    """Signals BUY once, on a chosen bar index. Test double."""

    def __init__(self, at_index: int) -> None:
        self.at_index = at_index

    @property
    def name(self) -> str:
        return "buy_on_bar"

    def on_bar(self, history: list[Bar]) -> Signal:
        return Signal.BUY if len(history) - 1 == self.at_index else Signal.HOLD


def series(prices: list[tuple[float, float]]) -> list[Bar]:
    """Build bars from (open, close) pairs, one per consecutive day."""
    start = date(2026, 1, 1)
    out = []
    for i, (o, c) in enumerate(prices):
        hi, lo = max(o, c) + 1, min(o, c) - 1
        out.append(
            Bar(symbol="TEST", day=start + timedelta(days=i), open=o, high=hi, low=lo, close=c, volume=1_000)
        )
    return out


def test_fills_at_next_open_not_current_close():
    """A signal on bar 0 must fill at bar 1's open.

    Bar 0 closes at 100, bar 1 opens at 200. Filling at the close would
    buy at 100 and report a profit that was never available.
    """
    bars = series([(100.0, 100.0), (200.0, 200.0)])
    result = engine.run(bars, BuyOnBar(at_index=0), starting_cash=1_000.0)

    # 1000 // 200 = 5 shares at 200, not 10 shares at 100.
    assert result.n_trades == 1
    fill_prices = {200.0}
    assert result.final_value == pytest.approx(5 * 200.0 + (1_000.0 - 5 * 200.0))
    assert fill_prices  # documents intent


def test_signal_on_final_bar_never_fills():
    """Nothing can execute after the last bar, so it must not be counted."""
    bars = series([(100.0, 100.0), (100.0, 100.0)])
    result = engine.run(bars, BuyOnBar(at_index=1), starting_cash=1_000.0)

    assert result.n_trades == 0
    assert result.final_value == 1_000.0


def test_equity_curve_has_one_point_per_bar():
    bars = series([(100.0, 100.0)] * 5)
    result = engine.run(bars, BuyOnBar(at_index=99), starting_cash=1_000.0)

    assert len(result.equity_curve) == 5


def test_total_return_pct():
    bars = series([(100.0, 100.0), (100.0, 200.0)])
    result = engine.run(bars, BuyOnBar(at_index=0), starting_cash=1_000.0)

    # Buys 10 at 100 on bar 1's open, bar 1 closes at 200 -> 2000.
    assert result.total_return_pct == pytest.approx(100.0)


def test_max_drawdown_is_negative_or_zero():
    bars = series([(100.0, 100.0), (100.0, 50.0), (50.0, 100.0)])
    result = engine.run(bars, BuyOnBar(at_index=0), starting_cash=1_000.0)

    assert result.max_drawdown_pct <= 0.0


def test_rejects_empty_bars():
    with pytest.raises(ValueError, match="no bars"):
        engine.run([], BuyOnBar(at_index=0))


def test_rejects_mixed_symbols():
    bars = series([(100.0, 100.0), (100.0, 100.0)])
    mixed = [bars[0], Bar(symbol="OTHER", day=bars[1].day, open=1, high=2, low=0.5, close=1, volume=1)]
    with pytest.raises(ValueError, match="one symbol"):
        engine.run(mixed, BuyOnBar(at_index=0))
