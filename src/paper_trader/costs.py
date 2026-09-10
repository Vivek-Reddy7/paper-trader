"""Transaction costs.

Until this existed, every backtest in this project assumed trading was
free. That assumption is what made the results look good: a strategy that
trades 29 times and returns -9.99% before costs is considerably worse
after them, and the ranking between strategies changes once you charge
for turnover.

Two components, because real trading has both:

  commission  brokerage, as a percentage of notional, charged per side.
  slippage    the difference between the price you saw and the price you
              got. Modelled as a percentage that always moves against
              you: buys fill higher, sells fill lower. Real slippage is
              random, but a fixed adverse assumption is the honest
              default -- a random one averages out and lets you pretend
              it doesn't matter.

Defaults are zero so existing behaviour is unchanged unless you ask for
costs. That keeps the "before and after" comparison available rather than
silently rewriting history.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Commission and slippage, both as percentages.

    Indian discount brokers charge roughly 0.03% or a flat fee per order,
    whichever is lower, plus statutory charges. 0.05% total per side is a
    reasonable rough figure for equity delivery; intraday differs. This
    model deliberately doesn't try to reproduce a specific broker's fee
    schedule -- it exists to stop the backtest assuming zero.
    """

    commission_pct: float = 0.0
    slippage_pct: float = 0.0

    def __post_init__(self) -> None:
        if self.commission_pct < 0:
            raise ValueError(f"commission_pct cannot be negative: {self.commission_pct}")
        if self.slippage_pct < 0:
            raise ValueError(f"slippage_pct cannot be negative: {self.slippage_pct}")

    @property
    def is_free(self) -> bool:
        return self.commission_pct == 0.0 and self.slippage_pct == 0.0

    def commission_on(self, qty: int, price: float) -> float:
        """Brokerage for one side of a trade."""
        return qty * price * self.commission_pct / 100.0

    def fill_price(self, side: str, quoted: float) -> float:
        """The price actually paid or received, after slippage.

        Slippage always hurts: you buy above the quote and sell below it.
        """
        drift = quoted * self.slippage_pct / 100.0
        if side == "BUY":
            return quoted + drift
        if side == "SELL":
            return quoted - drift
        raise ValueError(f"unknown side {side!r}")


FREE = CostModel()
"""Zero-cost model. Explicit name for the old default."""
