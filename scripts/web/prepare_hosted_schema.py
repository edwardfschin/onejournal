#!/usr/bin/env python3
"""Compile an empty, pinned DuckDB schema into the PostgreSQL baseline.

No live database input is accepted. This is a build-time schema producer, not
startup migration or private-data import. Existing outputs are never replaced.
"""
from __future__ import annotations

import argparse
from hashlib import sha256
from pathlib import Path
import re
import tempfile

import duckdb

from onejournal.journal.migrations import apply_schema_migrations, DEFAULT_MIGRATIONS_DIR


def postgres_ddl(sql: str) -> str:
    sql = sql.replace('main."position"(storage_key, \'://\')', "strpos(storage_key, '://')")
    sql = re.sub(r"\buuid\(\)", "gen_random_uuid()", sql, flags=re.I)
    sql = re.sub(r"\bBLOB\b", "BYTEA", sql)
    sql = re.sub(r"\bDOUBLE\b(?! PRECISION)", "DOUBLE PRECISION", sql)
    sql = re.sub(r"\bFLOAT\b", "REAL", sql)
    sql = re.sub(r"(REFERENCES [a-z_0-9]+\([^)]*\))", r"\1 DEFERRABLE INITIALLY IMMEDIATE", sql)
    return sql


def compile_schema() -> str:
    with tempfile.TemporaryDirectory(prefix="onejournal-empty-schema-") as tmp:
        path = Path(tmp) / "empty.duckdb"
        apply_schema_migrations(path, target_version="0028")
        with duckdb.connect(str(path), read_only=True) as con:
            tables = dict(con.execute("SELECT table_name, sql FROM duckdb_tables() WHERE schema_name='main'").fetchall())
            dependencies = {name: set() for name in tables}
            for name, parent in con.execute("SELECT table_name, referenced_table FROM duckdb_constraints() WHERE constraint_type='FOREIGN KEY'").fetchall():
                if parent != name:
                    dependencies[name].add(parent)
            statements = []
            while tables:
                ready = sorted(name for name in tables if not dependencies[name].intersection(tables))
                if not ready:
                    raise ValueError("Schema has an unresolved foreign-key dependency.")
                for name in ready:
                    ddl = tables.pop(name)
                    # DuckDB 1.5.3 emits empty catalog clauses for self-FKs.
                    # Reconstruct them from structured catalog metadata, never
                    # silently discard the review/activation lineage constraint.
                    for cols, parent, parent_cols in con.execute(
                        "SELECT constraint_column_names, referenced_table, referenced_column_names FROM duckdb_constraints() WHERE table_name=? AND constraint_type='FOREIGN KEY' AND constraint_text=''", [name]
                    ).fetchall():
                        identifiers = [*cols, parent, *parent_cols]
                        if any(not re.fullmatch(r"[a-z_][a-z_0-9]*", value) for value in identifiers):
                            raise ValueError("Unsupported schema identifier.")
                        clause = f"FOREIGN KEY ({','.join(cols)}) REFERENCES {parent}({','.join(parent_cols)})"
                        ddl = ddl.replace(", ,", ", " + clause + ",", 1)
                    if ", ," in ddl:
                        raise ValueError("Unresolved empty schema constraint.")
                    statements.append(postgres_ddl(ddl))
            # The final views all come from 0028. Preserve their declared
            # dependency order and original explicit SELECT lists rather than
            # DuckDB's catalog-expanded star/USING expressions.
            migration = next(DEFAULT_MIGRATIONS_DIR.glob("0028_*.sql")).read_text()
            first = migration.index("CREATE VIEW")
            statements.append(postgres_ddl(migration[first:]))
            indexes = con.execute("SELECT sql FROM duckdb_indexes() WHERE schema_name='main' ORDER BY index_name").fetchall()
            statements.extend(postgres_ddl(row[0]) for row in indexes)
    sources = [p for p in sorted(DEFAULT_MIGRATIONS_DIR.glob("*.sql")) if int(p.name[:4]) <= 28]
    lineage = "\n".join(f"-- source {p.name} sha256 {sha256(p.read_bytes()).hexdigest()}" for p in sources)
    return ("-- PostgreSQL baseline 0001; empty schema through DuckDB 0028 only.\n"
            "-- No 0029 history-backfill migration, data import or startup execution.\n" + lineage + "\n"
            "CREATE SCHEMA main;\nSET search_path=main,pg_catalog;\n"
            + "\n".join(statements)
            + "\nCREATE TABLE hosted_schema_meta (version text PRIMARY KEY, schema_sha256 text NOT NULL, binding_uid uuid NOT NULL);\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with args.output.open("x", encoding="utf-8") as output:
        output.write(compile_schema())
    print("Empty hosted schema prepared; no private source or PostgreSQL write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
