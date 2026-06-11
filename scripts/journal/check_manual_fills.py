#!/usr/bin/env python3
"""Check manual CSV fills parsing.

Purpose
-------
Read a manual fills CSV file and show a small review of the normalized fills.

This script is read-only:
- no broker API calls
- no database writes
- no output files
- no order placement
- no order cancellation
- no automation
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check manual CSV fills parsing into OneJournal normalized fills."
    )
    parser.add_argument(
        "--asof",
        required=True,
        help="Market date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--file",
        required=True,
        help="Manual fills CSV file path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    asof = date.fromisoformat(args.asof)
    csv_path = Path(args.file)

    print("===== OneJournal manual fills check =====")
    print(f"ASOF      : {asof}")
    print(f"CSV FILE  : {csv_path}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print()

    records = parse_manual_fills_csv(csv_path)

    mismatch_count = sum(1 for r in records if r.asof != asof)

    print("===== Result =====")
    print(f"RECORDS   : {len(records)}")
    print(f"MISMATCH  : {mismatch_count} row(s) with asof different from --asof")

    if not records:
        print("STATUS    : no records found")
        return 1

    first = records[0]

    print()
    print("===== First normalized fill =====")
    print(f"fill_uid          : {first.fill_uid}")
    print(f"source_broker     : {first.source_broker}")
    print(f"source_account_id : {first.source_account_id}")
    print(f"filled_at         : {first.filled_at}")
    print(f"asset_class       : {first.asset_class}")
    print(f"symbol            : {first.symbol}")
    print(f"side              : {first.side}")
    print(f"quantity          : {first.quantity}")
    print(f"fill_price        : {first.fill_price}")
    print(f"commission        : {first.commission}")
    print(f"fees              : {first.fees}")
    print(f"currency          : {first.currency}")
    print(f"raw_path          : {first.raw_path}")

    if mismatch_count:
        print()
        print("STATUS    : failed asof consistency check")
        return 1

    print()
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
