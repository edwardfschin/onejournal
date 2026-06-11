#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
scripts/journal/ingest_acct_activity.py
Version: 1.0.1 (auto-migrate schema + robust raw ingest)

Why this exists
---------------
Schwab streamer payload shapes evolve (OTOCO/OCO, equity vs options, nested price objects, etc).
This ingester stores raw account-activity events WITHOUT brittle casts so your session won't crash.

It also auto-migrates journal.acct_activity_raw if the table already exists with older columns.
"""

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

import duckdb

SCHEMA = "journal"
TABLE = "acct_activity_raw"
FQN = f"{SCHEMA}.{TABLE}"

# Desired columns (additive; safe to add if missing)
DESIRED_COLS: List[Tuple[str, str]] = [
    ("ingested_at", "TIMESTAMP"),
    ("stream_file", "TEXT"),
    ("seq", "BIGINT"),
    ("stream_key", "TEXT"),
    ("account_number", "TEXT"),
    ("event_type", "TEXT"),
    ("payload_text", "TEXT"),
    ("payload_json", "JSON"),
]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _table_exists(con: duckdb.DuckDBPyConnection) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*) 
        FROM information_schema.tables
        WHERE table_schema = ? AND table_name = ?
        """,
        [SCHEMA, TABLE],
    ).fetchone()
    return bool(row and row[0] > 0)


def _get_existing_cols(con: duckdb.DuckDBPyConnection) -> Dict[str, str]:
    rows = con.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ?
        ORDER BY ordinal_position
        """,
        [SCHEMA, TABLE],
    ).fetchall()
    return {str(r[0]): str(r[1]) for r in rows}


def ensure_schema_and_table(con: duckdb.DuckDBPyConnection, debug: bool = False) -> None:
    con.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA};")

    if not _table_exists(con):
        # Fresh create with latest schema
        con.execute(
            f"""
            CREATE TABLE {FQN} (
                ingested_at    TIMESTAMP,
                stream_file    TEXT,
                seq            BIGINT,
                stream_key     TEXT,
                account_number TEXT,
                event_type     TEXT,
                payload_text   TEXT,
                payload_json   JSON
            );
            """
        )
        if debug:
            print(f"[schema] created {FQN}")
        return

    # Table exists: migrate additively
    existing = _get_existing_cols(con)
    if debug:
        print(f"[schema] {FQN} exists; columns={list(existing.keys())}")

    for col, coltype in DESIRED_COLS:
        if col not in existing:
            con.execute(f"ALTER TABLE {FQN} ADD COLUMN {col} {coltype};")
            if debug:
                print(f"[schema] added column {col} {coltype}")


def _build_insert_sql(existing_cols: Dict[str, str]) -> Tuple[str, List[str]]:
    """
    Build an INSERT that targets only columns that actually exist.
    payload_json uses TRY_CAST(? AS JSON) to avoid hard failures.
    """
    desired_names = [c for c, _t in DESIRED_COLS]
    cols_to_use = [c for c in desired_names if c in existing_cols]

    values_expr: List[str] = []
    for c in cols_to_use:
        if c == "payload_json":
            values_expr.append("TRY_CAST(? AS JSON)")
        else:
            values_expr.append("?")

    cols_sql = ", ".join(cols_to_use)
    vals_sql = ", ".join(values_expr)
    sql = f"INSERT INTO {FQN} ({cols_sql}) VALUES ({vals_sql});"
    return sql, cols_to_use


def ingest_file(db_path: str, ndjson_path: str, debug: bool = False) -> int:
    p = Path(ndjson_path)
    if not p.exists():
        raise FileNotFoundError(f"NDJSON file not found: {ndjson_path}")

    con = duckdb.connect(db_path)
    try:
        ensure_schema_and_table(con, debug=debug)
        existing = _get_existing_cols(con)
        insert_sql, cols_to_use = _build_insert_sql(existing)

        if debug:
            print(f"[ingest] insert columns={cols_to_use}")

        inserted = 0
        ingested_at = datetime.now(timezone.utc).replace(tzinfo=None)  # DuckDB TIMESTAMP tz-naive

        with p.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue

                try:
                    outer = json.loads(line)
                except Exception as e:
                    if debug:
                        print(f"[warn] outer JSON parse failed line={line_no}: {e}")
                    continue

                seq = outer.get("seq")
                stream_key = outer.get("key")
                account_number = outer.get("1")
                event_type = outer.get("2")
                payload_text = outer.get("3")

                payload_json_str = None
                if isinstance(payload_text, str) and payload_text.strip():
                    # Validate inner JSON (it's an escaped JSON string inside the outer JSON)
                    try:
                        json.loads(payload_text)
                        payload_json_str = payload_text
                    except Exception as e:
                        if debug:
                            print(f"[warn] inner JSON invalid line={line_no}: {e}")

                # Build params aligned to cols_to_use
                params = []
                for c in cols_to_use:
                    if c == "ingested_at":
                        params.append(ingested_at)
                    elif c == "stream_file":
                        params.append(str(p))
                    elif c == "seq":
                        params.append(None if seq is None else int(seq))
                    elif c == "stream_key":
                        params.append(None if stream_key is None else str(stream_key))
                    elif c == "account_number":
                        params.append(None if account_number is None else str(account_number))
                    elif c == "event_type":
                        params.append(None if event_type is None else str(event_type))
                    elif c == "payload_text":
                        params.append(None if payload_text is None else str(payload_text))
                    elif c == "payload_json":
                        params.append(payload_json_str)  # TRY_CAST handles None/invalid
                    else:
                        params.append(None)

                con.execute(insert_sql, params)
                inserted += 1

        if debug:
            print(f"[ingest] db={db_path}")
            print(f"[ingest] file={ndjson_path}")
            print(f"[ingest] inserted={inserted} at={_utc_now_iso()}")

        return inserted
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.environ.get("TGPS_DB", ""), help="DuckDB path")
    ap.add_argument("--file", "--ndjson", dest="ndjson", required=True, help="acct_activity_*.ndjson")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    db_path = args.db.strip()
    if not db_path:
        raise SystemExit("Missing --db (or set TGPS_DB)")

    inserted = ingest_file(db_path=db_path, ndjson_path=args.ndjson, debug=args.debug)
    print(f"[ingest_acct_activity] OK inserted={inserted}")


if __name__ == "__main__":
    main()
