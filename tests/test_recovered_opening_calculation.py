from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import patch

import duckdb
import pytest

import test_phase1_reporting_calculation as reporting_fixture
from test_snapshot_cutoff_evidence import inputs
from onejournal.brokers.schwab.archive_review import ArchiveTradeObservation
from onejournal.instruments import InstrumentIdentity
from onejournal.journal.phase1_reporting_calculation import RealizedScopeOmission
from onejournal.journal.schwab_evidence_assembly import (
    _family, build_schwab_phase1_evidence_assembly_v3,
    calculate_schwab_evidence_assembly_fingerprint,
)
from onejournal.journal.recovered_opening_calculation import (
    RecoveredOpeningError, build_recovered_opening_supplement,
    calculate_recovered_opening_preview, load_recovered_opening_supplement_bytes,
    recovered_opening_supplement_bytes,
)

MODULE = 'onejournal.journal.recovered_opening_calculation.'
OBSERVED = datetime(2026, 9, 7, tzinfo=UTC)


def assembly_with(original, **families):
    changed = tuple(_family(family.family, source_manifest_sha256s=family.source_manifest_sha256s,
        source_raw_sha256s=family.source_raw_sha256s, source_record_count=len(families[family.family]),
        records=tuple(families[family.family])) if family.family in families else family for family in original.families)
    candidate = replace(original, families=changed)
    fingerprint = calculate_schwab_evidence_assembly_fingerprint(candidate)
    return replace(candidate, result_fingerprint=fingerprint, assembly_uid='schwab-evidence-assembly:' + fingerprint)


def setup_case(option=False):
    parent = build_schwab_phase1_evidence_assembly_v3(**inputs())
    old = dict(next(f.records[0] for f in parent.families if f.family == 'fills'))
    close = dict(old, source_fill_id='schwab_txn:456:order:555:position:2:item:0',
                 source_order_id='555', symbol='TEST', side='sell', open_close='close',
                 fill_price='120', commission='0.5')
    opener = dict(close, source_fill_id='schwab_txn:123:order:111:position:1:item:0',
                  source_order_id='111', asof='2026-08-05', filled_at='2026-08-05T14:00:00Z',
                  side='buy', open_close='open', fill_price='100', commission='1', fees='0.5')
    key = 'instrument.v1|equity|US|USD|TEST'
    cost, net = '200', '-201.5'
    if option:
        fields = dict(asset_class='option', option_symbol='TEST  260918P00100000',
                      underlying_symbol='TEST', option_type='PUT', expiry='2026-09-18',
                      strike='100', multiplier='100')
        close.update(fields, side='buy', fill_price='8')
        opener.update(fields, side='sell', fill_price='10')
        key = 'instrument.v1|option|US|USD|TEST|2026-09-18|PUT|100|100'
        cost, net = '-2000', '1998.5'
    parent = assembly_with(parent, fills=(close,))
    observations = (ArchiveTradeObservation('123', 'a' * 64, 'b' * 64, (opener,)),
                    ArchiveTradeObservation('123', 'c' * 64, 'd' * 64, (opener,)))
    cash = {opener['source_fill_id']: tuple({'raw_sha256': raw * 64, 'canonical_record_sha256': record * 64,
             'net_amount': net, 'security_cost': cost} for raw, record in (('a', 'b'), ('c', 'd')))}
    kwargs = dict(assembly=parent, observations=observations,
        selected_source_fill_ids=(opener['source_fill_id'],), reviewed_instrument_keys=(key,),
        cash_versions=cash, base_realized_fingerprint='e' * 64,
        base_revision_uids=('synthetic-revision',), approval_id='SYNTHETIC-OWNER-APPROVAL', observed_at=OBSERVED)
    return kwargs, close


def test_roundtrip_preserves_recovered_provenance_and_order_independent_identity():
    kwargs, _ = setup_case()
    supplement = build_recovered_opening_supplement(**kwargs)
    assert supplement['source_kind'] == 'recovered_retained_json'
    assert supplement['original_acquisition_manifest'] is supplement['original_capture_instant'] is None
    reverse = dict(kwargs, observations=tuple(reversed(kwargs['observations'])))
    assert build_recovered_opening_supplement(**reverse) == supplement
    body = recovered_opening_supplement_bytes(supplement)
    assert load_recovered_opening_supplement_bytes(body, assembly=kwargs['assembly'],
              expected_fingerprint=supplement['supplement_fingerprint']) == supplement
    changed = json.loads(body); changed['source_kind'] = 'new_acquisition'
    with pytest.raises(RecoveredOpeningError):
        load_recovered_opening_supplement_bytes(json.dumps(changed).encode(), assembly=kwargs['assembly'],
            expected_fingerprint=supplement['supplement_fingerprint'])


@pytest.mark.parametrize('change', ['cash', 'missing_version', 'id_drift', 'wrong_scope', 'not_opening'])
def test_unsupported_source_or_cash_fails_closed(change):
    kwargs, _ = setup_case()
    uid = kwargs['selected_source_fill_ids'][0]
    if change == 'cash':
        kwargs['cash_versions'][uid] = ({**kwargs['cash_versions'][uid][0], 'net_amount': '-200'}, *kwargs['cash_versions'][uid][1:])
    elif change == 'missing_version':
        kwargs['cash_versions'][uid] = kwargs['cash_versions'][uid][:1]
    elif change == 'id_drift':
        source = kwargs['observations'][1]
        kwargs['observations'] = (kwargs['observations'][0], replace(source, rows=({**source.rows[0], 'source_fill_id': uid[:-1] + '1'},)))
    elif change == 'wrong_scope':
        kwargs['reviewed_instrument_keys'] = ('instrument.v1|equity|US|USD|OTHER',)
    else:
        kwargs['observations'] = tuple(replace(source, rows=({**source.rows[0], 'open_close': 'close'},)) for source in kwargs['observations'])
    with pytest.raises(RecoveredOpeningError):
        build_recovered_opening_supplement(**kwargs)


