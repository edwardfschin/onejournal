"""Atomic, append-only activity evidence/checkpoint and optional saved Journal.

The canonical artifact stores new normalized records, exact source-manifest
lineage and the resulting checkpoint together. Existing financial read models
remain unchanged for copy rehearsals. The website writer additionally retains
the Journal read model in the same immutable artifact and transaction.
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
JOURNAL_CONTRACT = 'onejournal.incremental-activity-import.v2'


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
    from onejournal.refresh_activity import (
        _FAMILIES, _index, _prior_order_variants, _review_order_corrections,
    )
    if not _schema(con):
        return [], {}, baseline.cutoff
    rows = con.execute('''SELECT import_uid, source_broker, source_account_id,
        import_sequence, acquisition_run_uid, artifact_json
        FROM incremental_activity_imports WHERE source_broker='schwab'
        AND source_account_id=? ORDER BY import_sequence''', [binding.source_account_id]).fetchall()
    if not rows:
        # An empty additive ledger must preserve the accepted baseline exactly.
        # Legacy observation variants are reconciled only when an increment
        # actually compares identities; a schema-only rehearsal adds no cursor.
        return [], {}, baseline.cutoff
    previous = ''
    cutoff = baseline.assembly.snapshot_cutoff_utc
    records = {name: [] for name in _FAMILIES}
    indexes = {name: (_prior_order_variants(next(f.records for f in baseline.assembly.families if f.family == name))
                      if name == 'orders' else _index(next(f.records for f in baseline.assembly.families if f.family == name), identity, observation))
               for name, (identity, observation, _) in _FAMILIES.items()}
    artifacts = []
    for sequence, (uid, broker, account, stored_sequence, run, body) in enumerate(rows, 1):
        artifact = json.loads(body)
        if (sha256(body.encode()).hexdigest() != uid
                or canonical_schwab_evidence_json(artifact) != body
                or stored_sequence != sequence or artifact['sequence'] != sequence
                or artifact['contract_version'] not in (CONTRACT, JOURNAL_CONTRACT) or artifact['predecessor_uid'] != previous
                or artifact['source_broker'] != broker or artifact['source_account_id'] != account
                or artifact['run_uid'] != run or artifact['binding_sha256'] != _binding_hash(binding)
                or artifact['activation_uid'] != baseline.activation_uid
                or artifact['revision_uid'] != baseline.revision_uid
                or artifact['assembly_fingerprint'] != baseline.assembly.result_fingerprint):
            raise ValueError('Activity lineage differs; explicit source reconciliation is required.')
        if artifact['contract_version'] == JOURNAL_CONTRACT and artifact.get('journal_view', {}).get('contract_version') != 'onejournal.activity-journal.v1':
            raise ValueError('Saved activity Journal view is missing.')
        next_cutoff = datetime.fromisoformat(artifact['checkpoint_utc'])
        if next_cutoff.tzinfo is None or next_cutoff < cutoff or set(artifact['records']) != set(_FAMILIES):
            raise ValueError('Invalid activity checkpoint or record families.')
        incoming_orders = _index(artifact['records']['orders'], 'order_uid', 'order_observation_uid')
        reviewed = _review_order_corrections(indexes['orders'], incoming_orders,
            (*next(f.records for f in baseline.assembly.families if f.family == 'fills'),
             *records['fills'], *artifact['records']['fills']))
        if (artifact.get('order_corrections', []) != [reviewed[uid] for uid in sorted(reviewed)]
                or artifact['review'].get('source_reviewed_order_correction_count', 0) != len(reviewed)):
            raise ValueError('Persisted order correction review differs.')
        for name, (identity, observation, _) in _FAMILIES.items():
            additions = _index(artifact['records'][name], identity, observation)
            duplicate_ids = indexes[name].keys() & additions.keys()
            if (len(additions) != len(artifact['records'][name])
                    or duplicate_ids != (reviewed.keys() if name == 'orders' else set())):
                raise ValueError('Persisted activity identity was duplicated.')
            if name == 'orders':
                for order_uid, encoded in additions.items():
                    indexes[name].setdefault(order_uid, set()).add(encoded)
            else:
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


def activity_recovery_digests(con):
    """Extend the existing recovery allowlist with exact retained activity files.

    No filesystem discovery or broker capability. This verifies stored artifact
    bytes, append lineage and the existing manifest contract before selecting
    source responses, acknowledgements and private account bindings for backup.
    """
    from onejournal.provider_connectors.external_acquisition import (
        _parse_manifest, SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE,
    )
    tables = {r[0] for r in con.execute('SHOW TABLES').fetchall()}
    if 'schema_migrations' not in tables:
        if 'incremental_activity_imports' in tables:
            raise ValueError('Activity recovery ledger lacks migration authority.')
        return set()
    if not _schema(con):
        return set()
    required, heads = set(), {}
    for uid, account, sequence, run, body in con.execute('''SELECT import_uid,source_account_id,
        import_sequence,acquisition_run_uid,artifact_json FROM incremental_activity_imports
        WHERE source_broker='schwab' ORDER BY source_account_id,import_sequence''').fetchall():
        artifact = json.loads(body)
        previous, expected_sequence = heads.get(account,('',1))
        if (sha256(body.encode()).hexdigest()!=uid or canonical_schwab_evidence_json(artifact)!=body
                or artifact['contract_version'] not in (CONTRACT,JOURNAL_CONTRACT) or artifact['source_broker']!='schwab'
                or artifact['source_account_id']!=account or artifact['sequence']!=sequence
                or sequence!=expected_sequence or artifact['predecessor_uid']!=previous
                or artifact['run_uid']!=run):
            raise ValueError('Activity recovery artifact or append chain differs.')
        manifest = _parse_manifest(artifact['source_manifest'])
        manifest_bytes = external_provider_acquisition_manifest_bytes(manifest)
        if (manifest.profile!=SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE
                or manifest.acquisition_run_uid!=run or manifest.controls.oauth_refresh_count!=0
                or sha256(manifest_bytes).hexdigest()!=artifact['manifest_sha256']):
            raise ValueError('Activity recovery source manifest differs.')
        digests = {artifact['manifest_sha256'], artifact['binding_sha256'], manifest.acknowledgement_sha256,
                   *(r.response_sha256 for r in manifest.requests)}
        if any(not isinstance(d,str) or len(d)!=64 or set(d)-set('0123456789abcdef') for d in digests):
            raise ValueError('Activity recovery source digest is invalid.')
        required.update(digests)
        heads[account] = (uid,sequence+1)
    return required


def append_activity_copy(*, db, binding, asof, overlap_days, expected_plan_sha256, **capture_args):
    checked = disposable_target(db)
    return _append_activity(db=checked, binding=binding, asof=asof,
        overlap_days=overlap_days, expected_plan_sha256=expected_plan_sha256, **capture_args)


def append_activity_journal(*, db, **capture_args):
    """Server-selected Mac target; a validated upload saves Journal and cursor."""
    checked = private_file(Path(db), 'saved journal', private_parent=True)
    if checked.stat().st_nlink != 1:
        raise ValueError('Saved journal must not have another hard link.')
    return _append_activity(db=checked, save_journal=True, **capture_args)


def _append_activity(*, db, binding, asof, overlap_days, expected_plan_sha256,
                     save_journal=False, **capture_args):
    """Revalidate bytes, then append records + checkpoint in one transaction.

    Any failure rolls back the entire insert. A unique account sequence prevents
    two writers advancing the same predecessor. Exact run replay returns the
    original receipt, including when subsequent increments already exist.
    """
    from onejournal.refresh_activity import (
        _confirmed_import, activity_plan, load_activity_capture, _review_delta,
        _index, _prior_order_variants, _review_order_corrections, _FAMILIES,
    )
    acquisition, converted = load_activity_capture(binding=binding, **capture_args)
    manifest = acquisition.manifest
    with duckdb.connect(str(db)) as con:
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
                if save_journal and saved.get('journal_view', {}).get('contract_version') != 'onejournal.activity-journal.v1':
                    raise ValueError('This retained import has no saved Journal view.')
                con.execute('ROLLBACK')
                return dict(import_uid=replay[0], created=False, replayed=True,
                            checkpoint_utc=saved['checkpoint_utc'], new_records=saved['new_records'],
                            **(_journal_receipt(saved) if save_journal else {}))
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
            order_corrections = {}
            for name, (identity, observation, attribute) in _FAMILIES.items():
                prior = (*families[name].records, *baseline.appended_records.get(name, ()))
                before = (_prior_order_variants(prior) if name == 'orders' else
                          _index(prior, identity, observation))
                incoming = _index(getattr(converted, attribute), identity, observation)
                if name == 'orders':
                    order_corrections = _review_order_corrections(before, incoming,
                        (*families['fills'].records, *baseline.appended_records.get('fills', ()),
                         *converted.transaction_rows))
                selected = (incoming.keys() - before.keys()) | (order_corrections.keys() if name == 'orders' else set())
                records[name] = [json.loads(incoming[k]) for k in sorted(selected)]
            if len(order_corrections) != review['source_reviewed_order_correction_count']:
                raise ValueError('Order correction review changed before append.')
            sequence = con.execute('''SELECT COALESCE(MAX(import_sequence),0)+1 FROM incremental_activity_imports
                WHERE source_broker='schwab' AND source_account_id=?''', [binding.source_account_id]).fetchone()[0]
            artifact = dict(contract_version=CONTRACT, sequence=sequence, run_uid=run,
                source_broker='schwab', source_account_id=binding.source_account_id,
                binding_sha256=_binding_hash(binding), activation_uid=baseline.activation_uid,
                revision_uid=baseline.revision_uid, assembly_fingerprint=baseline.assembly.result_fingerprint,
                predecessor_uid=baseline.checkpoint_uid, checkpoint_utc=cutoff.astimezone(UTC).isoformat(),
                plan=plan, manifest_sha256=acquisition.manifest_sha256,
                source_manifest=json.loads(external_provider_acquisition_manifest_bytes(manifest)),
                records=records, new_records=sum(len(v) for v in records.values()), review=review,
                order_corrections=[order_corrections[uid] for uid in sorted(order_corrections)])
            if save_journal:
                _save_journal(con, artifact, baseline, records, cutoff)
            body = canonical_schwab_evidence_json(artifact)
            uid = sha256(body.encode()).hexdigest()
            con.execute('INSERT INTO incremental_activity_imports VALUES (?,?,?,?,?,?)',
                        [uid, 'schwab', binding.source_account_id, sequence, run, body])
            # Full canonical read-back before COMMIT; failure leaves no cursor.
            restored = _confirmed_import(con, binding)
            if restored.checkpoint_uid != uid or restored.cutoff != cutoff:
                raise ValueError('Activity read-back differs.')
            if save_journal:
                from onejournal.journal.domain import current_journal_relation
                relation = current_journal_relation(con, 'trade_episodes')
                found = {r[0] for r in con.execute(f'SELECT episode_uid FROM {relation} WHERE source_broker=? AND source_account_id=?',
                    ['schwab', binding.source_account_id]).fetchall()}
                expected = {r['episode_uid'] for r in artifact['journal_view']['relations']['trade_episodes']}
                if found != expected:
                    raise ValueError('Saved Journal read-back differs.')
            con.execute('COMMIT')
            return dict(import_uid=uid, created=True, replayed=False,
                        checkpoint_utc=artifact['checkpoint_utc'], new_records=artifact['new_records'],
                        **(_journal_receipt(artifact) if save_journal else {}))
        except Exception:
            con.execute('ROLLBACK')
            raise


def _journal_receipt(artifact):
    rows = artifact['journal_view']['relations']
    return dict(journal_written=True, trade_count=len(rows['trade_episodes']),
                execution_count=len(rows['phase1_journal_projected_executions']))


def _save_journal(con, artifact, baseline, records, cutoff):
    from onejournal.activity_financial_preview import _build_preview
    from onejournal.journal.pnl_repository import load_approved_lifecycle_events
    from onejournal.journal.schwab_history_revision import _insert_fill, _stable_fill_row, _stored_stable_fill_row
    pending = replace(baseline, checkpoint_uid='activity-journal:' + sha256(
        canonical_schwab_evidence_json(artifact).encode()).hexdigest(), checkpoint_cutoff=cutoff,
        appended_records={name: (*baseline.appended_records.get(name, ()), *rows)
                          for name, rows in records.items()})
    preview = _build_preview(pending, approved_events=load_approved_lifecycle_events(con, asof=cutoff.date()),
                             account_alias='Journal', include_journal=True)
    view = preview.journal_relations
    incoming_uids = {r['episode_uid'] for r in view['relations']['trade_episodes']}
    # Preserve note/review links if an unusual source correction changes grouping.
    from onejournal.journal.domain import current_journal_relation
    prior = current_journal_relation(con, 'trade_episodes')
    linked = {r[0] for r in con.execute(f'''SELECT e.episode_uid FROM {prior} e
        WHERE e.source_broker='schwab' AND e.source_account_id=? AND
        (EXISTS (SELECT 1 FROM journal_entry_revisions n WHERE n.episode_uid=e.episode_uid)
         OR EXISTS (SELECT 1 FROM manual_reviews r WHERE r.episode_uid=e.episode_uid))''',
        [baseline.assembly.source_account_id]).fetchall()}
    if not linked.issubset(incoming_uids):
        raise ValueError('New grouping would detach an existing Journal entry or review.')
    new_fills = []
    for fill in preview.normalized_fills:
        stored = _stored_stable_fill_row(con, fill.fill_uid)
        if stored is None:
            new_fills.append(fill)
        elif stored != _stable_fill_row(fill):
            raise ValueError('Saved normalized fill differs from the upload.')
    if new_fills:
        con.execute('''INSERT INTO import_runs VALUES (?, 'schwab_activity_journal', NULL, ?, ?, ?,
                    'completed', 'validated incremental Journal import')''',
            [pending.checkpoint_uid, cutoff.date(), cutoff.replace(tzinfo=None), len(new_fills)])
        for fill in new_fills:
            _insert_fill(con, fill, import_run_id=pending.checkpoint_uid)
    artifact.update(contract_version=JOURNAL_CONTRACT, journal_view=view)
