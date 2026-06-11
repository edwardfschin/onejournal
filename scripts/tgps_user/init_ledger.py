#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/tgps_user/init_ledger.py

Version: 0.3.2
Updated: 2026-01-11 (SGT)

Purpose
-------
Initialize / migrate the local user ledger DuckDB used by the "tgps-user" workflow.

Key points (DuckDB v1.4.2)
--------------------------
- We connect to an in-memory DuckDB and ATTACH the ledger file as catalog "ledger".
- We create/use schema "lcl" inside that attached catalog.
- Fully qualified references must be: ledger.lcl.<table>

This version adds a KISS root-cause fix:
- --repair-views : drops & recreates v_actions_latest to fix view-signature drift
  after actions table columns evolve.

CLI
---
python -m scripts.tgps_user.init_ledger --check
python -m scripts.tgps_user.init_ledger --repair-views --check
python -m scripts.tgps_user.init_ledger --reset
"""

from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

import duckdb

SGT = timezone(timedelta(hours=8))

# Repo root bootstrap: <repo>/scripts/tgps_user/init_ledger.py -> parents[2]
CODE_DIR = Path(__file__).resolve().parents[2]

DEFAULT_DB_PATH = str(CODE_DIR / "tgps-user" / "ledger" / "lcl.ledger.duckdb")
TARGET_SCHEMA_VERSION = "0.3"


def _now_sgt_iso() -> str:
    return datetime.now(SGT).isoformat(timespec="seconds")


def _fq_schema() -> str:
    return "ledger.lcl"


def _attach_ledger(con: duckdb.DuckDBPyConnection, db_path: str) -> str:
    db_path = os.path.expanduser(db_path)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"ATTACH '{db_path}' AS ledger;")
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {_fq_schema()};")
    return db_path


def _table_exists(con: duckdb.DuckDBPyConnection, name: str) -> bool:
    r = con.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_catalog='ledger' AND table_schema='lcl' AND table_name=?
        LIMIT 1
        """,
        [name],
    ).fetchone()
    return bool(r)


def _table_columns(con: duckdb.DuckDBPyConnection, name: str) -> List[str]:
    rows = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_catalog='ledger' AND table_schema='lcl' AND table_name=?
        ORDER BY ordinal_position
        """,
        [name],
    ).fetchall()
    return [str(r[0]) for r in rows]


def _ensure_meta_kv(con: duckdb.DuckDBPyConnection) -> None:
    """
    Ensure meta_kv schema is:
      ("key" VARCHAR PRIMARY KEY, "value" VARCHAR, updated_at VARCHAR)

    Migrates older meta_kv variants safely.
    """
    schema = _fq_schema()

    if not _table_exists(con, "meta_kv"):
        con.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.meta_kv (
              "key"        VARCHAR PRIMARY KEY,
              "value"      VARCHAR,
              updated_at   VARCHAR
            );
            """
        )
        return

    cols = _table_columns(con, "meta_kv")
    colset = set(cols)

    # Already modern?
    if "key" in colset and "value" in colset:
        if "updated_at" not in colset:
            con.execute(f"ALTER TABLE {schema}.meta_kv ADD COLUMN updated_at VARCHAR;")
        return

    # Old style k/v?
    if "k" in colset and "v" in colset:
        con.execute(f"DROP TABLE IF EXISTS {schema}.meta_kv__new;")
        con.execute(
            f"""
            CREATE TABLE {schema}.meta_kv__new (
              "key"        VARCHAR PRIMARY KEY,
              "value"      VARCHAR,
              updated_at   VARCHAR
            );
            """
        )
        con.execute(
            f"""
            INSERT INTO {schema}.meta_kv__new("key","value",updated_at)
            SELECT CAST(k AS VARCHAR), CAST(v AS VARCHAR), NULL
            FROM {schema}.meta_kv;
            """
        )
        con.execute(f"DROP TABLE {schema}.meta_kv;")
        con.execute(f"ALTER TABLE {schema}.meta_kv__new RENAME TO meta_kv;")
        return

    # Unknown legacy: best-effort stringify first 2 columns
    con.execute(f"DROP TABLE IF EXISTS {schema}.meta_kv__new;")
    con.execute(
        f"""
        CREATE TABLE {schema}.meta_kv__new (
          "key"        VARCHAR PRIMARY KEY,
          "value"      VARCHAR,
          updated_at   VARCHAR
        );
        """
    )
    if cols:
        c0 = cols[0]
        c1 = cols[1] if len(cols) > 1 else cols[0]
        con.execute(
            f"""
            INSERT INTO {schema}.meta_kv__new("key","value",updated_at)
            SELECT CAST("{c0}" AS VARCHAR), CAST("{c1}" AS VARCHAR), NULL
            FROM {schema}.meta_kv;
            """ 
        )

    con.execute(f"DROP TABLE {schema}.meta_kv;")
    con.execute(f"ALTER TABLE {schema}.meta_kv__new RENAME TO meta_kv;")


