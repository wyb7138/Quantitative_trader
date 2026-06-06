"""Paper trading loop.

Runs indefinitely, fetching the latest data, computing signals, and
simulating order execution against current market prices.  State is
persisted to DynamoDB when STATE_TABLE env var is set, otherwise to a
local JSON file so the app works without AWS credentials.
"""

import datetime
import json
import os
import time

import pandas as pd

from config import PAPER, PORTFOLIO, STRATEGY, UNIVERSE
from data.fetcher import fetch
from paper_trader.trade_store import record_trade
from strategy.signals import compute_signals, rank_symbols


STATE_FILE = PAPER["portfolio_file"]
LOOKBACK_DAYS = 90

# AWS feature flags — enabled by env vars, disabled when not set
_STATE_TABLE   = os.environ.get("STATE_TABLE", "")
_ALERT_TOPIC   = os.environ.get("ALERT_TOPIC_ARN", "")
_CACHE_BUCKET  = os.environ.get("CACHE_BUCKET", "")   # used by fetcher; referenced here for log context
_LOG_GROUP     = os.environ.get("CW_LOG_GROUP", "/quant/paper-trader")
_LOG_STREAM    = os.environ.get("AWS_LAMBDA_LOG_STREAM_NAME", "local")
_USE_CW_LOGS   = os.environ.get("CW_LOG_GROUP", "") != ""


# ── CloudWatch logging ────────────────────────────────────────────────────────

_cw_client = None
_cw_seq_token = None  # PutLogEvents requires a sequence token for existing streams


def _cw():
    global _cw_client
    if _cw_client is None:
        import boto3
        _cw_client = boto3.client("logs")
        _ensure_log_stream()
    return _cw_client


def _ensure_log_stream():
    try:
        _cw_client.create_log_group(logGroupName=_LOG_GROUP)
    except _cw_client.exceptions.ResourceAlreadyExistsException:
        pass
    try:
        _cw_client.create_log_stream(logGroupName=_LOG_GROUP, logStreamName=_LOG_STREAM)
    except _cw_client.exceptions.ResourceAlreadyExistsException:
        pass


def _cw_log(payload: dict) -> None:
    """Publish a JSON log event to CloudWatch. No-op if CW_LOG_GROUP not set."""
    if not _USE_CW_LOGS:
        return
    global _cw_seq_token
    kwargs = dict(
        logGroupName=_LOG_GROUP,
        logStreamName=_LOG_STREAM,
        logEvents=[{"timestamp": int(time.time() * 1000), "message": json.dumps(payload, default=str)}],
    )
    if _cw_seq_token:
        kwargs["sequenceToken"] = _cw_seq_token
    try:
        resp = _cw().put_log_events(**kwargs)
        _cw_seq_token = resp.get("nextSequenceToken")
    except Exception as e:
        print(f"  [CW] log failed: {e}")


# ── SNS alerts ────────────────────────────────────────────────────────────────

def _publish_trade(trade: dict) -> None:
    """Publish a trade event to SNS. No-op if ALERT_TOPIC_ARN not set."""
    if not _ALERT_TOPIC:
        return
    import boto3
    sns = boto3.client("sns")
    try:
        sns.publish(
            TopicArn=_ALERT_TOPIC,
            Subject=f"[Quant] {trade['action']} {trade['symbol']}",
            Message=json.dumps(trade, indent=2, default=str),
        )
    except Exception as e:
        print(f"  [SNS] publish failed: {e}")


# ── State persistence (DynamoDB or local JSON) ────────────────────────────────

def _default_state() -> dict:
    return {
        "capital": PORTFOLIO["initial_capital"],
        "positions": {},
        "entry_prices": {},
        "peak_value": PORTFOLIO["initial_capital"],
        "trades": [],
        "started": datetime.datetime.now().isoformat(),
    }


