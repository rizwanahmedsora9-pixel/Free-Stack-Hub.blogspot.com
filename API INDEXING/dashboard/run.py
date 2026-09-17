#!/usr/bin/env python3
"""Start the Indexing Console.

    python3 run.py                 # http://127.0.0.1:5000
    python3 run.py --demo          # start straight into demo mode (no key needed)
    python3 run.py --host 0.0.0.0 --port 8080
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

parser = argparse.ArgumentParser()
parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "5000")))
parser.add_argument("--demo", action="store_true", help="enter demo mode on first start")
parser.add_argument("--debug", action="store_true")
args = parser.parse_args()

if args.demo:
    os.environ["INDEXER_DEMO"] = "1"

from indexer.app import create_app  # noqa: E402

app = create_app()
if __name__ == "__main__":
    print(f" * Indexing Console on http://{args.host}:{args.port}")
    app.run(host=args.host, port=args.port, debug=args.debug, threaded=True, use_reloader=False)
