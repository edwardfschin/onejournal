#!/usr/bin/env python3
"""Calculate a privacy-safe summary of the bounded Phase 1 realized result."""

from __future__ import annotations

import argparse
from pathlib import Path

from onejournal.journal.phase1_reporting_calculation import (
    calculate_bounded_realized_result,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Calculate bounded realized P&L from the exact active history revision."
    )
    parser.add_argument("--db", required=True, help="Existing private DuckDB path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = calculate_bounded_realized_result(Path(args.db))
    print("===== OneJournal bounded realized result =====")
    print("MODE                   : read-only")
    print("BROKER API             : disabled")
    print("ORDER API              : disabled")
    print(f"CALCULATION_RUN_ID     : {result.calculation_run_id}")
    print(f"RESULT_FINGERPRINT     : {result.result_fingerprint}")
    print(f"HISTORY_REVISIONS      : {len(result.authorities)}")
    print(f"COVERAGE_START         : {result.coverage_start_date}")
    print(f"COVERAGE_END           : {result.coverage_end_date}")
    print(f"AVAILABLE_ALLOCATIONS  : {len(result.items)}")
    print(f"UNAVAILABLE_SCOPES     : {len(result.omissions)}")
    print(f"REASON_COUNTS          : {result.reason_counts}")
    print(f"QUALITY                : {result.quality}")
    print("STATUS                 : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
