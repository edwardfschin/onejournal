"""Offline activity planning/review and disposable-copy append rehearsal only."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path

import duckdb

from onejournal.brokers.schwab.account_binding import (
    load_schwab_account_private_binding_bytes, schwab_account_private_binding_bytes,
)
from onejournal.journal.schwab_evidence_assembly import canonical_schwab_evidence_json
from onejournal.journal.schwab_history_revision import _database_contract
from onejournal.journal.schwab_snapshot_evidence_repository import _contract, _read
from onejournal.local_web import private_file
from onejournal.provider_connectors.external_acquisition import (
    SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE,
    convert_external_schwab_lifecycle, load_external_provider_acquisition,
)
from onejournal.provider_connectors.usage_policy import load_provider_usage_policy
from onejournal.refresh_intake import acquisition_bundle, read_private


@dataclass(frozen=True)
class ConfirmedActivityImport:
    activation_uid: str
    revision_uid: str
    assembly: object
    checkpoint_uid: str = ''
    checkpoint_cutoff: datetime | None = None
    appended_records: dict = field(default_factory=dict)

    @property
    def cutoff(self):
        return self.checkpoint_cutoff or self.assembly.snapshot_cutoff_utc


def confirmed_import(db: Path, binding) -> ConfirmedActivityImport:
    """Read one consistent active revision, not the newest saved evidence.

    Legacy date-only coverage deliberately cannot become an incremental cursor.
    Existing migration and canonical-artifact checks are reused, not bypassed.
    """
    checked = private_file(db, 'journal', private_parent=True)
    with duckdb.connect(str(checked), read_only=True) as con:
        con.execute('BEGIN TRANSACTION')
        return _confirmed_import(con, binding)


def _confirmed_import(con, binding):
    """Same reader for offline planning and the writer's commit transaction."""
    _database_contract(con)
    _contract(con)
    row = con.execute('''SELECT c.activation_uid, c.revision_uid, r.assembly_uid,
                                    r.history_window_start, r.history_window_end,
                                    r.snapshot_cutoff_utc
            FROM phase1_journal_current_revision_ids c
            JOIN phase1_journal_all_history_revisions r
              ON c.revision_uid = r.revision_uid
             AND c.source_account_id = r.source_account_id
             AND c.source_broker = r.source_broker
            WHERE c.source_broker = 'schwab' AND c.source_account_id = ?''',
            [binding.source_account_id]).fetchone()
    if row is None or row[5] is None:
        raise ValueError('An active exact-cutoff import is required.')
    assembly = _read(con, row[2])
    if (assembly.connection_uid != binding.connection_uid
                or assembly.source_account_id != binding.source_account_id
                or assembly.lifecycle_window_start != row[3]
                or assembly.lifecycle_window_end != row[4]
                or assembly.snapshot_cutoff_utc != datetime.fromisoformat(row[5])):
        raise ValueError('Active import lineage differs.')
    from onejournal.journal.activity_refresh_repository import with_activity_checkpoint
    return with_activity_checkpoint(con, ConfirmedActivityImport(row[0], row[1], assembly), binding)


def activity_plan(baseline: ConfirmedActivityImport, binding, *, asof: date,
                  overlap_days: int) -> dict:
    """One paired window, at most 30 UTC dates; never skip an intraday cutoff.

    Overlap is explicit configuration, not a silently selected operating policy.
    At most 29 overlap days reserves forward progress in a 30-day capture.
    This plan is not a durable cursor or permission to execute broker requests.
    """
    assembly = baseline.assembly
    cutoff = baseline.cutoff
    if (cutoff is None or type(overlap_days) is not int or not 1 <= overlap_days <= 29
            or type(asof) is not date or asof < cutoff.astimezone(UTC).date()
            or binding.source_account_id != assembly.source_account_id
            or binding.connection_uid != assembly.connection_uid):
        raise ValueError('Incremental window or binding is invalid.')
    start = max(assembly.lifecycle_window_start,
                cutoff.astimezone(UTC).date() - timedelta(days=overlap_days - 1))
    end = min(asof, start + timedelta(days=29))
    plan = dict(contract_version='onejournal.activity-refresh-plan.v1',
                window_start=start.isoformat(), window_end=end.isoformat(),
                target_asof=asof.isoformat(), overlap_days=overlap_days,
                more_windows_pending=end < asof, broker_execution_authorized=False)
    # Bind both activation (including rollback) and exact source/account mapping.
    lineage = [baseline.activation_uid, baseline.revision_uid,
               assembly.result_fingerprint,
               sha256(schwab_account_private_binding_bytes(binding)).hexdigest(), plan]
    if baseline.checkpoint_uid:
        lineage.append(baseline.checkpoint_uid)
    plan['plan_sha256'] = sha256(canonical_schwab_evidence_json(lineage).encode()).hexdigest()
    return plan


