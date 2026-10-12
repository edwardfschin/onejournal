"""Versioned recovered-opening supplement and read-only financial preview.

Recovered retained JSON files are not verified external acquisitions. This
route preserves that distinction and cannot persist or authorize a report.
"""
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, localcontext
from hashlib import sha256
import json
from pathlib import Path
import re

import duckdb

from onejournal.brokers.schwab.archive_review import review_archive_trade_versions
from onejournal.instruments import InstrumentIdentity
from onejournal.journal.lifecycle import build_lifecycle_fill_events
from onejournal.journal.phase1_reporting_calculation import (
    _load_episode_scopes, _ordinary_realized_item, calculate_bounded_realized_result,
)
from onejournal.journal.pnl_repository import load_approved_lifecycle_events, load_normalized_fills
from onejournal.journal.schwab_evidence_assembly import (
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V3, canonical_schwab_evidence_json,
    freeze_schwab_evidence_value, schwab_phase1_evidence_assembly_bytes,
    validate_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_execution_projection import _calculated_net_cash
from onejournal.journal.schwab_journal_lifecycle_reconciliation import _event_instrument_key
from onejournal.journal.schwab_snapshot_evidence_repository import load_schwab_snapshot_evidence
from onejournal.pnl.bounded_reconciliation import normalized_fill_from_lifecycle_transaction_row
from onejournal.pnl.calculations import build_instrument_key, calculate_fifo_pnl_from_fills


SUPPLEMENT_VERSION = "onejournal.recovered-opening-supplement.v1"
PREVIEW_VERSION = "onejournal.recovered-opening-realized-preview.v1"


class RecoveredOpeningError(ValueError):
    """Value-free failure at the recovered-evidence boundary."""


def _hash(value):
    return sha256(canonical_schwab_evidence_json(value).encode()).hexdigest()


def _digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise RecoveredOpeningError("exact fingerprint is required")
    return value


def _families(assembly):
    validate_schwab_phase1_evidence_assembly(assembly)
    if assembly.contract_version != SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V3:
        raise RecoveredOpeningError("recovered preview requires an exact snapshot assembly v3")
    families = {family.family: family.records for family in assembly.families}
    if families['account'][0].get('account_complete') is not True:
        raise RecoveredOpeningError("complete position snapshot is required")
    return families


def _fill(row, observed_at, locator):
    try:
        fill = normalized_fill_from_lifecycle_transaction_row(
            row, fetched_at=observed_at, raw_path=locator)
        InstrumentIdentity.from_fill(fill)
        if (fill.quantity <= 0 or fill.fill_price < 0 or fill.commission < 0 or fill.fees < 0
                or fill.side not in {'BUY', 'SELL'} or fill.episode_group_id):
            raise ValueError('unsupported economics or grouping')
        return fill
    except (ValueError, TypeError, KeyError) as exc:
        raise RecoveredOpeningError("recovered opening has invalid exact fill evidence") from exc


def _validate(document, assembly):
    families = _families(assembly)
    required = {'contract_version', 'source_kind', 'original_acquisition_manifest',
                'original_capture_instant', 'normalization_observed_at_utc', 'approval_id',
                'base_assembly_uid', 'base_assembly_fingerprint', 'base_realized_fingerprint',
                'base_revision_uids', 'reviewed_instrument_keys', 'openings', 'supplement_fingerprint'}
    if (set(document) != required or document['contract_version'] != SUPPLEMENT_VERSION
            or document['source_kind'] != 'recovered_retained_json'
            or document['original_acquisition_manifest'] is not None
            or document['original_capture_instant'] is not None
            or document['base_assembly_uid'] != assembly.assembly_uid
            or document['base_assembly_fingerprint'] != assembly.result_fingerprint
            or not re.fullmatch(r'[A-Za-z0-9_.:-]{8,192}', str(document['approval_id']))):
        raise RecoveredOpeningError("supplement source kind, approval or parent differs")
    _digest(document['base_realized_fingerprint'])
    if not document['base_revision_uids'] or len(set(document['base_revision_uids'])) != len(document['base_revision_uids']):
        raise RecoveredOpeningError("exact parent revisions are required")
    _digest(document['supplement_fingerprint'])
    if document['supplement_fingerprint'] != _hash({key: value for key, value in document.items() if key != 'supplement_fingerprint'}):
        raise RecoveredOpeningError("supplement fingerprint differs")
    try:
        observed = datetime.fromisoformat(document['normalization_observed_at_utc'])
    except (TypeError, ValueError) as exc:
        raise RecoveredOpeningError("invalid normalization observation instant") from exc
    if observed.tzinfo is None or observed.astimezone(UTC) < assembly.snapshot_cutoff_utc:
        raise RecoveredOpeningError("normalization observation requires an explicit post-snapshot instant")
    keys = document['reviewed_instrument_keys']
    if not 1 <= len(keys) <= 2 or len(set(keys)) != len(keys) or len(document['openings']) != len(keys):
        raise RecoveredOpeningError("supplement permits at most two explicit independent scopes")
    existing_ids = {row['source_fill_id'] for row in families['fills']}
    result = []
    found_keys, found_ids = set(), set()
    for opening in document['openings']:
        if set(opening) != {'normalized_row', 'cash_versions'}:
            raise RecoveredOpeningError("opening evidence fields differ")
        row = opening['normalized_row']
        fill = _fill(row, observed, 'recovered-opening:' + document['supplement_fingerprint'])
        key = InstrumentIdentity.from_fill(fill).key
        if (fill.source_broker != assembly.provider or fill.source_account_id != assembly.source_account_id
                or key not in keys or key in found_keys or fill.source_fill_id in found_ids
                or fill.source_fill_id in existing_ids or fill.open_close != 'open'
                or fill.asof >= assembly.lifecycle_window_start
                or fill.filled_at.date() >= assembly.lifecycle_window_start
                or fill.currency != families['account'][0]['currency']):
            raise RecoveredOpeningError("opening scope, identity or prior-history boundary differs")
        found_keys.add(key); found_ids.add(fill.source_fill_id)
        cash_versions = opening['cash_versions']
        if not cash_versions:
            raise RecoveredOpeningError("all retained cash versions are required")
        for cash in cash_versions:
            if set(cash) != {'raw_sha256', 'canonical_record_sha256', 'net_amount', 'security_cost'}:
                raise RecoveredOpeningError("cash evidence fields differ")
            _digest(cash['raw_sha256']); _digest(cash['canonical_record_sha256'])
            if any(not isinstance(cash[field], str) for field in ('net_amount', 'security_cost')):
                raise RecoveredOpeningError("cash evidence requires exact decimal text")
            try:
                net, cost = Decimal(cash['net_amount']), Decimal(cash['security_cost'])
            except InvalidOperation as exc:
                raise RecoveredOpeningError("cash evidence must be exact decimal text") from exc
            if not net.is_finite() or not cost.is_finite():
                raise RecoveredOpeningError("cash evidence must be finite")
            calc = dict(row); calc['multiplier'] = row['multiplier'] or None
            with localcontext() as context:
                context.prec = 80
                if (net != _calculated_net_cash(calc)
                        or abs(cost) != fill.quantity * fill.fill_price * (fill.multiplier or Decimal(1))):
                    raise RecoveredOpeningError("recovered execution cash does not reconcile")
        result.append(fill)
    return families, tuple(result)


def build_recovered_opening_supplement(*, assembly, observations, selected_source_fill_ids,
                                     reviewed_instrument_keys, cash_versions, base_realized_fingerprint,
                                     base_revision_uids, approval_id, observed_at):
    """Build an immutable supplement only after all retained versions agree."""
    families = _families(assembly)
    reviews = review_archive_trade_versions(tuple(observations), source_account_id=assembly.source_account_id,
                                           existing_rows=tuple(families['fills']))
    selected = tuple(selected_source_fill_ids)
    if len(set(selected)) != len(selected):
        raise RecoveredOpeningError("selected opening IDs must be distinct")
    openings = []
    for uid in sorted(selected):
        matches = [item for item in reviews if any(row['source_fill_id'] == uid for row in item.new_rows)]
        if len(matches) != 1 or matches[0].status != 'candidate' or len(matches[0].rows) != 1:
            raise RecoveredOpeningError("opening has conflicting, duplicate or multi-security source versions")
        item = matches[0]
        activity = item.rows[0]['source_fill_id'].split(':')[1]
        expected = {(ob.raw_sha256, ob.record_sha256) for ob in observations if ob.activity_id == activity}
        cash = tuple(cash_versions.get(uid, ()))
        actual = {(row['raw_sha256'], row['canonical_record_sha256']) for row in cash}
        if actual != expected:
            raise RecoveredOpeningError("cash evidence does not cover every retained source version")
        openings.append({'normalized_row': dict(item.rows[0]),
                         'cash_versions': sorted(cash, key=canonical_schwab_evidence_json)})
    document = {'contract_version': SUPPLEMENT_VERSION, 'source_kind': 'recovered_retained_json',
                'original_acquisition_manifest': None, 'original_capture_instant': None,
                'normalization_observed_at_utc': observed_at.isoformat(), 'approval_id': approval_id,
                'base_assembly_uid': assembly.assembly_uid, 'base_assembly_fingerprint': assembly.result_fingerprint,
                'base_realized_fingerprint': base_realized_fingerprint,
                'base_revision_uids': tuple(sorted(base_revision_uids)),
                'reviewed_instrument_keys': tuple(sorted(reviewed_instrument_keys)), 'openings': openings}
    document['supplement_fingerprint'] = _hash(document)
    _validate(document, assembly)
    return freeze_schwab_evidence_value(document)


def recovered_opening_supplement_bytes(document):
    return canonical_schwab_evidence_json(document).encode()


def load_recovered_opening_supplement_bytes(body, *, assembly, expected_fingerprint):
    document = json.loads(body)
    if document.get('supplement_fingerprint') != _digest(expected_fingerprint):
        raise RecoveredOpeningError("exact expected supplement is required")
    _validate(document, assembly)
    return freeze_schwab_evidence_value(document)


def calculate_recovered_opening_preview(db_path: Path, *, assembly, supplement, expected_fingerprint):
    """Read an exact parent and calculate only the approved recovered scopes.

    No DB writes or financial acceptance exist here. Parent items are retained
    exactly, and only wholly covered opening-history omissions may be removed.
    """
    if supplement['supplement_fingerprint'] != _digest(expected_fingerprint):
        raise RecoveredOpeningError("exact expected supplement is required")
    families, recovered = _validate(supplement, assembly)
    stored = load_schwab_snapshot_evidence(db_path, assembly_uid=assembly.assembly_uid)
    if schwab_phase1_evidence_assembly_bytes(stored) != schwab_phase1_evidence_assembly_bytes(assembly):
        raise RecoveredOpeningError("stored parent assembly differs")
    base = calculate_bounded_realized_result(db_path)
    if (base.result_fingerprint != supplement['base_realized_fingerprint']
            or tuple(sorted(authority.revision_uid for authority in base.authorities)) != tuple(supplement['base_revision_uids'])
            or any(authority.source_account_id != assembly.source_account_id or authority.snapshot_cutoff_utc != assembly.snapshot_cutoff_utc
                   for authority in base.authorities)):
        raise RecoveredOpeningError("parent financial or active history authority differs")
    keys = set(supplement['reviewed_instrument_keys'])
    with duckdb.connect(str(db_path), read_only=True) as con:
        _, fill_episodes = _load_episode_scopes(con)
        fills = [fill for fill in load_normalized_fills(con, asof=assembly.lifecycle_window_end)
                 if fill.fill_uid in fill_episodes and InstrumentIdentity.from_fill(fill).key in keys]
        pnl_keys = {build_instrument_key(fill) for fill in fills}
        if any(event.option_instrument_key in pnl_keys or set(event.predecessor_open_fill_uids) & {fill.fill_uid for fill in fills}
               for event in load_approved_lifecycle_events(con, asof=assembly.lifecycle_window_end)):
            raise RecoveredOpeningError("recovered scope requires separate approved-event integration")
    fill_ids = {fill.fill_uid for fill in fills}
    if not fill_ids or len(fill_ids) != len(fills):
        raise RecoveredOpeningError("selected scopes lack distinct verified parent fills")
    for leg in families['lifecycle_event_legs']:
        if leg.get('leg_kind') == 'security' and _event_instrument_key(leg, currency=families['account'][0]['currency']) in keys:
            raise RecoveredOpeningError("recovered scope requires separate lifecycle-event review")
    combined = [*fills, *recovered]
    if len({fill.fill_uid for fill in combined}) != len(combined):
        raise RecoveredOpeningError("recovered fill duplicates verified history")
    for key in keys:
        scope = [fill for fill in combined if InstrumentIdentity.from_fill(fill).key == key]
        if not any(fill.fill_uid in fill_ids for fill in scope) or len({build_instrument_key(fill) for fill in scope}) != 1:
            raise RecoveredOpeningError("scope identity needs alias resolution or verified history")
        try:
            build_lifecycle_fill_events(scope)
        except ValueError as exc:
            raise RecoveredOpeningError("recovered scope remains lifecycle-incomplete") from exc
    try:
        calculation = calculate_fifo_pnl_from_fills(combined, allow_unmatched_close=False)
    except ValueError as exc:
        raise RecoveredOpeningError("recovered scope cannot produce reconciled FIFO allocations") from exc
    positions = {row['instrument_key']: Decimal(row['quantity']) for row in families['positions']}
    for key in keys:
        representative = next(fill for fill in combined if InstrumentIdentity.from_fill(fill).key == key)
        group = calculation.groups[(representative.source_broker, representative.source_account_id,
                                    build_instrument_key(representative), representative.currency)]
        if group.open_quantity != positions.get(key, Decimal(0)):
            raise RecoveredOpeningError("recovered scope does not reconcile to the same complete snapshot")
    removed = [omission for omission in base.omissions if set(omission.source_fill_uids) & fill_ids]
    if (not removed or any(omission.reason_code != 'opening_history_missing'
                          or not set(omission.source_fill_uids).issubset(fill_ids) for omission in removed)):
        raise RecoveredOpeningError("only fully covered missing-opening omissions may be replaced")
    by_uid = {fill.fill_uid: fill for fill in combined}
    scope_items = tuple(_ordinary_realized_item(item, by_uid[item.close_fill_uid]) for item in calculation.closed_allocations)
    if any(not base.coverage_start_date <= item.close_market_date <= base.coverage_end_date for item in scope_items):
        raise RecoveredOpeningError("supplement cannot expand verified report date coverage")
    old = {item.item_uid: item for item in base.items}
    new = {item.item_uid: item for item in scope_items}
    if len(new) != len(scope_items) or any(old[uid] != new[uid] for uid in old.keys() & new.keys()):
        raise RecoveredOpeningError("prior admitted allocations changed or duplicated")
    scope_pnl_keys = {build_instrument_key(fill) for fill in combined}
    if any(item.instrument_key in scope_pnl_keys and item.item_uid not in new for item in base.items):
        raise RecoveredOpeningError("prior scoped allocations were lost")
    added = tuple(item for item in scope_items if item.item_uid not in old)
    removed_ids = {item.omission_uid for item in removed}
    result = {'contract_version': PREVIEW_VERSION, 'supplement_fingerprint': expected_fingerprint,
              'calculation_version': base.calculation_version + '+recovered-openings-v1',
              'added_allocation_calculation_version': calculation.calculation_version,
              'base_realized_fingerprint': base.result_fingerprint,
              'verified_coverage_start_date': base.coverage_start_date, 'verified_coverage_end_date': base.coverage_end_date,
              'coverage_expanded': False, 'lifetime_history_complete': False,
              'financial_acceptance': False, 'report_persistence_authority': False,
              'items': tuple(asdict(item) for item in (*base.items, *added)),
              'omissions': tuple(asdict(item) for item in base.omissions if item.omission_uid not in removed_ids),
              'added_item_uids': tuple(sorted(item.item_uid for item in added)),
              'removed_omission_uids': tuple(sorted(removed_ids)),
              'reviewed_instrument_keys': tuple(sorted(keys))}
    result['preview_fingerprint'] = _hash(result)
    return freeze_schwab_evidence_value(result)
