"""Paper portfolio.

Simulated cash and one position per symbol. No broker, no real orders,
no real money -- this only ever moves numbers in memory.

Three deliberate choices worth reading:

1. Every fill is appended to `self.fills`, and commission is recorded on
   the fill itself. Position and cash are derived state; the fill log is
   the source of truth. That means position can always be recomputed from
   the log and checked against what we think it is, which is
   `reconcile()`. Same idea as a ledger: trust the entries, derive the
   balance. Charging commission straight to cash without recording it on
   the fill would break that, and reconcile() would catch it.

2. Orders fill at the *next* bar's open, not the current bar's close.
   A signal generated from today's close could not have been acted on
   until tomorrow. Filling at today's close is the most common way a
   backtest lies to you.

3. Slippage is applied inside buy/sell, so the recorded fill price is
   what was actually paid rather than what was quoted. The log should say
   what happened, not what was hoped for.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from paper_trader.costs import FREE, CostModel


@dataclass(frozen=True)
class Fill:
    day: date
    symbol: str
    side: str  # "BUY" or "SELL"
    qty: int
    price: float  # the price actually paid/received, after slippage
    commission: float = 0.0

    @property
    def cash_delta(self) -> float:
        """Net effect on cash, commission included."""
        signed = -1 if self.side == "BUY" else 1
        return signed * self.qty * self.price - self.commission


class ReconciliationError(Exception):
    """Derived state disagrees with the fill log."""


@dataclass
class Portfolio:
    starting_cash: float = 100_000.0
    costs: CostModel = FREE
    cash: float = field(init=False)
    positions: dict[str, int] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = self.starting_cash

    def max_affordable(self, quoted_price: float) -> int:
        """Largest quantity buyable at `quoted_price`, costs included.

        The engine needs this to size a position. Sizing off the raw quote
        and then adding costs is how you end up trying to spend money you
        don't have.
        """
        if quoted_price <= 0:
            raise ValueError(f"price must be positive, got {quoted_price}")

        fill = self.costs.fill_price("BUY", quoted_price)
        # Each unit costs fill + its share of commission.
        per_unit = fill * (1.0 + self.costs.commission_pct / 100.0)
        return int(self.cash // per_unit) if per_unit > 0 else 0

    def buy(self, day: date, symbol: str, qty: int, price: float) -> None:
        """Buy `qty` at the quoted `price`, before slippage and commission."""
        if qty <= 0:
            raise ValueError("qty must be positive")

        fill_price = self.costs.fill_price("BUY", price)
        commission = self.costs.commission_on(qty, fill_price)
        total = qty * fill_price + commission

        if total > self.cash:
            raise ValueError(
                f"insufficient cash: need {total:.2f} "
                f"({qty} x {fill_price:.2f} + {commission:.2f} commission), "
                f"have {self.cash:.2f}"
            )

        fill = Fill(day=day, symbol=symbol, side="BUY", qty=qty,
                    price=fill_price, commission=commission)
        self.fills.append(fill)
        self.cash += fill.cash_delta
        self.positions[symbol] = self.positions.get(symbol, 0) + qty

    def sell(self, day: date, symbol: str, qty: int, price: float) -> None:
        """Sell `qty` at the quoted `price`, before slippage and commission."""
        if qty <= 0:
            raise ValueError("qty must be positive")

        held = self.positions.get(symbol, 0)
        if qty > held:
            # No shorting in v1. Being explicit beats silently going negative.
            raise ValueError(f"cannot sell {qty} of {symbol}, hold {held}")

        fill_price = self.costs.fill_price("SELL", price)
        commission = self.costs.commission_on(qty, fill_price)

        fill = Fill(day=day, symbol=symbol, side="SELL", qty=qty,
                    price=fill_price, commission=commission)
        self.fills.append(fill)
        self.cash += fill.cash_delta
        self.positions[symbol] = held - qty
        if self.positions[symbol] == 0:
            del self.positions[symbol]

    @property
    def total_commission(self) -> float:
        return sum(f.commission for f in self.fills)

    def market_value(self, prices: dict[str, float]) -> float:
        """Total portfolio value at the given prices."""
        held = sum(qty * prices[sym] for sym, qty in self.positions.items())
        return self.cash + held

    def reconcile(self) -> None:
        """Recompute cash and positions from the fill log and compare.

        Raises ReconciliationError on any mismatch. Cheap to run, and it
        catches the class of bug where an accounting path updates one of
        cash/positions and forgets the other, or charges a cost without
        recording it.
        """
        expected_cash = self.starting_cash + sum(f.cash_delta for f in self.fills)
        if abs(expected_cash - self.cash) > 1e-6:
            raise ReconciliationError(
                f"cash mismatch: derived {expected_cash:.6f}, tracked {self.cash:.6f}"
            )

        expected_positions: dict[str, int] = {}
        for f in self.fills:
            delta = f.qty if f.side == "BUY" else -f.qty
            expected_positions[f.symbol] = expected_positions.get(f.symbol, 0) + delta
        expected_positions = {s: q for s, q in expected_positions.items() if q != 0}

        if expected_positions != self.positions:
            raise ReconciliationError(
                f"position mismatch: derived {expected_positions}, tracked {self.positions}"
            )
