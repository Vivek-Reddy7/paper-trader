"""Chart a backtest result.

Two panels, because they answer two different questions:

  Top     price, with the actual buy and sell fills marked. Lets you see
          whether the strategy traded where you'd expect it to, which is
          how I found the next-open fill bug in the first place.

  Bottom  strategy equity against buy-and-hold. This is the comparison
          that matters. A strategy returning 25% while the stock returned
          40% did worse than doing nothing, and a single return number
          hides that completely.

Rendered to a file rather than shown interactively, so it works the same
from a terminal, a test, or CI.
"""

from __future__ import annotations

from pathlib import Path

from paper_trader.backtest.engine import BacktestResult


def render(result: BacktestResult, out_path: str | Path) -> Path:
    try:
        import matplotlib
        matplotlib.use("Agg")  # no display needed
        import matplotlib.pyplot as plt
        from matplotlib.ticker import FuncFormatter
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "matplotlib is not installed. Run: pip install -r requirements.txt"
        ) from exc

    if not result.bars:
        raise ValueError("result has no bars to plot")

    days = [b.day for b in result.bars]
    closes = [b.close for b in result.bars]
    equity = [p.value for p in result.equity_curve]

    # Buy-and-hold equity, day by day, on the same starting cash.
    first_open = result.bars[0].open
    bh_qty = int(result.starting_cash // first_open)
    bh_cash = result.starting_cash - bh_qty * first_open
    buy_hold = [bh_qty * c + bh_cash for c in closes]

    fig, (ax_price, ax_eq) = plt.subplots(
        2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [1, 1]}
    )

    ink = "#1f2933"
    grid = "#dfe3e8"

    # ---------------------------------------------------------- price panel
    ax_price.plot(days, closes, color="#52606d", linewidth=1.1, label="close")

    buys = [f for f in result.fills if f.side == "BUY"]
    sells = [f for f in result.fills if f.side == "SELL"]

    if buys:
        ax_price.scatter(
            [f.day for f in buys], [f.price for f in buys],
            marker="^", s=70, color="#2f6f4e", zorder=3,
            label=f"buy ({len(buys)})",
        )
    if sells:
        ax_price.scatter(
            [f.day for f in sells], [f.price for f in sells],
            marker="v", s=70, color="#a03d3d", zorder=3,
            label=f"sell ({len(sells)})",
        )

    ax_price.set_title(
        f"{result.symbol}  ·  {result.strategy}  ·  {days[0]} to {days[-1]}",
        color=ink, fontsize=12, loc="left", pad=12,
    )
    ax_price.set_ylabel("price", color=ink, fontsize=10)
    ax_price.legend(frameon=False, fontsize=9, loc="upper left")

    # -------------------------------------------------------- equity panel
    ax_eq.plot(days, equity, color="#1f5459", linewidth=1.6,
               label=f"strategy  {result.total_return_pct:+.2f}%")
    ax_eq.plot(days, buy_hold, color="#94661f", linewidth=1.2, linestyle="--",
               label=f"buy & hold  {result.buy_and_hold_return_pct:+.2f}%")
    ax_eq.axhline(result.starting_cash, color=grid, linewidth=1, zorder=0)

    ax_eq.set_ylabel("portfolio value", color=ink, fontsize=10)
    ax_eq.legend(frameon=False, fontsize=9, loc="upper left")
    ax_eq.annotate(
        f"max drawdown {result.max_drawdown_pct:.2f}%   ·   {result.n_trades} trades",
        xy=(0.995, 0.04), xycoords="axes fraction", ha="right",
        fontsize=9, color="#7b8794",
    )

    for ax in (ax_price, ax_eq):
        ax.grid(True, color=grid, linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(grid)
        ax.tick_params(colors="#7b8794", labelsize=9)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))

    fig.tight_layout()

    out = Path(out_path)
    fig.savefig(out, dpi=140, facecolor="white")
    plt.close(fig)
    return out
