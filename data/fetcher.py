import io
import os

import pandas as pd
import yfinance as yf

from config import DATA

# S3 cache is used when the CACHE_BUCKET env var is set; otherwise falls back
# to the local parquet cache so the app works without AWS credentials.
_CACHE_BUCKET = os.environ.get("CACHE_BUCKET", "")


def _s3_client():
    import boto3
    return boto3.client("s3")


def _s3_key(symbol: str, start: str, end: str) -> str:
    return f"cache/{symbol}_{start}_{end}.parquet"


def _load_s3(symbol: str, start: str, end: str):
    s3 = _s3_client()
    try:
        obj = s3.get_object(Bucket=_CACHE_BUCKET, Key=_s3_key(symbol, start, end))
        return pd.read_parquet(io.BytesIO(obj["Body"].read()))
    except s3.exceptions.NoSuchKey:
        return None
    except Exception as e:
        print(f"  Warning: S3 cache read failed for {symbol}: {e}")
        return None


def _save_s3(df: pd.DataFrame, symbol: str, start: str, end: str) -> None:
    s3 = _s3_client()
    buf = io.BytesIO()
    df.to_parquet(buf, index=True)
    buf.seek(0)
    try:
        s3.put_object(Bucket=_CACHE_BUCKET, Key=_s3_key(symbol, start, end), Body=buf)
    except Exception as e:
        print(f"  Warning: S3 cache write failed for {symbol}: {e}")


def fetch(symbols, start=None, end=None, use_cache=True):
    """Download adjusted OHLCV data from Yahoo Finance with parquet caching.

    Cache backend is S3 when CACHE_BUCKET env var is set, otherwise local disk.
    Returns dict[symbol -> DataFrame] with columns: Open, High, Low, Close, Volume.
    Symbols that fail to download are omitted silently.
    """
    start = start or DATA["default_start"]
    end = end or DATA["default_end"]
    use_s3 = bool(_CACHE_BUCKET)

    if not use_s3:
        cache_dir = DATA["cache_dir"]
        os.makedirs(cache_dir, exist_ok=True)

    result = {}
    to_download = []

    for sym in symbols:
        if use_cache:
            if use_s3:
                cached = _load_s3(sym, start, end)
                if cached is not None:
                    result[sym] = cached
                    continue
            else:
                cache_path = f"{DATA['cache_dir']}/{sym}_{start}_{end}.parquet"
                if os.path.exists(cache_path):
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
            if use_cache:
                if use_s3:
                    _save_s3(df, sym, start, end)
                else:
                    cache_path = f"{DATA['cache_dir']}/{sym}_{start}_{end}.parquet"
                    df.to_parquet(cache_path)
            result[sym] = df
        except Exception as e:
            print(f"  Warning: failed to fetch {sym}: {e}")

    return result