def load_state() -> dict:
    if _STATE_TABLE:
        import boto3
        ddb = boto3.resource("dynamodb")
        table = ddb.Table(_STATE_TABLE)
        resp = table.get_item(Key={"pk": "paper_state"})
        if "Item" in resp:
            return json.loads(resp["Item"]["data"])
        return _default_state()

    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return _default_state()


def save_state(state: dict) -> None:
    if _STATE_TABLE:
        import boto3
        ddb = boto3.resource("dynamodb")
        table = ddb.Table(_STATE_TABLE)
        table.put_item(Item={"pk": "paper_state", "data": json.dumps(state, default=str)})
        return

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2, default=str)


# ── Portfolio value helper ────────────────────────────────────────────────────

def _portfolio_value(state: dict, prices: dict) -> float:
    return state["capital"] + sum(
        state["positions"].get(sym, 0) * prices.get(sym, 0)
        for sym in state["positions"]
    )


# ── Single tick ───────────────────────────────────────────────────────────────

def _tick(state: dict, symbols: list[str]) -> None:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.date.today()
    start = (today - datetime.timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    end = today.strftime("%Y-%m-%d")

    print(f"\n[{now}] Fetching latest data...")
    _cw_log({"event": "tick_start", "time": now, "symbols": symbols})

    price_data = fetch(symbols, start=start, end=end, use_cache=False)
    price_data = {k: v for k, v in price_data.items() if not v.empty and len(v) >= 30}

    if not price_data:
        print("  No data available — skipping tick.")
        _cw_log({"event": "tick_skip", "reason": "no_data"})
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
            trade = {"time": now, "symbol": sym, "action": "STOP_LOSS",
                     "shares": shares, "price": round(price, 4),
                     "entry_price": round(entry, 4), "pnl": pnl}
            state["trades"].append(trade)
            record_trade(trade)
            _publish_trade(trade)
            _cw_log({"event": "trade", **trade})

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
            trade = {"time": now, "symbol": sym, "action": "SELL",
                     "shares": shares, "price": round(price, 4),
                     "entry_price": round(entry, 4), "pnl": pnl}
            state["trades"].append(trade)
            record_trade(trade)
            _publish_trade(trade)
            _cw_log({"event": "trade", **trade})

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
        trade = {"time": now, "symbol": sym, "action": "BUY",
                 "shares": shares, "price": round(price, 4),
                 "entry_price": round(price, 4), "pnl": 0}
        state["trades"].append(trade)
        record_trade(trade)
        _publish_trade(trade)
        _cw_log({"event": "trade", **trade})

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

    _cw_log({"event": "tick_summary", "portfolio_value": round(pv, 2),
             "return_pct": round(ret, 4), "drawdown_pct": round(dd, 4),
             "positions": len(state["positions"])})
    save_state(state)


# ── Main loop ─────────────────────────────────────────────────────────────────

def run_paper_trading(symbols: list[str] = None, poll_seconds: int = None) -> None:
    symbols = symbols or UNIVERSE
    poll_seconds = poll_seconds or PAPER["poll_interval_sec"]
    state = load_state()

    print("=" * 60)
    print("PAPER TRADING AGENT")
    print(f"  Capital : ${state['capital']:,.2f}")
    print(f"  Universe: {symbols}")
    print(f"  Poll    : every {poll_seconds}s  (Ctrl-C to stop)")
    if _STATE_TABLE:
        print(f"  State   : DynamoDB → {_STATE_TABLE}")
    if _ALERT_TOPIC:
        print(f"  Alerts  : SNS → {_ALERT_TOPIC}")
    if _USE_CW_LOGS:
        print(f"  Logs    : CloudWatch → {_LOG_GROUP}")
    print("=" * 60)

    while True:
        try:
            _tick(state, symbols)
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as exc:
            print(f"  [ERROR] {exc}")
            _cw_log({"event": "error", "message": str(exc)})
        time.sleep(poll_seconds)
