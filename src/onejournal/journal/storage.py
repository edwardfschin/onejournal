"""Explicit operational-store boundary; never infer a DSN from a journal path."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re

import duckdb


@dataclass(frozen=True)
class PostgresTarget:
    # Suppress credentials in exceptions/debug reprs. Configuration is operator-only.
    dsn: str = field(repr=False)

    def __post_init__(self):
        from psycopg.conninfo import conninfo_to_dict
        values = conninfo_to_dict(self.dsn)
        allowed = {"host", "port", "dbname", "user", "password"}
        if set(values) - allowed:
            raise ValueError("Use only explicit local host, port, database, role and optional password.")
        if not values.get("dbname") or not values.get("user"):
            raise ValueError("PostgreSQL requires an explicit database and role.")
        host = values.get("host", "")
        if host not in {"127.0.0.1", "::1"} and not (host.startswith("/") and "," not in host):
            raise ValueError("Hosted storage must use a local socket or loopback.")
        import os
        if any(name in os.environ for name in ("PGHOSTADDR", "PGSERVICE", "PGSERVICEFILE", "PGOPTIONS")):
            raise ValueError("Remove PostgreSQL service/address/options environment overrides.")


def _postgres_sql(sql: str, parameters: bool) -> str:
    """Translate only DB-API parameter notation, never quoted text or SQL logic."""
    if sql.strip().upper() == "SHOW TABLES":
        return "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    if not parameters:
        return sql
    # Our static application SQL has no dollar-quoted bodies. Refuse these rather
    # than guessing; schema installation uses psycopg directly with no parameters.
    if re.search(r"\$[A-Za-z_0-9]*\$", sql):
        raise ValueError("Dollar-quoted parameter SQL is unsupported.")
    tokens = re.split(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|--[^\n]*|/\*[\s\S]*?\*/)", sql)
    return "".join(token.replace("%", "%%").replace("?", "%s") if i % 2 == 0
                   else token.replace("%", "%%") for i, token in enumerate(tokens))


class PostgresConnection:
    """Small cursor compatibility boundary for the existing journal services.

    SQL and transaction ownership stay in those services. A database advisory
    lock covers the whole journal operation, including receipt replay checks
    before BEGIN. This also serializes cooperating operator writes.
    """
    def __init__(self, target: PostgresTarget, *, read_only=False):
        import psycopg
        self.connection = psycopg.connect(target.dsn, autocommit=True,
            connect_timeout=5, options="-c search_path=main,pg_catalog -c timezone=UTC -c statement_timeout=15000 -c lock_timeout=5000")
        if read_only:
            self.connection.execute("SET default_transaction_read_only=on")
        self.read_only = read_only
        self.cursor = None

    def execute(self, sql, params=None):
        self.cursor = self.connection.execute(_postgres_sql(sql, params is not None), params)
        return self

    def executemany(self, sql, params):
        self.cursor = self.connection.cursor()
        self.cursor.executemany(_postgres_sql(sql, True), params)
        return self

    @property
    def description(self):
        return self.cursor.description

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def close(self):
        self.connection.close()  # Rolls back unfinished transactions, releases locks.

    def __enter__(self):
        try:
            if not self.read_only:
                self.connection.execute("SELECT pg_advisory_lock(731021)")
        except Exception:
            self.close()
            raise
        return self

    def __exit__(self, *args):
        self.close()


def connect(target: str | Path | PostgresTarget, *, read_only=False):
    if isinstance(target, PostgresTarget):
        return PostgresConnection(target, read_only=read_only)
    return duckdb.connect(str(target), read_only=read_only)


def validate_runtime_role(target: PostgresTarget, *, security=False):
    """The app must not run as a database/schema owner or privileged operator."""
    with connect(target, read_only=True) as con:
        row = con.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
        create_schema = con.execute("SELECT has_schema_privilege(current_user,'main','CREATE')").fetchone()[0]
        owner = con.execute("SELECT pg_get_userbyid(datdba)=current_user FROM pg_database WHERE datname=current_database()").fetchone()[0]
        grants = con.execute("SELECT tablename, has_table_privilege(current_user,format('%I.%I',schemaname,tablename),'INSERT'), has_table_privilege(current_user,format('%I.%I',schemaname,tablename),'UPDATE'), has_table_privilege(current_user,format('%I.%I',schemaname,tablename),'DELETE'), has_table_privilege(current_user,format('%I.%I',schemaname,tablename),'TRUNCATE') FROM pg_tables WHERE schemaname='main'").fetchall()
    if any(row) or create_schema or owner:
        raise ValueError("Use a non-owner, least-privilege hosted runtime role.")
    allowed_insert = {"passkeys", "access_failures", "access_audit", "access_denial_counts"} if security else {
        "journal_entries", "journal_entry_revisions", "journal_reviews", "manual_reviews",
        "local_owner_api_operation_receipts", "local_owner_api_audit_events",
        "local_owner_financial_api_audit_events", "phase1_reporting_api_audit_events"}
    allowed_update = {"access_meta", "passkeys", "access_denial_counts"} if security else {"manual_reviews"}
    allowed_delete = {"access_failures"} if security else set()
    if any((insert and name not in allowed_insert) or (update and name not in allowed_update)
           or (delete and name not in allowed_delete) or truncate
           for name, insert, update, delete, truncate in grants):
        raise ValueError("Hosted runtime grants exceed the approved write boundary.")
