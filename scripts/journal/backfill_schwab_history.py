#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
RAW_ROOT = PROJECT_DIR / "data" / "raw" / "schwab"


@dataclass(frozen=True)
class RawPair:
    asof: str
    orders_count: int
    transactions_count: int


def extract_asof(path: Path) -> str:
    return path.name.rsplit("__", 1)[-1].replace(".json", "")


def discover_pairs() -> list[RawPair]:
    orders: dict[str, list[Path]] = {}
    txns: dict[str, list[Path]] = {}

    for p in RAW_ROOT.glob("*/orders_all/*.json"):
        orders.setdefault(extract_asof(p), []).append(p)

    for p in RAW_ROOT.glob("*/transactions/*.json"):
        txns.setdefault(extract_asof(p), []).append(p)

    common = sorted(set(orders) & set(txns))
    return [
        RawPair(asof=d, orders_count=len(orders[d]), transactions_count=len(txns[d]))
        for d in common
    ]


def run(cmd: list[str]) -> int:
    print("")
    print("$ " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=PROJECT_DIR, text=True)
    return result.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill OneJournal from existing Schwab raw JSON files.")
    parser.add_argument("--start", default=None, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--end", default=None, help="Inclusive YYYY-MM-DD")
    parser.add_argument("--db", default="data/journal/onejournal.duckdb")
    parser.add_argument("--import-db", action="store_true", help="Actually import into DuckDB. Default is dry-run only.")
    parser.add_argument("--use-latest-snapshot", action="store_true", help="Allow duplicate raw snapshots by selecting newest path by name.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max number of dates to process.")
    parser.add_argument("--report-dir", default="output/reports/schwab_backfill", help="Directory for CSV backfill report.")
    args = parser.parse_args()

    pairs = discover_pairs()
    if args.start:
        pairs = [p for p in pairs if p.asof >= args.start]
    if args.end:
        pairs = [p for p in pairs if p.asof <= args.end]
    if args.limit and args.limit > 0:
        pairs = pairs[: args.limit]

    print("===== Schwab Historical Backfill =====")
    print(f"PROJECT_DIR        : {PROJECT_DIR}")
    print(f"RAW_ROOT           : {RAW_ROOT}")
    print(f"DATES              : {len(pairs)}")
    print(f"IMPORT_DB          : {args.import_db}")
    print(f"USE_LATEST_SNAPSHOT: {args.use_latest_snapshot}")
    print("BROKER API         : disabled")
    print("ORDER API          : disabled")
    print("")

    if not pairs:
        print("STATUS             : FAIL")
        print("REASON             : no common Schwab orders/transactions dates found")
        return 1

    ok = 0
    fail = 0
    skipped_duplicate = 0
    report_rows: list[dict[str, object]] = []

    print("===== Dates =====")
    for pair in pairs:
        duplicate = pair.orders_count > 1 or pair.transactions_count > 1
        duplicate_text = " DUPLICATE_RAW" if duplicate else ""
        print(f"{pair.asof} orders={pair.orders_count} transactions={pair.transactions_count}{duplicate_text}")
    print("")

    for pair in pairs:
        duplicate = pair.orders_count > 1 or pair.transactions_count > 1
        if duplicate and not args.use_latest_snapshot:
            print(f"SKIP_DUPLICATE_RAW : {pair.asof} orders={pair.orders_count} transactions={pair.transactions_count}")
            skipped_duplicate += 1
            report_rows.append({
                "asof": pair.asof,
                "orders_raw_count": pair.orders_count,
                "transactions_raw_count": pair.transactions_count,
                "duplicate_raw": duplicate,
                "use_latest_snapshot": args.use_latest_snapshot,
                "import_db": args.import_db,
                "return_code": "",
                "status": "skipped_duplicate_raw",
            })
            continue

        cmd = [
            sys.executable,
            "scripts/journal/find_and_run_schwab_daily_import.py",
            "--asof",
            pair.asof,
            "--db",
            args.db,
        ]
        if args.import_db:
            cmd.append("--import-db")
        if args.use_latest_snapshot:
            cmd.append("--use-latest-snapshot")

        rc = run(cmd)
        if rc == 0:
            ok += 1
            status = "ok"
        else:
            fail += 1
            status = "failed"
            print(f"FAILED_DATE        : {pair.asof}")
        report_rows.append({
            "asof": pair.asof,
            "orders_raw_count": pair.orders_count,
            "transactions_raw_count": pair.transactions_count,
            "duplicate_raw": duplicate,
            "use_latest_snapshot": args.use_latest_snapshot,
            "import_db": args.import_db,
            "return_code": rc,
            "status": status,
        })
        if rc != 0:
            break

    report_dir = PROJECT_DIR / args.report_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"{stamp}_schwab_backfill_report.csv"
    with report_path.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = [
            "asof",
            "orders_raw_count",
            "transactions_raw_count",
            "duplicate_raw",
            "use_latest_snapshot",
            "import_db",
            "return_code",
            "status",
        ]
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(report_rows)

    print("")
    print("===== Backfill Report =====")
    print(f"REPORT_PATH         : {report_path.relative_to(PROJECT_DIR)}")
    print("")
    print("===== Backfill Summary =====")
    print(f"DATES_SELECTED      : {len(pairs)}")
    print(f"DATES_OK            : {ok}")
    print(f"DATES_FAILED        : {fail}")
    print(f"DATES_SKIPPED_DUP   : {skipped_duplicate}")
    print(f"IMPORT_DB           : {args.import_db}")

    if fail:
        print("STATUS              : FAIL")
        return 1

    print("STATUS              : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