_FAMILIES = {
    'orders': ('order_uid', 'order_observation_uid', 'order_records'),
    'transactions': ('transaction_uid', 'transaction_observation_uid', 'transaction_records'),
    'fills': ('source_fill_id', None, 'transaction_rows'),
    'cash': ('cash_uid', 'cash_observation_uid', 'cash_rows'),
    'lifecycle_events': ('event_uid', 'event_observation_uid', 'lifecycle_events'),
    'lifecycle_event_legs': ('event_leg_uid', 'event_leg_observation_uid', 'lifecycle_event_legs'),
}


def _index(records, identity, observation):
    indexed = {}
    for record in records:
        # Remove only assembly observation lineage, never economic/status fields.
        excluded = ({observation, 'source_manifest_sha256', 'source_window_start_date',
                     'source_window_end_date'} if observation else set())
        value = {k: v for k, v in record.items() if k not in excluded}
        uid = value.get(identity)
        if not isinstance(uid, str) or not uid:
            raise ValueError('Activity identity is missing.')
        encoded = canonical_schwab_evidence_json(value)
        if uid in indexed and indexed[uid] != encoded:
            raise ValueError('Conflicting observations require source review.')
        indexed[uid] = encoded
    return indexed


def _prior_order_variants(records):
    """Keep every accepted order-status observation for comparison.

    Historical assemblies can retain several immutable states of one order.
    A new state from a fresh capture still requires source review; none is
    selected as the authoritative financial fill.
    """
    variants = {}
    for record in records:
        indexed = _index((record,), 'order_uid', 'order_observation_uid')
        for uid, encoded in indexed.items():
            variants.setdefault(uid, set()).add(encoded)
    return variants


def _review_delta(baseline, converted, plan) -> dict:
    """Value-free candidate summary, never financial acceptance or import.

    Orders are corroboration; only transaction-derived fills are counted. A
    changed identity blocks the candidate, even if the change looks harmless.
    Missing records are retained, never interpreted as deletes or reversals.
    """
    assembly = baseline.assembly
    if (converted.source_broker != 'schwab'
            or converted.source_account_id != assembly.source_account_id
            or converted.connection_uid != assembly.connection_uid
            or converted.window_start_date.isoformat() != plan['window_start']
            or converted.window_end_date.isoformat() != plan['window_end']):
        raise ValueError('Activity evidence differs from its pinned plan.')
    families = {f.family: f for f in assembly.families}
    counts = {}
    for name, (identity, observation, attribute) in _FAMILIES.items():
        prior = (*families[name].records, *baseline.appended_records.get(name, ()))
        before = (_prior_order_variants(prior) if name == 'orders' else
                  {uid: {encoded} for uid, encoded in _index(prior, identity, observation).items()})
        incoming = _index(getattr(converted, attribute), identity, observation)
        counts[name] = dict(new=sum(k not in before for k in incoming),
                           unchanged=sum(v in before.get(k, ()) for k, v in incoming.items()),
                           changed=sum(k in before and v not in before[k] for k, v in incoming.items()))
    unresolved = (not converted.reconciliation.exact or any(
        row.get('evidence_status') == 'review_required'
        for row in (*converted.cash_rows, *converted.lifecycle_event_legs)))
    conflict = any(c['changed'] for c in counts.values())
    return dict(contract_version='onejournal.activity-refresh-review.v1',
                plan_sha256=plan['plan_sha256'],
                manifest_sha256=converted.external_manifest_sha256,
                status='review_required' if conflict or unresolved else 'candidate_only',
                counts=counts, source_reconciliation_exact=converted.reconciliation.exact,
                cursor_advanced=False, journal_written=False,
                financial_publication_authorized=False)


