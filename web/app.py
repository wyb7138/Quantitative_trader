"""Flask application factory and HTTP routes.

Routes
  GET  /                     dashboard (single-page UI)
  GET  /api/config           universe + strategy/portfolio defaults
  GET  /api/signals          current signal scores  (?symbols=AAPL,MSFT)
  POST /api/backtest         run a backtest         {symbols, start, end}
  GET  /api/trades           trade history + stats  (?symbol=&limit=)
  GET  /api/portfolio        paper-trading portfolio snapshot
  POST /api/paper/tick       run one paper-trading tick
  GET  /api/health           liveness probe
"""

import traceback

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException

from web import services


def _parse_symbols(raw) -> list[str] | None:
    """Accept a comma/space separated string or a list; normalise to upper."""
    if not raw:
        return None
    if isinstance(raw, str):
        raw = raw.replace(",", " ").split()
    syms = [s.strip().upper() for s in raw if s and s.strip()]
    return syms or None


def create_app() -> Flask:
    app = Flask(__name__)

    # ── pages ────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return render_template("index.html")

    # ── api ──────────────────────────────────────────────────────────────
    @app.get("/api/health")
    def health():
        return jsonify({"status": "ok"})

    @app.get("/api/config")
    def config():
        return jsonify(services.get_config())

    @app.get("/api/signals")
    def signals():
        symbols = _parse_symbols(request.args.get("symbols"))
        return jsonify(services.get_signals(symbols))

    @app.post("/api/backtest")
    def backtest():
        payload = request.get_json(silent=True) or {}
        symbols = _parse_symbols(payload.get("symbols"))
        start = (payload.get("start") or "").strip() or None
        end = (payload.get("end") or "").strip() or None
        result = services.run_backtest_service(symbols, start, end)
        status = 400 if "error" in result else 200
        return jsonify(result), status

    @app.get("/api/trades")
    def trades():
        symbol = request.args.get("symbol") or None
        try:
            limit = int(request.args.get("limit", 50))
        except (TypeError, ValueError):
            limit = 50
        return jsonify(services.get_trades(symbol, limit))

    @app.get("/api/portfolio")
    def portfolio():
        return jsonify(services.get_portfolio())

    @app.post("/api/paper/tick")
    def paper_tick():
        return jsonify(services.run_paper_tick())

    # ── favicon ──────────────────────────────────────────────────────────
    @app.get("/favicon.ico")
    def favicon():
        return "", 204

    # ── errors ───────────────────────────────────────────────────────────
    @app.errorhandler(Exception)
    def handle_error(exc):
        if isinstance(exc, HTTPException):
            return jsonify({"error": exc.description}), exc.code
        app.logger.error("Unhandled error: %s\n%s", exc, traceback.format_exc())
        return jsonify({"error": str(exc)}), 500

    return app
