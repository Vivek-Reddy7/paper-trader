"""Self-contained HTML backtest report.

One file, no server, no external assets. The chart is embedded as a
base64 data URI so the report can be emailed, committed, or opened from
anywhere without breaking.

The trade table is the reason this exists. The summary metrics tell you a
strategy returned 24.53%; the trade table tells you whether that came
from nine decent trades or two lucky ones and seven losers. That second
question is the one worth answering, and it's the one the CLI output
can't show.
"""

from __future__ import annotations

import base64
import html
import io
from dataclasses import dataclass
from pathlib import Path

from paper_trader.backtest.engine import BacktestResult
from paper_trader.portfolio import Fill


@dataclass
class RoundTrip:
    """A completed buy-then-sell pair.

    P&L is only knowable once a position is closed, so an open position at
    the end of the backtest is deliberately excluded from win-rate maths
    rather than marked to market and counted as a win.
    """

    entry: Fill
    exit: Fill

    @property
    def pnl(self) -> float:
        return (self.exit.price - self.entry.price) * self.entry.qty

    @property
    def pnl_pct(self) -> float:
        return (self.exit.price / self.entry.price - 1.0) * 100.0

    @property
    def held_days(self) -> int:
        return (self.exit.day - self.entry.day).days

    @property
    def won(self) -> bool:
        return self.pnl > 0


def pair_round_trips(fills: list[Fill]) -> tuple[list[RoundTrip], Fill | None]:
    """Pair BUY fills with the SELL that closed them.

    Returns the closed round trips plus any still-open entry. v1 is
    all-in / all-out on one symbol, so pairing is strictly sequential.
    """
    trips: list[RoundTrip] = []
    open_entry: Fill | None = None

    for fill in fills:
        if fill.side == "BUY":
            open_entry = fill
        elif fill.side == "SELL" and open_entry is not None:
            trips.append(RoundTrip(entry=open_entry, exit=fill))
            open_entry = None

    return trips, open_entry


def _chart_data_uri(result: BacktestResult) -> str:
    """Render the chart to an in-memory PNG and return it as a data URI."""
    from paper_trader.backtest import plot

    buffer = io.BytesIO()
    plot.render_to_buffer(result, buffer)
    buffer.seek(0)
    return "data:image/png;base64," + base64.b64encode(buffer.read()).decode("ascii")


CSS = """
:root {
  --ink:#1b1f23; --soft:#57606a; --faint:#8b949e;
  --rule:#e1e4e8; --surface:#ffffff; --ground:#fafbfc;
  --win:#1a7f4b; --loss:#b03a3a; --accent:#1f5459;
}
* { box-sizing:border-box; }
body {
  margin:0; padding:40px 24px 80px;
  background:var(--ground); color:var(--ink);
  font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
}
.wrap { max-width:1000px; margin:0 auto; }
h1 { font-size:26px; margin:0 0 4px; letter-spacing:-.01em; }
.sub { color:var(--soft); font-size:14px; margin:0 0 28px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:1px; background:var(--rule); border:1px solid var(--rule); margin-bottom:28px; }
.card { background:var(--surface); padding:14px 16px; }
.card .label { font-size:11px; letter-spacing:.08em; text-transform:uppercase; color:var(--faint); }
.card .value { font-size:22px; font-weight:600; margin-top:4px; font-variant-numeric:tabular-nums; }
.pos { color:var(--win); } .neg { color:var(--loss); }
h2 { font-size:17px; margin:34px 0 12px; }
.chart { border:1px solid var(--rule); background:var(--surface); padding:10px; }
.chart img { display:block; width:100%; height:auto; }
.scroll { overflow-x:auto; border:1px solid var(--rule); background:var(--surface); }
table { border-collapse:collapse; width:100%; font-size:14px; }
th { text-align:left; font-size:11px; letter-spacing:.07em; text-transform:uppercase;
     color:var(--faint); padding:10px 14px; border-bottom:1px solid var(--rule); white-space:nowrap; }
td { padding:9px 14px; border-bottom:1px solid var(--rule); font-variant-numeric:tabular-nums; }
tr:last-child td { border-bottom:none; }
td.num, th.num { text-align:right; }
.note { color:var(--soft); font-size:14px; margin:10px 0 0; max-width:70ch; }
.open { background:#fff9e6; }
"""


