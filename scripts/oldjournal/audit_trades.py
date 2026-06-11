#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/audit_trades.py
Version: 2.0.0 (2025-11-20, SGT)

Purpose
-------
Quick health-checks for the Schwab Trade Journal DuckDB store.

Aligned with the current schema:

    DB:     ~/tgps-project/data/journal/tgps_trades.duckdb
    Schema: journal
    Table:  journal.trades

Checks performed:
  1) Table exists and has rows
  2) Window bounds & row count (optional --from/--to)
  3) Year-by-year coverage
  4) Duplicate detection (by MERGE_KEY)
  5) Nulls in core columns
  6) Option-detail presence
  7) Optional sample rows

CLI examples
------------
    # Default DB, full history
    python -m scripts.journal.audit_trades

    # Audit a specific window
    python -m scripts.journal.audit_trades --from 2025-01-01 --to 2025-11-19

    # Show duplicate groups summary and exit with 1 on any FAIL
    python -m scripts.journal.audit_trades --show-dups --strict
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from typing import Optional, Tuple

import duckdb
import pandas as pd

DEFAULT_DB = os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb")
SCHEMA = "journal"
TABLE = "trades"  # we will always refer to it as journal.trades
MERGE_KEY = ["account_hash", "order_id", "exec_id", "trade_time", "symbol", "qty", "price"]


# --- Pretty printing ----------------------------------------------------------
class C:
    G = "\033[92m"   # green
    Y = "\033[93m"   # yellow
    R = "\033[91m"   # red
    B = "\033[94m"   # blue
    D = "\033[0m"    # default


def ok(msg: str) -> None:
    print(f"{C.G}✔{C.D} {msg}")


def info(msg: str) -> None:
    print(f"{C.B}•{C.D} {msg}")


def warn(msg: str) -> None:
    print(f"{C.Y}!{C.D} {msg}")


def fail(msg: str) -> None:
    print(f"{C.R}✘{C.D} {msg}")


# --- Window handling ----------------------------------------------------------
@dataclass
class Window:
    date_from: Optional[str] = None
    date_to: Optional[str] = None

    def to_sql_clause(self) -> str:
        """
        Returns a WHERE clause on trade_time for journal.trades.

        Uses inclusive date window:
          [date_from 00:00:00, date_to 23:59:59.999]
        """
        if self.date_from and self.date_to:
            return (
                f"WHERE trade_time BETWEEN TIMESTAMP '{self.date_from} 00:00:00' "
                f"AND TIMESTAMP '{self.date_to} 23:59:59.999'"
            )
        elif self.date_from:
            return f"WHERE trade_time >= TIMESTAMP '{self.date_from} 00:00:00'"
        elif self.date_to:
            return f"WHERE trade_time <= TIMESTAMP '{self.date_to} 23:59:59.999'"
        return ""


