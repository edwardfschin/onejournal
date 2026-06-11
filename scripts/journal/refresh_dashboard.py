#!/usr/bin/env python3
"""Refresh OneJournal dashboard payload and manual review template.

Safe internal prototype runner.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[2]
DEFAULT_FILE = PROJECT_DIR / "docs/examples/manual_csv/fills_template.csv"
DEFAULT_REVIEWS = PROJECT_DIR / "data/journal/reviews/manual_reviews.csv"
DEFAULT_OUTPUT = PROJECT_DIR / "output/dashboard/latest/dashboard_payload.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh OneJournal dashboard payload and review template.")
    parser.add_argument("--asof", required=True, help="Market date in YYYY-MM-DD format.")
    parser.add_argument("--file", default=str(DEFAULT_FILE), help="Manual fills CSV path.")
    parser.add_argument("--reviews", default=str(DEFAULT_REVIEWS), help="Manual reviews CSV path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Dashboard payload JSON path.")
    return parser.parse_args()


def run_step(label: str, cmd: list[str]) -> None:
    print(f"===== {label} =====")
    print("COMMAND   : " + " ".join(cmd))
    result = subprocess.run(cmd, text=True, cwd=str(PROJECT_DIR))
    if result.returncode != 0:
        raise SystemExit(f"FAILED    : {label} returned {result.returncode}")
    print(f"OK        : {label}")
    print()


def main() -> int:
    args = parse_args()
    py = sys.executable

    print("===== OneJournal dashboard refresh =====")
    print(f"ASOF      : {args.asof}")
    print(f"FILLS     : {args.file}")
    print(f"REVIEWS   : {args.reviews}")
    print(f"OUTPUT    : {args.output}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    print()

    run_step("Build dashboard payload", [py, str(PROJECT_DIR / "scripts/journal/check_dashboard_payload.py"), "--asof", args.asof, "--file", args.file, "--reviews", args.reviews, "--output", args.output, "--write"])
    run_step("Update review template", [py, str(PROJECT_DIR / "scripts/journal/update_review_template.py"), "--asof", args.asof, "--payload", args.output, "--reviews", args.reviews])
    run_step("Rebuild dashboard payload with updated reviews", [py, str(PROJECT_DIR / "scripts/journal/check_dashboard_payload.py"), "--asof", args.asof, "--file", args.file, "--reviews", args.reviews, "--output", args.output, "--write"])

    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
