#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/journal/rebuild_db.py
Version: 1.2.0
Updated: 2025-12-21 (SGT)

Purpose
-------
Rebuild a DuckDB database into a new file, copying tables + views,
optionally excluding specific objects (e.g., journal.transactions).

Compatibility
-------------
- DuckDB v1.4.x: duckdb_sequences() does NOT include an "internal" column.
  This script introspects the available columns and filters only when present.

Key improvements
----------------
- DETACH old DB before creating views (prevents accidental resolution via old.*).
- View creation is dependency-safe via multi-pass retries:
  it will keep retrying failed views until their dependencies exist.

Usage
-----
python -m scripts.journal.rebuild_db \
  --old "$HOME/tgps-project/data/journal/tgps_trades.duckdb" \
  --new "$HOME/tgps-project/data/journal/tgps_trades_no_transactions.duckdb" \
  --exclude journal.transactions \
  --overwrite
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

import duckdb


IDENT_BOUNDARY = r"[A-Za-z0-9_]"
NEXTVAL_RE = re.compile(r"(?i)nextval\s*\(\s*'([^']+)'\s*\)")


def _norm_excludes(excludes: Sequence[str]) -> List[str]:
    out: List[str] = []
    for x in excludes:
        x = (x or "").strip()
        if x:
            out.append(x)
    return out


def ddl_mentions_excluded(ddl: str, excluded_fqns: Sequence[str]) -> bool:
    """
    Identifier-safe match:
      - 'journal.transactions' matches 'journal.transactions'
      - does NOT match 'journal.transactions_raw'
    """
    s = ddl or ""
    for fqn in excluded_fqns:
        pat = re.compile(
            rf"(?i)(?<!{IDENT_BOUNDARY}){re.escape(fqn)}(?!{IDENT_BOUNDARY})"
        )
        if pat.search(s):
            return True
    return False


def extract_nextval_sequences(table_ddl: str) -> Set[str]:
    seqs: Set[str] = set()
    if not table_ddl:
        return seqs
    for m in NEXTVAL_RE.finditer(table_ddl):
        seqs.add(m.group(1))
    return seqs


def split_qualified(name: str) -> Tuple[Optional[str], str]:
    if "." in name:
        a, b = name.split(".", 1)
        return a.strip() or None, b.strip()
    return None, name.strip()


def qident(name: str) -> str:
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    return f'"{name.replace(chr(34), chr(34) + chr(34))}"'


def fq(schema: Optional[str], obj: str) -> str:
    if schema:
        return f"{qident(schema)}.{qident(obj)}"
    return qident(obj)


def relation_columns(con: duckdb.DuckDBPyConnection, rel_sql: str) -> List[str]:
    cur = con.execute(f"SELECT * FROM {rel_sql} LIMIT 0")
    return [d[0] for d in cur.description]  # type: ignore[index]


def is_system_schema(schema_name: str) -> bool:
    return schema_name.lower() in {"information_schema", "pg_catalog"}


@dataclass(frozen=True)
class DbObject:
    schema: str
    name: str
    sql: str  # CREATE TABLE/VIEW ...


# ----------------------------
# Discovery (OLD DB)
# ----------------------------


def discover_schemas(con_old: duckdb.DuckDBPyConnection) -> List[str]:
    rows = con_old.execute(
        """
        SELECT DISTINCT schema_name
        FROM duckdb_schemas()
        ORDER BY 1
        """
    ).fetchall()
    return [r[0] for r in rows]


def discover_tables(con_old: duckdb.DuckDBPyConnection) -> List[DbObject]:
    cols = set(relation_columns(con_old, "duckdb_tables()"))

    where_parts: List[str] = ["1=1"]
    if "internal" in cols:
        where_parts.append("internal = false")
    if "system" in cols:
        where_parts.append("system = false")
    if "temporary" in cols:
        where_parts.append("temporary = false")

    where_sql = " AND ".join(where_parts)

    rows = con_old.execute(
        f"""
        SELECT schema_name, table_name, sql
        FROM duckdb_tables()
        WHERE {where_sql}
        ORDER BY schema_name, table_name
        """
    ).fetchall()

    out: List[DbObject] = []
    for schema_name, table_name, sql in rows:
        if is_system_schema(schema_name):
            continue
        if sql:
            out.append(DbObject(schema=schema_name, name=table_name, sql=sql))
    return out


