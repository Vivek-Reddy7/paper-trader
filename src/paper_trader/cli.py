"""Command line entry point.

Two commands:

    ingest    fetch bars from the data source into the local store
    backtest  run a strategy over stored bars and print a report

Ingest and backtest are separate on purpose. Fetching is slow, rate
limited and can fail; backtesting should be fast and repeatable. Keeping
them apart means you can iterate on a strategy a hundred times without
hitting the network once.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime

from paper_trader.backtest import engine
from paper_trader.datasource.yfinance_source import YFinanceSource
from paper_trader.storage.store import BarStore
from paper_trader.strategy.sma_crossover import SmaCrossover


def parse_day(text: str) -> date:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {text!r}") from None


def cmd_ingest(args: argparse.Namespace) -> int:
    store = BarStore(args.db)
    source = YFinanceSource()

    for symbol in args.symbols:
        bars = source.fetch(symbol, args.start, args.end)
        if not bars:
            print(f"{symbol}: no bars returned for {args.start} to {args.end}")
            continue

        written = store.upsert(bars)
        gaps = store.missing_weekdays(symbol, bars[0].day, bars[-1].day)

        print(f"{symbol}: {written} bars, {bars[0].day} to {bars[-1].day}, total stored {store.count(symbol)}")
        if gaps:
            # Weekday gaps are usually exchange holidays, so this is
            # information rather than an error.
            shown = ", ".join(d.isoformat() for d in gaps[:5])
            more = f" (+{len(gaps) - 5} more)" if len(gaps) > 5 else ""
            print(f"  {len(gaps)} weekday(s) with no bar: {shown}{more}")

    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    store = BarStore(args.db)
    bars = store.load(args.symbol, args.start, args.end)

    if not bars:
        print(f"no stored bars for {args.symbol} in {args.start}..{args.end}", file=sys.stderr)
        print("run `ingest` first", file=sys.stderr)
        return 1

    strategy = SmaCrossover(fast=args.fast, slow=args.slow)
    result = engine.run(bars, strategy, starting_cash=args.cash)

    print(f"strategy      {result.strategy}")
    print(f"symbol        {result.symbol}")
    print(f"period        {bars[0].day} to {bars[-1].day} ({len(bars)} bars)")
    print(f"starting cash {result.starting_cash:>12,.2f}")
    print(f"final value   {result.final_value:>12,.2f}")
    print(f"total return  {result.total_return_pct:>11.2f}%")
    print(f"max drawdown  {result.max_drawdown_pct:>11.2f}%")
    print(f"trades        {result.n_trades}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="paper-trader", description=__doc__)
    parser.add_argument("--db", default="market.db", help="SQLite path (default: market.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    ing = sub.add_parser("ingest", help="fetch bars into the local store")
    ing.add_argument("symbols", nargs="+", help="e.g. AAPL MSFT, or RELIANCE.NS for NSE")
    ing.add_argument("--start", type=parse_day, required=True)
    ing.add_argument("--end", type=parse_day, required=True)
    ing.set_defaults(func=cmd_ingest)

    bt = sub.add_parser("backtest", help="run a strategy over stored bars")
    bt.add_argument("symbol")
    bt.add_argument("--start", type=parse_day, required=True)
    bt.add_argument("--end", type=parse_day, required=True)
    bt.add_argument("--fast", type=int, default=20)
    bt.add_argument("--slow", type=int, default=50)
    bt.add_argument("--cash", type=float, default=100_000.0)
    bt.set_defaults(func=cmd_backtest)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
