"""Backtest engine.

Walks bars forward one at a time, asks the strategy for a signal, and
fills any resulting order at the NEXT bar's open. The strategy never sees
a bar it could not have seen at decision time.

Position sizing in v1 is all-in / all-out on a single symbol. That keeps
the accounting easy to verify by hand, which matters more than realism
while the pipeline is being built.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from paper_trader.costs import FREE, CostModel
from paper_trader.datasource.base import Bar
from paper_trader.portfolio import Fill, Portfolio
from paper_trader.strategy.base import Signal, Strategy


@dataclass
class EquityPoint:
    day: date
    value: float


@dataclass
class BacktestResult:
    strategy: str
    symbol: str
    starting_cash: float
    final_value: float
    equity_curve: list[EquityPoint]
    n_trades: int
    fills: list[Fill] = field(default_factory=list)
    bars: list[Bar] = field(default_factory=list)
    total_commission: float = 0.0

    @property
    def buy_and_hold_value(self) -> float:
        """What you'd have by simply buying on day one and holding.

        The only comparison that matters. A strategy that returns 25% in a
        market that returned 40% lost you money in the way that counts.
        """
        if not self.bars:
            return self.starting_cash
        qty = int(self.starting_cash // self.bars[0].open)
        leftover = self.starting_cash - qty * self.bars[0].open
        return qty * self.bars[-1].close + leftover

    @property
    def buy_and_hold_return_pct(self) -> float:
        return (self.buy_and_hold_value / self.starting_cash - 1.0) * 100.0

    @property
    def total_return_pct(self) -> float:
        return (self.final_value / self.starting_cash - 1.0) * 100.0

    @property
    def max_drawdown_pct(self) -> float:
        """Largest peak-to-trough fall in portfolio value, as a percentage."""
        peak = float("-inf")
        worst = 0.0
        for point in self.equity_curve:
            peak = max(peak, point.value)
            if peak > 0:
                drawdown = (point.value / peak - 1.0) * 100.0
                worst = min(worst, drawdown)
        return worst


def run(
    bars: list[Bar],
    strategy: Strategy,
    starting_cash: float = 100_000.0,
    costs: CostModel = FREE,
) -> BacktestResult:
    if not bars:
        raise ValueError("no bars to backtest")

    symbol = bars[0].symbol
    if any(b.symbol != symbol for b in bars):
        raise ValueError("run() handles one symbol at a time")

    portfolio = Portfolio(starting_cash=starting_cash, costs=costs)
    equity: list[EquityPoint] = []
    pending: Signal | None = None

    for i, bar in enumerate(bars):
        # Execute whatever last bar's signal asked for, at today's open.
        if pending is Signal.BUY and not portfolio.positions:
            qty = portfolio.max_affordable(bar.open)
            if qty > 0:
                portfolio.buy(bar.day, symbol, qty, bar.open)
        elif pending is Signal.SELL and portfolio.positions.get(symbol, 0) > 0:
            portfolio.sell(bar.day, symbol, portfolio.positions[symbol], bar.open)
        pending = None

        # Now decide, using history only up to and including today.
        signal = strategy.on_bar(bars[: i + 1])
        if signal is not Signal.HOLD:
            pending = signal

        equity.append(EquityPoint(day=bar.day, value=portfolio.market_value({symbol: bar.close})))

    # Catches accounting bugs before they reach the report.
    portfolio.reconcile()

    return BacktestResult(
        strategy=strategy.name,
        symbol=symbol,
        starting_cash=starting_cash,
        final_value=equity[-1].value,
        equity_curve=equity,
        n_trades=len(portfolio.fills),
        fills=list(portfolio.fills),
        bars=list(bars),
        total_commission=portfolio.total_commission,
    )
