#!/usr/bin/env python3
"""Initialize OneJournal DuckDB schema.

Safe local journal storage initializer.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_DB = Path("data/journal/onejournal.duckdb")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Initialize OneJournal DuckDB schema.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    return parser.parse_args()


def init_schema(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("""
        CREATE TABLE IF NOT EXISTS import_runs (
            import_run_id VARCHAR PRIMARY KEY,
            source_type VARCHAR NOT NULL,
            source_path VARCHAR,
            asof_date DATE,
            imported_at TIMESTAMP NOT NULL,
            row_count INTEGER NOT NULL,
            status VARCHAR NOT NULL,
            notes VARCHAR
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS normalized_fills (
            fill_uid VARCHAR PRIMARY KEY,
            source_broker VARCHAR NOT NULL,
            source_account_id VARCHAR NOT NULL,
            source_fill_id VARCHAR NOT NULL,
            source_order_id VARCHAR,
            episode_group_id VARCHAR,
            asof_date DATE NOT NULL,
            filled_at TIMESTAMP NOT NULL,
            asset_class VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            side VARCHAR NOT NULL,
            quantity DECIMAL(38, 10) NOT NULL,
            fill_price DECIMAL(38, 10) NOT NULL,
            commission DECIMAL(38, 10) NOT NULL,
            fees DECIMAL(38, 10) NOT NULL,
            currency VARCHAR NOT NULL,
            fetched_at TIMESTAMP NOT NULL,
            raw_path VARCHAR,
            option_symbol VARCHAR,
            underlying_symbol VARCHAR,
            option_type VARCHAR,
            expiry DATE,
            strike DECIMAL(38, 10),
            multiplier DECIMAL(38, 10),
            open_close VARCHAR,
            execution_venue VARCHAR,
            liquidity_flag VARCHAR,
            import_run_id VARCHAR
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS manual_reviews (
            episode_uid VARCHAR PRIMARY KEY,
            review_status VARCHAR NOT NULL,
            setup_quality VARCHAR NOT NULL,
            entry_reason VARCHAR,
            notes VARCHAR,
            updated_at TIMESTAMP NOT NULL
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS trade_episodes (
            episode_uid VARCHAR PRIMARY KEY,
            source_broker VARCHAR NOT NULL,
            source_account_id VARCHAR NOT NULL,
            primary_symbol VARCHAR NOT NULL,
            asset_class VARCHAR NOT NULL,
            strategy_type VARCHAR NOT NULL,
            strategy_label VARCHAR NOT NULL,
            opened_at TIMESTAMP NOT NULL,
            status VARCHAR NOT NULL,
            fill_count INTEGER NOT NULL,
            leg_count INTEGER NOT NULL,
            leg_summary VARCHAR,
            cashflow_label VARCHAR,
            net_quantity DECIMAL(38, 10),
            gross_cashflow DECIMAL(38, 10),
            commission DECIMAL(38, 10),
            fees DECIMAL(38, 10),
            updated_at TIMESTAMP NOT NULL
        )
        """)
        con.execute("""
        CREATE TABLE IF NOT EXISTS trade_episode_legs (
            episode_uid VARCHAR NOT NULL,
            leg_index INTEGER NOT NULL,
            asset_class VARCHAR,
            symbol VARCHAR,
            side VARCHAR,
            quantity DECIMAL(38, 10),
            option_type VARCHAR,
            expiry DATE,
            strike DECIMAL(38, 10),
            raw_leg_json VARCHAR,
            PRIMARY KEY (episode_uid, leg_index)
        )
        """)
    finally:
        con.close()


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