def _get_schema_version(con: duckdb.DuckDBPyConnection) -> Optional[str]:
    try:
        r = con.execute(
            f'SELECT "value" FROM {_fq_schema()}.meta_kv WHERE "key"=? LIMIT 1',
            ["schema_version"],
        ).fetchone()
        if r and r[0]:
            return str(r[0])
    except Exception:
        return None
    return None


def _set_schema_version(con: duckdb.DuckDBPyConnection, v: str) -> None:
    con.execute(
        f"""
        INSERT INTO {_fq_schema()}.meta_kv("key", "value", updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT("key") DO UPDATE SET
          "value"=excluded."value",
          updated_at=excluded.updated_at
        """,
        ["schema_version", str(v), _now_sgt_iso()],
    )


def _init_schema(con: duckdb.DuckDBPyConnection, *, reset: bool) -> None:
    schema = _fq_schema()

    if reset:
        con.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE;")
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {schema};")

    _ensure_meta_kv(con)

    # Create minimum set of tables if missing (KISS).
    # Note: we DO NOT try to remodel existing tables; we only ensure meta_kv and schema_version here.

    _set_schema_version(con, TARGET_SCHEMA_VERSION)


def _sql_default(alias: str, expr: str) -> str:
    return f"{expr} AS {alias}"


def _repair_views(con: duckdb.DuckDBPyConnection) -> None:
    """
    Root-cause fix: v_actions_latest view can break after actions table schema evolves.
    We rebuild it with an explicit, stable output column list.
    """
    schema = _fq_schema()

    if not _table_exists(con, "actions"):
        # If actions table isn't there yet, just skip quietly.
        return

    a_cols = set(_table_columns(con, "actions"))

    def sel(col: str, default_expr: str) -> str:
        # If column exists, select it, else produce a typed default.
        return col if col in a_cols else _sql_default(col, default_expr)

    # Stable key for grouping (idea_id preferred)
    if "idea_id" in a_cols:
        idea_key_expr = "COALESCE(a.idea_id, a.ticker || '|' || CAST(a.expiry AS VARCHAR) || '|' || CAST(a.strike_found AS VARCHAR))"
    elif "idea_key" in a_cols:
        idea_key_expr = "a.idea_key"
    else:
        idea_key_expr = "a.ticker || '|' || CAST(a.expiry AS VARCHAR) || '|' || CAST(a.strike_found AS VARCHAR)"

    # Drop & recreate
    con.execute(f"DROP VIEW IF EXISTS {schema}.v_actions_latest;")

    # Build SELECT list (keep it useful, but stable)
    select_list = [
        sel("action_id", "CAST(NULL AS VARCHAR)"),
        sel("created_at", "CAST(NULL AS TIMESTAMP)"),
        sel("updated_at", "CAST(NULL AS TIMESTAMP)"),
        sel("user_name", "CAST(NULL AS VARCHAR)"),
        sel("module", "CAST(NULL AS VARCHAR)"),
        sel("action", "CAST(NULL AS VARCHAR)"),
        sel("status", "CAST(NULL AS VARCHAR)"),
        sel("idea_id", "CAST(NULL AS VARCHAR)"),
        sel("ticker", "CAST(NULL AS VARCHAR)"),
        sel("expiry", "CAST(NULL AS DATE)"),
        sel("strike_found", "CAST(NULL AS DOUBLE)"),
        sel("qty_override", "CAST(NULL AS DOUBLE)"),
        sel("entry_order_type", "CAST(NULL AS VARCHAR)"),
        sel("duration", "CAST(NULL AS VARCHAR)"),
        sel("limit_price_override", "CAST(NULL AS DOUBLE)"),
        sel("exit_mode", "CAST(NULL AS VARCHAR)"),
        sel("tp_limit", "CAST(NULL AS DOUBLE)"),
        sel("stop_type", "CAST(NULL AS VARCHAR)"),
        sel("stop_price", "CAST(NULL AS DOUBLE)"),
        sel("stop_limit_price", "CAST(NULL AS DOUBLE)"),
        sel("user_notes", "CAST(NULL AS VARCHAR)"),
        sel("notes", "CAST(NULL AS VARCHAR)"),
        sel("policy_decision", "CAST(NULL AS VARCHAR)"),
        sel("policy_reasons", "CAST(NULL AS VARCHAR)"),
        sel("source_queue_path", "CAST(NULL AS VARCHAR)"),
        sel("source_queue_sha256", "CAST(NULL AS VARCHAR)"),
        sel("source_row_index", "CAST(NULL AS INTEGER)"),
        sel("action_hash", "CAST(NULL AS VARCHAR)"),
        sel("action_ts", "CAST(NULL AS TIMESTAMP)"),
        _sql_default("idea_key", idea_key_expr),
    ]

    # Ordering expressions (only reference cols that exist)
    order_terms: List[str] = []
    if "action_ts" in a_cols:
        order_terms.append("a.action_ts DESC NULLS LAST")
    if "updated_at" in a_cols:
        order_terms.append("a.updated_at DESC NULLS LAST")
    if "created_at" in a_cols:
        order_terms.append("a.created_at DESC NULLS LAST")
    if not order_terms:
        order_terms.append("1 DESC")

    sql = f"""
    CREATE VIEW {schema}.v_actions_latest AS
    WITH ranked AS (
      SELECT
        {", ".join(select_list)},
        row_number() OVER (
          PARTITION BY idea_key
          ORDER BY {", ".join(order_terms)}
        ) AS rn
      FROM {schema}.actions a
    )
    SELECT
      action_id,
      created_at,
      updated_at,
      user_name,
      module,
      action,
      status,
      idea_id,
      ticker,
      expiry,
      strike_found,
      qty_override,
      entry_order_type,
      duration,
      limit_price_override,
      exit_mode,
      tp_limit,
      stop_type,
      stop_price,
      stop_limit_price,
      COALESCE(user_notes, notes) AS user_notes,
      policy_decision,
      policy_reasons,
      source_queue_path,
      source_queue_sha256,
      source_row_index,
      action_hash,
      action_ts,
      idea_key
    FROM ranked
    WHERE rn = 1;
    """
    con.execute(sql)


