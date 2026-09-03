"""Launch the local sizing web app (supported path; Phase W5).

Loads the ~5.5 GB LUT engine once in a background thread, then serves:

    http://127.0.0.1:8000/            the UI
    http://127.0.0.1:8000/api/v1/health
    http://127.0.0.1:8000/api/v1/size

Binds to localhost by default; do not expose it on a network without adding
authentication and rate limiting (see docs/WEB_APP_IMPLEMENTATION_PLAN.md §8).

    .venv/Scripts/python scripts/run_web_app.py [--port 8000]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind address (default: 127.0.0.1 - keep it local)")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    import uvicorn
    from analog_ai.web.app import create_app

    app = create_app()   # LUTs load in a background thread at startup
    print()
    print("=" * 64)
    print("Analog AI - ideal-tail 5T OTA sizing web app")
    print(f"  UI:     http://{args.host}:{args.port}/")
    print(f"  Health: http://{args.host}:{args.port}/api/v1/health")
    print("  The sizing engine loads in the background (~5.5 GB LUTs;")
    print("  first start can take a few minutes). The UI polls health.")
    print("  Nominal-TT LUT candidates only - Cadence remains the final")
    print("  authority. Keep the service bound to localhost.")
    print("=" * 64)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
