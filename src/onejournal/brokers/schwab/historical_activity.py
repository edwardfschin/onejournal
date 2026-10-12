"""Offline Schwab evidence adapters. No credentials, network, native fills or P&L."""
from hashlib import sha256
import json
from decimal import Decimal

from onejournal.journal.historical_activity import (
    HistoricalActivityError, canonical, economic_payload, observation,
)
from onejournal.brokers.schwab.web_history_review import (
    parse_web_history, review_assignment_links, WebHistoryReviewError, _decimal,
)
from onejournal.brokers.schwab.transactions_json import (
    load_transactions_json_bytes, normalized_transaction_evidence_from_transactions,
    schwab_transaction_currency_consensus,
)


def _verified(body, doc, kind):
    if doc['source_broker'] != 'schwab' or doc['source_kind'] != kind or sha256(body).hexdigest() != doc['raw_sha256']:
        raise HistoricalActivityError('historical adapter source checksum, kind or broker differs')


def website_observations(body, doc):
    _verified(body, doc, 'website_export')
    try:
        rows = parse_web_history(json.loads(body, parse_float=Decimal))
    except (ValueError, TypeError, KeyError) as exc:
        raise HistoricalActivityError('website historical activity cannot be decoded') from exc
    records = []
    for row in rows:
        payload = {'source_row': row.source_row, 'action': row.action, 'source_record': row.raw,
                   'instrument_identity': canonical(row.identity) if row.raw['Symbol'] else None,
                   'instrument_classification_is_canonical': False,
                   'quantity': str(row.quantity) if row.quantity is not None else None,
                   'price': str(row.price) if row.price is not None else None,
                   'combined_cost': str(row.fees) if row.fees is not None else None,
                   'net_amount': str(row.amount) if row.amount is not None else None,
                   'currency': None, 'commission': None, 'fee_split': None}
        records.append(observation(doc, locator=f'row:{row.source_row}', payload=payload,
            dates={'posting_date': row.posting_date.isoformat(), 'asof_date': row.asof_date.isoformat() if row.asof_date else None}))
    return records


def api_record_observations(records, doc, *, original_records=None):
    """Accept verified normalized accounting records, not normalized executions."""
    if doc['source_broker'] != 'schwab' or doc['source_kind'] not in {'api_transactions', 'normalized_api_assembly'}:
        raise HistoricalActivityError('API historical source kind differs')
    result, seen = [], set()
    for ordinal, record in enumerate(records, 1):
        if (record['source_broker'], record['source_account_id']) != (doc['source_broker'], doc['source_account_id']):
            raise HistoricalActivityError('API historical account differs')
        activity = record['source_transaction_id']
        if activity in seen and doc['source_kind'] != 'normalized_api_assembly':
            raise HistoricalActivityError('API historical activity is repeated within one document')
        seen.add(activity)
        payload = canonical(record)
        # References under the released adapter's formula, not newly admitted
        # fills or proof that a lifecycle/unsupported activity became a fill.
        payload['legacy_fill_key_references'] = [
            f"schwab_txn:{activity}:order:{record['source_order_id']}:position:{record['source_position_id']}:item:{i}"
            for i, item in enumerate(record['items']) if record['transaction_type'] == 'TRADE'
            and record['transaction_status'] == 'VALID' and item['provider_asset_type'] in {'OPTION', 'EQUITY', 'STOCK'}]
        if original_records is not None:
            original = original_records[activity]
            # Original account identity remains in immutable raw evidence, not
            # duplicated in this broker-independent private ledger projection.
            payload['source_record'] = canonical({k: v for k, v in original.items() if k != 'accountNumber'})
            payload['contract_terms'] = [canonical(item['instrument']) for item in original['transferItems']]
        else:
            payload.setdefault('contract_terms', [None] * len(record['items']))
        payload['acquisition_metadata_not_invented'] = True
        locator = (f'transaction-row:{ordinal}:activity:{activity}' if doc['source_kind'] == 'normalized_api_assembly'
                   else 'activity:' + activity)
        result.append(observation(doc, locator=locator, payload=payload,
            occurred_at_utc=record['transaction_at_utc'], provider_activity_id=activity, economics=economic_payload(payload)))
    return result


def api_observations(body, doc, *, provider_account_number):
    _verified(body, doc, 'api_transactions')
    try:
        raw = load_transactions_json_bytes(body)
        records = normalized_transaction_evidence_from_transactions(raw,
            provider_account_number=provider_account_number, source_account_id=doc['source_account_id'],
            currency_consensus=schwab_transaction_currency_consensus(raw))
        return api_record_observations(records, doc, original_records={str(r['activityId']): r for r in raw})
    except (ValueError, TypeError, KeyError) as exc:
        raise HistoricalActivityError('API historical source account or accounting fields differ') from exc


