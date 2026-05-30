#!/usr/bin/env python3
"""
Quantitative Algorithmic Trading Agent

Commands:
  backtest   Run historical backtest and plot equity curve
  signals    Show current indicator signals for the universe
  paper      Start paper trading loop (live data, simulated orders)

Examples:
  python main.py backtest --start 2022-01-01 --end 2024-12-31
  python main.py backtest --symbols AAPL MSFT NVDA --start 2023-01-01
  python main.py signals
  python main.py signals --symbols AAPL TSLA
  python main.py paper --poll 300
"""

import argparse
import datetime
import sys


# ── backtest ────────────────────────────────────────────────────────────────

def cmd_backtest(args):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates

    from config import DATA, PORTFOLIO, UNIVERSE
    from data.fetcher import fetch
    from strategy.signals import compute_signals
    from backtest.engine import buy_and_hold, run_backtest
    from backtest.metrics import compute_metrics

    symbols = args.symbols or UNIVERSE
    start = args.start or DATA["default_start"]
    end = args.end or DATA["default_end"]

    print(f"\nFetching data for {len(symbols)} symbols  [{start} → {end}]")
    price_data = fetch(symbols, start=start, end=end)
    price_data = {k: v for k, v in price_data.items() if not v.empty and len(v) > 30}
    print(f"  Ready: {sorted(price_data)}")

    if not price_data:
        print("No usable data.  Exiting.")
        sys.exit(1)

    print("\nComputing signals...")
    signals_data = {sym: compute_signals(df) for sym, df in price_data.items()}

    print("Running backtest...")
    pv, trades = run_backtest(price_data, signals_data)

    print("Building benchmark...")
    bh = buy_and_hold(price_data, PORTFOLIO["initial_capital"])

    metrics = compute_metrics(pv, PORTFOLIO["initial_capital"], trades, bh)

    print("\n" + "=" * 50)
    print("  BACKTEST RESULTS")
    print("=" * 50)
    for label, val in metrics.items():
        print(f"  {label:<22} {val}")

    if not trades.empty:
        n = min(15, len(trades))
        print(f"\n  Last {n} trades:")
        print(trades.tail(n).to_string(index=False))

    # ── Equity curve plot ────────────────────────────────────────────────
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]}, sharex=True
    )

    strategy_vals = pv["value"]
    bh_vals = bh["value"]

    ax1.plot(strategy_vals.index, strategy_vals.values,
             label="Strategy", color="steelblue", linewidth=1.5)
    ax1.plot(bh_vals.index, bh_vals.values,
             label="Buy & Hold", color="darkorange", linewidth=1.2, linestyle="--")
    ax1.axhline(PORTFOLIO["initial_capital"], color="gray",
                linestyle=":", alpha=0.6, label="Initial Capital")
    ax1.set_ylabel("Portfolio Value ($)")
    ax1.set_title(
        f"Backtest: Mean Reversion + Momentum  |  "
        f"{len(price_data)} symbols  |  {start} → {end}"
    )
    ax1.legend(loc="upper left")
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"${x:,.0f}"))
    ax1.grid(alpha=0.25)

    dd = (strategy_vals - strategy_vals.cummax()) / strategy_vals.cummax()
    ax2.fill_between(dd.index, dd.values, 0, color="crimson", alpha=0.45, label="Drawdown")
    ax2.set_ylabel("Drawdown")
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:.0%}"))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax2.legend(loc="lower left")
    ax2.grid(alpha=0.25)

    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()

    out = "backtest_results.png"
    plt.savefig(out, dpi=150, bbox_inches="tight")
    print(f"\n  Equity curve saved → {out}")


# ── signals ─────────────────────────────────────────────────────────────────

def cmd_signals(args):
    from config import UNIVERSE
    from data.fetcher import fetch
    from strategy.signals import compute_signals, rank_symbols

    symbols = args.symbols or UNIVERSE
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    print(f"\nFetching last 90 days for {len(symbols)} symbols...")
    price_data = fetch(symbols, start=start, end=end, use_cache=False)
    price_data = {k: v for k, v in price_data.items() if not v.empty and len(v) >= 30}

    if not price_data:
        print("No data available.")
        sys.exit(1)

    signals_data = {sym: compute_signals(df) for sym, df in price_data.items()}
    ranked = rank_symbols(signals_data)

    print("\n" + "=" * 60)
    print(f"  CURRENT SIGNALS  (as of {today})")
    print("=" * 60)
    print(f"  {'Symbol':<8} {'Score':>6}  {'Close':>8}  {'RSI':>6}  RSI BB MACD")
    print("  " + "-" * 52)
    for _, row in ranked.iterrows():
        signal_bar = (
            f"{row['rsi_sig']:+d} {row['bb_sig']:+d} {row['macd_sig']:+d}"
        )
        flag = "  <<< BUY" if row["score"] >= 2 else ("  <<< SELL" if row["score"] <= -2 else "")
        print(
            f"  {row['symbol']:<8} {row['score']:>+6}  "
            f"${row['close']:>7.2f}  {row['rsi']:>6.1f}  {signal_bar}{flag}"
        )


# ── paper ────────────────────────────────────────────────────────────────────

def cmd_paper(args):
    from config import UNIVERSE
    from paper_trader.trader import run_paper_trading

    symbols = args.symbols or UNIVERSE
    poll = args.poll or None
    run_paper_trading(symbols=symbols, poll_seconds=poll)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Quantitative Algorithmic Trading Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    bt = sub.add_parser("backtest", help="Run historical backtest")
    bt.add_argument("--start", metavar="DATE", help="Start date YYYY-MM-DD")
    bt.add_argument("--end", metavar="DATE", help="End date YYYY-MM-DD")
    bt.add_argument("--symbols", nargs="+", metavar="SYM")

    sig = sub.add_parser("signals", help="Print current signal scores")
    sig.add_argument("--symbols", nargs="+", metavar="SYM")

    pap = sub.add_parser("paper", help="Run paper trading loop")
    pap.add_argument("--symbols", nargs="+", metavar="SYM")
    pap.add_argument("--poll", type=int, metavar="SEC",
                     help="Poll interval in seconds (default from config)")

    args = parser.parse_args()

    if args.command == "backtest":
        cmd_backtest(args)
    elif args.command == "signals":
        cmd_signals(args)
    elif args.command == "paper":
        cmd_paper(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
