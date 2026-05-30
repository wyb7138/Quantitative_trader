UNIVERSE = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META",
    "NVDA", "TSLA", "JPM", "V", "JNJ",
    "WMT", "PG", "HD", "MA", "UNH",
    "BAC", "ABBV", "PFE", "AVGO", "COST",
]

STRATEGY = {
    "rsi_period": 14,
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "bb_period": 20,
    "bb_std": 2.0,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "signal_threshold": 2,   # min score (+/-3 max) to open a position
    "max_positions": 5,
}

PORTFOLIO = {
    "initial_capital": 100_000.0,
    "position_size": 0.15,       # fraction of portfolio per position
    "max_position_pct": 0.25,    # hard cap per position
    "stop_loss_pct": 0.05,       # 5% stop loss from entry
    "commission": 0.001,         # 0.1% per side
    "slippage": 0.001,           # 0.1% per side
}

DATA = {
    "default_start": "2022-01-01",
    "default_end": "2024-12-31",
    "cache_dir": "data/cache",
    "interval": "1d",
}

PAPER = {
    "poll_interval_sec": 60,
    "portfolio_file": "paper_trader/portfolio_state.json",
}
