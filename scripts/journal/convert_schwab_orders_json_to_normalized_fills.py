from __future__ import annotations

import argparse
from pathlib import Path

from onejournal.brokers.schwab.orders_json import convert_orders_json_to_normalized_csv, validate_asof


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert Schwab orders JSON into OneJournal normalized fills CSV.")
    parser.add_argument("--asof", required=False, help="Optional YYYY-MM-DD filter. When provided, only fills on this date are written.")
    parser.add_argument("--input", required=True, help="Raw Schwab orders JSON path.")
    parser.add_argument("--output", required=True, help="Output normalized fills CSV path.")
    args = parser.parse_args()

    asof = validate_asof(args.asof)
    stats = convert_orders_json_to_normalized_csv(Path(args.input), Path(args.output), asof=asof)

    print("===== Schwab orders JSON to normalized fills =====")
    print(f"INPUT     : {args.input}")
    print(f"OUTPUT    : {args.output}")
    print(f"ASOF      : {asof or all}")
    print("MODE      : read-only")
    print("BROKER API: disabled")
    print("ORDER API : disabled")
    print("")
    print("===== Stats =====")
    print(f"TOP_LEVEL_ORDERS       : {stats.top_level_orders}")
    print(f"FLATTENED_ORDERS       : {stats.flattened_orders}")
    print(f"FILL_ACTIVITIES        : {stats.fill_activities}")
    print(f"FILL_ROWS_WRITTEN      : {stats.fill_rows}")
    print(f"SKIPPED_NON_FILL       : {stats.skipped_non_fill_activities}")
    print(f"SKIPPED_UNMATCHED_LEGS : {stats.skipped_unmatched_legs}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

