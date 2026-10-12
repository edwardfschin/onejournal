"""Guarded disposable-copy rehearsal; source DB and services are never opened for writes."""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import stat
import struct
from uuid import UUID

import duckdb

from onejournal.journal.historical_activity import (
    HistoricalActivityError, TABLES, encode, load_bundle_bytes, persist_bundle, read_bundle,
)
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.brokers.schwab.historical_activity import assignment_preview, validate_source_observations


def _private_file(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise HistoricalActivityError('rehearsal inputs must be absolute private regular files')
    return path


def _digest(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def _preservation_value(value):
    # This hashes existing database values; it does not calculate financials or
    # parse broker numbers through floats. Keep even legacy DOUBLE bits exact.
    if isinstance(value, float):
        return ['binary_float', struct.pack('!d', value).hex()]
    if isinstance(value, Decimal):
        return ['decimal', str(value)]
    if isinstance(value, (bytes, bytearray)):
        return ['bytes', bytes(value).hex()]
    if isinstance(value, UUID):
        return ['uuid', value.hex]
    if hasattr(value, 'isoformat'):
        return [type(value).__name__, value.isoformat()]
    if isinstance(value, (list, tuple)):
        return [_preservation_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _preservation_value(v) for k, v in value.items()}
    return value


def preservation_snapshot(db_path, *, names=None):
    result = {}
    with duckdb.connect(str(db_path), read_only=True) as con:
        names = names if names is not None else [r[0] for r in con.execute('SHOW TABLES').fetchall()]
        for name in names:
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
                raise HistoricalActivityError('database table name cannot be safely inspected')
            schema = con.execute(f'PRAGMA table_info("{name}")').fetchall()
            where = " WHERE version != '0029'" if name == 'schema_migrations' else ''
            rows = con.execute(f'SELECT * FROM "{name}"{where}').fetchall()
            hashes = sorted(sha256(encode(_preservation_value(row)).encode()).hexdigest() for row in rows)
            result[name] = {'row_count': len(rows), 'schema_sha256': sha256(encode(_preservation_value(schema)).encode()).hexdigest(),
                            'rows_sha256': sha256(encode(hashes).encode()).hexdigest()}
    return result


def rehearse(*, source_db, source_db_sha256, bundle_path, expected_bundle_fingerprint, output_dir, migrations_dir=None):
    """Create exactly one new copy, apply only 0029, import/replay/read back there."""
    source_db, bundle_path = _private_file(source_db), _private_file(bundle_path)
    out = Path(output_dir)
    if not out.is_absolute() or out.exists() or out.is_symlink() or not out.parent.is_dir():
        raise HistoricalActivityError('a new absolute disposable rehearsal directory is required')
    repo = Path(__file__).resolve().parents[3]
    if out.resolve().is_relative_to(repo.resolve()):
        raise HistoricalActivityError('private rehearsal output must stay outside the source repository')
    if source_db.with_suffix(source_db.suffix + '.wal').exists():
        raise HistoricalActivityError('source database must be a quiescent saved copy')
    body = source_db.read_bytes()
    if not re.fullmatch(r'[0-9a-f]{64}', source_db_sha256) or sha256(body).hexdigest() != source_db_sha256:
        raise HistoricalActivityError('source database is not the exact selected copy')
    bundle = load_bundle_bytes(bundle_path.read_bytes(), expected_fingerprint=expected_bundle_fingerprint)
    validate_source_observations(bundle)
    for doc in bundle['documents']:
        path = Path(doc['source_path'])
        if not path.is_absolute() or path.is_symlink() or not path.is_file() or _digest(path) != doc['raw_sha256']:
            raise HistoricalActivityError('historical raw document no longer matches its checksum')
    with duckdb.connect(str(source_db), read_only=True) as con:
        version = con.execute("SELECT max(CAST(version AS INTEGER)) FROM schema_migrations WHERE status='applied'").fetchone()[0]
        if version != 28 or set(TABLES) & {r[0] for r in con.execute('SHOW TABLES').fetchall()}:
            raise HistoricalActivityError('rehearsal requires the pinned pre-ledger schema-0028 copy')
    before = preservation_snapshot(source_db)
    if _digest(source_db) != source_db_sha256:
        raise HistoricalActivityError('source database changed during read-only preparation')
    out.mkdir(mode=0o700)
    candidate = out / 'candidate.duckdb'
    with candidate.open('xb') as f:
        f.write(body)
    candidate.chmod(0o600)
    if _digest(candidate) != source_db_sha256:
        raise HistoricalActivityError('disposable database copy verification failed')
    if apply_schema_migrations(candidate, target_version='0029', migrations_dir=migrations_dir) != 29:
        raise HistoricalActivityError('disposable migration did not reach exactly schema 0029')
    first = persist_bundle(candidate, bundle)
    replay = persist_bundle(candidate, bundle)
    readback = read_bundle(candidate, run_uid=bundle['run_uid'], expected_fingerprint=bundle['bundle_fingerprint'])
    if not first['created'] or replay['created'] or readback != bundle:
        raise HistoricalActivityError('historical import exact replay differs')
    after = preservation_snapshot(candidate, names=list(before))
    if after != before or _digest(source_db) != source_db_sha256:
        raise HistoricalActivityError('predecessor history or source bytes changed')
    preview = assignment_preview(readback)
    summary = {'contract_version': bundle['contract_version'], 'bundle_fingerprint': bundle['bundle_fingerprint'],
               'source_database_sha256': source_db_sha256, 'candidate_database_sha256': _digest(candidate),
               'schema_version': '0029', 'observation_count': len(bundle['observations']),
               'document_count': len(bundle['documents']), 'exact_replay': True, 'exact_readback': True,
               'all_predecessor_rows_and_schemas_preserved': True, 'source_database_bytes_unchanged': True,
               'financial_authority': False, 'canonical_fills_added': 0, 'live_writes': 0, 'runtime_changes': 0}
    for name, value in [('summary.json', summary), ('preservation.json', before), ('assignment-preview.json', preview)]:
        path = out / name
        with path.open('x') as f:
            f.write(encode(value) + '\n')
        path.chmod(0o600)
    return summary