def discover_views(con_old: duckdb.DuckDBPyConnection) -> List[DbObject]:
    cols = set(relation_columns(con_old, "duckdb_views()"))

    where_parts: List[str] = ["1=1"]
    if "internal" in cols:
        where_parts.append("internal = false")
    if "system" in cols:
        where_parts.append("system = false")
    if "temporary" in cols:
        where_parts.append("temporary = false")

    where_sql = " AND ".join(where_parts)

    rows = con_old.execute(
        f"""
        SELECT schema_name, view_name, sql
        FROM duckdb_views()
        WHERE {where_sql}
        ORDER BY schema_name, view_name
        """
    ).fetchall()

    out: List[DbObject] = []
    for schema_name, view_name, sql in rows:
        if is_system_schema(schema_name):
            continue
        if sql:
            out.append(DbObject(schema=schema_name, name=view_name, sql=sql))
    return out


def discover_sequences(con_old: duckdb.DuckDBPyConnection) -> List[Tuple[str, str]]:
    cols = set(relation_columns(con_old, "duckdb_sequences()"))

    where_parts: List[str] = ["1=1"]
    if "internal" in cols:
        where_parts.append("internal = false")
    if "system" in cols:
        where_parts.append("system = false")
    if "temporary" in cols:
        where_parts.append("temporary = false")

    where_sql = " AND ".join(where_parts)

    rows = con_old.execute(
        f"""
        SELECT schema_name, sequence_name
        FROM duckdb_sequences()
        WHERE {where_sql}
        ORDER BY schema_name, sequence_name
        """
    ).fetchall()

    return [(r[0], r[1]) for r in rows]


# ----------------------------
# Build (NEW DB)
# ----------------------------


def ensure_schema(con_new: duckdb.DuckDBPyConnection, schema_name: str) -> None:
    if not schema_name or schema_name.lower() == "main":
        return
    if is_system_schema(schema_name):
        return
    con_new.execute(f"CREATE SCHEMA IF NOT EXISTS {qident(schema_name)}")


def ensure_sequence(
    con_new: duckdb.DuckDBPyConnection, schema_name: Optional[str], seq_name: str
) -> None:
    if schema_name and schema_name.lower() != "main":
        ensure_schema(con_new, schema_name)
    con_new.execute(f"CREATE SEQUENCE IF NOT EXISTS {fq(schema_name, seq_name)}")


def ensure_sequences_from_nextval(
    con_new: duckdb.DuckDBPyConnection,
    referenced_seq_names: Set[str],
    known_seq_schema_map: Dict[str, Set[str]],
) -> None:
    for raw in sorted(referenced_seq_names):
        raw = raw.strip()
        if not raw:
            continue

        sch, nm = split_qualified(raw)
        if sch:
            print(f"[CREATE SEQUENCE] {sch}.{nm}")
            ensure_sequence(con_new, sch, nm)
            continue

        # Unqualified
        print(f"[ENSURE SEQUENCE] main.{nm}")
        ensure_sequence(con_new, "main", nm)

        for known_schema in sorted(known_seq_schema_map.get(nm, set())):
            if not is_system_schema(known_schema):
                print(f"[ENSURE SEQUENCE] {known_schema}.{nm}")
                ensure_sequence(con_new, known_schema, nm)

        if "journal" not in known_seq_schema_map.get(nm, set()):
            print(f"[ENSURE SEQUENCE] journal.{nm}")
            ensure_sequence(con_new, "journal", nm)


def bump_sequence_best_effort(
    con_new: duckdb.DuckDBPyConnection, schema_name: str, seq_name: str
) -> None:
    full = fq(schema_name, seq_name)
    target = 100000
    try:
        con_new.execute(f"ALTER SEQUENCE {full} RESTART WITH {target}")
        print(f"[BUMP SEQUENCE] {schema_name}.{seq_name} -> {target}")
    except Exception:
        print(
            f"[BUMP SEQUENCE] {schema_name}.{seq_name} skipped (syntax not supported in this build)"
        )


