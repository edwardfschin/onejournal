#!/usr/bin/env python3
"""Plan an offline, sequential Schwab raw-history backfill.

This command deliberately has no broker, token, file, or DuckDB dependency.
It only converts an inclusive date range into bounded calendar-day windows for
the future live raw-fetch operator.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence


DEFAULT_CHUNK_DAYS = 30


def parse_date(value: str) -> date:
    """Parse a strict ISO calendar date for command-line input."""

    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid date {value!r}; expected YYYY-MM-DD"
        ) from exc


@dataclass(frozen=True)
class FetchWindow:
    """One inclusive calendar-date range for a future raw GET pair."""

    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def plan_windows(start: date, end: date, chunk_days: int) -> list[FetchWindow]:
    """Return contiguous inclusive windows, each no longer than chunk_days."""

    if end < start:
        raise ValueError("end date must be on or after start date")
    if chunk_days <= 0:
        raise ValueError("chunk days must be greater than zero")

    windows: list[FetchWindow] = []
    cursor = start
    while cursor <= end:
        window_end = min(cursor + timedelta(days=chunk_days - 1), end)
        windows.append(FetchWindow(start=cursor, end=window_end))
        cursor = window_end + timedelta(days=1)
    return windows


def estimated_api_calls(window_count: int) -> dict[str, int]:
    """Estimate the future sequential operator's GET requests.

    One account lookup discovers the account hash once. Every window then
    requires one orders GET and one transactions GET. A future operator that
    accepts an already-known account hash can omit the lookup; the planner
    exposes both totals so that distinction is not hidden.
    """

    if window_count < 0:
        raise ValueError("window count cannot be negative")
    orders = window_count
    transactions = window_count
    account_lookup = 1
    return {
        "account_lookup": account_lookup,
        "orders": orders,
        "transactions": transactions,
        "without_account_lookup": orders + transactions,
        "with_account_lookup": account_lookup + orders + transactions,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan offline Schwab raw-history fetch windows; makes no external calls."
    )
    parser.add_argument("--start", required=True, type=parse_date, help="Inclusive YYYY-MM-DD.")
    parser.add_argument("--end", required=True, type=parse_date, help="Inclusive YYYY-MM-DD.")
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=DEFAULT_CHUNK_DAYS,
        help=f"Maximum inclusive calendar days per window (default: {DEFAULT_CHUNK_DAYS}).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        windows = plan_windows(args.start, args.end, args.chunk_days)
    except ValueError as exc:
        raise SystemExit(f"FAIL: {exc}") from exc

    calls = estimated_api_calls(len(windows))

    print("===== Schwab Raw History Backfill Plan =====")
    print("MODE                         : offline planning only")
    print("NETWORK_ACCESS               : disabled")
    print("TOKEN_ACCESS                 : disabled")
    print("FILESYSTEM_WRITE              : disabled")
    print("DUCKDB_WRITE                  : disabled")
    print("BROKER_ORDER_WRITE            : disabled")
    print(f"START                        : {args.start.isoformat()}")
    print(f"END                          : {args.end.isoformat()}")
    print(f"CHUNK_DAYS                   : {args.chunk_days}")
    print(f"WINDOWS_TOTAL                : {len(windows)}")
    print(f"ESTIMATED_ACCOUNT_LOOKUP_GET : {calls['account_lookup']}")
    print(f"ESTIMATED_ORDERS_GET         : {calls['orders']}")
    print(f"ESTIMATED_TRANSACTIONS_GET   : {calls['transactions']}")
    print(f"ESTIMATED_GETS_WITH_HASH     : {calls['without_account_lookup']}")
    print(f"ESTIMATED_GETS_WITH_DISCOVERY: {calls['with_account_lookup']}")
    print("")
    print("===== Planned Windows =====")
    for number, window in enumerate(windows, start=1):
        day_label = "day" if window.days == 1 else "days"
        print(
            f"WINDOW {number:03d} : {window.start.isoformat()} to "
            f"{window.end.isoformat()} ({window.days} {day_label})"
        )
    print("")
    print("STATUS                       : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
