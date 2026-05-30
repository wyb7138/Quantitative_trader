import numpy as np
import pandas as pd


def compute_metrics(portfolio_values: pd.DataFrame, initial_capital: float,
                    trades_df: pd.DataFrame = None, benchmark: pd.DataFrame = None) -> dict:
    """Return a dict of labelled performance metric strings."""
    pv = portfolio_values["value"].dropna()
    returns = pv.pct_change().dropna()

    n_days = len(pv)
    n_years = n_days / 252.0

    total_return = (pv.iloc[-1] - initial_capital) / initial_capital
    cagr = (pv.iloc[-1] / initial_capital) ** (1.0 / n_years) - 1 if n_years > 0 else 0.0

    sharpe = (
        returns.mean() / returns.std() * np.sqrt(252) if returns.std() > 1e-10 else 0.0
    )

    downside = returns[returns < 0].std()
    sortino = (
        returns.mean() / downside * np.sqrt(252) if downside > 1e-10 else 0.0
    )

    running_max = pv.cummax()
    drawdown = (pv - running_max) / running_max
    max_dd = drawdown.min()
    calmar = cagr / abs(max_dd) if max_dd < -1e-10 else float("inf")

    metrics = {
        "Period": f"{pv.index[0].date()} → {pv.index[-1].date()} ({n_days} days)",
        "Total Return": f"{total_return:+.2%}",
        "CAGR": f"{cagr:+.2%}",
        "Sharpe Ratio": f"{sharpe:.2f}",
        "Sortino Ratio": f"{sortino:.2f}",
        "Max Drawdown": f"{max_dd:.2%}",
        "Calmar Ratio": f"{calmar:.2f}",
    }

    if benchmark is not None and not benchmark.empty:
        bv = benchmark["value"].dropna()
        bh_return = (bv.iloc[-1] - initial_capital) / initial_capital
        metrics["Buy & Hold Return"] = f"{bh_return:+.2%}"
        metrics["Alpha (approx)"] = f"{total_return - bh_return:+.2%}"

    if trades_df is not None and not trades_df.empty:
        closed = trades_df[trades_df["action"].isin(["SELL", "STOP_LOSS"])].copy()
        if not closed.empty:
            wins = closed[closed["pnl"] > 0]
            metrics["Total Trades"] = str(len(closed))
            metrics["Win Rate"] = f"{len(wins) / len(closed):.2%}"
            metrics["Avg PnL/Trade"] = f"${closed['pnl'].mean():,.2f}"
            metrics["Total PnL"] = f"${closed['pnl'].sum():,.2f}"
            stop_hits = trades_df[trades_df["action"] == "STOP_LOSS"]
            metrics["Stop Losses Hit"] = str(len(stop_hits))

    return metrics
