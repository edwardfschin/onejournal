"""Hash-pinned DuckDB-to-PostgreSQL rehearsal; no live-target or activation path."""
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import tempfile
from uuid import UUID

import duckdb
from psycopg.conninfo import conninfo_to_dict

from onejournal.hosted_schema import validate
from onejournal.journal.migrations import DEFAULT_MIGRATIONS_DIR
from onejournal.journal.storage import PostgresTarget, connect
from onejournal.local_web import private_file

CONTRACT = 'onejournal.hosted-migration-rehearsal.v1'
MAX_ROWS = 1_000_000  # Explicit per-relation memory bound; refuse, never omit.


def _temporary_private_directory(path):
    path = Path(path)
    resolved = path.resolve()
    bases = {Path('/private/tmp').resolve(), Path(tempfile.gettempdir()).resolve()}
    if (not path.is_absolute() or path.is_symlink() or not resolved.is_dir()
            or not any(resolved != base and resolved.is_relative_to(base) for base in bases)
            or resolved.stat().st_mode & 0o777 != 0o700 or resolved.stat().st_uid != os.getuid()):
        raise ValueError('Use an owner-only temporary rehearsal directory.')
    return resolved


def _file_hash(path):
    digest = sha256()
    with path.open('rb') as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _identifier(name):
    if not re.fullmatch('[a-z_][a-z_0-9]*', name):
        raise ValueError('Unsupported rehearsal schema identifier.')
    return '"' + name + '"'


def _value(value):
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Non-finite financial values are unsupported.')
        return ['float', value.hex()]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError('Non-finite financial values are unsupported.')
        return ['decimal', str(value)]
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return ['datetime', value.isoformat(timespec='microseconds')]
    if isinstance(value, date):
        return ['date', value.isoformat()]
    if isinstance(value, UUID):
        return ['uuid', str(value)]
    if isinstance(value, (bytes, memoryview)):
        return ['bytes', bytes(value).hex()]
    raise ValueError('Unsupported rehearsal scalar type.')


def relation_proof(con, name):
    cursor = con.execute('SELECT * FROM ' + _identifier(name))
    columns = [col[0] for col in cursor.description]
    rows = []
    while batch := cursor.fetchmany(1000):
        for row in batch:
            encoded = json.dumps([_value(value) for value in row], ensure_ascii=True,
                                 separators=(',', ':'), allow_nan=False).encode()
            rows.append(sha256(encoded).digest())
        if len(rows) > MAX_ROWS:
            raise ValueError('Rehearsal relation exceeds the explicit row limit.')
    digest = sha256()
    for row_hash in sorted(rows):  # Multiset: preserve duplicates, ignore DB collation/order.
        digest.update(row_hash)
    return {'columns': columns, 'rows': len(rows), 'sha256': digest.hexdigest()}


def _type(value):
    value = value.lower().replace(' ', '')
    if value.startswith('varchar') or value.startswith('charactervarying') or value == 'text':
        return 'text'
    if value.startswith('decimal('):
        return value.replace('decimal(', 'numeric(', 1)
    return {'timestamp': 'timestampwithouttimezone', 'timestamptz': 'timestampwithtimezone',
            'double': 'doubleprecision', 'float': 'real', 'blob': 'bytea'}.get(value, value)


