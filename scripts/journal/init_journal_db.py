#!/usr/bin/env python3
"""Initialize OneJournal DuckDB schema.

Safe local journal storage initializer.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
from onejournal.journal.migrations import apply_schema_migrations

DEFAULT_DB = Path("data/journal/onejournal.duckdb")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize OneJournal DuckDB schema.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    return parser.parse_args()


def init_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    apply_schema_migrations(db_path)


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    init_schema(db_path)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        tables = con.execute("SHOW TABLES").fetchall()
        print("===== OneJournal DB schema =====")
        print(f"DB        : {db_path}")
        for (table_name,) in tables:
            count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            print(f"{table_name}: {count}")
    finally:
        con.close()
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
