#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/incremental_export.py
Version: 1.0.1
Updated: 2025-12-23 (SGT)

Purpose
-------
Incrementally pull Schwab TRANSACTIONS into DuckDB in safe chunks, resuming
from the latest data already in the DB (or a user-specified date window).

This script is aligned with the "raw + views" journal design:

- Auto-detects current coverage from:
    * journal.v_transactions_raw_latest (prefers MAX(time), else MAX(trade_date))
    * journal.transactions_raw          (fallback using MAX(to_iso))
    * journal.trades (optional)         (MAX(trade_time)) if present
  and restarts from the earlier of the two (tx vs trades), with overlap.

- Chunks the export in N-day windows and calls:
    python -m scripts.journal.export_trx --db ... --from ... --to ...
  NOTE: export_trx only supports: --db --from --to [--debug].
        This runner accepts legacy flags (--raw / --include-open-orders) but
        does NOT pass them through.

- Finishes with a read-only health check:
    python -m scripts.journal.db_inspect --db ... --schema journal

CLI (examples)
--------------
# Fully automatic resume until today (defaults: debug on)
python -m scripts.journal.incremental_export --db "$HOME/tgps-project/data/journal/tgps_trades.duckdb"

# Force a specific window with 30-day chunks and gentle pacing
python -m scripts.journal.incremental_export \
  --db "$HOME/tgps-project/data/journal/tgps_trades.duckdb" \
  --from 2023-01-01 --to 2025-11-18 \
  --chunk-days 30 --pace-sec 0.6 --debug
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import date, timedelta

import duckdb


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="incremental_export.py",
        description="Chunked, resumable Schwab->DuckDB journal export (transactions)",
    )
    p.add_argument(
        "--db",
        default=os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb"),
        help="Path to DuckDB file",
    )

    # Primary names
    p.add_argument(
        "--since",
        type=str,
        help="Start date (YYYY-MM-DD). If omitted, auto-detect from DB.",
    )
    p.add_argument("--until", type=str, help="End date (YYYY-MM-DD). Default: today.")
    p.add_argument(
        "--step-days", type=int, default=30, help="Chunk size in days (default: 30)"
    )
    p.add_argument(
        "--sleep-sec",
        type=float,
        default=0.6,
        help="Sleep seconds between chunks (default: 0.6)",
    )

    # Back-compat aliases (mapped at runtime)
    p.add_argument("--from", dest="from_date", type=str, help="Alias for --since")
    p.add_argument("--to", dest="to_date", type=str, help="Alias for --until")
    p.add_argument("--chunk-days", type=int, help="Alias for --step-days")
    p.add_argument("--pace-sec", type=float, help="Alias for --sleep-sec")

    # Kept for back-compat UX (NOT passed to export_trx)
    p.add_argument(
        "--include-open-orders",
        dest="include_open_orders",
        action="store_true",
        default=True,
        help="Back-compat flag (ignored for export_trx). Use --no-open-orders to disable.",
    )
    p.add_argument("--no-open-orders", dest="include_open_orders", action="store_false")

    p.add_argument(
        "--raw",
        dest="raw",
        action="store_true",
        default=True,
        help="Back-compat flag (ignored for export_trx). Use --no-raw to disable.",
    )
    p.add_argument("--no-raw", dest="raw", action="store_false")

    p.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        default=True,
        help="Verbose logging for export_trx (default: on). Use --no-debug to reduce logging.",
    )
    p.add_argument("--no-debug", dest="debug", action="store_false")

    # Post-processing
    p.add_argument(
        "--no-repair", action="store_true", help="Skip final db_inspect health-check."
    )

    # Optional guard
    p.add_argument(
        "--allow-future-until",
        action="store_true",
        help="Allow --until dates after today (default: clamp to today).",
    )

    return p.parse_args()


def parse_ymd(s: str) -> date:
    y, m, d = map(int, s.split("-"))
    return date(y, m, d)