def preview_case(tmp_path, option=False, reason='opening_history_missing', quantity=0):
    kwargs, close = setup_case(option)
    if quantity:
        parent = kwargs['assembly']
        positions = list(next(f.records for f in parent.families if f.family == 'positions'))
        positions.append(dict(positions[0], instrument_key=kwargs['reviewed_instrument_keys'][0],
            identity=dict(asset_class='equity', market_scope='US', currency='USD', symbol='TEST'), quantity=str(quantity)))
        parent = assembly_with(parent, positions=positions)
        parent = replace(parent, reconciliation=replace(parent.reconciliation,
            position_count=2, positions_without_quotes=1, all_positions_have_quotes=False))
        fingerprint = calculate_schwab_evidence_assembly_fingerprint(parent)
        kwargs['assembly'] = replace(parent, result_fingerprint=fingerprint, assembly_uid='schwab-evidence-assembly:' + fingerprint)
    supplement = build_recovered_opening_supplement(**kwargs)
    parent = kwargs['assembly']
    path = tmp_path / 'copy.duckdb'
    with duckdb.connect(str(path)) as con:
        reporting_fixture.Phase1ReportingCalculationTests._create_schema(con)
        values = list(reporting_fixture.Phase1ReportingCalculationTests._fill('close', episode_uid='gap', side=close['side'].upper(),
            open_close='close', price=close['fill_price'], filled_at=close['filled_at']))
        values[2:7] = [parent.source_account_id, close['source_fill_id'], close['source_order_id'], None, date(2026, 9, 4)]
        values[8:16] = [close['asset_class'], 'TEST', close['side'].upper(), Decimal(2), Decimal(close['fill_price']), Decimal('0.5'), Decimal(0), 'USD']
        if option:
            values[18:24] = [close['option_symbol'], 'TEST', 'PUT', date(2026, 9, 18), Decimal(100), Decimal(100)]
        con.execute('INSERT INTO normalized_fills VALUES (' + ','.join('?' for _ in values) + ')', values)
        con.execute("INSERT INTO phase1_journal_current_revision_ids VALUES ('synthetic-revision')")
        con.execute('INSERT INTO phase1_journal_history_revision_episodes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
            ['synthetic-revision', 'gap', 'schwab', parent.source_account_id, 'scope', 'TEST', 'review_required',
             'review_required', 'review_required', reason, 'history_extension_required', 'not_applicable'])
        con.execute("INSERT INTO phase1_journal_history_revision_episode_fills VALUES ('synthetic-revision', 'gap', 1, 'close')")
    base = SimpleNamespace(result_fingerprint='e' * 64, calculation_version='synthetic-base-calculation-v1',
        authorities=(SimpleNamespace(revision_uid='synthetic-revision', source_account_id=parent.source_account_id,
                                     snapshot_cutoff_utc=parent.snapshot_cutoff_utc),),
        items=(), omissions=(RealizedScopeOmission('omission', 'schwab', parent.source_account_id, 'gap',
            date(2026, 9, 4), 'TEST', reason, ('close',)),),
        coverage_start_date=date(2026, 8, 6), coverage_end_date=date(2026, 9, 5))
    return path, parent, supplement, base


@pytest.mark.parametrize('option,expected', [(False, '38.0'), (True, '398.0')])
def test_readonly_equity_and_short_option_cash_fees_and_unchanged_coverage(tmp_path, option, expected):
    path, parent, supplement, base = preview_case(tmp_path, option)
    before = path.read_bytes()
    with patch(MODULE + 'load_schwab_snapshot_evidence', return_value=parent), patch(MODULE + 'calculate_bounded_realized_result', return_value=base):
        result = calculate_recovered_opening_preview(path, assembly=parent, supplement=supplement,
                    expected_fingerprint=supplement['supplement_fingerprint'])
        replay = calculate_recovered_opening_preview(path, assembly=parent, supplement=supplement,
                    expected_fingerprint=supplement['supplement_fingerprint'])
    assert result == replay and path.read_bytes() == before
    assert Decimal(result['items'][0]['realized_pnl']) == Decimal(expected)
    assert result['omissions'] == () and not result['coverage_expanded']
    assert not result['financial_acceptance'] and not result['report_persistence_authority']


@pytest.mark.parametrize('reason,quantity', [('lifecycle_review_required', 0), ('opening_history_missing', 1)])
def test_other_review_reasons_or_quantity_mismatch_are_not_promoted(tmp_path, reason, quantity):
    path, parent, supplement, base = preview_case(tmp_path, reason=reason, quantity=quantity)
    with patch(MODULE + 'load_schwab_snapshot_evidence', return_value=parent), patch(MODULE + 'calculate_bounded_realized_result', return_value=base):
        with pytest.raises(RecoveredOpeningError):
            calculate_recovered_opening_preview(path, assembly=parent, supplement=supplement,
                expected_fingerprint=supplement['supplement_fingerprint'])