def review_activity(*, db, binding, asof, overlap_days, expected_plan_sha256,
                    acquisition_root, acknowledgement, usage_policy,
                    expected_run_uid, expected_approval_id, expected_owner_uid,
                    expected_owner_epoch_uid, evaluated_at):
    baseline = confirmed_import(db, binding)
    plan = activity_plan(baseline, binding, asof=asof, overlap_days=overlap_days)
    if plan['plan_sha256'] != expected_plan_sha256:
        raise ValueError('Active import or planned window changed; replan first.')
    acquisition, converted = load_activity_capture(binding=binding,
        acquisition_root=acquisition_root, acknowledgement=acknowledgement,
        usage_policy=usage_policy, expected_run_uid=expected_run_uid,
        expected_approval_id=expected_approval_id, expected_owner_uid=expected_owner_uid,
        expected_owner_epoch_uid=expected_owner_epoch_uid, evaluated_at=evaluated_at)
    if any(r.requested_at_utc < baseline.cutoff for r in acquisition.manifest.requests):
        raise ValueError('Activity capture predates the confirmed checkpoint.')
    result = _review_delta(baseline, converted, plan)
    current = activity_plan(confirmed_import(db, binding), binding,
                            asof=asof, overlap_days=overlap_days)
    if current != plan:
        raise ValueError('Active import changed during review; replan first.')
    return result


def load_activity_capture(*, binding, acquisition_root, acknowledgement, usage_policy,
                          expected_run_uid, expected_approval_id, expected_owner_uid,
                          expected_owner_epoch_uid, evaluated_at):
    """One exact-byte validation boundary shared by review and append."""
    manifest, responses = acquisition_bundle(acquisition_root, response_count=2)
    acquisition = load_external_provider_acquisition(
        manifest, response_bytes=responses,
        acknowledgement_bytes=read_private(acknowledgement, 256 * 1024),
        usage_policy=usage_policy, evaluated_at_utc=evaluated_at,
        expected_acquisition_run_uid=expected_run_uid,
        expected_acquisition_approval_id=expected_approval_id,
        expected_owner_uid=expected_owner_uid,
        expected_owner_epoch_uid=expected_owner_epoch_uid)
    if (acquisition.manifest.profile != SCHWAB_LIFECYCLE_EXTERNAL_ACQUISITION_PROFILE
            or acquisition.manifest.connection_uid != binding.connection_uid
            or acquisition.manifest.controls.oauth_refresh_count != 0):
        raise ValueError('Activity capture scope or timing differs.')
    converted = convert_external_schwab_lifecycle(
        acquisition, provider_account_hash=binding.provider_account_hash,
        provider_account_number=binding.provider_account_number,
        source_account_id=binding.source_account_id)
    return acquisition, converted


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--account-binding', type=Path, required=True)
    parser.add_argument('--asof', type=date.fromisoformat, required=True,
                        help='UTC acquisition end date, not a P&L valuation date')
    parser.add_argument('--overlap-days', type=int, required=True)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('plan')
    for command in ('review', 'rehearse'):
        sub = commands.add_parser(command)
        for name in ('acquisition-root', 'acknowledgement', 'usage-policy'):
            sub.add_argument('--' + name, type=Path, required=True)
        for name in ('expected-plan-sha256', 'expected-run-uid', 'expected-approval-id',
                     'expected-owner-uid', 'expected-owner-epoch-uid'):
            sub.add_argument('--' + name, required=True)
    args = parser.parse_args(argv)
    try:
        now = datetime.now(UTC)
        if args.asof > now.date():
            raise ValueError('A future acquisition end date is not supported.')
        binding = load_schwab_account_private_binding_bytes(read_private(args.account_binding, 256 * 1024))
        if args.command == 'plan':
            result = activity_plan(confirmed_import(args.db, binding), binding,
                                   asof=args.asof, overlap_days=args.overlap_days)
        else:
            kwargs = dict(binding=binding, asof=args.asof,
                overlap_days=args.overlap_days, expected_plan_sha256=args.expected_plan_sha256,
                acquisition_root=args.acquisition_root, acknowledgement=args.acknowledgement,
                usage_policy=load_provider_usage_policy(args.usage_policy),
                expected_run_uid=args.expected_run_uid, expected_approval_id=args.expected_approval_id,
                expected_owner_uid=args.expected_owner_uid,
                expected_owner_epoch_uid=args.expected_owner_epoch_uid, evaluated_at=now)
            if args.command == 'rehearse':
                from onejournal.activity_rehearsal import rehearse_activity
                result = rehearse_activity(args.db, **kwargs)
            else:
                result = review_activity(db=args.db, **kwargs)
        print(json.dumps(result, sort_keys=True))
        return 2 if result.get('status') == 'review_required' else 0
    except Exception:
        print('Activity preparation stopped. Check the active exact-cutoff import, pinned plan, private binding and verified bundle. No broker call or live write was attempted; any temporary rehearsal copy is discarded.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