def get_rowcount(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> int:
    return int(
        con.execute(
            f"SELECT count(*) FROM {qident(schema)}.{qident(table)}"
        ).fetchone()[0]
    )


def create_views_multipass(
    con_new: duckdb.DuckDBPyConnection,
    views: List[DbObject],
    excludes: List[str],
    max_passes: int = 10,
) -> Tuple[List[str], List[Tuple[str, str]]]:
    """
    Create views in dependency-safe passes.
    Any view that fails will be retried in later passes (until no progress).
    """
    pending: List[DbObject] = []
    for v in views:
        fqn_name = f"{v.schema}.{v.name}"
        if any(fqn_name.lower() == ex.lower() for ex in excludes):
            print(f"[SKIP VIEW] {fqn_name} (excluded)")
            continue
        if ddl_mentions_excluded(v.sql, excludes):
            print(f"[SKIP VIEW] {fqn_name} (references excluded object)")
            continue
        pending.append(v)

    created: List[str] = []
    last_errors: Dict[str, str] = {}

    for pass_no in range(1, max_passes + 1):
        if not pending:
            break

        print(f"[VIEWS] Pass {pass_no}/{max_passes} (pending={len(pending)})")
        new_pending: List[DbObject] = []
        progress = 0

        for v in pending:
            fqn_name = f"{v.schema}.{v.name}"
            try:
                print(f"[CREATE VIEW] {fqn_name}")
                ensure_schema(con_new, v.schema)
                con_new.execute(v.sql)
                created.append(fqn_name)
                progress += 1
                last_errors.pop(fqn_name, None)
            except Exception as e:
                last_errors[fqn_name] = str(e)
                new_pending.append(v)

        pending = new_pending
        if progress == 0:
            break

    failed: List[Tuple[str, str]] = [
        (k, last_errors[k]) for k in sorted(last_errors.keys())
    ]
    return created, failed


# ----------------------------
# Main
# ----------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Rebuild a DuckDB DB into a new file (optionally excluding objects)."
    )
    p.add_argument("--old", required=True, help="Path to old DuckDB file")
    p.add_argument(
        "--new",
        required=True,
        help="Path to new DuckDB file (will be created/overwritten)",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Fully qualified object to exclude (repeatable)",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="If set, remove --new file if it exists",
    )
    args = p.parse_args(argv)

    old_path = str(Path(os.path.expanduser(args.old)).resolve())
    new_path = str(Path(os.path.expanduser(args.new)).resolve())
    excludes = _norm_excludes(args.exclude)

    print(f"[REBUILD] old={old_path}")
    print(f"[REBUILD] new={new_path}")
    print(f"[REBUILD] exclude={excludes}")

    if not Path(old_path).exists():
        print(f"[ERROR] Old DB not found: {old_path}", file=sys.stderr)
        return 2

    if Path(new_path).exists():
        if args.overwrite:
            Path(new_path).unlink()
        else:
            print(
                f"[ERROR] New DB already exists (use --overwrite): {new_path}",
                file=sys.stderr,
            )
            return 2

    con_old = duckdb.connect(old_path, read_only=True)

    schemas = discover_schemas(con_old)
    tables_all = discover_tables(con_old)
    views_all = discover_views(con_old)
    sequences_old = discover_sequences(con_old)

    known_seq_schema_map: Dict[str, Set[str]] = {}
    for sch, nm in sequences_old:
        known_seq_schema_map.setdefault(nm, set()).add(sch)

    referenced_seq_names: Set[str] = set()
    for t in tables_all:
        referenced_seq_names |= extract_nextval_sequences(t.sql)

    print(
        f"[DISCOVER] schemas: {', '.join([s for s in schemas if not is_system_schema(s)])}"
    )
    print(f"[DISCOVER] tables: {len(tables_all)}")
    print(f"[DISCOVER] views : {len(views_all)}")
    print(f"[DISCOVER] sequences (from duckdb_sequences): {len(sequences_old)}")
    if referenced_seq_names:
        print(
            f"[DISCOVER] sequences (from nextval in table DDL): {', '.join(sorted(referenced_seq_names))}"
        )

    tables: List[DbObject] = []
    for t in tables_all:
        fqn_name = f"{t.schema}.{t.name}"
        if any(fqn_name.lower() == ex.lower() for ex in excludes):
            print(f"[SKIP TABLE] {fqn_name} (excluded)")
            continue
        tables.append(t)

    con_new = duckdb.connect(new_path)

    # Attach OLD into NEW for table data copy
    old_alias = "old"
    con_new.execute(f"ATTACH '{old_path}' AS {qident(old_alias)} (READ_ONLY)")

    # Create schemas
    for sch in schemas:
        ensure_schema(con_new, sch)

    # Create sequences from old DB
    for sch, nm in sequences_old:
        if is_system_schema(sch):
            continue
        print(f"[CREATE SEQUENCE] {sch}.{nm}")
        try:
            ensure_sequence(con_new, sch, nm)
        except Exception as e:
            print(f"[WARN] Failed creating sequence {sch}.{nm}: {e}")

    # Ensure sequences referenced in table DDL via nextval(...)
    if referenced_seq_names:
        ensure_sequences_from_nextval(
            con_new, referenced_seq_names, known_seq_schema_map
        )

    # Create tables (DDL)
    created_tables: List[DbObject] = []
    for t in tables:
        fqn_name = f"{t.schema}.{t.name}"
        try:
            print(f"[CREATE TABLE] {fqn_name}")
            ensure_schema(con_new, t.schema)
            con_new.execute(t.sql)
            created_tables.append(t)
        except Exception as e:
            print(f"[ERROR] Failed creating table {fqn_name}")
            print(f"DDL: {t.sql}")
            print(f"ERROR: {e}")
            raise

    # Copy table data
    for t in created_tables:
        fqn_name = f"{t.schema}.{t.name}"
        n_old = con_old.execute(
            f"SELECT count(*) FROM {qident(t.schema)}.{qident(t.name)}"
        ).fetchone()[0]
        print(f"[COPY DATA] {fqn_name}: {n_old:,} rows")
        con_new.execute(
            f"INSERT INTO {qident(t.schema)}.{qident(t.name)} "
            f"SELECT * FROM {qident(old_alias)}.{qident(t.schema)}.{qident(t.name)}"
        )

    # Best-effort bump sequences
    for sch, nm in sequences_old:
        if is_system_schema(sch):
            continue
        bump_sequence_best_effort(con_new, sch, nm)

    # IMPORTANT: Detach old before creating views
    con_new.execute(f"DETACH {qident(old_alias)}")

    # Create views with dependency-safe multi-pass
    created_views, failed_views = create_views_multipass(
        con_new, views_all, excludes, max_passes=10
    )

    print("")
    print(f"[RESULT] tables created: {len(created_tables)}")
    print(f"[RESULT] views created : {len(created_views)}")
    if failed_views:
        print(f"[WARN] views failed  : {len(failed_views)}")
        for fqn_name, err in failed_views:
            print(f"  - {fqn_name}: {err}")

    print("")
    print("[VERIFY] Row counts (old vs new):")
    for t in created_tables:
        fqn_name = f"{t.schema}.{t.name}"
        old_n = get_rowcount(con_old, t.schema, t.name)
        new_n = get_rowcount(con_new, t.schema, t.name)
        status = "OK" if old_n == new_n else "DIFF"
        print(f"  {status:<4} {fqn_name:<40} old={old_n:,} new={new_n:,}")

    con_old.close()
    con_new.close()

    print("")
    print("[DONE]")
    print(f"New DB created: {new_path}")
    print("Next steps:")
    print("  1) Point your scripts to the new DB path (or pass --db <new_db>)")
    print("  2) Run: python -m scripts.journal.transactions_report --db <new_db>")
    print("  3) If happy, archive/delete the old DB yourself")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
