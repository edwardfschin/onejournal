#!/usr/bin/env python3
"""Validate OneJournal DuckDB journal storage.

Read-only DB health check.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_DB = Path("data/journal/onejournal.duckdb")
REQUIRED_TABLES = ["import_runs", "normalized_fills", "trade_episodes", "trade_episode_legs", "manual_reviews"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check OneJournal DuckDB journal storage.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    return parser.parse_args()


def fail(message: str) -> None:
    raise SystemExit(f"FAIL {message}")


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    print("===== OneJournal DB check =====")
    print(f"DB        : {db_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print()

    if not db_path.exists():
        fail(f"DB not found: {db_path}")

    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        missing = sorted(set(REQUIRED_TABLES) - tables)
        if missing:
            fail(f"missing required table(s): {missing}")

        counts = {}
        for table in REQUIRED_TABLES:
            counts[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {counts[table]}")

        if counts["normalized_fills"] <= 0:
            fail("normalized_fills has no rows")
        if counts["trade_episodes"] <= 0:
            fail("trade_episodes has no rows")
        if counts["manual_reviews"] <= 0:
            fail("manual_reviews has no rows")
        if counts["trade_episode_legs"] < counts["trade_episodes"]:
            fail("trade_episode_legs count is less than trade_episodes count")

        duplicate_fills = con.execute("SELECT COUNT(*) FROM (SELECT fill_uid FROM normalized_fills GROUP BY fill_uid HAVING COUNT(*) > 1)").fetchone()[0]
        duplicate_episodes = con.execute("SELECT COUNT(*) FROM (SELECT episode_uid FROM trade_episodes GROUP BY episode_uid HAVING COUNT(*) > 1)").fetchone()[0]
        duplicate_reviews = con.execute("SELECT COUNT(*) FROM (SELECT episode_uid FROM manual_reviews GROUP BY episode_uid HAVING COUNT(*) > 1)").fetchone()[0]

        print(f"duplicate_fill_uid: {duplicate_fills}")
        print(f"duplicate_episode_uid: {duplicate_episodes}")
        print(f"duplicate_review_episode_uid: {duplicate_reviews}")

        if duplicate_fills:
            fail("duplicate fill_uid found")
        if duplicate_episodes:
            fail("duplicate episode_uid found")
        if duplicate_reviews:
            fail("duplicate manual review episode_uid found")

    finally:
        con.close()

    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
