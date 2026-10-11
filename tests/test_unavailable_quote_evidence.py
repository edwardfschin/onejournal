from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import Path
import tempfile
import unittest

from onejournal.brokers.schwab.quotes_json import (
    SchwabQuoteRequest, SchwabQuoteAdapterError, load_quotes_json_bytes,
    normalized_quotes_with_unavailable_from_payload,
)
from onejournal.market_data.ingestion import (
    CAPTURE_CONTRACT_VERSION_V2, QuoteCaptureContractError, QuoteInstrumentRequest,
    UnavailableQuoteEvidence, build_quote_capture_fingerprint, validate_quote_capture,
)
from onejournal.market_data.capture_artifact import quote_capture_artifact_bytes, load_quote_capture_artifact_bytes
from onejournal.market_data.repository import persist_quote_capture_result, load_quote_capture_run
from onejournal.journal.migrations import apply_schema_migrations
import test_quote_capture_ingestion as ingestion_fixture
import test_quote_capture_preparation as preparation_fixture
from onejournal.provider_connectors.quote_capture_preparation import prepare_quote_capture_runner


class UnavailableQuoteTests(unittest.TestCase):
    def setUp(self):
        self.helper = ingestion_fixture.QuoteCaptureIngestionTests()
        self.helper.setUp()
        self.original = self.helper.capture()
        self.missing = UnavailableQuoteEvidence('stock|MISSING', 'MISSING', 'stock', 'USD', 'a'*64)
        self.capture = replace(self.original, contract_version=CAPTURE_CONTRACT_VERSION_V2,
            requests=(*self.original.requests, QuoteInstrumentRequest('stock|MISSING','MISSING','stock','USD')),
            unavailable=(self.missing,))

    def test_value_free_roundtrip_and_complete_accounting_preserves_v1(self):
        policy = self.helper.policy.freshness
        validate_quote_capture(self.capture, policy=policy)
        body = quote_capture_artifact_bytes(self.capture)
        self.assertEqual(load_quote_capture_artifact_bytes(body), self.capture)
        self.assertEqual(quote_capture_artifact_bytes(load_quote_capture_artifact_bytes(body)), body)
        self.assertEqual(set(asdict(self.missing)), {'instrument_key','provider_instrument_id','asset_class','currency','raw_sha256','reason_code'})
        legacy = quote_capture_artifact_bytes(self.original)
        self.assertNotIn(b'unavailable', legacy)
        self.assertEqual(load_quote_capture_artifact_bytes(legacy), self.original)
        for invalid in (replace(self.capture, unavailable=()), replace(self.capture, unavailable=(self.missing,self.missing)),
                        replace(self.capture, unavailable=(replace(self.missing,raw_sha256='b'*64),)),
                        replace(self.capture, contract_version=self.original.contract_version)):
            with self.assertRaises(QuoteCaptureContractError): validate_quote_capture(invalid, policy=policy)
        self.assertNotEqual(build_quote_capture_fingerprint(self.capture), build_quote_capture_fingerprint(self.original))

    def test_copy_persistence_replay_readback_and_tamper(self):
        import duckdb
        with tempfile.TemporaryDirectory() as directory:
            db=Path(directory)/'copy.duckdb'
            apply_schema_migrations(db, migrations_dir=ingestion_fixture.MIGRATIONS_DIR, target_version=12)
            first=persist_quote_capture_result(db,self.capture,policy=self.helper.policy.freshness)
            self.assertEqual(first.persisted_quote_count,1)
            self.assertTrue(persist_quote_capture_result(db,self.capture,policy=self.helper.policy.freshness).was_replay)
            kwargs=dict(quote_run_uid=self.capture.quote_run_uid,provider=self.capture.provider,
                        connection_uid=self.capture.connection_uid,asof=self.capture.asof,policy=self.helper.policy.freshness)
            self.assertEqual(load_quote_capture_run(db,**kwargs).unavailable,self.capture.unavailable)
            with duckdb.connect(str(db)) as con:
                self.assertEqual(con.execute('SELECT requested_instrument_count,received_quote_count,accepted_quote_count,rejected_quote_count FROM market_quote_ingestion_runs').fetchone(),(2,2,1,1))
                con.execute("UPDATE market_quote_ingestion_runs SET notes = '{}' ")
            with self.assertRaises(ValueError): load_quote_capture_run(db,**kwargs)
            with self.assertRaises(ValueError): persist_quote_capture_result(db,self.capture,policy=self.helper.policy.freshness)

    def test_adapter_never_substitutes_trade_time_and_requires_exact_approval(self):
        time=int(datetime(2026,10,9,20,tzinfo=UTC).timestamp()*1000)
        payload={symbol:{'symbol':symbol,'assetMainType':'EQUITY','realtime':True,
            'quote':{'quoteTime':time if symbol=='A' else 0,'tradeTime':time,'bidPrice':1,'askPrice':2,'lastPrice':1}}
            for symbol in ('A','B')}
        requests=tuple(SchwabQuoteRequest(s,'stock|'+s,'stock','USD') for s in ('A','B'))
        context=dict(connection_uid='synthetic-owner',asof=date(2026,10,9),received_at=datetime(2026,10,11,3,tzinfo=UTC),raw_path='data/raw/schwab/test.json',raw_sha256='a'*64)
        quotes,unavailable=normalized_quotes_with_unavailable_from_payload(payload,requests=requests,allowed_unavailable_symbols=frozenset({'B'}),**context)
        self.assertEqual([q.provider_instrument_id for q in quotes],['A'])
        self.assertEqual([u.provider_instrument_id for u in unavailable],['B'])
        with self.assertRaises(SchwabQuoteAdapterError): normalized_quotes_with_unavailable_from_payload(payload,requests=requests,allowed_unavailable_symbols=frozenset(),**context)

    def test_runner_allows_only_exact_named_zero_timestamp_instrument(self):
        helper=preparation_fixture.QuoteCapturePreparationTests(); helper.setUp()
        spec=replace(helper.spec,allowed_unavailable_symbol_sha256s=(sha256(b'B').hexdigest(),))
        values={'__name__':'synthetic_runner'}
        exec(compile(prepare_quote_capture_runner(preparation_fixture.SOURCE,helper.guards,spec),'synthetic_runner','exec'),values)
        t=int(datetime(2026,10,9,20,tzinfo=UTC).timestamp()*1000)
        body={'A':{'symbol':'A','quote':{'quoteTime':t}},'B':{'symbol':'B','quote':{'quoteTime':0,'tradeTime':t}}}
        self.assertEqual(values['_validated_response'](operation='quote',body=json.dumps(body).encode(),status_code=200,content_type='application/json',symbols=('A','B'),market_date=None),date(2026,10,9))
        body['A']['quote']['quoteTime']=0
        with self.assertRaises(values['CaptureError']): values['_validated_response'](operation='quote',body=json.dumps(body).encode(),status_code=200,content_type='application/json',symbols=('A','B'),market_date=None)


if __name__=='__main__': unittest.main()