def render(result: BacktestResult, out_path: str | Path) -> Path:
    trips, open_entry = pair_round_trips(result.fills)
    wins = [t for t in trips if t.won]
    win_rate = (len(wins) / len(trips) * 100.0) if trips else 0.0
    beat_market = result.total_return_pct - result.buy_and_hold_return_pct

    def signed(value: float, suffix: str = "%") -> str:
        cls = "pos" if value > 0 else ("neg" if value < 0 else "")
        return f'<span class="{cls}">{value:+.2f}{suffix}</span>'

    cards = [
        ("strategy return", signed(result.total_return_pct)),
        ("buy &amp; hold", signed(result.buy_and_hold_return_pct)),
        ("vs market", signed(beat_market, "pp")),
        ("max drawdown", f'<span class="neg">{result.max_drawdown_pct:.2f}%</span>'),
        ("round trips", str(len(trips))),
        ("win rate", f"{win_rate:.0f}%" if trips else "n/a"),
        ("final value", f"{result.final_value:,.0f}"),
    ]

    card_html = "\n".join(
        f'<div class="card"><div class="label">{label}</div><div class="value">{value}</div></div>'
        for label, value in cards
    )

    rows = []
    for i, t in enumerate(trips, 1):
        cls = "pos" if t.won else "neg"
        rows.append(
            f"<tr><td>{i}</td>"
            f"<td>{t.entry.day}</td><td class='num'>{t.entry.price:,.2f}</td>"
            f"<td>{t.exit.day}</td><td class='num'>{t.exit.price:,.2f}</td>"
            f"<td class='num'>{t.entry.qty:,}</td>"
            f"<td class='num'>{t.held_days}</td>"
            f"<td class='num {cls}'>{t.pnl:+,.0f}</td>"
            f"<td class='num {cls}'>{t.pnl_pct:+.2f}%</td></tr>"
        )

    if open_entry is not None:
        last_close = result.bars[-1].close
        unrealised = (last_close - open_entry.price) * open_entry.qty
        cls = "pos" if unrealised > 0 else "neg"
        rows.append(
            f"<tr class='open'><td>{len(trips) + 1}</td>"
            f"<td>{open_entry.day}</td><td class='num'>{open_entry.price:,.2f}</td>"
            f"<td colspan='2'>still open</td>"
            f"<td class='num'>{open_entry.qty:,}</td><td class='num'>&mdash;</td>"
            f"<td class='num {cls}'>{unrealised:+,.0f}</td>"
            f"<td class='num {cls}'>unrealised</td></tr>"
        )

    table_html = "\n".join(rows) or "<tr><td colspan='9'>no trades</td></tr>"

    period = f"{result.bars[0].day} to {result.bars[-1].day}" if result.bars else "unknown period"
    verdict = (
        f"Beat buy-and-hold by {beat_market:.2f} percentage points."
        if beat_market > 0
        else f"Underperformed buy-and-hold by {abs(beat_market):.2f} percentage points."
    )

    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>{html.escape(result.symbol)} backtest &middot; {html.escape(result.strategy)}</title>
<style>{CSS}</style></head><body><div class="wrap">

<h1>{html.escape(result.symbol)} &middot; {html.escape(result.strategy)}</h1>
<p class="sub">{period} &middot; {len(result.bars)} bars &middot; starting cash {result.starting_cash:,.0f}</p>

<div class="cards">{card_html}</div>

<h2>Equity</h2>
<div class="chart"><img alt="equity curve" src="{_chart_data_uri(result)}"></div>
<p class="note">{verdict} The strategy sits in cash until its first crossover,
so some of any outperformance comes from being absent during a fall rather
than from picking well.</p>

<h2>Round trips</h2>
<div class="scroll"><table>
<thead><tr>
<th>#</th><th>entry</th><th class="num">price</th>
<th>exit</th><th class="num">price</th>
<th class="num">qty</th><th class="num">days</th>
<th class="num">P&amp;L</th><th class="num">return</th>
</tr></thead>
<tbody>{table_html}</tbody>
</table></div>
<p class="note">Win rate counts closed round trips only. An open position at the
end is shown but excluded, because its P&amp;L isn't decided yet and counting
an unrealised gain as a win flatters the number.</p>

<h2>Assumptions that flatter these results</h2>
<p class="note">No brokerage, no slippage, no taxes. Orders fill at the next
bar's open, which is realistic, but at exactly that price with no spread,
which is not. All-in / all-out sizing on a single symbol, so there is no
diversification and no position risk management.</p>

</div></body></html>
"""

    out = Path(out_path)
    out.write_text(doc, encoding="utf-8")
    return out
