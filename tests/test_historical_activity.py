"""Focused synthetic ledger, source-replay and disposable-copy safety tests."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID

import duckdb
import pytest

from onejournal.journal.historical_activity import (
    HistoricalActivityError, document, observation, make_bundle, encode, fingerprint,
    load_bundle_bytes, persist_bundle, read_bundle, review_provider_bundles,
)
from onejournal.journal.historical_activity_rehearsal import rehearse, _preservation_value
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.brokers.schwab.historical_activity import (
    website_observations, api_observations, api_record_observations, statement_observation, assignment_preview,
)

ACCOUNT = 'account:test-one'
MIGRATIONS = Path(__file__).resolve().parents[1] / 'scripts/journal/migrations'


def web_row(action='Buy', day='06/01/2001', symbol='TEST', quantity='100', price='25', cost='0', amount='-2500'):
    return {'Date': day, 'Action': action, 'Symbol': symbol, 'Description': 'synthetic',
            'Quantity': quantity, 'Price': price, 'Fees & Comm': cost, 'Amount': amount}


def source_doc(body, *, kind='website_export', path='source.json', proof='scope.json'):
    return document(source_broker='schwab', source_account_id=ACCOUNT, source_kind=kind,
        raw_sha256=sha256(body).hexdigest(), source_path=path,
        scope_evidence_sha256='a'*64, scope_evidence_path=proof)


def bundle(docs, rows, run='synthetic-history-one'):
    return make_bundle(run_uid=run, source_broker='schwab', source_account_id=ACCOUNT,
        asof='2001-07-02', observed_at_utc='2001-07-02T12:00:00Z', documents=docs, observations=rows)


def web_source(rows=None):
    body = encode({'BrokerageTransactions': rows or [web_row()]}).encode()
    doc = source_doc(body)
    return body, doc, website_observations(body, doc)


def raw_transaction(position='position-one', *, price='2', terms='100', reverse=False, duplicate=False, asset='OPTION'):
    security = {'amount': '-1', 'price': price, 'cost': '200', 'positionEffect': 'OPENING',
        'instrument': {'assetType': asset, 'symbol': 'TEST  010720P00025000', 'underlyingSymbol': 'TEST',
                       'putCall': 'PUT', 'expirationDate': '2001-07-20', 'strikePrice': '25',
                       'optionPremiumMultiplier': terms, 'instrumentId': 'synthetic-instrument-one'}}
    fee = {'amount': '0.75', 'cost': '0.75', 'feeType': 'COMMISSION',
           'instrument': {'assetType': 'CURRENCY', 'symbol': 'CURRENCY_USD'}}
    items = [security, fee]
    if duplicate:
        items.insert(1, deepcopy(security))
    if reverse:
        items.reverse()
    return {'activityId': '1000001', 'accountNumber': 'SYNTHETIC-ACCOUNT', 'type': 'TRADE', 'status': 'VALID',
            'tradeDate': '2001-06-01T16:00:00Z', 'orderId': 'order-one', 'positionId': position,
            'netAmount': '199.25', 'transferItems': items}


def api_source(raw):
    body = encode([raw]).encode()
    doc = source_doc(body, kind='api_transactions')
    return doc, api_observations(body, doc, provider_account_number='SYNTHETIC-ACCOUNT')


def fresh_db(tmp_path, version='0029'):
    db = tmp_path / 'journal.duckdb'
    apply_schema_migrations(db, target_version=version, migrations_dir=MIGRATIONS)
    db.chmod(0o600)
    return db


def test_dates_costs_and_row_multiplicity_are_not_invented():
    _, doc, rows = web_source([web_row(cost=''), web_row(cost='')])
    data = bundle([doc], rows)
    assert len(rows) == 2 and rows[0]['observation_uid'] != rows[1]['observation_uid']
    assert all(r['occurred_at_utc'] is None and r['provider_activity_id'] is None and r['date_precision']=='day' for r in rows)
    assert all(r['payload']['combined_cost'] is None and r['payload']['currency'] is None for r in rows)
    assert data == bundle([doc], list(reversed(rows)))


def test_day_source_cannot_become_synthetic_instant():
    _, doc, _ = web_source()
    with pytest.raises(HistoricalActivityError):
        observation(doc, locator='row:1', payload={}, dates={'posting_date':'2001-06-01'}, occurred_at_utc='2001-06-01T00:00:00Z')


def test_float_nonfinite_and_wrong_account_fail():
    _, doc, rows = web_source()
    with pytest.raises(HistoricalActivityError):
        observation(doc, locator='row:1', payload={'amount': 0.1})
    wrong = {**doc, 'source_account_id':'account:other'}
    with pytest.raises(HistoricalActivityError):
        bundle([wrong], rows)
    with pytest.raises(HistoricalActivityError):
        api_source(raw_transaction(price='NaN'))
    doc, _ = api_source(raw_transaction())
    with pytest.raises(HistoricalActivityError):
        api_observations(encode([raw_transaction()]).encode(), doc, provider_account_number='WRONG-ACCOUNT')


def test_changed_item_positions_keep_one_consistent_activity_bundle():
    d1, r1 = api_source(raw_transaction())
    d2, r2 = api_source(raw_transaction('position-two', reverse=True))
    review = review_provider_bundles(bundle([d1,d2], r1+r2))[0]
    assert review['status']=='consistent_bundle' and len(review['observation_uids'])==2
    assert len(review['legacy_fill_key_references'])==2
    assert not review['canonical_fill_identity_selected'] and not review['financial_admission']


@pytest.mark.parametrize('changed', [raw_transaction(price='3'), raw_transaction(terms='50')])
def test_changed_economics_or_deliverables_are_conflicts(changed):
    d1, r1 = api_source(raw_transaction())
    d2, r2 = api_source(changed)
    assert review_provider_bundles(bundle([d1,d2], r1+r2))[0]['status']=='economic_conflict'


def test_duplicate_security_items_and_unknown_assets_are_withheld():
    d, r = api_source(raw_transaction(duplicate=True))
    assert review_provider_bundles(bundle([d],r))[0]['status']=='ambiguous_security_items'
    d, r = api_source(raw_transaction(asset='COLLECTIVE_INVESTMENT'))
    assert review_provider_bundles(bundle([d],r))[0]['status']=='unsupported_assets'


def test_distinct_native_activity_ids_are_never_economics_deduplicated():
    d1, r1 = api_source(raw_transaction())
    other = raw_transaction(); other['activityId']='1000002'
    d2, r2 = api_source(other)
    assert len(review_provider_bundles(bundle([d1,d2],r1+r2)))==2


def test_assembly_preserves_repeated_capture_versions():
    _, r = api_source(raw_transaction())
    records = [r[0]['payload'], deepcopy(r[0]['payload'])]
    records[1]['source_position_id'] = 'new-position'
    doc = source_doc(b'synthetic assembly',kind='normalized_api_assembly')
    rows = api_record_observations(records,doc)
    assert len(rows)==2 and rows[0]['observation_uid']!=rows[1]['observation_uid']
    assert review_provider_bundles(bundle([doc],rows))[0]['status']=='consistent_bundle'
    assert rows[0]['payload']['contract_terms']==records[0]['contract_terms']


def test_append_replay_and_separate_delivery_preserve_source_rows(tmp_path):
    db = fresh_db(tmp_path)
    _, doc, rows = web_source()
    data = bundle([doc],rows)
    assert persist_bundle(db,data)['created']
    assert not persist_bundle(db,data)['created']
    assert read_bundle(db,run_uid=data['run_uid'],expected_fingerprint=data['bundle_fingerprint'])==data
    second = bundle([doc],rows,run='synthetic-history-two')
    assert persist_bundle(db,second)['created']
    with duckdb.connect(str(db),read_only=True) as con:
        assert con.execute('SELECT count(*) FROM historical_activity_observations').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM historical_activity_import_runs').fetchone()[0]==2
        assert con.execute('SELECT count(*) FROM normalized_fills').fetchone()[0]==0


def test_conflicting_interpretation_is_atomic(tmp_path):
    db = fresh_db(tmp_path)
    _, doc, rows = web_source()
    data = bundle([doc],rows);persist_bundle(db,data)
    changed = observation(doc,locator='row:1',payload={**rows[0]['payload'],'combined_cost':'1'},dates={'posting_date':'2001-06-01'})
    with pytest.raises(HistoricalActivityError):
        persist_bundle(db,bundle([doc],[changed],run='synthetic-conflict'))
    with duckdb.connect(str(db),read_only=True) as con:
        assert con.execute('SELECT count(*) FROM historical_activity_import_runs').fetchone()[0]==1
    assert read_bundle(db,run_uid=data['run_uid'],expected_fingerprint=data['bundle_fingerprint'])==data


def test_fingerprint_and_stored_typed_dates_are_checked(tmp_path):
    db = fresh_db(tmp_path);_,doc,rows=web_source();data=bundle([doc],rows)
    with pytest.raises(HistoricalActivityError):
        load_bundle_bytes(encode(data),expected_fingerprint='f'*64)
    persist_bundle(db,data)
    with duckdb.connect(str(db)) as con:
        con.execute("UPDATE historical_activity_observations SET posting_date=DATE '2001-06-02'")
    with pytest.raises(HistoricalActivityError):
        read_bundle(db,run_uid=data['run_uid'],expected_fingerprint=data['bundle_fingerprint'])


def assignment_rows():
    return [web_row('Sell to Open','06/01/2001','TEST 07/20/2001 25 P','1','2','0.75','199.25'),
            web_row('Assigned','06/20/2001 as of 06/19/2001','TEST 07/20/2001 25 P','1','','',''),
            web_row('Buy','06/20/2001 as of 06/19/2001','TEST','100','25','','-2500')]


def test_day_assignment_preview_and_same_day_ambiguity():
    _,d,r=web_source(assignment_rows());preview=assignment_preview(bundle([d],r))[0]
    assert preview['links'][0]['status']=='source_linked_candidate'
    assert not preview['financial_acceptance']
    added=assignment_rows()+[web_row('Sell to Open','06/20/2001','TEST 07/20/2001 25 P','1','2','0.75','199.25')]
    _,d,r=web_source(added)
    assert assignment_preview(bundle([d],r))[0]['links'][0]['status']=='withheld'


def test_statement_preserves_settlement_and_combined_unknown_cost():
    d=source_doc(b'synthetic PDF',kind='statement')
    r={'sha256':d['raw_sha256'],'page':1,'row_y':'123.0','date_kind':'explicit_settlement_process_date','date':'2001-06-04',
       'source_dates':{},'identity':['equity','TEST'],'action':'Buy','quantity':'100','price':'25','amount':'-2500','explicit_cost_total':None}
    out=statement_observation(r,d)
    assert out['settlement_date']=='2001-06-04' and out['trade_date'] is None and out['occurred_at_utc'] is None
    assert out['payload']['combined_cost'] is None and out['payload']['commission'] is None


def prepared_web_bundle(tmp_path, *, tamper=False):
    body, _, _ = web_source()
    raw=tmp_path/'source.json';raw.write_bytes(body);raw.chmod(0o600)
    receipt=tmp_path/'receipt.json'
    receipt.write_text(encode({'raw_files':[{'sha256':sha256(body).hexdigest()}]}));receipt.chmod(0o600)
    d=document(source_broker='schwab',source_account_id=ACCOUNT,source_kind='website_export',raw_sha256=sha256(body).hexdigest(),
        source_path=str(raw),scope_evidence_sha256=sha256(receipt.read_bytes()).hexdigest(),scope_evidence_path=str(receipt))
    rows=website_observations(body,d)
    if tamper:
        rows=[observation(d,locator='row:1',payload={**rows[0]['payload'],'price':'26'},dates={'posting_date':'2001-06-01'})]
    data=bundle([d],rows)
    path=tmp_path/'bundle.json';path.write_text(encode(data));path.chmod(0o600)
    return path,data


def test_guarded_copy_migration_import_replay_preserves_prior_notes(tmp_path):
    db=fresh_db(tmp_path,'0028')
    with duckdb.connect(str(db)) as con:
        con.execute("INSERT INTO manual_reviews VALUES ('synthetic-episode','ready','good','synthetic','preserve me',TIMESTAMP '2001-01-01')")
    pin=sha256(db.read_bytes()).hexdigest();path,data=prepared_web_bundle(tmp_path)
    out=tmp_path/'rehearsal'
    result=rehearse(source_db=db,source_db_sha256=pin,bundle_path=path,
        expected_bundle_fingerprint=data['bundle_fingerprint'],output_dir=out,migrations_dir=MIGRATIONS)
    assert result['exact_replay'] and result['all_predecessor_rows_and_schemas_preserved']
    assert sha256(db.read_bytes()).hexdigest()==pin
    with duckdb.connect(str(out/'candidate.duckdb'),read_only=True) as con:
        assert con.execute('SELECT notes FROM manual_reviews').fetchone()[0]=='preserve me'
        assert con.execute('SELECT count(*) FROM normalized_fills').fetchone()[0]==0
    with pytest.raises(HistoricalActivityError):
        rehearse(source_db=db,source_db_sha256=pin,bundle_path=path,
            expected_bundle_fingerprint=data['bundle_fingerprint'],output_dir=out,migrations_dir=MIGRATIONS)


def test_changed_prepared_source_fails_before_copy_creation(tmp_path):
    db=fresh_db(tmp_path,'0028');path,data=prepared_web_bundle(tmp_path,tamper=True)
    out=tmp_path/'rehearsal'
    with pytest.raises(HistoricalActivityError):
        rehearse(source_db=db,source_db_sha256=sha256(db.read_bytes()).hexdigest(),bundle_path=path,
            expected_bundle_fingerprint=data['bundle_fingerprint'],output_dir=out,migrations_dir=MIGRATIONS)
    assert not out.exists()


def test_cli_failure_is_value_free(tmp_path,capsys):
    from scripts.journal.rehearse_historical_activity_import import main
    private=str(tmp_path/'do-not-expose-this')
    assert main(['--source-db',private,'--source-db-sha256','bad','--bundle',private,
                 '--bundle-fingerprint','bad','--rehearsal-dir',private])==1
    assert private not in capsys.readouterr().err


def test_preservation_hash_supports_existing_audit_uuid_without_coercing_fields():
    first=UUID('00000000-0000-0000-0000-000000000001')
    second=UUID('00000000-0000-0000-0000-000000000002')
    assert encode(_preservation_value((first,)))==encode([['uuid',first.hex]])
    assert fingerprint(_preservation_value((first,)))!=fingerprint(_preservation_value((second,)))


def test_preservation_reads_timezone_aware_existing_database_values(tmp_path):
    from onejournal.journal.historical_activity_rehearsal import preservation_snapshot
    db=tmp_path/'timezone.duckdb'
    with duckdb.connect(str(db)) as con:
        con.execute('CREATE TABLE existing_audit(event_at TIMESTAMPTZ)')
        con.execute("INSERT INTO existing_audit VALUES (TIMESTAMPTZ '2001-01-01 00:00:00.123456+00')")
    before=preservation_snapshot(db)
    assert before==preservation_snapshot(db)
    with duckdb.connect(str(db)) as con:
        con.execute("UPDATE existing_audit SET event_at=event_at+INTERVAL 1 MICROSECOND")
    assert before!=preservation_snapshot(db)
