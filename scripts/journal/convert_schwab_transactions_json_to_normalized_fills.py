#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from onejournal.brokers.schwab.transactions_json import convert_transactions_json_to_normalized_csv, validate_asof


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Schwab transactions JSON into OneJournal normalized fills CSV.")
    parser.add_argument("--asof", required=True, help="YYYY-MM-DD trading date to write.")
    parser.add_argument("--input", required=True, help="Raw Schwab transactions JSON path.")
    parser.add_argument("--output", required=True, help="Output normalized fills CSV path.")
    args = parser.parse_args()

    asof = validate_asof(args.asof)
    stats = convert_transactions_json_to_normalized_csv(Path(args.input), Path(args.output), asof=asof)

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
    if stats.unsupported_record_counts:
        print("UNSUPPORTED_RECORD_COUNTS:")
        for key, count in sorted(stats.unsupported_record_counts.items()):
            print(f"  - {key:<24} : {count}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
