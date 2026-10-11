"""Immutable v3 assembly storage; no migration, activation or financial writes.

One canonical artifact retains all ten checksum-bound families and exclusions.
Legacy stores remain untouched. This evidence store does not activate a journal
history revision or a reporting release.
"""
from hashlib import sha256
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from onejournal.journal.schwab_evidence_assembly import (
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V3, SchwabPhase1EvidenceAssembly,
    load_schwab_phase1_evidence_assembly_bytes, schwab_phase1_evidence_assembly_bytes,
    validate_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_import_repository import SchwabEvidencePersistenceResult

MIGRATION_PATH = Path(__file__).resolve().parents[3] / 'scripts/journal/migrations/0027_add_snapshot_cutoff_evidence.sql'


def _contract(connection):
    if connection.execute(
        "SELECT migration_name, file_checksum, status FROM schema_migrations WHERE version = '0027'"
    ).fetchone() != ('add_snapshot_cutoff_evidence', sha256(MIGRATION_PATH.read_bytes()).hexdigest(), 'applied'):
        raise ValueError('snapshot evidence requires exact migration 0027')


def _expected(assembly, body):
    return (assembly.assembly_uid, assembly.contract_version, assembly.source_account_id,
            assembly.connection_uid, assembly.asof, assembly.lifecycle_window_start,
            assembly.lifecycle_window_end, assembly.snapshot_cutoff_utc, assembly.result_fingerprint,
            sha256(body).hexdigest(), body.decode('utf-8'))


def _read(connection, assembly_uid):
    row = connection.execute(
        '''SELECT assembly_uid, contract_version, source_account_id, connection_uid,
                  asof_date, lifecycle_window_start, lifecycle_window_end,
                  epoch_us(snapshot_cutoff_utc), result_fingerprint, artifact_sha256, artifact_json
           FROM phase1_schwab_snapshot_evidence_imports WHERE assembly_uid = ?''', [assembly_uid]
    ).fetchone()
    if row is None:
        raise ValueError('exact snapshot assembly is absent')
    body = row[-1].encode('utf-8')
    if sha256(body).hexdigest() != row[-2]:
        raise ValueError('snapshot assembly artifact checksum differs')
    assembly = load_schwab_phase1_evidence_assembly_bytes(body)
    expected = list(_expected(assembly, body))
    # Compare exact microseconds without DuckDB's optional timezone-result dependency.
    if assembly.snapshot_cutoff_utc is None:
        raise ValueError('snapshot assembly cutoff is absent')
    elapsed = assembly.snapshot_cutoff_utc - datetime(1970, 1, 1, tzinfo=UTC)
    expected[7] = (elapsed.days * 86400 + elapsed.seconds) * 1000000 + elapsed.microseconds
    if assembly.contract_version != SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V3 or row != tuple(expected):
        raise ValueError('snapshot assembly metadata or content differs')
    return assembly


def load_schwab_snapshot_evidence(db_path: Path, *, assembly_uid: str) -> SchwabPhase1EvidenceAssembly:
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError('database must be a pre-existing non-symlink file')
    with duckdb.connect(str(db_path), read_only=True) as connection:
        _contract(connection)
        return _read(connection, assembly_uid)


def persist_schwab_snapshot_evidence(db_path: Path, assembly: SchwabPhase1EvidenceAssembly) -> SchwabEvidencePersistenceResult:
    validate_schwab_phase1_evidence_assembly(assembly)
    if assembly.contract_version != SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V3:
        raise ValueError('snapshot evidence requires assembly v3')
    body = schwab_phase1_evidence_assembly_bytes(assembly)
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError('database must be a pre-existing non-symlink file')
    with duckdb.connect(str(db_path)) as connection:
        _contract(connection)
        connection.execute('BEGIN TRANSACTION')
        try:
            exists = connection.execute(
                'SELECT assembly_uid FROM phase1_schwab_snapshot_evidence_imports WHERE assembly_uid = ?',
                [assembly.assembly_uid]).fetchone() is not None
            if not exists:
                connection.execute('INSERT INTO phase1_schwab_snapshot_evidence_imports VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                                   _expected(assembly, body))
            restored = _read(connection, assembly.assembly_uid)
            if schwab_phase1_evidence_assembly_bytes(restored) != body:
                raise ValueError('snapshot assembly replay differs')
            connection.execute('COMMIT')
        except Exception:
            connection.execute('ROLLBACK')
            raise
    return SchwabEvidencePersistenceResult(assembly_uid=assembly.assembly_uid,
        family_count=len(assembly.families), normalized_record_count=sum(f.normalized_record_count for f in assembly.families),
        created=not exists, replayed=exists)
