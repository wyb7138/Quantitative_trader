"""Service layer for the web app.

Each function wraps an existing engine (data / strategy / backtest /
paper_trader) and returns plain JSON-serialisable Python structures so the
Flask routes stay trivial.  No business logic lives here that isn't already
in the underlying modules — this is purely glue + serialisation.
"""

import datetime

import pandas as pd

from config import DATA, PORTFOLIO, STRATEGY, UNIVERSE
from data.fetcher import fetch
from strategy.signals import compute_signals, rank_symbols
from backtest.engine import buy_and_hold, run_backtest
from backtest.metrics import compute_metrics
from paper_trader.trade_store import (
    get_recent_trades,
    get_trades_for_symbol,
    get_trade_stats,
)
from paper_trader.trader import _tick, load_state, save_state


# ── helpers ──────────────────────────────────────────────────────────────────

def _usable(price_data: dict, min_rows: int = 30) -> dict:
    return {k: v for k, v in price_data.items() if not v.empty and len(v) > min_rows}


def _iso_dates(index) -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in index]


def _latest_prices(symbols: list[str]) -> tuple[dict, bool]:
    """Best-effort latest close per symbol.

    Tries a short recent window (cache first, then live).  Returns
    (prices, live) where ``live`` is False when nothing could be fetched.
    """
    if not symbols:
        return {}, True
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=14)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")
    try:
        data = fetch(symbols, start=start, end=end, use_cache=False)
    except Exception:
        data = {}
    prices = {
        sym: float(df["Close"].iloc[-1])
        for sym, df in data.items()
        if not df.empty
    }
    return prices, bool(prices)


# ── config ───────────────────────────────────────────────────────────────────

def get_config() -> dict:
    """Expose the parts of config the UI needs to render forms/defaults."""
    return {
        "universe": list(UNIVERSE),
        "strategy": dict(STRATEGY),
        "portfolio": dict(PORTFOLIO),
        "default_start": DATA["default_start"],
        "default_end": DATA["default_end"],
    }


# ── signals ──────────────────────────────────────────────────────────────────

def get_signals(symbols: list[str] | None = None) -> dict:
    symbols = symbols or list(UNIVERSE)
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=90)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    price_data = fetch(symbols, start=start, end=end, use_cache=False)
    price_data = {k: v for k, v in price_data.items() if not v.empty and len(v) >= 30}
    if not price_data:
        return {"as_of": str(today), "signals": [], "error": "No data available."}

    signals_data = {sym: compute_signals(df) for sym, df in price_data.items()}
    ranked = rank_symbols(signals_data)

    rows = []
    for _, r in ranked.iterrows():
        score = int(r["score"])
        rows.append({
            "symbol": r["symbol"],
            "score": score,
            "close": float(r["close"]),
            "rsi": float(r["rsi"]),
            "rsi_sig": int(r["rsi_sig"]),
            "bb_sig": int(r["bb_sig"]),
            "macd_sig": int(r["macd_sig"]),
            "flag": "BUY" if score >= 2 else ("SELL" if score <= -2 else ""),
        })
    return {"as_of": str(today), "signals": rows, "threshold": STRATEGY["signal_threshold"]}


# ── backtest ─────────────────────────────────────────────────────────────────

def run_backtest_service(
    symbols: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
) -> dict:
    symbols = symbols or list(UNIVERSE)
    start = start or DATA["default_start"]
    end = end or DATA["default_end"]

    price_data = _usable(fetch(symbols, start=start, end=end))
    if not price_data:
        return {"error": "No usable data for the selected symbols / date range."}

    signals_data = {sym: compute_signals(df) for sym, df in price_data.items()}
    pv, trades = run_backtest(price_data, signals_data)
    bh = buy_and_hold(price_data, PORTFOLIO["initial_capital"])
    metrics = compute_metrics(pv, PORTFOLIO["initial_capital"], trades, bh)

    strat = pv["value"]
    drawdown = (strat - strat.cummax()) / strat.cummax()

    # Align benchmark onto the strategy's dates for a clean overlay
    bh_vals = bh["value"].reindex(strat.index).ffill()

    equity = {
        "dates": _iso_dates(strat.index),
        "strategy": [round(float(v), 2) for v in strat.values],
        "buy_hold": [round(float(v), 2) for v in bh_vals.values],
        "drawdown": [round(float(v) * 100, 3) for v in drawdown.values],
        "initial_capital": PORTFOLIO["initial_capital"],
    }

    trade_rows = []
    if not trades.empty:
        for _, t in trades.iterrows():
            trade_rows.append({
                "date": t["date"].strftime("%Y-%m-%d") if hasattr(t["date"], "strftime") else str(t["date"]),
                "symbol": t["symbol"],
                "action": t["action"],
                "shares": int(t["shares"]),
                "price": float(t["price"]),
                "pnl": float(t["pnl"]),
            })

    return {
        "symbols": sorted(price_data),
        "start": start,
        "end": end,
        "metrics": metrics,
        "equity": equity,
        "trades": trade_rows,
    }


# ── trades / history ─────────────────────────────────────────────────────────

def get_trades(symbol: str | None = None, limit: int = 50) -> dict:
    if symbol:
        trades = get_trades_for_symbol(symbol, limit)
    else:
        trades = get_recent_trades(limit)
    return {"trades": trades, "stats": get_trade_stats()}


# ── paper portfolio ──────────────────────────────────────────────────────────

def get_portfolio() -> dict:
    state = load_state()
    held = list(state.get("positions", {}).keys())
    prices, live = _latest_prices(held)

    positions = []
    holdings_value = 0.0
    for sym, shares in state.get("positions", {}).items():
        entry = state.get("entry_prices", {}).get(sym, 0.0)
        price = prices.get(sym, entry)  # fall back to entry when offline
        mkt = shares * price
        holdings_value += mkt
        pnl_pct = ((price - entry) / entry * 100) if entry else 0.0
        positions.append({
            "symbol": sym,
            "shares": int(shares),
            "entry_price": round(float(entry), 2),
            "price": round(float(price), 2),
            "market_value": round(float(mkt), 2),
            "pnl_pct": round(float(pnl_pct), 2),
        })

    cash = float(state.get("capital", 0.0))
    total = cash + holdings_value
    initial = PORTFOLIO["initial_capital"]
    ret = (total - initial) / initial * 100 if initial else 0.0
    peak = float(state.get("peak_value", total)) or total
    dd = (total - peak) / peak * 100 if peak else 0.0

    return {
        "cash": round(cash, 2),
        "holdings_value": round(holdings_value, 2),
        "total_value": round(total, 2),
        "initial_capital": initial,
        "return_pct": round(ret, 2),
        "drawdown_pct": round(dd, 2),
        "positions": sorted(positions, key=lambda p: p["market_value"], reverse=True),
        "prices_live": live,
        "started": state.get("started"),
        "trade_count": len(state.get("trades", [])),
    }


def run_paper_tick() -> dict:
    """Execute a single paper-trading tick, persist, and return the portfolio."""
    state = load_state()
    _tick(state, list(UNIVERSE))
    save_state(state)
    return get_portfolio()
