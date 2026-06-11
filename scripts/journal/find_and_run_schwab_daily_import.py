#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_DIR / "data" / "raw" / "schwab"


def find_one(pattern: str, label: str, use_latest_snapshot: bool) -> Path:
    matches = sorted(RAW_ROOT.glob(pattern))
    if not matches:
        raise SystemExit(f"FAIL: no {label} file found under {RAW_ROOT} using pattern {pattern}")
    if len(matches) > 1:
        if use_latest_snapshot:
            print(f"DUPLICATE: multiple {label} files found for this asof.")
            print("Operator explicitly allowed latest snapshot selection with --use-latest-snapshot.")
        else:
            print(f"FAIL: multiple {label} files found for this asof.")
            print("Choose one by removing or archiving duplicates, or rerun with --use-latest-snapshot.")
        for m in matches:
            print(f"  {m.relative_to(PROJECT_DIR)}")
        if not use_latest_snapshot:
            raise SystemExit(2)
        print(f"USING LATEST SNAPSHOT BY NAME: {matches[-1].relative_to(PROJECT_DIR)}")
    return matches[-1]


def run(cmd: list[str]) -> None:
    print("")
    print("$ " + " ".join(cmd))
    subprocess.run(cmd, cwd=PROJECT_DIR, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Find Schwab raw files for an asof date and run guarded daily import.")
    parser.add_argument("--asof", required=True, help="YYYY-MM-DD end date to locate and import.")
    parser.add_argument("--db", default="data/journal/onejournal.duckdb")
    parser.add_argument("--import-db", action="store_true", help="Actually import into DuckDB. Without this, runs dry-run gates only.")
    parser.add_argument("--keep-files", action="store_true", help="Keep generated normalized CSV files.")
    parser.add_argument("--use-latest-snapshot", action="store_true", help="If multiple raw files match the asof date, use the newest path by name. Default is to fail safely.")
    args = parser.parse_args()

    asof = args.asof
    orders = find_one(f"*/orders_all/*__{asof}.json", "orders_all", args.use_latest_snapshot)
    transactions = find_one(f"*/transactions/*__{asof}.json", "transactions", args.use_latest_snapshot)

    print("===== Schwab Auto-Discovery Daily Import =====")
    print(f"PROJECT_DIR : {PROJECT_DIR}")
    print(f"RAW_ROOT    : {RAW_ROOT}")
    print(f"ASOF        : {asof}")
    print(f"ORDERS      : {orders.relative_to(PROJECT_DIR)}")
    print(f"TRANSACTIONS: {transactions.relative_to(PROJECT_DIR)}")
    print(f"IMPORT_DB   : {args.import_db}")
    print(f"USE_LATEST  : {args.use_latest_snapshot}")
    print("BROKER API  : disabled")
    print("ORDER API   : disabled")

    cmd = [
        sys.executable,
        "scripts/journal/run_schwab_daily_import.py",
        "--asof",
        asof,
        "--orders",
        str(orders),
        "--transactions",
        str(transactions),
        "--db",
        args.db,
    ]
    if args.import_db:
        cmd.append("--import-db")
    if args.keep_files:
        cmd.append("--keep-files")

    run(cmd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
