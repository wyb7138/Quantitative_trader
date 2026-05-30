import os
import yfinance as yf
import pandas as pd
from config import DATA


def fetch(symbols, start=None, end=None, use_cache=True):
    """Download adjusted OHLCV data from Yahoo Finance with local parquet caching.

    Returns dict[symbol -> DataFrame] with columns: Open, High, Low, Close, Volume.
    Symbols that fail to download are omitted silently.
    """
    start = start or DATA["default_start"]
    end = end or DATA["default_end"]
    cache_dir = DATA["cache_dir"]
    os.makedirs(cache_dir, exist_ok=True)

    result = {}
    to_download = []

    for sym in symbols:
        cache_path = f"{cache_dir}/{sym}_{start}_{end}.parquet"
        if use_cache and os.path.exists(cache_path):
            try:
                result[sym] = pd.read_parquet(cache_path)
                continue
            except Exception:
                pass
        to_download.append(sym)

    for sym in to_download:
        try:
            df = yf.download(
                sym, start=start, end=end,
                auto_adjust=True, progress=False, actions=False,
            )
            if df.empty:
                print(f"  Warning: no data returned for {sym}")
                continue
            # Flatten MultiIndex columns (yfinance >= 0.2 may return them)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df.index = pd.to_datetime(df.index)
            df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
            cache_path = f"{cache_dir}/{sym}_{start}_{end}.parquet"
            df.to_parquet(cache_path)
            result[sym] = df
        except Exception as e:
            print(f"  Warning: failed to fetch {sym}: {e}")

    return result
