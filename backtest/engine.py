"""Daily bar backtesting engine.

Signal-to-execution timing (no look-ahead):
  Day T close  →  signals computed
  Day T+1 open →  orders executed
"""

import pandas as pd
from config import STRATEGY, PORTFOLIO


def run_backtest(
    price_data: dict, signals_data: dict
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run vectorised daily backtest across multiple symbols.

    Args:
        price_data:   {symbol: OHLCV DataFrame}
        signals_data: {symbol: signals DataFrame with 'score' column}

    Returns:
        portfolio_values: DataFrame indexed by date with column 'value'
        trades:           DataFrame of all executed trades
    """
    cfg_p = PORTFOLIO
    cfg_s = STRATEGY

    # Common trading dates (intersection across all symbols)
    all_dates = sorted(
        set.intersection(*[set(df.index) for df in price_data.values()])
    )
    if len(all_dates) < 2:
        raise ValueError("Not enough common dates to run backtest.")

    capital = cfg_p["initial_capital"]
    positions: dict[str, int] = {}      # symbol -> shares
    entry_prices: dict[str, float] = {} # symbol -> price paid
    portfolio_values = []
    trades = []

    for i, date in enumerate(all_dates):
        open_prices = {
            sym: float(price_data[sym].loc[date, "Open"])
            for sym in price_data
            if date in price_data[sym].index
        }
        close_prices = {
            sym: float(price_data[sym].loc[date, "Close"])
            for sym in price_data
            if date in price_data[sym].index
        }

        # ── Stop-loss checks at today's open ────────────────────────────
        for sym in list(positions.keys()):
            price = open_prices.get(sym)
            if price is None:
                continue
            entry = entry_prices[sym]
            if (price - entry) / entry <= -cfg_p["stop_loss_pct"]:
                shares = positions.pop(sym)
                entry_prices.pop(sym)
                proceeds = shares * price * (1 - cfg_p["commission"] - cfg_p["slippage"])
                capital += proceeds
                trades.append(
                    {
                        "date": date,
                        "symbol": sym,
                        "action": "STOP_LOSS",
                        "shares": shares,
                        "price": round(price, 4),
                        "pnl": round(proceeds - shares * entry, 2),
                    }
                )

        # ── On day 0 there is no prior signal; just record value ─────────
        if i == 0:
            pv = capital + sum(
                positions.get(sym, 0) * close_prices.get(sym, 0) for sym in positions
            )
            portfolio_values.append({"date": date, "value": pv})
            continue

        # ── Derive desired longs from YESTERDAY's signals ────────────────
        prev_date = all_dates[i - 1]
        scores: dict[str, int] = {}
        for sym, sdf in signals_data.items():
            if prev_date in sdf.index:
                scores[sym] = int(sdf.loc[prev_date, "score"])

        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        desired = [
            sym
            for sym, sc in ranked
            if sc >= cfg_s["signal_threshold"]
        ][: cfg_s["max_positions"]]

        # ── Exit positions no longer desired ─────────────────────────────
        for sym in list(positions.keys()):
            if sym not in desired:
                price = open_prices.get(sym)
                if price is None:
                    continue
                shares = positions.pop(sym)
                entry = entry_prices.pop(sym)
                proceeds = shares * price * (1 - cfg_p["commission"] - cfg_p["slippage"])
                capital += proceeds
                trades.append(
                    {
                        "date": date,
                        "symbol": sym,
                        "action": "SELL",
                        "shares": shares,
                        "price": round(price, 4),
                        "pnl": round(proceeds - shares * entry, 2),
                    }
                )

        # ── Enter new desired positions ──────────────────────────────────
        portfolio_value = capital + sum(
            positions.get(sym, 0) * close_prices.get(sym, 0) for sym in positions
        )
        available_slots = cfg_s["max_positions"] - len(positions)
        new_entries = [sym for sym in desired if sym not in positions][:available_slots]

        for sym in new_entries:
            price = open_prices.get(sym)
            if price is None or price <= 0:
                continue
            alloc = min(
                portfolio_value * cfg_p["position_size"],
                portfolio_value * cfg_p["max_position_pct"],
            )
            alloc = min(alloc, capital * 0.98)
            if alloc <= 0:
                continue
            cost_per_share = price * (1 + cfg_p["commission"] + cfg_p["slippage"])
            shares = int(alloc / cost_per_share)
            if shares <= 0:
                continue
            capital -= shares * cost_per_share
            positions[sym] = shares
            entry_prices[sym] = price
            trades.append(
                {
                    "date": date,
                    "symbol": sym,
                    "action": "BUY",
                    "shares": shares,
                    "price": round(price, 4),
                    "pnl": 0.0,
                }
            )

        # ── Mark-to-market at close ──────────────────────────────────────
        pv = capital + sum(
            positions.get(sym, 0) * close_prices.get(sym, 0) for sym in positions
        )
        portfolio_values.append({"date": date, "value": pv})

    pv_df = pd.DataFrame(portfolio_values).set_index("date")
    trades_df = pd.DataFrame(trades) if trades else pd.DataFrame(
        columns=["date", "symbol", "action", "shares", "price", "pnl"]
    )
    return pv_df, trades_df


def buy_and_hold(price_data: dict, initial_capital: float) -> pd.DataFrame:
    """Equal-weight buy-and-hold benchmark using all provided symbols."""
    all_dates = sorted(
        set.intersection(*[set(df.index) for df in price_data.values()])
    )
    n = len(price_data)
    alloc = initial_capital / n
    shares = {
        sym: alloc / float(price_data[sym].loc[all_dates[0], "Open"])
        for sym in price_data
    }
    rows = []
    for date in all_dates:
        pv = sum(
            shares[sym] * float(price_data[sym].loc[date, "Close"])
            for sym in price_data
            if date in price_data[sym].index
        )
        rows.append({"date": date, "value": pv})
    return pd.DataFrame(rows).set_index("date")
