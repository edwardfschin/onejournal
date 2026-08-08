from __future__ import annotations

import argparse
from collections import Counter
from datetime import date
from pathlib import Path

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
from onejournal.journal.identity import conflicting_fill_identity_report

VALID_ASSET_CLASSES = {"option", "stock"}
VALID_SIDES = {"buy", "sell"}
VALID_OPTION_TYPES = {"call", "put"}

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check OneJournal normalized fills CSV contract.")
    parser.add_argument("--asof", required=True, help="Expected as-of date in YYYY-MM-DD format.")
    parser.add_argument("--file", required=True, help="Normalized fills CSV file to validate.")
    return parser.parse_args()

def main() -> int:
    args = parse_args()
    asof = date.fromisoformat(args.asof)
    path = Path(args.file)

    print("===== OneJournal normalized fills contract check =====")
    print(f"FILE      : {path}")
    print(f"ASOF      : {asof}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")

    failures: list[str] = []

    if not path.exists():
        print()
        print("===== Result =====")
        print("STATUS    : failed missing file")
        return 1

    records = parse_manual_fills_csv(path)

    if not records:
        failures.append("no fill rows")

    asof_mismatch = sum(1 for row in records if row.asof != asof)
    if asof_mismatch:
        failures.append(f"{asof_mismatch} row(s) have asof different from --asof")

    fill_uid_counts = Counter(row.fill_uid for row in records)
    duplicate_fill_uids = sorted(uid for uid, count in fill_uid_counts.items() if count > 1)
    fill_identity_conflicts = conflicting_fill_identity_report(records)
    if fill_identity_conflicts:
        failures.append(f"identity conflict count {len(fill_identity_conflicts)}")
    elif duplicate_fill_uids:
        # Duplicate fill_uids with identical payload is an idempotent redelivery and is acceptable.
        pass
    for msg in sorted(fill_identity_conflicts):
        failures.append(f"identity conflict: {msg}")

    asset_class_bad = 0
    side_bad = 0
    option_bad = 0
    stock_bad = 0

    for row in records:
        asset_class = (row.asset_class or "").strip().lower()
        side = (row.side or "").strip().lower()

        if asset_class not in VALID_ASSET_CLASSES:
            asset_class_bad += 1

        if side not in VALID_SIDES:
            side_bad += 1

        if asset_class == "option":
            option_type = (row.option_type or "").strip().lower()
            if not row.option_symbol:
                option_bad += 1
            elif not row.underlying_symbol:
                option_bad += 1
            elif option_type not in VALID_OPTION_TYPES:
                option_bad += 1
            elif row.expiry is None:
                option_bad += 1
            elif row.strike is None:
                option_bad += 1
            elif row.multiplier is None:
                option_bad += 1

        if asset_class == "stock":
            if not row.symbol:
                stock_bad += 1

    if asset_class_bad:
        failures.append(f"{asset_class_bad} row(s) have invalid asset_class")
    if side_bad:
        failures.append(f"{side_bad} row(s) have invalid side")
    if option_bad:
        failures.append(f"{option_bad} option row(s) have invalid option fields")
    if stock_bad:
        failures.append(f"{stock_bad} stock row(s) have invalid stock fields")

    print()
    print("===== Counts =====")
    print(f"ROWS                 : {len(records)}")
    print(f"ASOF_MISMATCH        : {asof_mismatch}")
    print(f"DUPLICATE_FILL_UIDS  : {len(duplicate_fill_uids)}")
    print(f"IDENTITY_CONFLICTS   : {len(fill_identity_conflicts)}")
    print(f"BAD_ASSET_CLASS      : {asset_class_bad}")
    print(f"BAD_SIDE             : {side_bad}")
    print(f"BAD_OPTION_FIELDS    : {option_bad}")
    print(f"BAD_STOCK_FIELDS     : {stock_bad}")

    print()
    print("===== Result =====")
    if failures:
        print("STATUS    : failed normalized fills contract")
        for failure in failures:
            print(f"FAIL      : {failure}")
        return 1

    print("STATUS    : OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
