"""Disposable-copy activity rehearsal; originals are read-only and retained."""
from contextlib import contextmanager
from pathlib import Path
import tempfile

import duckdb

from onejournal.journal.activity_refresh_repository import append_activity_copy
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.local_web import private_file
from onejournal.mac_journal_backup import copy_private, file_hash, inventory


def _proof(con, names):
    # DuckDB serializes DECIMAL directly, without passing through Python float.
    from hashlib import sha256
    result = {}
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        rows = sorted(sha256(row[0].encode()).digest() for row in
                      con.execute(f'SELECT to_json(t) FROM {quoted} AS t').fetchall())
        result[name] = (len(rows), sha256(b''.join(rows)).hexdigest())
    return result


@contextmanager
def disposable_journal(source):
    """Copy under a read-only lock. Refuse WAL/lock conflicts; never checkpoint."""
    source = private_file(Path(source), 'source journal', private_parent=True)
    wal = Path(str(source) + '.wal')
    if wal.exists():
        raise ValueError('Source has a pending WAL; no checkpoint was attempted.')
    with tempfile.TemporaryDirectory(prefix='onejournal-activity-', dir='/private/tmp') as directory:
        target = Path(directory) / 'activity-rehearsal.duckdb'
        with duckdb.connect(str(source), read_only=True):
            if wal.exists():
                raise ValueError('Source WAL appeared.')
            original = file_hash(source)
            copy_private(source, target)
            if wal.exists() or file_hash(source) != original or file_hash(target) != original:
                raise ValueError('Source changed during copy.')
        try:
            yield target
        finally:
            if wal.exists() or file_hash(source) != original:
                raise ValueError('Source changed during rehearsal; do not claim preservation.')


def prepare_copy(target):
    """Migrate the temporary copy only and prove all prior rows/views survive."""
    from onejournal.journal.activity_refresh_repository import disposable_target
    target = disposable_target(target)
    with duckdb.connect(str(target), read_only=True) as con:
        prior = inventory(con)
        names = [r[1] for r in prior['relations'] if r[1] != 'schema_migrations']
        rows = _proof(con, names)
        ledger = con.execute('SELECT * FROM schema_migrations ORDER BY version').fetchall()
    apply_schema_migrations(target, target_version='0030')
    with duckdb.connect(str(target), read_only=True) as con:
        after = inventory(con)
        if (any(c not in after['columns'] for c in prior['columns'])
                or any(r not in after['relations'] for r in prior['relations'])
                or _proof(con, names) != rows
                or con.execute('SELECT * FROM schema_migrations ORDER BY version').fetchall()[:len(ledger)] != ledger):
            raise ValueError('Copy migration changed pre-existing state.')
    return after


def rehearse_activity(source, **kwargs):
    with disposable_journal(source) as target:
        before = prepare_copy(target)
        names = [r[1] for r in before['relations'] if r[1] != 'incremental_activity_imports']
        with duckdb.connect(str(target), read_only=True) as con:
            preserved = _proof(con, names)
        result = append_activity_copy(db=target, **kwargs)
        replay = append_activity_copy(db=target, **kwargs)
        with duckdb.connect(str(target), read_only=True) as con:
            if _proof(con, names) != preserved:
                raise ValueError('Append changed an existing journal relation.')
        if not replay['replayed'] or replay['import_uid'] != result['import_uid']:
            raise ValueError('Exact replay failed.')
    return dict(status='disposable_rehearsal_passed', new_records=result['new_records'],
                append_committed_on_copy_only=result['created'], original_unchanged=True,
                financial_publication_authorized=False)