def _relation_exists(con: duckdb.DuckDBPyConnection, schema: str, name: str) -> bool:
    return (
        con.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = ? AND table_name = ?
            LIMIT 1
            """,
            [schema, name],
        ).fetchone()
        is not None
    )


def _column_exists(
    con: duckdb.DuckDBPyConnection, schema: str, table: str, col: str
) -> bool:
    return (
        con.execute(
            """
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = ? AND table_name = ? AND column_name = ?
            LIMIT 1
            """,
            [schema, table, col],
        ).fetchone()
        is not None
    )


def detect_start(db_path: str, debug: bool = True) -> date:
    """
    Resume point (conservative):
      - prefer MAX(time)::date from journal.transactions if it exists
      - else prefer MAX(time)::date from journal.v_transactions_raw_latest (if present)
      - else prefer MAX(trade_date) from journal.v_transactions_raw_latest
      - else fallback to MAX(to_iso)::date from journal.transactions_raw (window coverage)
      - trades side: MAX(trade_time)::date from journal.trades if present
    Then start from the earlier of the two, with a small overlap (idempotent reruns).
    """
    RESUME_FLOOR = date(2023, 1, 1)
    OVERLAP_DAYS = 3

    con = duckdb.connect(db_path)
    try:
        last_tx = RESUME_FLOOR

        if _relation_exists(con, "journal", "transactions") and _column_exists(
            con, "journal", "transactions", "time"
        ):
            last_tx = con.execute(
                "SELECT COALESCE(CAST(MAX(time) AS DATE), DATE '2023-01-01') FROM journal.transactions"
            ).fetchone()[0]

        elif _relation_exists(con, "journal", "v_transactions_raw_latest"):
            if _column_exists(con, "journal", "v_transactions_raw_latest", "time"):
                last_tx = con.execute(
                    "SELECT COALESCE(CAST(MAX(time) AS DATE), DATE '2023-01-01') FROM journal.v_transactions_raw_latest"
                ).fetchone()[0]
            elif _column_exists(
                con, "journal", "v_transactions_raw_latest", "trade_date"
            ):
                last_tx = con.execute(
                    "SELECT COALESCE(MAX(trade_date), DATE '2023-01-01') FROM journal.v_transactions_raw_latest"
                ).fetchone()[0]
            else:
                last_tx = RESUME_FLOOR

        elif _relation_exists(con, "journal", "transactions_raw"):
            last_tx = con.execute(
                """
                SELECT COALESCE(
                    MAX(CAST(SUBSTR(to_iso, 1, 10) AS DATE)),
                    DATE '2023-01-01'
                )
                FROM journal.transactions_raw
                """
            ).fetchone()[0]

        last_fill = RESUME_FLOOR
        if _relation_exists(con, "journal", "trades") and _column_exists(
            con, "journal", "trades", "trade_time"
        ):
            last_fill = con.execute(
                "SELECT COALESCE(CAST(MAX(trade_time) AS DATE), DATE '2023-01-01') FROM journal.trades"
            ).fetchone()[0]

    finally:
        con.close()

    start = min(last_tx, last_fill) - timedelta(days=OVERLAP_DAYS)
    if start < RESUME_FLOOR:
        start = RESUME_FLOOR

    if debug:
        print(
            f"[DETECT] last_tx={last_tx} last_fill={last_fill} -> start={start} (overlap={OVERLAP_DAYS}d)"
        )

    return start


def run_export_chunk(
    db_path: str,
    d0: date,
    d1: date,
    include_open_orders: bool,
    keep_raw: bool,
    debug: bool,
):
    """
    NOTE: export_trx only supports: --db --from --to [--debug]
    include_open_orders / keep_raw are accepted here for back-compat only.
    """
    cmd = [
        sys.executable,
        "-m",
        "scripts.journal.export_trx",
        "--db",
        db_path,
        "--from",
        d0.isoformat(),
        "--to",
        d1.isoformat(),
    ]
    if debug:
        cmd.append("--debug")

    print(">>", " ".join(cmd))
    subprocess.run(cmd, check=True)


def run_repair_fast(db_path: str):
    """
    Post-export health check (read-only).
    """
    cmd = [
        sys.executable,
        "-m",
        "scripts.journal.db_inspect",
        "--db",
        db_path,
        "--schema",
        "journal",
    ]
    print(">>", " ".join(cmd))
    subprocess.run(cmd, check=True)


def main():
    args = parse_args()

    db_path = os.path.expanduser(args.db)
    if not os.path.exists(db_path):
        print(f"❌ DB not found: {db_path}")
        sys.exit(1)

    # Map aliases to primaries
    since = args.since or args.from_date
    until = args.until or args.to_date
    step_days = args.chunk_days if args.chunk_days else args.step_days
    sleep_sec = args.pace_sec if args.pace_sec else args.sleep_sec

    # Resolve date window
    if since:
        start = parse_ymd(since)
        if args.debug:
            print(f"[ARGS] start forced: {start}")
    else:
        start = detect_start(db_path, debug=args.debug)

    end = parse_ymd(until) if until else date.today()

    # Optional: clamp future end date (common operator mistake)
    if not args.allow_future_until and end > date.today():
        if args.debug:
            print(
                f"[ARGS] until {end} is in the future -> clamped to today {date.today()}"
            )
        end = date.today()

    if start > end:
        print(f"[INFO] Nothing to do: start {start} > end {end}")
        return

    step = timedelta(days=step_days)

    # Chunked export loop
    d = start
    while d <= end:
        d_to = min(d + step - timedelta(days=1), end)
        run_export_chunk(
            db_path=db_path,
            d0=d,
            d1=d_to,
            include_open_orders=args.include_open_orders,
            keep_raw=args.raw,
            debug=args.debug,
        )
        if d_to < end and sleep_sec > 0:
            time.sleep(sleep_sec)
        d = d_to + timedelta(days=1)

    if not args.no_repair:
        run_repair_fast(db_path)

    print("DONE")


if __name__ == "__main__":
    main()
