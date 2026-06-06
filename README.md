# Quant Trader

A quantitative algorithmic trading agent (mean reversion + momentum using RSI,
Bollinger Bands, and MACD) with a CLI, a paper-trading loop, a backtesting
engine, and a **browser dashboard**.

## Install

```bash
pip install -r requirements.txt
```

## Web dashboard

Launch the UI and open it in your browser:

```bash
python main.py web                 # http://127.0.0.1:5000
python main.py web --port 8080     # custom port
python run_web.py                  # equivalent entry point
```

The dashboard has four tabs:

| Tab        | What it does                                                              |
|------------|--------------------------------------------------------------------------|
| **Dashboard** | Live paper-portfolio value, cash, return, drawdown, open positions; run a trading tick on demand. |
| **Signals**   | Current RSI / Bollinger / MACD composite scores ranked across the universe, with BUY/SELL flags. |
| **Backtest**  | Run a historical backtest over any symbols / date range; interactive equity-curve and drawdown charts, performance metrics, and the trade blotter. |
| **Trades**    | Persisted trade history with win-rate / P&L stats, filterable by symbol. |

### HTTP API

The UI is a thin client over a JSON API (handy for scripting too):

| Method | Endpoint            | Description                         |
|--------|---------------------|-------------------------------------|
| GET    | `/api/config`       | Universe + strategy/portfolio config |
| GET    | `/api/signals`      | Current signals (`?symbols=AAPL,MSFT`) |
| POST   | `/api/backtest`     | Run a backtest (`{symbols, start, end}`) |
| GET    | `/api/trades`       | Trade history + stats (`?symbol=&limit=`) |
| GET    | `/api/portfolio`    | Paper-portfolio snapshot            |
| POST   | `/api/paper/tick`   | Execute one paper-trading tick      |
| GET    | `/api/health`       | Liveness probe                      |

The web layer reuses the existing engines unchanged — it only adds
serialisation (`web/services.py`) and routing (`web/app.py`).

## Command line

```bash
python main.py backtest --start 2022-01-01 --end 2024-12-31
python main.py signals --symbols AAPL TSLA
python main.py paper --poll 300
python main.py trades --symbol AAPL
```

## Architecture

```
config.py            Universe + strategy / portfolio / data parameters
data/fetcher.py      yfinance download with parquet cache (local or S3)
strategy/            Indicators (RSI, BB, MACD) and composite signal scoring
backtest/            Daily-bar backtest engine + performance metrics
paper_trader/        Paper-trading loop, state + trade persistence
web/                 Flask app, services, and the dashboard UI
main.py              CLI entry point (backtest | signals | paper | trades | web)
lambda_handler.py    AWS Lambda entry point for the paper-trading tick
```

State and caching transparently use AWS (S3 / DynamoDB / SNS / CloudWatch)
when the corresponding environment variables are set, and fall back to local
files otherwise — so the app runs with or without AWS credentials.
