"""Explicit, empty-database-only PostgreSQL baseline installation and verification."""
from hashlib import sha256
from importlib.resources import files
from uuid import uuid4

from onejournal.journal.storage import PostgresTarget, connect


def schema_bytes():
    return files("onejournal").joinpath("hosted_schema.sql").read_bytes()


def install_empty(target: PostgresTarget):
    source = schema_bytes()
    with connect(target) as con:
        con.execute("BEGIN")
        # No IF NOT EXISTS, no destructive repair, no startup invocation.
        con.execute(source.decode())
        con.execute("INSERT INTO hosted_schema_meta VALUES ('0001', ?, ?)",
                    [sha256(source).hexdigest(), uuid4()])
        con.execute("COMMIT")


def validate(target: PostgresTarget):
    with connect(target, read_only=True) as con:
        rows = con.execute("SELECT version, schema_sha256 FROM hosted_schema_meta").fetchall()
    if rows != [("0001", sha256(schema_bytes()).hexdigest())]:
        raise ValueError("Hosted schema version/checksum is not approved by this release.")
