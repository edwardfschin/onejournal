#!/usr/bin/env python3
"""Run OneJournal CSV-to-DB dashboard transition validation.

This is a safe transition runner:
- refreshes the current CSV-built dashboard payload
- imports the current CSV/review data into DuckDB
- validates DuckDB
- builds a DB-built dashboard payload
- compares CSV payload vs DB payload
- runs baseline

It does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_ASOF = "2026-06-02"
DEFAULT_DB = PROJECT_DIR / "data/journal/onejournal.duckdb"
DEFAULT_FILLS = PROJECT_DIR / "docs/examples/manual_csv/fills_template.csv"
DEFAULT_REVIEWS = PROJECT_DIR / "data/journal/reviews/manual_reviews.csv"
DEFAULT_CSV_PAYLOAD = PROJECT_DIR / "output/dashboard/latest/dashboard_payload.json"
DEFAULT_DB_PAYLOAD = PROJECT_DIR / "output/dashboard/latest/dashboard_payload_from_db.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run OneJournal DB transition validation.")
    parser.add_argument("--asof", default=DEFAULT_ASOF, help="Market date in YYYY-MM-DD format.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    parser.add_argument("--fills", default=str(DEFAULT_FILLS), help="Manual fills CSV path.")
    parser.add_argument("--reviews", default=str(DEFAULT_REVIEWS), help="Manual reviews CSV path.")
    return parser.parse_args()


def run_step(label: str, cmd: list[str]) -> tuple[int, str]:
    print(f"===== {label} =====")
    print("COMMAND   : " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=str(PROJECT_DIR), text=True, capture_output=True)
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0:
        print(f"{label}=PASS")
    else:
        print(f"{label}=FAIL")
        print(output[-4000:])
    print()
    return result.returncode, output


def main() -> int:
    args = parse_args()
    py = sys.executable
    db_path = Path(args.db)

    print("===== OneJournal DB transition refresh =====")
    print(f"PROJECT   : {PROJECT_DIR}")
    print(f"ASOF      : {args.asof}")
    print(f"DB        : {db_path}")
    print(f"FILLS     : {args.fills}")
    print(f"REVIEWS   : {args.reviews}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print()

    steps: list[tuple[str, list[str]]] = [
        (
            "CSV_PAYLOAD_REFRESH",
            [
                py,
                str(PROJECT_DIR / "scripts/journal/refresh_dashboard.py"),
                "--asof",
                args.asof,
                "--file",
                str(Path(args.fills)),
                "--reviews",
                str(Path(args.reviews)),
                "--output",
                str(DEFAULT_CSV_PAYLOAD),
            ],
        ),
        (
            "DB_IMPORT",
            [
                py,
                str(PROJECT_DIR / "scripts/journal/import_journal_to_db.py"),
                "--db",
                str(db_path),
                "--fills",
                str(Path(args.fills)),
                "--reviews",
                str(Path(args.reviews)),
                "--replace",
            ],
        ),
        (
            "DB_CHECK",
            [
                py,
                str(PROJECT_DIR / "scripts/journal/check_journal_db.py"),
                "--db",
                str(db_path),
            ],
        ),
        (
            "DB_PAYLOAD_BUILD",
            [
                py,
                str(PROJECT_DIR / "scripts/journal/build_dashboard_payload_from_db.py"),
                "--asof",
                args.asof,
                "--db",
                str(db_path),
                "--output",
                str(DEFAULT_DB_PAYLOAD),
                "--write",
            ],
        ),
        (
            "CSV_VS_DB_PAYLOAD_COMPARE",
            [
                py,
                str(PROJECT_DIR / "scripts/journal/compare_dashboard_payloads.py"),
                "--left",
                str(DEFAULT_CSV_PAYLOAD),
                "--right",
                str(DEFAULT_DB_PAYLOAD),
            ],
        ),
        (
            "BASELINE",
            [
                str(PROJECT_DIR / "bin/onejournal_check.sh"),
            ],
        ),
    ]

    results: dict[str, int] = {}
    for label, cmd in steps:
        rc, _output = run_step(label, cmd)
        results[label] = rc

    print("===== FINAL RESULT =====")
    for label in [name for name, _cmd in steps]:
        print(f"{label}={'PASS' if results[label] == 0 else 'FAIL'}")

    overall_pass = all(rc == 0 for rc in results.values())
    print(f"OVERALL={'PASS' if overall_pass else 'FAIL'}")
    print("NEXT_STEP=Switch Streamlit read path to DB payload only after another clean pass.")

    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
