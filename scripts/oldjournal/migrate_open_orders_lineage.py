#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/migrate_open_orders_lineage.py
Version: 0.1.0
Updated: 2025-12-23 (SGT)

Purpose
-------
1) Ensure lineage columns exist:
   - parent_order_id  (BIGINT)
   - root_order_id    (BIGINT)
   - depth            (INTEGER)

in:
   - journal.open_orders_live
   - journal.open_orders_snapshots

2) Backfill lineage using the latest journal.orders_raw payload.
   (Works even if the API does not provide parentOrderId fields; we infer it from
    the childOrderStrategies nesting.)

Run
---
python -m scripts.journal.migrate_open_orders_lineage
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import duckdb
import pandas as pd


def get_db_path() -> str:
    default = os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb")
    return os.environ.get("TGPS_JOURNAL_DB", default)


def _table_exists(con: duckdb.DuckDBPyConnection, fq: str) -> bool:
    # fq like "journal.open_orders_live"
    if "." not in fq:
        return False
    schema, name = fq.split(".", 1)
    row = con.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        LIMIT 1;
        """,
        [schema, name],
    ).fetchone()
    return bool(row)


def _get_columns(con: duckdb.DuckDBPyConnection, fq: str) -> List[str]:
    # PRAGMA table_info wants unquoted string; schema-qualified works in DuckDB
    rows = con.execute(f"PRAGMA table_info('{fq}');").fetchall()
    # rows: (cid, name, type, notnull, dflt_value, pk)
    return [r[1] for r in rows]


def _add_column_if_missing(
    con: duckdb.DuckDBPyConnection,
    fq: str,
    col: str,
    col_type: str,
) -> None:
    cols = _get_columns(con, fq)
    if col in cols:
        return
    con.execute(f"ALTER TABLE {fq} ADD COLUMN {col} {col_type};")
    print(f"[migrate] Added column {fq}.{col} {col_type}")


def _read_latest_orders_raw_payload(con: duckdb.DuckDBPyConnection) -> Optional[str]:
    row = con.execute(
        """
        SELECT CAST(payload AS VARCHAR) AS payload_json
        FROM journal.orders_raw
        ORDER BY fetched_at DESC
        LIMIT 1;
        """
    ).fetchone()
    return row[0] if row else None


def _iter_order_tree(
    orders: Iterable[Dict[str, Any]],
) -> Iterator[Tuple[Dict[str, Any], Optional[int], Optional[int], int]]:
    """
    Yield: (order_obj, parent_order_id, root_order_id, depth)
    root_order_id is the top-most orderId in that tree.
    """

    def walk(
        ord_obj: Dict[str, Any],
        parent_id: Optional[int],
        root_id: Optional[int],
        depth: int,
    ) -> Iterator[Tuple[Dict[str, Any], Optional[int], Optional[int], int]]:
        oid = ord_obj.get("orderId")
        try:
            oid_int = int(oid) if oid is not None else None
        except Exception:
            oid_int = None

        if root_id is None:
            root_id = oid_int

        yield ord_obj, parent_id, root_id, depth

        children = ord_obj.get("childOrderStrategies") or []
        if isinstance(children, list) and children:
            for ch in children:
                if isinstance(ch, dict):
                    yield from walk(ch, oid_int, root_id, depth + 1)

    for top in orders:
        if not isinstance(top, dict):
            continue
        top_oid = top.get("orderId")
        try:
            top_oid_int = int(top_oid) if top_oid is not None else None
        except Exception:
            top_oid_int = None
        yield from walk(top, None, top_oid_int, 0)


def _build_lineage_map(payload_json: str) -> pd.DataFrame:
    payload = json.loads(payload_json)
    if not isinstance(payload, list):
        raise RuntimeError("orders_raw.payload is not a JSON array")

    rows: List[Dict[str, Any]] = []
    for ord_obj, parent_id, root_id, depth in _iter_order_tree(payload):
        oid = ord_obj.get("orderId")
        try:
            oid_int = int(oid) if oid is not None else None
        except Exception:
            oid_int = None
        if oid_int is None:
            continue
        rows.append(
            {
                "order_id": oid_int,
                "parent_order_id": parent_id,
                "root_order_id": root_id,
                "depth": int(depth),
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=["order_id", "parent_order_id", "root_order_id", "depth"]
        )

    df = pd.DataFrame(rows).drop_duplicates(subset=["order_id"]).copy()

    # Nullable integer dtypes (DuckDB will see NULLs correctly)
    df["order_id"] = pd.to_numeric(df["order_id"], errors="coerce").astype("Int64")
    df["parent_order_id"] = pd.to_numeric(
        df["parent_order_id"], errors="coerce"
    ).astype("Int64")
    df["root_order_id"] = pd.to_numeric(df["root_order_id"], errors="coerce").astype(
        "Int64"
    )
    df["depth"] = pd.to_numeric(df["depth"], errors="coerce").fillna(0).astype("Int64")

    return df


def _backfill(
    con: duckdb.DuckDBPyConnection,
    df_map: pd.DataFrame,
) -> None:
    if df_map.empty:
        print("[migrate] Lineage map is empty; nothing to backfill.")
        return

    con.register("order_lineage_map", df_map)

    if _table_exists(con, "journal.open_orders_live"):
        con.execute(
            """
            UPDATE journal.open_orders_live AS t
            SET
                parent_order_id = m.parent_order_id,
                root_order_id   = m.root_order_id,
                depth           = m.depth
            FROM order_lineage_map AS m
            WHERE t.order_id = m.order_id;
            """
        )
        print("[migrate] Backfilled journal.open_orders_live")

    if _table_exists(con, "journal.open_orders_snapshots"):
        con.execute(
            """
            UPDATE journal.open_orders_snapshots AS t
            SET
                parent_order_id = m.parent_order_id,
                root_order_id   = m.root_order_id,
                depth           = m.depth
            FROM order_lineage_map AS m
            WHERE t.order_id = m.order_id
              AND t.snapshot_ts >= now() - INTERVAL '60 days';
            """
        )
        print("[migrate] Backfilled journal.open_orders_snapshots (last 60 days)")

    con.unregister("order_lineage_map")


def main() -> None:
    db_path = get_db_path()
    con = duckdb.connect(db_path)

    for fq in ["journal.open_orders_live", "journal.open_orders_snapshots"]:
        if not _table_exists(con, fq):
            print(f"[migrate] Skip (table missing): {fq}")
            continue
        _add_column_if_missing(con, fq, "parent_order_id", "BIGINT")
        _add_column_if_missing(con, fq, "root_order_id", "BIGINT")
        _add_column_if_missing(con, fq, "depth", "INTEGER")

    payload_json = _read_latest_orders_raw_payload(con)
    if not payload_json:
        print("[migrate] No orders_raw payload found; done.")
        return

    df_map = _build_lineage_map(payload_json)
    print(f"[migrate] Lineage map rows: {len(df_map)}")

    _backfill(con, df_map)

    # Quick sanity print
    if _table_exists(con, "journal.open_orders_live"):
        r = con.execute(
            """
            SELECT
              COUNT(*) AS rows,
              SUM(CASE WHEN depth > 0 AND parent_order_id IS NULL THEN 1 ELSE 0 END) AS missing_parent,
              SUM(CASE WHEN parent_order_id IS NOT NULL THEN 1 ELSE 0 END) AS parent_filled
            FROM journal.open_orders_live;
            """
        ).fetchone()
        print(
            f"[migrate] open_orders_live rows={r[0]} missing_parent={r[1]} parent_filled={r[2]}"
        )


if __name__ == "__main__":
    main()
