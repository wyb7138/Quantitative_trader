#!/usr/bin/env python3
"""Launch the Quant Trader web dashboard.

Usage:
  python run_web.py                  # serve on http://127.0.0.1:5000
  python run_web.py --port 8080      # custom port
  python run_web.py --host 0.0.0.0   # listen on all interfaces

Equivalent to `python main.py web`.
"""

import argparse

from web import create_app


def main():
    parser = argparse.ArgumentParser(description="Quant Trader web dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Bind port (default 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable Flask debug reloader")
    args = parser.parse_args()

    app = create_app()
    print(f"\n  Quant Trader dashboard → http://{args.host}:{args.port}\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
