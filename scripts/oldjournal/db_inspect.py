#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/db_inspect.py
Version: 1.0.1
Updated: 2025-12-23 (SGT)

Purpose
-------
Quick inspection / health report for the Schwab journal DuckDB.

Important (current architecture)
--------------------------------
We DO NOT rely on a physical journal.transactions table anymore.

Source-of-truth + canonical layers:
  - journal.transactions_raw         : raw Schwab payload snapshots (by window)
  - journal.v_transactions_raw_latest: canonical deduped "transaction headers" view
  - journal.transaction_items        : normalized legs/items

This inspector therefore reports counts/ranges using transactions_raw + views.

It prints:
  - Schemas present
  - Tables & views in a given schema (default: journal)
  - Column info + constraints summary (where applicable)
  - Row counts for core relations
  - Sanity checks:
      * duplicate keys in transaction_items (should be 0)
      * null symbol counts in v_transaction_items_norm (if present)
      * basic min/max timestamps / dates

Usage
-----
    python -m scripts.journal.db_inspect --db "$DB"
    python -m scripts.journal.db_inspect --db "$DB" --schema journal
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Tuple

import duckdb


def _log(msg: str) -> None:
    print(msg, flush=True)


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Inspect DuckDB journal schema and basic health."
    )
    p.add_argument("--db", required=True, help="Path to DuckDB (e.g. $DB or $TGPS_DB).")
    p.add_argument(
        "--schema", default="journal", help="Schema to inspect (default: journal)."
    )
    return p.parse_args(argv)


