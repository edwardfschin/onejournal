#!/usr/bin/env python3
from __future__ import annotations

import csv
import argparse
from pathlib import Path

from onejournal.brokers.schwab.transactions_json import (
    LIFECYCLE_EVENT_COLUMNS,
    LIFECYCLE_EVENT_LEG_COLUMNS,
    convert_transactions_json_to_normalized_csv_from_rows,
    extract_lifecycle_event_legs_from_transactions,
    extract_lifecycle_events_from_transactions,
    load_transactions_json,
    validate_asof,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Schwab transactions JSON into OneJournal normalized fills CSV.")
    parser.add_argument("--asof", required=True, help="YYYY-MM-DD trading date to write.")
    parser.add_argument("--input", required=True, help="Raw Schwab transactions JSON path.")
    parser.add_argument("--output", required=True, help="Output normalized fills CSV path.")
    parser.add_argument(
        "--lifecycle-events",
        default=None,
        help="Optional output CSV path for lifecycle-only rows extracted from this transactions file.",
    )
    parser.add_argument(
        "--lifecycle-event-legs",
        default=None,
        help="Optional output CSV path for transfer-item evidence linked to lifecycle events.",
    )
    args = parser.parse_args()

    asof = validate_asof(args.asof)
    transactions = load_transactions_json(Path(args.input))
    output_path = Path(args.output)
    stats = convert_transactions_json_to_normalized_csv_from_rows(
        transactions,
        output_path,
        asof=asof,
    )
    lifecycle_events = extract_lifecycle_events_from_transactions(transactions, asof=asof)
    lifecycle_event_legs = extract_lifecycle_event_legs_from_transactions(
        transactions, asof=asof
    )
    if args.lifecycle_events:
        lifecycle_output = Path(args.lifecycle_events)
        lifecycle_output.parent.mkdir(parents=True, exist_ok=True)
        with lifecycle_output.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=LIFECYCLE_EVENT_COLUMNS)
            writer.writeheader()
            for row in lifecycle_events:
                writer.writerow(row)
    if args.lifecycle_event_legs:
        lifecycle_legs_output = Path(args.lifecycle_event_legs)
        lifecycle_legs_output.parent.mkdir(parents=True, exist_ok=True)
        with lifecycle_legs_output.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=LIFECYCLE_EVENT_LEG_COLUMNS)
            writer.writeheader()
            writer.writerows(lifecycle_event_legs)

    print("===== Schwab transactions JSON to normalized fills =====")
    print(f"INPUT     : {args.input}")
    print(f"OUTPUT    : {args.output}")
    print(f"ASOF      : {asof}")
    print("MODE      : read-only")
    print("BROKER API: disabled")
    print("ORDER API : disabled")
    print("")
    print("===== Stats =====")
    print(f"TRANSACTIONS       : {stats.transactions}")
    print(f"TRADE_VALID        : {stats.trade_valid}")
    print(f"SECURITY_ITEMS     : {stats.security_items}")
    print(f"CURRENCY_ITEMS     : {stats.currency_items}")
    print(f"FILL_ROWS_WRITTEN  : {stats.fill_rows}")
    print(f"UNSUPPORTED_ITEMS  : {stats.unsupported_items}")
    if stats.unsupported_activity_counts:
        print("UNSUPPORTED_ACTIVITY_COUNTS:")
        for key, count in sorted(stats.unsupported_activity_counts.items()):
            print(f"  - {key:<24} : {count}")
    if stats.unsupported_asset_counts:
        print("UNSUPPORTED_ASSET_COUNTS:")
        for key, count in sorted(stats.unsupported_asset_counts.items()):
            print(f"  - {key:<24} : {count}")
    if lifecycle_events:
        print(f"LIFECYCLE_EVENTS    : {len(lifecycle_events)}")
    if args.lifecycle_event_legs:
        print(f"LIFECYCLE_EVENT_LEGS: {len(lifecycle_event_legs)}")
    if stats.unsupported_record_counts:
        print("UNSUPPORTED_RECORD_COUNTS:")
        for key, count in sorted(stats.unsupported_record_counts.items()):
            print(f"  - {key:<24} : {count}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