# --- Small helpers ------------------------------------------------------------
def table_exists(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    sql = """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?;
    """
    (cnt,) = con.execute(sql, [schema, table]).fetchone()
    return cnt > 0


def one(con: duckdb.DuckDBPyConnection, sql: str, params: Tuple = ()) -> Optional[tuple]:
    cur = con.execute(sql, params)
    return cur.fetchone()


def df(con: duckdb.DuckDBPyConnection, sql: str) -> pd.DataFrame:
    return con.execute(sql).df()


def fq_table() -> str:
    """Return fully-qualified table name."""
    return f"{SCHEMA}.{TABLE}"


# --- Checks -------------------------------------------------------------------
def check_table_and_rows(con: duckdb.DuckDBPyConnection) -> bool:
    if not table_exists(con, SCHEMA, TABLE):
        fail(f"Table '{fq_table()}' does not exist.")
        return False
    count = one(con, f"SELECT COUNT(*) FROM {fq_table()};")[0]
    if count <= 0:
        fail(f"Table '{fq_table()}' has 0 rows.")
        return False
    ok(f"Table '{fq_table()}' exists, rows={count}.")
    return True


def check_bounds_and_total(con: duckdb.DuckDBPyConnection, win: Window) -> None:
    where = win.to_sql_clause()
    row = one(
        con,
        f"SELECT MIN(trade_time), MAX(trade_time), COUNT(*) FROM {fq_table()} {where};",
    )
    first, last, cnt = row
    if cnt == 0:
        warn("Selected window has 0 rows.")
    else:
        ok(f"Window rows={cnt}")
    info(f"First trade: {first}")
    info(f"Last  trade: {last}")


def check_yearly(con: duckdb.DuckDBPyConnection, win: Window) -> None:
    where = win.to_sql_clause()
    t = df(
        con,
        f"""
        SELECT
          strftime(trade_time, '%Y') AS yr,
          COUNT(*)                   AS rows
        FROM {fq_table()}
        {where}
        GROUP BY yr
        ORDER BY yr;
        """,
    )
    if t.empty:
        warn("No rows for yearly coverage (empty window?).")
    else:
        print("\nYearly coverage (rows per year):")
        print(t.to_string(index=False))

def check_freshness(con: duckdb.DuckDBPyConnection) -> None:
    """
    Simple freshness check: how far behind today is journal.trades?
    Uses the max(trade_time::date) across the whole table (ignores window).
    """
    row = one(
        con,
        f"SELECT MAX(trade_time::date) AS last_date FROM {fq_table()};",
    )

    last_date = row[0] if row else None
    if last_date is None:
        warn("Freshness: no trades found when checking last_date.")
        return

    # Use DuckDB to get CURRENT_DATE so it stays DB-driven
    today = one(con, "SELECT CURRENT_DATE;")[0]
    delta_days = (today - last_date).days

    if delta_days == 0:
        ok(f"Freshness: journal.trades is up to TODAY ({last_date}).")
    elif delta_days == 1:
        warn(
            f"Freshness: last trade date = {last_date} "
            f"(1 day behind today {today})."
        )
    else:
        fail(
            f"Freshness: last trade date = {last_date} "
            f"({delta_days} days behind today {today})."
        )


def check_duplicates(con: duckdb.DuckDBPyConnection) -> bool:
    key_cols = ", ".join(MERGE_KEY)
    t = df(
        con,
        f"""
        WITH grp AS (
          SELECT {key_cols}, COUNT(*) AS cnt
          FROM {fq_table()}
          GROUP BY {key_cols}
          HAVING COUNT(*) > 1
        )
        SELECT
          COUNT(*)        AS duplicate_groups,
          COALESCE(SUM(cnt), 0) AS duplicate_rows
        FROM grp;
        """,
    )

    if t.empty:
        # Should not happen because SELECT always returns one row,
        # but guard anyway.
        ok("No duplicate MERGE_KEY groups detected.")
        return True

    duplicate_groups = int((t["duplicate_groups"].iloc[0] or 0))
    duplicate_rows = int((t["duplicate_rows"].iloc[0] or 0))

    if duplicate_groups == 0:
        ok("No duplicate MERGE_KEY groups detected.")
        return True
    else:
        fail(f"Found {duplicate_groups} duplicate groups, {duplicate_rows} duplicate rows.")
        return False



def show_duplicates(con: duckdb.DuckDBPyConnection) -> None:
    key_cols = ", ".join(MERGE_KEY)
    t = df(
        con,
        f"""
        WITH grp AS (
          SELECT {key_cols}, COUNT(*) AS cnt
          FROM {fq_table()}
          GROUP BY {key_cols}
          HAVING COUNT(*) > 1
        )
        SELECT *
        FROM {fq_table()} t
        JOIN grp USING ({key_cols})
        ORDER BY trade_time;
        """,
    )
    if t.empty:
        info("No duplicates to show.")
    else:
        print("\nDuplicate rows detail:")
        print(t.to_string(index=False))


def check_nulls(con: duckdb.DuckDBPyConnection, win: Window) -> bool:
    where = win.to_sql_clause()
    row = one(
        con,
        f"""
        SELECT
          SUM(CASE WHEN trade_time IS NULL              THEN 1 ELSE 0 END),
          SUM(CASE WHEN symbol    IS NULL OR symbol=''  THEN 1 ELSE 0 END),
          SUM(CASE WHEN side      IS NULL OR side=''    THEN 1 ELSE 0 END),
          SUM(CASE WHEN qty       IS NULL               THEN 1 ELSE 0 END),
          SUM(CASE WHEN price     IS NULL               THEN 1 ELSE 0 END)
        FROM {fq_table()} {where};
        """,
    )
    if row is None:
        warn("No rows when checking nulls (empty window?).")
        return True
    n_time, n_symbol, n_side, n_qty, n_price = row
    labels = ["trade_time", "symbol", "side", "qty", "price"]
    counts = [n_time, n_symbol, n_side, n_qty, n_price]
    bad = [(lbl, cnt) for lbl, cnt in zip(labels, counts) if cnt and cnt > 0]
    if not bad:
        ok("No NULLs found in core columns.")
        return True
    else:
        for lbl, cnt in bad:
            fail(f"{lbl}: {cnt} NULL/empty values.")
        return False


def check_option_presence(con: duckdb.DuckDBPyConnection, win: Window) -> None:
    where = win.to_sql_clause()
    t = df(
        con,
        f"""
        SELECT
          COUNT(*)                                      AS total_rows,
          SUM(CASE WHEN put_call IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_put_call,
          SUM(CASE WHEN expiry   IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_expiry,
          SUM(CASE WHEN strike   IS NOT NULL THEN 1 ELSE 0 END) AS rows_with_strike
        FROM {fq_table()} {where};
        """,
    )
    if t.empty:
        warn("No rows for option-detail presence (empty window?).")
        return
    row = t.iloc[0]
    info(
        "Option-detail presence: "
        f"put_call={row['rows_with_put_call']}/{row['total_rows']}, "
        f"expiry={row['rows_with_expiry']}/{row['total_rows']}, "
        f"strike={row['rows_with_strike']}/{row['total_rows']}"
    )


def show_sample(con: duckdb.DuckDBPyConnection, win: Window, n: int) -> None:
    where = win.to_sql_clause()
    t = df(
        con,
        f"""
        SELECT
          trade_time,
          symbol,
          asset_type,
          side,
          qty,
          price,
          amount,
          fees,
          put_call,
          expiry,
          strike
        FROM {fq_table()}
        {where}
        ORDER BY trade_time
        LIMIT {int(n)};
        """,
    )
    if t.empty:
        warn("No rows to sample.")
    else:
        print(f"\nSample {len(t)} rows:")
        print(t.to_string(index=False))


# --- Main ---------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(
        description="Audit journal.trades in tgps_trades.duckdb"
    )
    ap.add_argument(
        "--db",
        default=DEFAULT_DB,
        help="Path to DuckDB file (default: %(default)s)",
    )
    ap.add_argument(
        "--from",
        dest="date_from",
        default="",
        help="Start date (YYYY-MM-DD). Default: earliest trade_time.",
    )
    ap.add_argument(
        "--to",
        dest="date_to",
        default="",
        help="End date (YYYY-MM-DD). Default: latest trade_time.",
    )
    ap.add_argument(
        "--sample",
        type=int,
        default=0,
        help="Print N sample rows from the window.",
    )
    ap.add_argument(
        "--show-dups",
        action="store_true",
        help="Print duplicate groups detail.",
    )
    ap.add_argument(
        "--strict",
        action="store_true",
        help="Exit with code 1 if any FAIL is encountered.",
    )
    ap.add_argument(
        "--verbose",
        action="store_true",
        help="Extra info prints.",
    )
    args = ap.parse_args()

    db_path = os.path.expanduser(args.db)
    if not os.path.exists(db_path):
        fail(f"DuckDB file not found: {db_path}")
        sys.exit(1)

    con = duckdb.connect(db_path)

    hard_fail = False

    # Determine window
    win = Window(
        date_from=args.date_from or None,
        date_to=args.date_to or None,
    )

    if args.verbose:
        info(f"Using DB: {db_path}")
        info(f"Schema.table: {fq_table()}")
        info(f"Window: from={win.date_from}, to={win.date_to}")

    # 1) table + total rows
    if not check_table_and_rows(con):
        hard_fail = True

    # 2) bounds + rows in scope
    check_bounds_and_total(con, win)

    # 3) yearly coverage
    check_yearly(con, win)

    # 3b) freshness vs today (global, ignores window)
    check_freshness(con)

    # 4) duplicates
    has_no_dups = check_duplicates(con)
    if not has_no_dups:
        hard_fail = True
    if args.show_dups:
        show_duplicates(con)

    # 5) nulls in core columns
    if not check_nulls(con, win):
        hard_fail = True

    # 6) option-detail presence
    check_option_presence(con, win)

    # 7) sample rows
    if args.sample and args.sample > 0:
        show_sample(con, win, args.sample)

    con.close()

    if args.strict and hard_fail:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