def _relation_exists(conn: duckdb.DuckDBPyConnection, schema: str, name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        LIMIT 1
        """,
        [schema, name],
    ).fetchone()
    return row is not None


def _relation_type(
    conn: duckdb.DuckDBPyConnection, schema: str, name: str
) -> Optional[str]:
    row = conn.execute(
        """
        SELECT table_type
        FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        LIMIT 1
        """,
        [schema, name],
    ).fetchone()
    return row[0] if row else None


def list_schemas(conn: duckdb.DuckDBPyConnection) -> None:
    _log("== Schemas ==")
    rows = conn.execute(
        "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name;"
    ).fetchall()
    for (name,) in rows:
        _log(f"  - {name}")
    _log("")


def list_tables_and_views(conn: duckdb.DuckDBPyConnection, schema: str) -> None:
    _log(f"== Tables & Views in schema '{schema}' ==")
    tables = conn.execute(
        """
        SELECT table_name, table_type
        FROM information_schema.tables
        WHERE table_schema = ?
        ORDER BY table_name;
        """,
        [schema],
    ).fetchall()

    if not tables:
        _log(f"  (no tables/views found in schema '{schema}')\n")
        return

    for name, ttype in tables:
        _log(f"  - {name} [{ttype}]")
    _log("")


def show_relation_info(conn: duckdb.DuckDBPyConnection, schema: str, name: str) -> None:
    fq = f"{schema}.{name}"
    rtype = _relation_type(conn, schema, name)
    if rtype is None:
        return

    _log(f"== Relation info: {fq} ({rtype}) ==")

    # Columns (PRAGMA table_info works for both tables and views in DuckDB)
    try:
        cols = conn.execute(f"PRAGMA table_info('{fq}');").fetchall()
        _log("  Columns:")
        for cid, col_name, col_type, notnull, dflt, pk in cols:
            nn = "NOT NULL" if notnull else "NULL"
            pkflag = "PK" if pk else ""
            _log(f"    - {col_name}: {col_type} {nn} {pkflag}".rstrip())
    except Exception as e:
        _log(f"  Columns: ERROR ({e})")

    # Constraints (tables only)
    if rtype == "BASE TABLE":
        cons = conn.execute(
            """
            SELECT constraint_name, constraint_type
            FROM information_schema.table_constraints
            WHERE table_schema = ? AND table_name = ?
            ORDER BY constraint_type, constraint_name;
            """,
            [schema, name],
        ).fetchall()

        if cons:
            _log("  Constraints:")
            for cname, ctype in cons:
                _log(f"    - {ctype}: {cname}")
        else:
            _log("  Constraints: (none)")
    else:
        _log("  Constraints: (views have no constraints)")

    _log("")


def basic_counts(conn: duckdb.DuckDBPyConnection, schema: str) -> None:
    _log("== Basic row counts ==")

    def count_relation(rel: str) -> None:
        fq = f"{schema}.{rel}"
        if not _relation_exists(conn, schema, rel):
            _log(f"  - {fq}: (missing)")
            return
        try:
            n = conn.execute(f"SELECT COUNT(*) FROM {fq};").fetchone()[0]
            _log(f"  - {fq}: {n}")
        except Exception as e:
            _log(f"  - {fq}: ERROR ({e})")

    # Current core set
    for rel in (
        "trades",
        "transactions_raw",
        "v_transactions_raw_latest",
        "transaction_items",
        "open_orders",
        "run_log",
    ):
        count_relation(rel)

    _log("")


def time_ranges(conn: duckdb.DuckDBPyConnection, schema: str) -> None:
    _log("== Time ranges ==")

    def minmax(fq: str, expr: str, label: str) -> None:
        try:
            res = conn.execute(
                f"SELECT MIN({expr}) AS min_v, MAX({expr}) AS max_v, COUNT(*) AS n FROM {fq};"
            ).fetchone()
            _log(f"  - {label}: min={res[0]} max={res[1]} n={res[2]}")
        except Exception as e:
            _log(f"  - {label}: ERROR ({e})")

    # trades
    if _relation_exists(conn, schema, "trades"):
        minmax(f"{schema}.trades", "trade_time", f"{schema}.trades.trade_time")

    # canonical "transactions" layer: v_transactions_raw_latest
    if _relation_exists(conn, schema, "v_transactions_raw_latest"):
        # Prefer time if present; else trade_date
        cols = [
            r[0]
            for r in conn.execute(
                """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = ? AND table_name = 'v_transactions_raw_latest'
            """,
                [schema],
            ).fetchall()
        ]
        if "time" in cols:
            minmax(
                f"{schema}.v_transactions_raw_latest",
                "time",
                f"{schema}.v_transactions_raw_latest.time",
            )
        elif "trade_date" in cols:
            minmax(
                f"{schema}.v_transactions_raw_latest",
                "trade_date",
                f"{schema}.v_transactions_raw_latest.trade_date",
            )

    # raw coverage windows (from_iso/to_iso are strings)
    if _relation_exists(conn, schema, "transactions_raw"):
        minmax(
            f"{schema}.transactions_raw",
            "CAST(SUBSTR(from_iso, 1, 10) AS DATE)",
            f"{schema}.transactions_raw.from_iso(date)",
        )
        minmax(
            f"{schema}.transactions_raw",
            "CAST(SUBSTR(to_iso, 1, 10) AS DATE)",
            f"{schema}.transactions_raw.to_iso(date)",
        )

    # open orders
    if _relation_exists(conn, schema, "open_orders"):
        minmax(
            f"{schema}.open_orders", "captured_at", f"{schema}.open_orders.captured_at"
        )

    _log("")


def sanity_unique_keys(conn: duckdb.DuckDBPyConnection, schema: str) -> None:
    _log("== transaction_items unique-key sanity ==")
    fq = f"{schema}.transaction_items"
    if not _relation_exists(conn, schema, "transaction_items"):
        _log(f"  - {fq}: (missing)\n")
        return

    try:
        n_dups = conn.execute(
            f"""
            SELECT COUNT(*) FROM (
              SELECT account_hash, activity_id, leg_index, COUNT(*) AS n
              FROM {fq}
              GROUP BY 1,2,3
              HAVING COUNT(*) > 1
            ) x
            """
        ).fetchone()[0]
        _log(f"  - Duplicate (account_hash, activity_id, leg_index) groups: {n_dups}")
    except Exception as e:
        _log(f"  - ERROR ({e})")

    _log("")


def sanity_norm_view(conn: duckdb.DuckDBPyConnection, schema: str) -> None:
    _log("== v_transaction_items_norm sanity ==")
    view_name = "v_transaction_items_norm"

    if not _relation_exists(conn, schema, view_name):
        _log(f"  - {schema}.{view_name} does not exist (skip).")
        _log("")
        return

    # Discover columns and pick the best "symbol-ish" field available
    cols = [
        r[0]
        for r in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = ? AND table_name = ?
            ORDER BY ordinal_position
            """,
            [schema, view_name],
        ).fetchall()
    ]
    colset = set(cols)

    # Priority order (best first)
    candidates = [
        "symbol_norm",
        "instrument_underlying_symbol",
        "instrument_root_symbol",
        "any_symbol",
        "symbol",
    ]
    sym_col = next((c for c in candidates if c in colset), None)

    try:
        n_total = conn.execute(
            f"SELECT COUNT(*) FROM {schema}.{view_name};"
        ).fetchone()[0]
        _log(f"  - rows: {n_total}")
    except Exception as e:
        _log(f"  - ERROR (count): {e}")
        _log("")
        return

    if not sym_col:
        _log(
            f"  - No known symbol column found. Available columns include: {', '.join(cols[:12])}{'...' if len(cols)>12 else ''}"
        )
        _log("")
        return

    # Null/blank check using the chosen column
    try:
        n_null = conn.execute(
            f"""
            SELECT COUNT(*)
            FROM {schema}.{view_name}
            WHERE {sym_col} IS NULL
               OR TRIM(CAST({sym_col} AS VARCHAR)) = ''
            """
        ).fetchone()[0]
        _log(f"  - symbol column used: {sym_col}")
        _log(f"  - rows with {sym_col} IS NULL/blank: {n_null}")
    except Exception as e:
        _log(f"  - ERROR (null check on {sym_col}): {e}")
        _log("")
        return

    # Optional: show top symbols
    try:
        rows = conn.execute(
            f"""
            SELECT {sym_col} AS sym, COUNT(*) AS n
            FROM {schema}.{view_name}
            GROUP BY 1
            ORDER BY n DESC
            LIMIT 20
            """
        ).fetchall()
        _log("  - Top symbols (sym, n):")
        for sym, n in rows:
            _log(f"    * {sym!r}: {n}")
    except Exception:
        pass

    _log("")


def main(argv: List[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    _log(f"[inspect] Opening DuckDB at {args.db}")
    conn = duckdb.connect(args.db)
    try:
        list_schemas(conn)
        list_tables_and_views(conn, args.schema)

        # Core relations (tables + views) we care about now
        for rel in (
            "trades",
            "transactions_raw",
            "v_transactions_raw_latest",
            "transaction_items",
            "open_orders",
            "run_log",
        ):
            if _relation_exists(conn, args.schema, rel):
                show_relation_info(conn, args.schema, rel)

        basic_counts(conn, args.schema)
        time_ranges(conn, args.schema)
        sanity_unique_keys(conn, args.schema)
        sanity_norm_view(conn, args.schema)

        _log("[inspect] Done.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