def _print_diagnostics(con: duckdb.DuckDBPyConnection, db_path: str) -> None:
    print(f"[ledger] db_path: {db_path}")
    v = con.execute("select version();").fetchone()
    print(f"[ledger] duckdb_version: {v[0] if v else '(unknown)'}")

    rows = con.execute("pragma database_list;").fetchall()
    print("[ledger] databases:")
    for r in rows:
        print(f"  - {r[0]}: {r[1]} -> {r[2]}")

    rows = con.execute(
        """
        select catalog_name, schema_name
        from information_schema.schemata
        order by catalog_name, schema_name
        """
    ).fetchall()
    print("[ledger] schemas (catalog.schema):")
    for c, s in rows:
        print(f"  - {c}.{s}")

    rows = con.execute(
        """
        select table_name
        from information_schema.tables
        where table_schema='lcl' and table_catalog='ledger'
        order by table_name
        """
    ).fetchall()
    print("[ledger] tables in schema 'lcl':")
    for (t,) in rows:
        print(f"  - {t}")

    sv = _get_schema_version(con)
    print(f"[ledger] schema_version: {sv if sv is not None else '(missing)'}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Initialize/migrate the local tgps-user ledger (DuckDB).")
    ap.add_argument(
        "--db",
        default=os.environ.get("TGPS_USER_LEDGER_DB", DEFAULT_DB_PATH),
        help=f"Ledger DuckDB path (default: {DEFAULT_DB_PATH})",
    )
    ap.add_argument("--check", action="store_true", help="Check/migrate schema and print diagnostics")
    ap.add_argument("--reset", action="store_true", help="DROP schema and recreate (destructive)")
    ap.add_argument(
        "--repair-views",
        action="store_true",
        help="Drop & recreate derived views (fixes view-signature drift).",
    )
    return ap


def main() -> None:
    args = build_parser().parse_args()
    db_path = os.path.expanduser(args.db)

    con = duckdb.connect(":memory:")
    try:
        _attach_ledger(con, db_path)
        _init_schema(con, reset=bool(args.reset))

        if args.repair_views:
            _repair_views(con)

        # Optional check output (kept as before)
        if args.check or args.reset or args.repair_views:
            _print_diagnostics(con, db_path)

    finally:
        con.close()


if __name__ == "__main__":
    main()
