# paper-trader

A market data pipeline and backtesting engine, in Python. Ingests daily
bars, stores them, runs a strategy over them, and reports what would have
happened.

**Paper only.** It never places a real order and has no broker
credentials anywhere in it. It moves numbers in a SQLite file.

I built this because I wanted to understand the engineering problems
underneath trading systems rather than the trading itself. Most of the
interesting work turned out to have nothing to do with strategies.

## Running it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Fetch some data
python -m paper_trader.cli ingest AAPL --start 2024-01-01 --end 2025-12-31

# Backtest a 20/50 moving average crossover over it
python -m paper_trader.cli backtest AAPL --start 2024-01-01 --end 2025-12-31
```

NSE symbols work too, with the Yahoo suffix: `RELIANCE.NS`, `INFY.NS`.

```bash
PYTHONPATH=src python -m pytest      # 36 tests
```

## How it fits together

```
datasource/  fetch bars from somewhere, validate at the boundary
storage/     SQLite store with idempotent writes and gap detection
strategy/    signal generation, no lookahead
backtest/    walk bars forward, fill orders, track equity
portfolio.py simulated cash and positions, reconciled against a fill log
```

`ingest` and `backtest` are deliberately separate commands. Fetching is
slow, rate limited and fails; backtesting should be instant and
repeatable. Splitting them means I can change a strategy fifty times
without touching the network.

## Three things I got wrong first

**Filling at the wrong price.** My first backtester generated a signal
from a bar's close and filled the order at that same close. That silently
assumes you can trade at a price you only knew at the end of the day, and
it made a mediocre strategy look good. Orders now fill at the *next*
bar's open. There's a test for it, because the bug is invisible in the
output.

**Re-ingesting duplicated bars.** Fetching an overlapping date range
appended rows instead of replacing them, so bars got counted twice and
every downstream number was wrong. The fix is a primary key on
`(symbol, day)` and `INSERT ... ON CONFLICT DO UPDATE`. This is the same
problem as not double-posting a payment, which I hadn't expected to run
into in a hobby project.

**Trusting the upstream data.** yfinance returns NaN rows, and its column
shape changes between versions and between single and multi-symbol
requests. Bars are now validated where they enter the system: high can't
be below low, close has to sit inside the day's range, volume can't be
negative. Bad rows are skipped rather than imputed, because inventing a
price is worse than having a gap.

## Reconciliation

Cash and positions are derived state. The fill log is the source of
truth. `Portfolio.reconcile()` recomputes both from the log and raises if
they disagree, and the backtest engine calls it before producing a
report.

I added it after a bug where a code path updated cash but not the
position. The numbers looked plausible, which was the problem.

## Built with

Written with **Claude Code** and **Cursor**, plus **GitHub Copilot** for
inline completion.

The division of labour that worked: I used the models heavily for
structure, boilerplate and test scaffolding, and did the thinking myself
on the parts where being wrong is invisible. The next-open fill rule, the
idempotency requirement and the reconciliation check are all mine, and
all three are places where a model happily generated code that ran fine
and was subtly incorrect.

That's roughly my working rule now: fast on the parts where being wrong
is loud, slow and manual on the parts where being wrong is quiet.

## Not done yet

- Exchange calendar, so holiday gaps stop being reported as suspicious
- Transaction costs and slippage, currently assumed zero
- Position sizing beyond all-in / all-out on one symbol
- A broker data source behind the same `DataSource` interface
- Sharpe and per-trade statistics in the report
