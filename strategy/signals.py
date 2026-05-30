import pandas as pd
from config import STRATEGY
from strategy.indicators import rsi, bollinger_bands, macd


def compute_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Compute composite signal score for one symbol's OHLCV DataFrame.

    Score per bar: sum of three sub-signals, each in {-1, 0, +1}.
    Total range: [-3, +3].  Positive = bullish, negative = bearish.

    Sub-signals:
      RSI   +1 oversold  (<30), -1 overbought  (>70)
      BB    +1 price < lower band, -1 price > upper band
      MACD  +1 histogram > 0 (bullish), -1 histogram < 0
    """
    cfg = STRATEGY
    close = df["Close"]

    rsi_vals = rsi(close, cfg["rsi_period"])
    rsi_sig = pd.Series(0, index=close.index, dtype=int)
    rsi_sig[rsi_vals < cfg["rsi_oversold"]] = 1
    rsi_sig[rsi_vals > cfg["rsi_overbought"]] = -1

    bb_low, _, bb_high = bollinger_bands(close, cfg["bb_period"], cfg["bb_std"])
    bb_sig = pd.Series(0, index=close.index, dtype=int)
    bb_sig[close < bb_low] = 1
    bb_sig[close > bb_high] = -1

    macd_line, signal_line, hist = macd(
        close, cfg["macd_fast"], cfg["macd_slow"], cfg["macd_signal"]
    )
    macd_sig = pd.Series(0, index=close.index, dtype=int)
    macd_sig[hist > 0] = 1
    macd_sig[hist < 0] = -1

    return pd.DataFrame(
        {
            "score": rsi_sig + bb_sig + macd_sig,
            "rsi": rsi_vals,
            "rsi_sig": rsi_sig,
            "bb_low": bb_low,
            "bb_high": bb_high,
            "bb_sig": bb_sig,
            "macd_line": macd_line,
            "macd_signal_line": signal_line,
            "macd_hist": hist,
            "macd_sig": macd_sig,
            "close": close,
        }
    )


def rank_symbols(signals_dict: dict, date=None) -> pd.DataFrame:
    """Rank all symbols by their score at a given date (defaults to latest bar)."""
    rows = []
    for sym, sdf in signals_dict.items():
        if sdf.empty:
            continue
        try:
            row = sdf.loc[date] if date is not None else sdf.iloc[-1]
        except KeyError:
            continue
        rows.append(
            {
                "symbol": sym,
                "score": int(row["score"]),
                "rsi": round(float(row["rsi"]), 1),
                "rsi_sig": int(row["rsi_sig"]),
                "bb_sig": int(row["bb_sig"]),
                "macd_sig": int(row["macd_sig"]),
                "close": round(float(row["close"]), 2),
            }
        )
    return (
        pd.DataFrame(rows)
        .sort_values("score", ascending=False)
        .reset_index(drop=True)
    )
