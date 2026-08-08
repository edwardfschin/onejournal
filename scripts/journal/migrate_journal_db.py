#!/usr/bin/env python3
"""Apply OneJournal DuckDB migration ledger."""

from __future__ import annotations

import argparse
from pathlib import Path

from onejournal.journal.migrations import apply_schema_migrations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply OneJournal journal migration ledger.")
    parser.add_argument("--db", default="data/journal/onejournal.duckdb", help="DuckDB journal database path.")
    parser.add_argument("--target-version", default=None, help="Stop at four-digit version.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    try:
        target = args.target_version
        version = apply_schema_migrations(db_path, target_version=target)
        print(f"database version: {version:04d}")
        return 0
    except Exception as exc:
        raise SystemExit(f"FAIL: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