def rehearse(source_copy: Path, source_sha256: str, target: PostgresTarget):
    """Copy only a pinned 0028 schema into an empty temporary rehearsal journal.

    The destination must be a local private temporary socket and an explicitly
    named oj_rehearsal_* database. This cannot install a live production journal.
    Security state, authorizations, services and release activation are excluded.
    """
    source_copy = private_file(source_copy, 'frozen rehearsal copy', private_parent=True)
    _temporary_private_directory(source_copy.parent)
    if not re.fullmatch('[0-9a-f]{64}', source_sha256):
        raise ValueError('An exact frozen-copy SHA-256 is required.')
    if Path(str(source_copy) + '.wal').exists() or _file_hash(source_copy) != source_sha256:
        raise ValueError('Frozen copy has pending writes or its hash differs.')
    values = conninfo_to_dict(target.dsn)
    if not re.fullmatch('oj_rehearsal_[a-z0-9_]+', values['dbname']):
        raise ValueError('Only explicitly named disposable rehearsal databases are admitted.')
    _temporary_private_directory(Path(values['host']))  # TCP and remote targets refused.
    validate(target)  # Baseline already installed explicitly, never by this command.
    with duckdb.connect(str(source_copy), read_only=True) as source, connect(target) as destination:
        source.execute('BEGIN TRANSACTION')
        expected = {}
        for path in sorted(DEFAULT_MIGRATIONS_DIR.glob('*.sql')):
            if int(path.name[:4]) <= 28:
                expected[path.name[:4]] = (path.stem[5:], sha256(path.read_bytes()).hexdigest(), 'applied')
        ledger = {version: (name, checksum, status) for version, name, checksum, status in
                  source.execute('SELECT version,migration_name,file_checksum,status FROM schema_migrations').fetchall()}
        if ledger != expected:
            raise ValueError('Only the complete pinned schema through 0028 is admitted; history is separate.')
        source_tables = [r[0] for r in source.execute("SELECT table_name FROM duckdb_tables() WHERE schema_name='main' ORDER BY table_name").fetchall()]
        source_views = [r[0] for r in source.execute("SELECT view_name FROM duckdb_views() WHERE schema_name='main' AND NOT internal ORDER BY view_name").fetchall()]
        destination.execute('BEGIN')
        destination.execute('SET CONSTRAINTS ALL DEFERRED')
        destination.execute('LOCK TABLE ' + ','.join(_identifier(n) for n in source_tables) + ' IN ACCESS EXCLUSIVE MODE')
        target_tables = [r[0] for r in destination.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='BASE TABLE' AND table_name!='hosted_schema_meta' ORDER BY table_name").fetchall()]
        target_views = [r[0] for r in destination.execute("SELECT table_name FROM information_schema.views WHERE table_schema='main' ORDER BY table_name").fetchall()]
        if source_tables != target_tables or source_views != target_views:
            raise ValueError('Source and destination relations must match exactly; nothing is omitted.')
        for name in source_tables:
            if destination.execute('SELECT COUNT(*) FROM ' + _identifier(name)).fetchone()[0]:
                raise ValueError('Rehearsal destination must be empty; replay/overwrite is refused.')
            source_columns = [(n, _type(t), nullable) for n, t, nullable in source.execute(
                "SELECT column_name,data_type,is_nullable FROM information_schema.columns WHERE table_schema='main' AND table_name=? ORDER BY ordinal_position", [name]).fetchall()]
            target_columns = [(n, _type(t), nullable) for n, t, nullable in destination.execute(
                "SELECT a.attname,pg_catalog.format_type(a.atttypid,a.atttypmod),CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END FROM pg_attribute a JOIN pg_class c ON a.attrelid=c.oid JOIN pg_namespace n ON c.relnamespace=n.oid WHERE n.nspname='main' AND c.relname=? AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum", [name]).fetchall()]
            if source_columns != target_columns:
                raise ValueError('Rehearsal column types, order and nullability must match.')
        proofs = {}
        for name in source_tables:
            cursor = source.execute('SELECT * FROM ' + _identifier(name))
            columns = [column[0] for column in cursor.description]
            query = ('INSERT INTO ' + _identifier(name) + ' (' + ','.join(_identifier(c) for c in columns)
                     + ') VALUES (' + ','.join('?' for _ in columns) + ')')
            count = 0
            while rows := cursor.fetchmany(1000):
                count += len(rows)
                if count > MAX_ROWS:
                    raise ValueError('Rehearsal relation exceeds the explicit row limit.')
                destination.executemany(query, rows)
        for name in source_tables + source_views:
            original = relation_proof(source, name)
            copied = relation_proof(destination.connection, name)
            if original != copied:
                raise ValueError('Exact rehearsal relation read-back differs; transaction refused.')
            proofs[name] = original
        if _file_hash(source_copy) != source_sha256:
            raise ValueError('Frozen copy changed during rehearsal; transaction refused.')
        destination.execute('SET CONSTRAINTS ALL IMMEDIATE')
        destination.execute('COMMIT')
    return {'contract_version': CONTRACT, 'source_sha256': source_sha256,
            'exact_relations': proofs, 'source_unchanged': True, 'activated': False}
