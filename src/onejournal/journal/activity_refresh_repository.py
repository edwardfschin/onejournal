"""Atomic, append-only activity evidence/checkpoint; disposable targets only.

The canonical artifact stores new normalized records, exact source-manifest
lineage and the resulting checkpoint together. Existing financial read models
remain unchanged. There is deliberately no live-write opt-in or activation.
"""
from dataclasses import replace
from datetime import UTC, datetime, time
from hashlib import sha256
import json
from pathlib import Path
import tempfile

import duckdb

from onejournal.brokers.schwab.account_binding import schwab_account_private_binding_bytes
from onejournal.journal.migrations import DEFAULT_MIGRATIONS_DIR
from onejournal.journal.schwab_evidence_assembly import canonical_schwab_evidence_json
from onejournal.local_web import private_file
from onejournal.provider_connectors.external_acquisition import external_provider_acquisition_manifest_bytes

MIGRATION = DEFAULT_MIGRATIONS_DIR / '0030_add_incremental_activity_imports.sql'
CONTRACT = 'onejournal.incremental-activity-import.v1'


def disposable_target(path):
    checked = private_file(Path(path), 'disposable activity journal', private_parent=True)
    bases = (Path('/private/tmp').resolve(), Path(tempfile.gettempdir()).resolve())
    if (not any(checked.is_relative_to(base) for base in bases)
            or checked.name != 'activity-rehearsal.duckdb' or checked.stat().st_nlink != 1):
        raise ValueError('Only an owner-private temporary activity-rehearsal.duckdb is writable.')
    return checked


def _schema(con, *, required=False):
    row = con.execute("SELECT migration_name, file_checksum, status FROM schema_migrations WHERE version='0030'").fetchone()
    exists = con.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name='incremental_activity_imports'").fetchone()[0]
    if row is None and not exists and not required:
        return False
    if row != ('add_incremental_activity_imports', sha256(MIGRATION.read_bytes()).hexdigest(), 'applied') or not exists:
        raise ValueError('Exact activity migration 0030 is required.')
    return True


def _binding_hash(binding):
    return sha256(schwab_account_private_binding_bytes(binding)).hexdigest()


def _ledger(con, baseline, binding):
    """Verify the entire append chain and rebuild its normalized-only overlay."""
    from onejournal.refresh_activity import _FAMILIES, _index
    if not _schema(con):
        return [], {}, baseline.cutoff
    rows = con.execute('''SELECT import_uid, source_broker, source_account_id,
        import_sequence, acquisition_run_uid, artifact_json
        FROM incremental_activity_imports WHERE source_broker='schwab'
        AND source_account_id=? ORDER BY import_sequence''', [binding.source_account_id]).fetchall()
    previous = ''
    cutoff = baseline.assembly.snapshot_cutoff_utc
    records = {name: [] for name in _FAMILIES}
    indexes = {name: _index(next(f.records for f in baseline.assembly.families if f.family == name), identity, observation)
               for name, (identity, observation, _) in _FAMILIES.items()}
    artifacts = []
    for sequence, (uid, broker, account, stored_sequence, run, body) in enumerate(rows, 1):
        artifact = json.loads(body)
        if (sha256(body.encode()).hexdigest() != uid
                or canonical_schwab_evidence_json(artifact) != body
                or stored_sequence != sequence or artifact['sequence'] != sequence
                or artifact['contract_version'] != CONTRACT or artifact['predecessor_uid'] != previous
                or artifact['source_broker'] != broker or artifact['source_account_id'] != account
                or artifact['run_uid'] != run or artifact['binding_sha256'] != _binding_hash(binding)
                or artifact['activation_uid'] != baseline.activation_uid
                or artifact['revision_uid'] != baseline.revision_uid
                or artifact['assembly_fingerprint'] != baseline.assembly.result_fingerprint):
            raise ValueError('Activity lineage differs; explicit source reconciliation is required.')
        next_cutoff = datetime.fromisoformat(artifact['checkpoint_utc'])
        if next_cutoff.tzinfo is None or next_cutoff < cutoff or set(artifact['records']) != set(_FAMILIES):
            raise ValueError('Invalid activity checkpoint or record families.')
        for name, (identity, observation, _) in _FAMILIES.items():
            additions = _index(artifact['records'][name], identity, observation)
            if len(additions) != len(artifact['records'][name]) or indexes[name].keys() & additions.keys():
                raise ValueError('Persisted activity identity was duplicated.')
            indexes[name].update(additions)
            records[name].extend(artifact['records'][name])
        previous, cutoff = uid, next_cutoff
        artifacts.append((uid, artifact))
    return artifacts, records, cutoff


