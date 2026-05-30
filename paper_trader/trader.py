"""Paper trading loop.

Runs indefinitely, fetching the latest data, computing signals, and
simulating order execution against current market prices.  State is
persisted to JSON so the loop can be interrupted and resumed.
"""

import datetime
import json
import os
import time

import pandas as pd

from config import PAPER, PORTFOLIO, STRATEGY, UNIVERSE
from data.fetcher import fetch
from strategy.signals import compute_signals, rank_symbols


STATE_FILE = PAPER["portfolio_file"]
LOOKBACK_DAYS = 90  # days of history needed to compute indicators


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {
        "capital": PORTFOLIO["initial_capital"],
        "positions": {},      # symbol -> shares
        "entry_prices": {},   # symbol -> entry price
        "peak_value": PORTFOLIO["initial_capital"],
        "trades": [],
        "started": datetime.datetime.now().isoformat(),
    }


def save_state(state: dict) -> None:
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


def _portfolio_value(state: dict, prices: dict) -> float:
    return state["capital"] + sum(
        state["positions"].get(sym, 0) * prices.get(sym, 0)
        for sym in state["positions"]
    )


def _tick(state: dict, symbols: list[str]) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    print(f"\n[{now}] Fetching latest data...")
    price_data = fetch(symbols, start=start, end=end, use_cache=False)
    price_data = {k: v for k, v in price_data.items() if not v.empty and len(v) >= 30}

    if not price_data:
        print("  No data available — skipping tick.")
        return

    current_prices = {
        sym: float(df["Close"].iloc[-1]) for sym, df in price_data.items()
    }

    signals_data = {sym: compute_signals(df) for sym, df in price_data.items()}
    ranked = rank_symbols(signals_data)

    desired = (
        ranked[ranked["score"] >= STRATEGY["signal_threshold"]]["symbol"]
        .tolist()[: STRATEGY["max_positions"]]
    )

    pv = _portfolio_value(state, current_prices)
    state["peak_value"] = max(state.get("peak_value", pv), pv)

    # ── Stop losses ──────────────────────────────────────────────────────
    for sym in list(state["positions"].keys()):
        price = current_prices.get(sym)
        if price is None:
            continue
        entry = state["entry_prices"].get(sym, price)
        if (price - entry) / entry <= -PORTFOLIO["stop_loss_pct"]:
            shares = state["positions"].pop(sym)
            state["entry_prices"].pop(sym, None)
            proceeds = shares * price * (1 - PORTFOLIO["commission"])
            state["capital"] += proceeds
            pnl = round(proceeds - shares * entry, 2)
            print(f"  STOP_LOSS {sym}: {shares} shares @ ${price:.2f}  PnL ${pnl:+,.2f}")
            state["trades"].append(
                {"time": now, "symbol": sym, "action": "STOP_LOSS",
                 "shares": shares, "price": round(price, 4), "pnl": pnl}
            )

    # ── Exit stale positions ─────────────────────────────────────────────
    for sym in list(state["positions"].keys()):
        if sym not in desired:
            price = current_prices.get(sym, 0)
            entry = state["entry_prices"].pop(sym, price)
            shares = state["positions"].pop(sym)
            proceeds = shares * price * (1 - PORTFOLIO["commission"])
            state["capital"] += proceeds
            pnl = round(proceeds - shares * entry, 2)
            print(f"  SELL      {sym}: {shares} shares @ ${price:.2f}  PnL ${pnl:+,.2f}")
            state["trades"].append(
                {"time": now, "symbol": sym, "action": "SELL",
                 "shares": shares, "price": round(price, 4), "pnl": pnl}
            )

    # ── Enter new positions ──────────────────────────────────────────────
    pv = _portfolio_value(state, current_prices)
    available = STRATEGY["max_positions"] - len(state["positions"])
    new_entries = [s for s in desired if s not in state["positions"]][:available]

    for sym in new_entries:
        price = current_prices.get(sym)
        if not price:
            continue
        alloc = min(pv * PORTFOLIO["position_size"], pv * PORTFOLIO["max_position_pct"])
        alloc = min(alloc, state["capital"] * 0.98)
        if alloc <= 0:
            continue
        shares = int(alloc / (price * (1 + PORTFOLIO["commission"])))
        if shares <= 0:
            continue
        cost = shares * price * (1 + PORTFOLIO["commission"])
        state["capital"] -= cost
        state["positions"][sym] = shares
        state["entry_prices"][sym] = round(price, 4)
        print(f"  BUY       {sym}: {shares} shares @ ${price:.2f}")
        state["trades"].append(
            {"time": now, "symbol": sym, "action": "BUY",
             "shares": shares, "price": round(price, 4), "pnl": 0}
        )

    # ── Summary ──────────────────────────────────────────────────────────
    pv = _portfolio_value(state, current_prices)
    inception = PORTFOLIO["initial_capital"]
    ret = (pv - inception) / inception * 100
    dd = (pv - state["peak_value"]) / state["peak_value"] * 100 if state["peak_value"] > 0 else 0
    print(f"\n  Portfolio: ${pv:>12,.2f}  Return: {ret:+.2f}%  Drawdown: {dd:.2f}%")
    print(f"  Cash:      ${state['capital']:>12,.2f}  Positions: {len(state['positions'])}")
    for sym, shares in state["positions"].items():
        price = current_prices.get(sym, 0)
        entry = state["entry_prices"].get(sym, price)
        pnl_pct = (price - entry) / entry * 100 if entry else 0
        score = int(signals_data[sym].iloc[-1]["score"]) if sym in signals_data else "?"
        print(f"    {sym:<6} {shares:>5} shares  ${price:>8.2f}  entry ${entry:.2f}  {pnl_pct:+.1f}%  score={score}")

    save_state(state)


def run_paper_trading(symbols: list[str] = None, poll_seconds: int = None) -> None:
    symbols = symbols or UNIVERSE
    poll_seconds = poll_seconds or PAPER["poll_interval_sec"]
    state = load_state()

    print("=" * 60)
    print("PAPER TRADING AGENT")
    print(f"  Capital : ${state['capital']:,.2f}")
    print(f"  Universe: {symbols}")
    print(f"  Poll    : every {poll_seconds}s  (Ctrl-C to stop)")
    print("=" * 60)

    while True:
        try:
            _tick(state, symbols)
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as exc:
            print(f"  [ERROR] {exc}")
        time.sleep(poll_seconds)
