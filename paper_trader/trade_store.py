"""Persistent trade-record storage.

Every executed trade is recorded so the history is queryable later.
Backend is DynamoDB when the TRADES_TABLE env var is set (fits the
serverless / Lambda architecture), otherwise a local JSON file so the
app still works without AWS.  Mirrors the opt-in env-var pattern used by
the rest of the AWS integration.

DynamoDB item layout (table key schema: pk HASH, sk RANGE):
    pk     = "TRADE"                      (single partition; volume is low)
    sk     = "<ISO timestamp>#<uuid8>"    (unique, sortable by time)
    symbol = "AAPL"                       (top-level for convenience)
    action = "BUY" | "SELL" | "STOP_LOSS"
    data   = JSON string of the full trade dict
"""

import csv
import datetime
import json
import os
import uuid

_TRADES_TABLE = os.environ.get("TRADES_TABLE", "")
_LOCAL_TRADES_FILE = "paper_trader/trades_log.json"


def _new_sk() -> str:
    """Time-ordered, collision-resistant sort key."""
    return f"{datetime.datetime.now().isoformat()}#{uuid.uuid4().hex[:8]}"


# ── Write ─────────────────────────────────────────────────────────────────────

def record_trade(trade: dict) -> None:
    """Persist a single executed trade. No-op-safe on failure."""
    enriched = dict(trade)
    enriched.setdefault("recorded_at", datetime.datetime.now().isoformat())

    if _TRADES_TABLE:
        import boto3
        try:
            table = boto3.resource("dynamodb").Table(_TRADES_TABLE)
            table.put_item(Item={
                "pk": "TRADE",
                "sk": _new_sk(),
                "symbol": enriched.get("symbol", "?"),
                "action": enriched.get("action", "?"),
                "data": json.dumps(enriched, default=str),
            })
        except Exception as e:
            print(f"  [TRADES] DynamoDB write failed: {e}")
        return

    # Local fallback — append to a JSON array file
    try:
        os.makedirs(os.path.dirname(_LOCAL_TRADES_FILE), exist_ok=True)
        log = []
        if os.path.exists(_LOCAL_TRADES_FILE):
            with open(_LOCAL_TRADES_FILE) as f:
                log = json.load(f)
        log.append(enriched)
        with open(_LOCAL_TRADES_FILE, "w") as f:
            json.dump(log, f, indent=2, default=str)
    except Exception as e:
        print(f"  [TRADES] local write failed: {e}")


# ── Read ──────────────────────────────────────────────────────────────────────

def _load_all() -> list[dict]:
    """Return every stored trade, most-recent first."""
    if _TRADES_TABLE:
        import boto3
        from boto3.dynamodb.conditions import Key
        table = boto3.resource("dynamodb").Table(_TRADES_TABLE)
        items, kwargs = [], {
            "KeyConditionExpression": Key("pk").eq("TRADE"),
            "ScanIndexForward": False,  # newest first
        }
        try:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            while "LastEvaluatedKey" in resp:
                resp = table.query(ExclusiveStartKey=resp["LastEvaluatedKey"], **kwargs)
                items.extend(resp.get("Items", []))
        except Exception as e:
            print(f"  [TRADES] DynamoDB read failed: {e}")
            return []
        return [json.loads(it["data"]) for it in items]

    if os.path.exists(_LOCAL_TRADES_FILE):
        with open(_LOCAL_TRADES_FILE) as f:
            return list(reversed(json.load(f)))  # newest first
    return []


def get_recent_trades(limit: int = 50) -> list[dict]:
    return _load_all()[:limit]


def get_trades_for_symbol(symbol: str, limit: int = 50) -> list[dict]:
    sym = symbol.upper()
    return [t for t in _load_all() if t.get("symbol", "").upper() == sym][:limit]


def get_trade_stats() -> dict:
    trades = _load_all()
    closed = [t for t in trades if t.get("action") in ("SELL", "STOP_LOSS")]
    wins = [t for t in closed if (t.get("pnl") or 0) > 0]
    total_pnl = sum((t.get("pnl") or 0) for t in closed)
    n = len(closed)
    return {
        "total_records": len(trades),
        "closed_trades": n,
        "winning_trades": len(wins),
        "win_rate": round(len(wins) / n, 4) if n else 0.0,
        "total_pnl": round(total_pnl, 2),
        "avg_pnl": round(total_pnl / n, 2) if n else 0.0,
    }


def export_csv(path: str = "trades_export.csv") -> str:
    """Write all trades to CSV in chronological order. Returns the path."""
    trades = list(reversed(_load_all()))  # oldest first
    if not trades:
        print("  No trades to export.")
        return path
    fields: list[str] = []
    for t in trades:
        for k in t:
            if k not in fields:
                fields.append(k)
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(trades)
    return path
