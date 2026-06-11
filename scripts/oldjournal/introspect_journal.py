#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/introspect_journal.py
Version: 1.0.0
Updated: 2025-11-19 (SGT)

Purpose
-------
Dump the structure of the DuckDB journal database:

- DuckDB version
- Schemas
- Tables & views
- Columns for all journal.* tables
- Constraints (PK/UNIQUE/CHECK)
- Foreign-key relationships (if any)
- Indexes via duckdb_indexes() if available
"""

from __future__ import annotations

import argparse
import os

import duckdb


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Inspect DuckDB journal structure (schemas, tables, columns, constraints)."
    )
    p.add_argument(
        "--db",
        default=os.path.expanduser("~/tgps-project/data/journal/tgps_trades.duckdb"),
        help="Path to DuckDB file",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    db_path = os.path.expanduser(args.db)

    if not os.path.exists(db_path):
        raise SystemExit(f"❌ DB not found: {db_path}")

    con = duckdb.connect(db_path)
    try:
        print("=== DuckDB version ===")
        print(con.execute("SELECT version();").fetchdf())
        print()

        print("=== Schemas ===")
        print(
            con.execute(
                "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name;"
            ).fetchdf()
        )
        print()

        print("=== Tables & views (all schemas) ===")
        print(
            con.execute(
                """
                SELECT table_schema, table_name, table_type
                FROM information_schema.tables
                ORDER BY table_schema, table_name;
                """
            ).fetchdf()
        )
        print()

        # journal.* tables
        print("=== Columns for journal.* tables ===")
        journal_tables = con.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'journal'
            ORDER BY table_name;
            """
        ).fetchall()

        for (tbl,) in journal_tables:
            print(f"-- journal.{tbl}")
            df_cols = con.execute(
                f"PRAGMA table_info('journal.{tbl}')"
            ).fetchdf()
            print(df_cols)
            print()

        print("=== Constraints in journal.* ===")
        print(
            con.execute(
                """
                SELECT
                  table_name,
                  constraint_name,
                  constraint_type
                FROM information_schema.table_constraints
                WHERE table_schema = 'journal'
                ORDER BY table_name, constraint_name;
                """
            ).fetchdf()
        )
        print()

        print("=== Foreign keys in journal.* (if any) ===")
        print(
            con.execute(
                """
                SELECT
                  rc.constraint_name,
                  tc_fk.table_name AS fk_table,
                  tc_pk.table_name AS pk_table
                FROM information_schema.referential_constraints rc
                JOIN information_schema.table_constraints tc_fk
                  ON rc.constraint_name     = tc_fk.constraint_name
                 AND rc.constraint_schema   = tc_fk.constraint_schema
                JOIN information_schema.table_constraints tc_pk
                  ON rc.unique_constraint_name   = tc_pk.constraint_name
                 AND rc.unique_constraint_schema = tc_pk.constraint_schema
                WHERE rc.constraint_schema = 'journal'
                ORDER BY rc.constraint_name;
                """
            ).fetchdf()
        )
        print()

        print("=== Indexes on journal.* (duckdb_indexes) ===")
        try:
            print(
                con.execute(
                    """
                    SELECT *
                    FROM duckdb_indexes()
                    WHERE schema_name = 'journal'
                    ORDER BY table_name, index_name;
                    """
                ).fetchdf()
            )
        except duckdb.Error as e:
            print(f"(duckdb_indexes() not available in this DuckDB build: {e})")

    finally:
        con.close()


if __name__ == "__main__":
    main()
