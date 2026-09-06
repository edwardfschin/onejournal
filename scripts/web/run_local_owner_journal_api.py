#!/usr/bin/env python3
"""Start the private OneJournal journal API on loopback only.

The database path is an operator-only process-start argument. It is never
accepted from a browser request, logged by this command, or returned by the
API. This launcher does not apply migrations, call providers, or open evidence.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from onejournal.api.local_owner_journal import create_local_owner_journal_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OneJournal local-owner journal API on loopback.")
    parser.add_argument("--db", required=True, help="Existing private DuckDB journal path.")
    parser.add_argument("--port", type=int, default=8765, help="Loopback TCP port (default: 8765).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1024 <= args.port <= 65535:
        raise ValueError("port must be between 1024 and 65535")
    app = create_local_owner_journal_app(journal_db_path=Path(args.db))
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
