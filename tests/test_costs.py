"""Transaction cost tests, written before the implementation.

The headline test is test_round_trip_at_same_price_loses_money. Without
costs, buying and selling at an identical price is free and nets zero,
which is the assumption that made every earlier backtest optimistic. It
should cost money, and the amount should be predictable.

Costs are modelled two ways because real trading has both:

  commission  a percentage of notional, per side. Brokerage.
  slippage    the gap between the price you saw and the price you got.
              Modelled as a percentage that always works against you:
              buys fill higher, sells fill lower.
"""

from datetime import date, timedelta

import pytest

from paper_trader.backtest import engine
from paper_trader.costs import CostModel
from paper_trader.datasource.base import Bar
from paper_trader.portfolio import Portfolio
from paper_trader.strategy.base import Signal, Strategy


# ------------------------------------------------------------- cost model

def test_zero_cost_model_is_free():
    free = CostModel()
    assert free.commission_on(10, 100.0) == 0.0
    assert free.fill_price("BUY", 100.0) == 100.0
    assert free.fill_price("SELL", 100.0) == 100.0


def test_commission_is_percentage_of_notional():
    # 0.03% per side, which is roughly Indian discount-broker territory
    model = CostModel(commission_pct=0.03)
    assert model.commission_on(10, 1_000.0) == pytest.approx(3.0)


def test_slippage_always_works_against_you():
    model = CostModel(slippage_pct=0.1)
    assert model.fill_price("BUY", 100.0) == pytest.approx(100.1)
    assert model.fill_price("SELL", 100.0) == pytest.approx(99.9)


def test_negative_costs_are_rejected():
    with pytest.raises(ValueError):
        CostModel(commission_pct=-1)
    with pytest.raises(ValueError):
        CostModel(slippage_pct=-1)


# --------------------------------------------------------------- portfolio

def test_commission_is_deducted_on_buy():
    p = Portfolio(starting_cash=10_000.0, costs=CostModel(commission_pct=1.0))
    p.buy(date(2026, 1, 5), "TEST", 10, 100.0)

    # 1,000 of stock plus 1% commission = 10
    assert p.cash == pytest.approx(10_000.0 - 1_000.0 - 10.0)
    p.reconcile()


def test_commission_is_deducted_on_sell():
    p = Portfolio(starting_cash=10_000.0, costs=CostModel(commission_pct=1.0))
    p.buy(date(2026, 1, 5), "TEST", 10, 100.0)
    p.sell(date(2026, 1, 6), "TEST", 10, 100.0)

    # Two 10.00 commissions on a flat round trip
    assert p.cash == pytest.approx(10_000.0 - 20.0)
    p.reconcile()


def test_round_trip_at_same_price_loses_money():
    """The whole point. Free trading is what flattered the old results."""
    p = Portfolio(starting_cash=10_000.0, costs=CostModel(commission_pct=0.5))
    p.buy(date(2026, 1, 5), "TEST", 10, 100.0)
    p.sell(date(2026, 1, 6), "TEST", 10, 100.0)

    assert p.cash < 10_000.0
    p.reconcile()


def test_reconcile_still_balances_with_costs():
    """Costs must be in the fill log, not applied out of band.

    If commission is subtracted from cash without being recorded, the
    ledger check would fail -- which is exactly what it's for.
    """
    p = Portfolio(starting_cash=10_000.0, costs=CostModel(commission_pct=0.3))
    p.buy(date(2026, 1, 5), "TEST", 10, 100.0)
    p.sell(date(2026, 1, 6), "TEST", 5, 110.0)
    p.buy(date(2026, 1, 7), "TEST", 3, 105.0)

    p.reconcile()  # must not raise


def test_buy_affordability_accounts_for_commission():
    """Cash must cover the commission too, not just the notional."""
    p = Portfolio(starting_cash=1_000.0, costs=CostModel(commission_pct=1.0))
    # 10 x 100 = 1,000 exactly, plus 10 commission -> unaffordable
    with pytest.raises(ValueError, match="insufficient cash"):
        p.buy(date(2026, 1, 5), "TEST", 10, 100.0)


# ---------------------------------------------------------------- backtest

class BuyThenSell(Strategy):
    """Buys on bar 0, sells on bar 2. Test double."""

    @property
    def name(self) -> str:
        return "buy_then_sell"

    def on_bar(self, history: list[Bar]) -> Signal:
        i = len(history) - 1
        if i == 0:
            return Signal.BUY
        if i == 2:
            return Signal.SELL
        return Signal.HOLD


def flat_series(n: int, price: float = 100.0) -> list[Bar]:
    start = date(2026, 1, 1)
    return [
        Bar(symbol="TEST", day=start + timedelta(days=i), open=price,
            high=price + 1, low=price - 1, close=price, volume=1_000)
        for i in range(n)
    ]


def test_backtest_without_costs_breaks_even_on_flat_prices():
    bars = flat_series(5)
    result = engine.run(bars, BuyThenSell(), starting_cash=10_000.0)

    assert result.total_return_pct == pytest.approx(0.0)


def test_backtest_with_costs_loses_on_flat_prices():
    bars = flat_series(5)
    result = engine.run(
        bars, BuyThenSell(), starting_cash=10_000.0,
        costs=CostModel(commission_pct=0.5),
    )

    assert result.total_return_pct < 0.0


def test_slippage_alone_loses_on_flat_prices():
    bars = flat_series(5)
    result = engine.run(
        bars, BuyThenSell(), starting_cash=10_000.0,
        costs=CostModel(slippage_pct=0.2),
    )

    assert result.total_return_pct < 0.0


def test_more_trades_cost_more():
    """A strategy that trades often should be punished harder by costs."""

    class Churn(Strategy):
        @property
        def name(self) -> str:
            return "churn"

        def on_bar(self, history: list[Bar]) -> Signal:
            # Alternate buy/sell every bar.
            return Signal.BUY if len(history) % 2 == 1 else Signal.SELL

    bars = flat_series(20)
    costs = CostModel(commission_pct=0.5)

    churn = engine.run(bars, Churn(), starting_cash=10_000.0, costs=costs)
    patient = engine.run(bars, BuyThenSell(), starting_cash=10_000.0, costs=costs)

    assert churn.n_trades > patient.n_trades
    assert churn.final_value < patient.final_value
