"""Paper portfolio.

Simulated cash and one position per symbol. No broker, no real orders,
no real money -- this only ever moves numbers in memory.

Two deliberate choices worth reading:

1. Every fill is appended to `self.fills`. Position and cash are derived
   state; the fill log is the source of truth. That means position can
   always be recomputed from the log and checked against what we think it
   is, which is `reconcile()`. Same idea as a ledger: trust the entries,
   derive the balance.

2. Orders fill at the *next* bar's open, not the current bar's close.
   A signal generated from today's close could not have been acted on
   until tomorrow. Filling at today's close is the most common way a
   backtest lies to you.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class Fill:
    day: date
    symbol: str
    side: str  # "BUY" or "SELL"
    qty: int
    price: float

    @property
    def cash_delta(self) -> float:
        signed = -1 if self.side == "BUY" else 1
        return signed * self.qty * self.price


class ReconciliationError(Exception):
    """Derived state disagrees with the fill log."""


@dataclass
class Portfolio:
    starting_cash: float = 100_000.0
    cash: float = field(init=False)
    positions: dict[str, int] = field(default_factory=dict)
    fills: list[Fill] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = self.starting_cash

    def buy(self, day: date, symbol: str, qty: int, price: float) -> None:
        if qty <= 0:
            raise ValueError("qty must be positive")
        cost = qty * price
        if cost > self.cash:
            raise ValueError(f"insufficient cash: need {cost:.2f}, have {self.cash:.2f}")
        fill = Fill(day=day, symbol=symbol, side="BUY", qty=qty, price=price)
        self.fills.append(fill)
        self.cash += fill.cash_delta
        self.positions[symbol] = self.positions.get(symbol, 0) + qty

    def sell(self, day: date, symbol: str, qty: int, price: float) -> None:
        if qty <= 0:
            raise ValueError("qty must be positive")
        held = self.positions.get(symbol, 0)
        if qty > held:
            # No shorting in v1. Being explicit beats silently going negative.
            raise ValueError(f"cannot sell {qty} of {symbol}, hold {held}")
        fill = Fill(day=day, symbol=symbol, side="SELL", qty=qty, price=price)
        self.fills.append(fill)
        self.cash += fill.cash_delta
        self.positions[symbol] = held - qty
        if self.positions[symbol] == 0:
            del self.positions[symbol]

    def market_value(self, prices: dict[str, float]) -> float:
        """Total portfolio value at the given prices."""
        held = sum(qty * prices[sym] for sym, qty in self.positions.items())
        return self.cash + held

    def reconcile(self) -> None:
        """Recompute cash and positions from the fill log and compare.

        Raises ReconciliationError on any mismatch. Cheap to run, and it
        catches the class of bug where an accounting path updates one of
        cash/positions and forgets the other.
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