def statement_observation(record, doc):
    """Load one checksum-bound reviewed table observation; never parse a PDF here."""
    if doc['source_kind'] != 'statement' or record['sha256'] != doc['raw_sha256']:
        raise HistoricalActivityError('reviewed statement source differs')
    locator = f"page:{record['page']}:row:{record.get('row_y', record.get('line'))}"
    if record.get('row_y', record.get('line')) is None or type(record['page']) is not int or record['page'] < 1:
        raise HistoricalActivityError('statement observation location is missing')
    if 'date_kind' in record:
        if record['date_kind'] == 'explicit_settlement_process_date':
            dates = {'settlement_date': record['date']}
        elif record['date_kind'] == 'explicit_trade_date':
            dates = {'trade_date': record['date'], 'settlement_date': record['source_dates'].get('settlement_date')}
        else:
            raise HistoricalActivityError('statement date semantics are not explicitly reviewed')
    else:
        dates = {'trade_date': record['trade_date'], 'settlement_date': record['settlement_date']}
    for key in ('quantity', 'price', 'amount'):
        _decimal(record[key])
    cost = record.get('explicit_cost_total', record.get('fees'))
    if _decimal(record['quantity']) <= 0 or _decimal(record['price']) < 0 or cost is not None and _decimal(cost) < 0:
        raise HistoricalActivityError('statement economics differ')
    payload = {'action': record['action'], 'instrument_identity': canonical(record['identity']),
               'quantity': str(_decimal(record['quantity'])), 'price': str(_decimal(record['price'])),
               'net_amount': str(_decimal(record['amount'])), 'combined_cost': str(_decimal(cost)) if cost is not None else None,
               'commission': None, 'fee_split': None, 'currency': None, 'reviewed_source_record': canonical(record)}
    return observation(doc, locator=locator, payload=payload, dates=dates)


def assignment_preview(bundle):
    """Reuse the narrow date-order-invariant source review, not an accepted P&L engine."""
    from onejournal.journal.historical_activity import validate_bundle
    bundle = validate_bundle(bundle)
    docs = {d['document_uid']: d for d in bundle['documents']}
    groups = {}
    for r in bundle['observations']:
        if docs[r['document_uid']]['source_kind'] == 'website_export':
            groups.setdefault(r['document_uid'], []).append(r)
    previews = []
    for uid, records in sorted(groups.items()):
        records.sort(key=lambda r: r['payload']['source_row'])
        if [r['payload']['source_row'] for r in records] != list(range(1, len(records) + 1)):
            raise HistoricalActivityError('assignment review requires the complete website document')
        rows = parse_web_history({'BrokerageTransactions': [r['payload']['source_record'] for r in records]})
        previews.append({'document_uid': uid, 'links': canonical(review_assignment_links(rows)),
                         'authoritative_pnl': False, 'financial_acceptance': False})
    return previews


def validate_source_observations(bundle):
    """Re-derive prepared observations from pinned originals before copy writes."""
    from pathlib import Path
    from onejournal.journal.historical_activity import encode, validate_bundle
    from onejournal.brokers.schwab.account_binding import load_schwab_account_private_binding_bytes
    bundle = validate_bundle(bundle)
    for doc in bundle['documents']:
        if doc['source_broker'] != 'schwab':
            raise HistoricalActivityError('historical source has no approved broker decoder')
        source, proof = Path(doc['source_path']), Path(doc['scope_evidence_path'])
        if not source.is_absolute() or not proof.is_absolute() or source.is_symlink() or proof.is_symlink():
            raise HistoricalActivityError('historical evidence paths must be explicit regular files')
        body, proof_bytes = source.read_bytes(), proof.read_bytes()
        if sha256(body).hexdigest() != doc['raw_sha256'] or sha256(proof_bytes).hexdigest() != doc['scope_evidence_sha256']:
            raise HistoricalActivityError('historical source or review proof checksum differs')
        members = [r for r in bundle['observations'] if r['document_uid'] == doc['document_uid']]
        kind = doc['source_kind']
        if kind == 'website_export':
            receipt = json.loads(proof_bytes)
            if doc['raw_sha256'] not in {r['sha256'] for r in receipt['raw_files']}:
                raise HistoricalActivityError('website document is outside its captured account scope')
            expected = website_observations(body, doc)
        elif kind in {'api_transactions', 'normalized_api_assembly'}:
            binding = load_schwab_account_private_binding_bytes(proof_bytes)
            if binding.source_account_id != doc['source_account_id']:
                raise HistoricalActivityError('API account binding differs')
            if kind == 'api_transactions':
                expected = api_observations(body, doc, provider_account_number=binding.provider_account_number)
            else:
                assembly = json.loads(body, parse_float=Decimal)
                records = next(f['records'] for f in assembly['families'] if f['family'] == 'transactions')
                expected = api_record_observations(records, doc)
        elif kind == 'statement':
            review = json.loads(proof_bytes, parse_float=Decimal)
            rows = review.get('observations', review.get('records'))
            if isinstance(rows, dict):
                rows = list(rows.values())
            if not isinstance(rows, list):
                raise HistoricalActivityError('statement review proof has no complete observation set')
            reviewed = {encode(r) for r in rows}
            expected = []
            for member in members:
                record = member['payload']['reviewed_source_record']
                if encode(record) not in reviewed:
                    raise HistoricalActivityError('statement observation is outside the exact reviewed evidence')
                expected.append(statement_observation(record, doc))
        else:
            raise HistoricalActivityError('historical source has no approved offline decoder')
        if sorted(encode(r) for r in members) != sorted(encode(r) for r in expected):
            raise HistoricalActivityError('prepared historical records differ from their actual sources')
