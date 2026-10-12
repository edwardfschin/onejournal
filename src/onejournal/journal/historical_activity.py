"""Immutable historical evidence, never canonical executions or financial authority."""
from collections import defaultdict
from datetime import date, datetime, UTC
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re

import duckdb

CONTRACT = 'onejournal.historical-activity-evidence.v1'
TABLES = ('historical_activity_import_runs', 'historical_activity_documents',
          'historical_activity_observations', 'historical_activity_run_observations',
          'historical_activity_bundle_reviews')
DATE_FIELDS = ('posting_date', 'asof_date', 'trade_date', 'settlement_date')
ECONOMIC_FIELDS = ('transaction_at_utc', 'transaction_type', 'transaction_status', 'currency', 'net_amount')
ITEM_FIELDS = ('provider_asset_type', 'provider_symbol', 'amount', 'price', 'cost', 'position_effect', 'fee_type')


class HistoricalActivityError(ValueError):
    """Value-free boundary failure; do not expose source records or paths."""


def canonical(value):
    if isinstance(value, float):
        raise HistoricalActivityError('binary floats are not historical evidence')
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise HistoricalActivityError('non-finite historical evidence')
        return str(value)
    if isinstance(value, dict):
        if any(not isinstance(k, str) for k in value):
            raise HistoricalActivityError('historical field names must be strings')
        return {k: canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [canonical(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise HistoricalActivityError('unsupported historical evidence type')


def encode(value):
    return json.dumps(canonical(value), sort_keys=True, separators=(',', ':'), allow_nan=False)


def fingerprint(value):
    return sha256(encode(value).encode()).hexdigest()


def _text(value):
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise HistoricalActivityError('required historical text is missing')
    return value


def _hash(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-f]{64}', value):
        raise HistoricalActivityError('exact source checksum is required')
    return value


def _day(value):
    if value is None:
        return None
    try:
        if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError as exc:
        raise HistoricalActivityError('historical date must be an ISO calendar date') from exc
    return value


def utc(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise ValueError()
    except (ValueError, AttributeError) as exc:
        raise HistoricalActivityError('explicit aware source timestamp is required') from exc
    return stamp.astimezone(UTC).isoformat()


def economic_payload(payload):
    """Keep all item multiplicity and financial fields, excluding reference metadata."""
    result = {k: payload[k] for k in ECONOMIC_FIELDS}
    if any(not isinstance(v, str) for v in result.values()):
        raise HistoricalActivityError('provider economic fields must be explicit strings')
    utc(result['transaction_at_utc'])
    if result['currency'] and not re.fullmatch(r'[A-Z]{3}', result['currency']):
        raise HistoricalActivityError('provider currency evidence is invalid')
    items = payload['items']
    if not isinstance(items, list):
        raise HistoricalActivityError('complete provider item array is required')
    terms = payload.get('contract_terms', [None] * len(items))
    if not isinstance(terms, list) or len(terms) != len(items):
        raise HistoricalActivityError('provider contract evidence does not match its items')
    result['items'] = []
    for item, contract in zip(items, terms):
        if set(item) != set(ITEM_FIELDS) | {'item_uid'} or any(not isinstance(v, str) for v in item.values()):
            raise HistoricalActivityError('provider item fields differ')
        for key in ('amount', 'price', 'cost'):
            _number(item[key])
        if contract is not None and not isinstance(contract, dict):
            raise HistoricalActivityError('provider contract evidence must retain an object or unknown')
        result['items'].append({**{k: item[k] for k in ITEM_FIELDS}, 'instrument_contract': canonical(contract)})
    _number(result['net_amount'])
    result['items'].sort(key=encode)
    return result


def _number(value):
    if not isinstance(value, str):
        raise HistoricalActivityError('financial evidence must retain exact strings')
    if value == '':
        return
    try:
        if not Decimal(value).is_finite():
            raise InvalidOperation()
    except InvalidOperation as exc:
        raise HistoricalActivityError('financial evidence is non-finite or malformed') from exc


def document(*, source_broker, source_account_id, source_kind, raw_sha256, source_path, scope_evidence_sha256, scope_evidence_path):
    identity = {'source_broker': _text(source_broker), 'source_account_id': _text(source_account_id),
                'source_kind': _text(source_kind), 'raw_sha256': _hash(raw_sha256)}
    return {**identity, 'document_uid': 'historical-document:' + fingerprint(identity),
            'source_path': _text(source_path), 'scope_evidence_sha256': _hash(scope_evidence_sha256),
            'scope_evidence_path': _text(scope_evidence_path)}


def observation(doc, *, locator, payload, dates=None, occurred_at_utc=None,
                provider_activity_id=None, economics=None):
    dates = dates or {}
    if set(dates) - set(DATE_FIELDS):
        raise HistoricalActivityError('unsupported date meaning')
    if provider_activity_id is not None:
        _text(provider_activity_id)
    if (provider_activity_id is None) != (economics is None):
        raise HistoricalActivityError('provider identity and complete economics must be paired')
    if doc['source_kind'] in {'website_export', 'statement'} and (occurred_at_utc is not None or provider_activity_id is not None):
        raise HistoricalActivityError('date-only source cannot claim provider execution identity or an instant')
    stamp = utc(occurred_at_utc) if occurred_at_utc is not None else None
    days = {k: _day(dates.get(k)) for k in DATE_FIELDS}
    record = {'document_uid': _text(doc['document_uid']), 'source_locator': _text(locator),
              **days, 'occurred_at_utc': stamp, 'timestamp_kind': 'provider_transaction' if stamp else 'none',
              'date_precision': 'instant' if stamp else 'day' if any(days.values()) else 'unknown',
              'provider_activity_id': provider_activity_id, 'payload': canonical(payload), 'economics': canonical(economics)}
    return {**record, 'observation_uid': 'historical-observation:' + fingerprint([record['document_uid'], record['source_locator']]),
            'record_fingerprint': fingerprint(record)}


def make_bundle(*, run_uid, source_broker, source_account_id, asof, observed_at_utc, documents, observations):
    bundle = {'contract_version': CONTRACT, 'run_uid': _text(run_uid), 'source_broker': _text(source_broker),
              'source_account_id': _text(source_account_id), 'asof': _day(asof), 'observed_at_utc': utc(observed_at_utc),
              'documents': sorted(documents, key=lambda d: d['document_uid']),
              'observations': sorted(observations, key=lambda r: r['observation_uid'])}
    bundle['bundle_fingerprint'] = fingerprint(bundle)
    return validate_bundle(bundle)


def validate_bundle(bundle):
    try:
        return _validate_bundle(bundle)
    except (KeyError, TypeError, AttributeError) as exc:
        raise HistoricalActivityError('historical bundle fields differ') from exc


def _validate_bundle(bundle):
    bundle = canonical(bundle)
    if set(bundle) != {'contract_version', 'run_uid', 'source_broker', 'source_account_id', 'asof', 'observed_at_utc',
                       'documents', 'observations', 'bundle_fingerprint'} or bundle['contract_version'] != CONTRACT:
        raise HistoricalActivityError('historical bundle contract differs')
    for k in ('run_uid', 'source_broker', 'source_account_id'):
        _text(bundle[k])
    if _day(bundle['asof']) is None or utc(bundle['observed_at_utc']) != bundle['observed_at_utc']:
        raise HistoricalActivityError('historical import observation scope differs')
    docs, seen = {}, set()
    if not isinstance(bundle['documents'], list) or not isinstance(bundle['observations'], list) or not bundle['observations']:
        raise HistoricalActivityError('historical bundle requires source observations')
    for d in bundle['documents']:
        expected = document(**{k: d[k] for k in ('source_broker', 'source_account_id', 'source_kind', 'raw_sha256', 'source_path', 'scope_evidence_sha256', 'scope_evidence_path')})
        if d != expected or (d['source_broker'], d['source_account_id']) != (bundle['source_broker'], bundle['source_account_id']) or d['document_uid'] in docs:
            raise HistoricalActivityError('historical document identity, account or multiplicity differs')
        docs[d['document_uid']] = d
    for r in bundle['observations']:
        if r['document_uid'] not in docs or r['observation_uid'] in seen:
            raise HistoricalActivityError('historical observation source or multiplicity differs')
        seen.add(r['observation_uid'])
        expected = observation(docs[r['document_uid']], locator=r['source_locator'], payload=r['payload'],
            dates={k: r[k] for k in DATE_FIELDS}, occurred_at_utc=r['occurred_at_utc'],
            provider_activity_id=r['provider_activity_id'], economics=r['economics'])
        if r != expected:
            raise HistoricalActivityError('historical observation content or temporal meaning differs')
        if r['provider_activity_id'] is not None:
            if (r['economics'] != economic_payload(r['payload']) or r['occurred_at_utc'] != utc(r['payload']['transaction_at_utc'])
                    or r['payload']['source_transaction_id'] != r['provider_activity_id']
                    or r['payload']['source_account_id'] != bundle['source_account_id']
                    or r['payload']['source_broker'] != bundle['source_broker']):
                raise HistoricalActivityError('provider activity source, account or complete economics differs')
    if bundle['documents'] != sorted(bundle['documents'], key=lambda d: d['document_uid']) or bundle['observations'] != sorted(bundle['observations'], key=lambda r: r['observation_uid']):
        raise HistoricalActivityError('historical bundle ordering is not canonical')
    if _hash(bundle['bundle_fingerprint']) != fingerprint({k: v for k, v in bundle.items() if k != 'bundle_fingerprint'}):
        raise HistoricalActivityError('historical bundle fingerprint differs')
    return bundle


def load_bundle_bytes(body, *, expected_fingerprint):
    try:
        bundle = json.loads(body, parse_float=Decimal,
                            parse_constant=lambda _: (_ for _ in ()).throw(HistoricalActivityError('non-finite JSON')))
        bundle = validate_bundle(bundle)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HistoricalActivityError('historical bundle cannot be decoded') from exc
    if bundle['bundle_fingerprint'] != _hash(expected_fingerprint):
        raise HistoricalActivityError('historical bundle is not the exact selected input')
    return bundle


def review_provider_bundles(bundle):
    """Review the exact selected source set, not lifetime completeness or admission."""
    bundle = validate_bundle(bundle)
    groups = defaultdict(list)
    for r in bundle['observations']:
        if r['provider_activity_id'] is not None:
            groups[r['provider_activity_id']].append(r)
    reviews = []
    for activity, members in sorted(groups.items()):
        signatures = sorted({fingerprint(r['economics']) for r in members})
        ambiguous, unsupported = False, False
        for r in members:
            items = r['economics']['items']
            securities = [encode(i) for i in items if i['provider_asset_type'] != 'CURRENCY']
            ambiguous |= len(securities) != len(set(securities))
            unsupported |= any(i['provider_asset_type'] not in {'CURRENCY', 'OPTION', 'EQUITY', 'STOCK'} for i in items)
        status = ('economic_conflict' if len(signatures) != 1 else 'ambiguous_security_items' if ambiguous
                  else 'unsupported_assets' if unsupported else 'consistent_bundle')
        reviews.append({'provider_activity_id': activity, 'status': status, 'economic_signatures': signatures,
                        'observation_uids': sorted(r['observation_uid'] for r in members),
                        'legacy_fill_key_references': sorted({uid for r in members for uid in r['payload'].get('legacy_fill_key_references', [])}),
                        'source_contract_objects_retained': all(i['instrument_contract'] is not None for r in members for i in r['economics']['items'] if i['provider_asset_type'] != 'CURRENCY'),
                        'instrument_terms_financial_validation_required': True,
                        'complete_lifetime_history_proven': False, 'canonical_fill_identity_selected': False, 'financial_admission': False})
    return reviews


def _run_values(bundle):
    return (bundle['run_uid'], CONTRACT, bundle['source_broker'], bundle['source_account_id'], date.fromisoformat(bundle['asof']),
            bundle['observed_at_utc'], bundle['bundle_fingerprint'], encode(bundle), len(bundle['observations']))


def _document_values(d):
    return tuple(d[k] for k in ('document_uid', 'source_broker', 'source_account_id', 'source_kind', 'raw_sha256'))


def _observation_values(r):
    return (r['observation_uid'], r['document_uid'], r['source_locator'], r['record_fingerprint'], encode(r),
            *(date.fromisoformat(r[k]) if r[k] else None for k in DATE_FIELDS),
            r['occurred_at_utc'], r['timestamp_kind'], r['date_precision'], r['provider_activity_id'])


def _verify_stored(con, bundle, reviews):
    run = con.execute('SELECT * FROM historical_activity_import_runs WHERE run_uid=?', [bundle['run_uid']]).fetchone()
    rows = con.execute('SELECT o.* FROM historical_activity_run_observations x JOIN historical_activity_observations o USING(observation_uid) WHERE x.run_uid=?', [bundle['run_uid']]).fetchall()
    stored_reviews = con.execute('SELECT provider_activity_id,status,review_json FROM historical_activity_bundle_reviews WHERE run_uid=?', [bundle['run_uid']]).fetchall()
    docs = {r[0]: r for r in con.execute('SELECT * FROM historical_activity_documents').fetchall()}
    if (run != _run_values(bundle) or sorted(rows) != sorted(_observation_values(r) for r in bundle['observations'])
            or sorted(stored_reviews) != sorted((r['provider_activity_id'], r['status'], encode(r)) for r in reviews)
            or any(docs.get(d['document_uid']) != _document_values(d) for d in bundle['documents'])):
        raise HistoricalActivityError('historical ledger exact read-back differs')


def persist_bundle(db_path, bundle):
    """Append exact evidence to an existing migrated DB; no migration or activation."""
    bundle = validate_bundle(bundle)
    path = Path(db_path)
    if not path.is_file() or path.is_symlink():
        raise HistoricalActivityError('an existing historical ledger database is required')
    reviews = review_provider_bundles(bundle)
    with duckdb.connect(str(path)) as con:
        if not set(TABLES) <= {r[0] for r in con.execute('SHOW TABLES').fetchall()}:
            raise HistoricalActivityError('historical ledger migration is required')
        con.execute('BEGIN TRANSACTION')
        try:
            previous = con.execute('SELECT bundle_json FROM historical_activity_import_runs WHERE run_uid=?', [bundle['run_uid']]).fetchone()
            if previous:
                if previous[0] != encode(bundle):
                    raise HistoricalActivityError('historical import identity has conflicting content')
                _verify_stored(con, bundle, reviews)
                con.execute('COMMIT')
                return {'created': False, 'observation_count': len(bundle['observations']), 'bundle_fingerprint': bundle['bundle_fingerprint']}
            docs = {r[0]: r for r in con.execute('SELECT * FROM historical_activity_documents').fetchall()}
            old_rows = dict(con.execute('SELECT observation_uid,record_json FROM historical_activity_observations').fetchall())
            new_docs, new_rows = [], []
            for d in bundle['documents']:
                values = _document_values(d)
                if d['document_uid'] in docs and docs[d['document_uid']] != values:
                    raise HistoricalActivityError('historical document content conflicts')
                if d['document_uid'] not in docs:
                    new_docs.append(values)
            for r in bundle['observations']:
                if r['observation_uid'] in old_rows and old_rows[r['observation_uid']] != encode(r):
                    raise HistoricalActivityError('historical source observation has changed interpretation')
                if r['observation_uid'] not in old_rows:
                    new_rows.append(_observation_values(r))
            if new_docs:
                con.executemany('INSERT INTO historical_activity_documents VALUES (?,?,?,?,?)', new_docs)
            if new_rows:
                con.executemany('INSERT INTO historical_activity_observations VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', new_rows)
            con.execute('INSERT INTO historical_activity_import_runs VALUES (?,?,?,?,?,?,?,?,?)', _run_values(bundle))
            con.executemany('INSERT INTO historical_activity_run_observations VALUES (?,?)',
                            [(bundle['run_uid'], r['observation_uid']) for r in bundle['observations']])
            if reviews:
                con.executemany('INSERT INTO historical_activity_bundle_reviews VALUES (?,?,?,?)',
                    [(bundle['run_uid'], r['provider_activity_id'], r['status'], encode(r)) for r in reviews])
            _verify_stored(con, bundle, reviews)
            con.execute('COMMIT')
        except Exception:
            con.execute('ROLLBACK')
            raise
    return {'created': True, 'observation_count': len(bundle['observations']), 'bundle_fingerprint': bundle['bundle_fingerprint']}


def read_bundle(db_path, *, run_uid, expected_fingerprint):
    if not Path(db_path).is_file() or Path(db_path).is_symlink():
        raise HistoricalActivityError('historical ledger database is missing')
    with duckdb.connect(str(db_path), read_only=True) as con:
        row = con.execute('SELECT bundle_json FROM historical_activity_import_runs WHERE run_uid=?', [_text(run_uid)]).fetchone()
        if row is None:
            raise HistoricalActivityError('selected historical import does not exist')
        bundle = load_bundle_bytes(row[0], expected_fingerprint=expected_fingerprint)
        _verify_stored(con, bundle, review_provider_bundles(bundle))
        return bundle