def with_activity_checkpoint(con, baseline, binding):
    artifacts, records, cutoff = _ledger(con, baseline, binding)
    if not artifacts:
        return baseline
    return replace(baseline, checkpoint_uid=artifacts[-1][0], checkpoint_cutoff=cutoff,
                   appended_records=records)


def append_activity_copy(*, db, binding, asof, overlap_days, expected_plan_sha256, **capture_args):
    """Revalidate bytes, then append records + checkpoint in one transaction.

    Any failure rolls back the entire insert. A unique account sequence prevents
    two writers advancing the same predecessor. Exact run replay returns the
    original receipt, including when subsequent increments already exist.
    """
    from onejournal.refresh_activity import (
        _confirmed_import, activity_plan, load_activity_capture, _review_delta, _index, _FAMILIES,
    )
    checked = disposable_target(db)
    acquisition, converted = load_activity_capture(binding=binding, **capture_args)
    manifest = acquisition.manifest
    with duckdb.connect(str(checked)) as con:
        con.execute('BEGIN TRANSACTION')
        try:
            _schema(con, required=True)
            baseline = _confirmed_import(con, binding)
            run = manifest.acquisition_run_uid
            replay = con.execute('''SELECT import_uid, artifact_json FROM incremental_activity_imports
                WHERE source_broker='schwab' AND source_account_id=? AND acquisition_run_uid=?''',
                [binding.source_account_id, run]).fetchone()
            if replay:
                saved = json.loads(replay[1])
                if (saved['manifest_sha256'] != acquisition.manifest_sha256
                        or saved['plan']['plan_sha256'] != expected_plan_sha256
                        or saved['plan']['target_asof'] != asof.isoformat()
                        or saved['plan']['overlap_days'] != overlap_days):
                    raise ValueError('Activity run replay differs.')
                con.execute('ROLLBACK')
                return dict(import_uid=replay[0], created=False, replayed=True,
                            checkpoint_utc=saved['checkpoint_utc'], new_records=saved['new_records'])
            plan = activity_plan(baseline, binding, asof=asof, overlap_days=overlap_days)
            if plan['plan_sha256'] != expected_plan_sha256:
                raise ValueError('Activity predecessor changed; replan before append.')
            review = _review_delta(baseline, converted, plan)
            if review['status'] != 'candidate_only':
                raise ValueError('Unresolved activity cannot advance a checkpoint.')
            # Never claim the unelapsed remainder of today's requested date.
            first_request = min(r.requested_at_utc for r in manifest.requests)
            end = datetime.combine(converted.window_end_date, time(23,59,59,999000), UTC)
            cutoff = min(first_request, end)
            if cutoff < baseline.cutoff:
                raise ValueError('Activity capture cannot regress the confirmed checkpoint.')
            families = {f.family: f for f in baseline.assembly.families}
            records = {}
            for name, (identity, observation, attribute) in _FAMILIES.items():
                before = _index((*families[name].records, *baseline.appended_records.get(name, ())), identity, observation)
                incoming = _index(getattr(converted, attribute), identity, observation)
                records[name] = [json.loads(incoming[k]) for k in sorted(incoming.keys() - before.keys())]
            sequence = con.execute('''SELECT COALESCE(MAX(import_sequence),0)+1 FROM incremental_activity_imports
                WHERE source_broker='schwab' AND source_account_id=?''', [binding.source_account_id]).fetchone()[0]
            artifact = dict(contract_version=CONTRACT, sequence=sequence, run_uid=run,
                source_broker='schwab', source_account_id=binding.source_account_id,
                binding_sha256=_binding_hash(binding), activation_uid=baseline.activation_uid,
                revision_uid=baseline.revision_uid, assembly_fingerprint=baseline.assembly.result_fingerprint,
                predecessor_uid=baseline.checkpoint_uid, checkpoint_utc=cutoff.astimezone(UTC).isoformat(),
                plan=plan, manifest_sha256=acquisition.manifest_sha256,
                source_manifest=json.loads(external_provider_acquisition_manifest_bytes(manifest)),
                records=records, new_records=sum(len(v) for v in records.values()), review=review)
            body = canonical_schwab_evidence_json(artifact)
            uid = sha256(body.encode()).hexdigest()
            con.execute('INSERT INTO incremental_activity_imports VALUES (?,?,?,?,?,?)',
                        [uid, 'schwab', binding.source_account_id, sequence, run, body])
            # Full canonical read-back before COMMIT; failure leaves no cursor.
            restored = _confirmed_import(con, binding)
            if restored.checkpoint_uid != uid or restored.cutoff != cutoff:
                raise ValueError('Activity read-back differs.')
            con.execute('COMMIT')
            return dict(import_uid=uid, created=True, replayed=False,
                        checkpoint_utc=artifact['checkpoint_utc'], new_records=artifact['new_records'])
        except Exception:
            con.execute('ROLLBACK')
            raise
