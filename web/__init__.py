"""Web application package for the Quant Trader.

Exposes the existing backtest / signals / paper-trading / trade-history
engines through a Flask HTTP API and a browser dashboard.  All heavy
lifting is delegated to the existing modules; this package only adds a
thin web/serialisation layer.
"""

from web.app import create_app

__all__ = ["create_app"]
