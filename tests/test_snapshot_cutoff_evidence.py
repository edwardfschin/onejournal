from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb
import test_schwab_phase1_evidence_import as assembly_fixture
import test_external_provider_acquisition as acquisition_fixture
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.schwab_evidence_assembly import (
    SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2, SchwabEvidenceAssemblyError,
    build_schwab_phase1_evidence_assembly_v3, load_schwab_phase1_evidence_assembly_bytes,
    schwab_phase1_evidence_assembly_bytes, validate_schwab_phase1_evidence_assembly,
)
from onejournal.journal.schwab_evidence_v2_repository import persist_schwab_phase1_evidence_assembly_v2
from onejournal.journal.schwab_snapshot_evidence_repository import (
    load_schwab_snapshot_evidence, persist_schwab_snapshot_evidence)
from onejournal.journal.schwab_journal_lifecycle_reconciliation import build_schwab_journal_lifecycle_reconciliation
from onejournal.journal.schwab_execution_projection import build_schwab_execution_projection_from_assembly
from onejournal.journal.schwab_history_revision import persist_schwab_history_revision
from onejournal.journal.schwab_history_revision import activate_prior_history_revision
import test_schwab_history_revision as history_fixture
from onejournal.market_data.quotes import build_quote_uid
from onejournal.market_data.sessions import build_provider_session_authority_uid
from onejournal.market_data.ingestion import QuoteInstrumentRequest, UnavailableQuoteEvidence, CAPTURE_CONTRACT_VERSION_V2
from onejournal.provider_connectors.external_acquisition import (
    SCHWAB_MULTI_BATCH_QUOTES_EXTERNAL_ACQUISITION_PROFILE,
    SCHWAB_BATCH_QUOTES_EXTERNAL_ACQUISITION_PROFILE,
    ExternalAcquisitionQueryParameter, ExternalProviderAcquisitionError,
    ExternalSchwabBatchQuoteMapping, convert_external_schwab_multi_batch_quotes,
    external_provider_acquisition_manifest_bytes,
)

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = datetime(2026, 9, 6, 2, tzinfo=UTC)  # September 5 in New York.
EVALUATED = CUTOFF + timedelta(minutes=5)


def inputs(*, two_quotes=False, late=False, events=False):
    with patch.object(assembly_fixture, 'build_schwab_phase1_evidence_assembly', side_effect=lambda **kw: kw):
        original = assembly_fixture.synthetic_assembly(include_unquoted_position=two_quotes,lifecycle_expiration=events)
    snapshot = replace(original['position'].snapshot, asof=date(2026,9,5), retrieved_at=CUTOFF)
    account = {**original['position'].account_record, 'asof':snapshot.asof, 'retrieved_at_utc':CUTOFF}
    position = replace(original['position'], snapshot=snapshot, account_record=account)
    window, = original['lifecycle_windows']
    cash = tuple({**row, 'transaction_at_utc':'2026-09-04T14:00:00+00:00'} for row in window.cash_rows)
    window = replace(window, window_end_date=CUTOFF.date(), cash_rows=cash)
    if late:
        row = {**window.transaction_rows[0], 'source_fill_id':'late-transaction-fill',
               'source_order_id':'late-order', 'filled_at':'2026-09-06T02:01:00+00:00', 'asof':'2026-09-06'}
        transaction = {**window.transaction_records[0], 'transaction_uid':'synthetic-late-transaction',
                       'source_transaction_id':'late-txn', 'transaction_at_utc':row['filled_at']}
        cash_row = {**cash[0], 'cash_uid':'synthetic-late-cash', 'source_transaction_id':'late-txn',
                    'transaction_at_utc':row['filled_at']}
        window = replace(window, transaction_rows=(*window.transaction_rows,row),
            order_rows=(*window.order_rows,dict(row,source_fill_id='late-order-fill')),
            transaction_records=(*window.transaction_records,transaction), cash_rows=(*cash,cash_row),
            transaction_stats=replace(window.transaction_stats,transactions=2,fill_rows=2))
    converted = original['quote']
    q = replace(converted.capture.quotes[0], received_at=EVALUATED-timedelta(seconds=1), data_mode='frozen')
    q = replace(q, quote_uid=build_quote_uid(q))
    capture = replace(converted.capture, quotes=(q,), started_at=EVALUATED-timedelta(seconds=2),
                      received_at=q.received_at, evaluated_at=EVALUATED)
    converted = replace(converted,capture=capture)
    authority = replace(original['session_authorities'][0], quote_uid=q.quote_uid,
        evaluated_at=EVALUATED, evaluation_market_date=date(2026,9,5),
        evaluation_market_session='closed', evaluation_trading_day_kind='closed_unspecified',
        evaluation_phase_started_at=datetime(2026,9,5,4,tzinfo=UTC),
        evaluation_phase_ends_at=datetime(2026,9,6,4,tzinfo=UTC),
        retrieved_at=q.received_at, resolved_at=EVALUATED, valid_until=EVALUATED+timedelta(minutes=5))
    authority = replace(authority,authority_uid=build_provider_session_authority_uid(authority))
    quotes, authorities = (converted,), (authority,)
    if two_quotes:
        identity = snapshot.positions[1].identity
        body = b'{"synthetic":"second-quote"}\n'
        digest = sha256(body).hexdigest()
        source = replace(converted.source,raw_sha256=digest,locator='schwab/synthetic/second-quote.json')
        second_q = replace(q, instrument_key=identity.key, provider_instrument_id='MSFT', symbol='MSFT', raw_sha256=digest)
        second_q = replace(second_q,quote_uid=build_quote_uid(second_q))
        second_capture = replace(capture,quote_run_uid='synthetic-second-capture',source=source,quotes=(second_q,),
            requests=(QuoteInstrumentRequest(identity.key,'MSFT','stock','USD'),))
        second = replace(converted,external_manifest_sha256='e'*64,external_request_uid='synthetic-second-request',
                         raw_response_bytes=body,source=source,capture=second_capture)
        second_auth = replace(authority, quote_uid=second_q.quote_uid, instrument_key=identity.key,provider_instrument_id='MSFT')
        second_auth = replace(second_auth,authority_uid=build_provider_session_authority_uid(second_auth))
        quotes, authorities = (*quotes,second), (*authorities,second_auth)
    return dict(position=position,lifecycle_windows=(window,),quotes=quotes,session_authorities=authorities,
                assembled_at_utc=EVALUATED+timedelta(seconds=1),freshness_policy=original['freshness_policy'])


class SnapshotCutoffTests(unittest.TestCase):
    def test_unavailable_quotes_are_counted_without_values_or_session_substitution(self):
        request = inputs(two_quotes=True)
        first, second = request['quotes']
        q, = second.capture.quotes
        unavailable = UnavailableQuoteEvidence(q.instrument_key, q.provider_instrument_id, q.asset_class, q.currency, q.raw_sha256)
        second = replace(second, capture=replace(second.capture, quotes=(), unavailable=(unavailable,), contract_version=CAPTURE_CONTRACT_VERSION_V2))
        request['quotes'] = (first, second)
        request['session_authorities'] = request['session_authorities'][:1]
        assembly = build_schwab_phase1_evidence_assembly_v3(**request)
        quotes = next(f for f in assembly.families if f.family == 'quotes')
        self.assertEqual((quotes.source_record_count, quotes.normalized_record_count, quotes.excluded_record_count), (2, 1, 1))
        self.assertEqual(quotes.exclusion_reasons, ('unavailable_provider_quote_timestamp',))
        self.assertEqual(assembly.reconciliation.positions_without_quotes, 1)
        self.assertEqual(load_schwab_phase1_evidence_assembly_bytes(schwab_phase1_evidence_assembly_bytes(assembly)), assembly)

    def test_snapshot_history_exact_readback_replay_and_cross_version_rollback(self):
        fixture = history_fixture.SchwabHistoryRevisionTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        legacy = persist_schwab_history_revision(fixture.db_path, fixture.v2,
            predecessor_materialization_uid=fixture.legacy.materialization_uid)
        assembly = build_schwab_phase1_evidence_assembly_v3(**inputs())
        persist_schwab_snapshot_evidence(fixture.db_path, assembly)
        kwargs = dict(predecessor_materialization_uid=build_schwab_journal_lifecycle_reconciliation(fixture.v2).source_materialization_uid)
        result = persist_schwab_history_revision(fixture.db_path, assembly, **kwargs)
        self.assertTrue(result.created)
        self.assertTrue(persist_schwab_history_revision(fixture.db_path, assembly, **kwargs).replayed)
        activate_prior_history_revision(fixture.db_path, revision_uid=legacy.revision_uid)
        with duckdb.connect(str(fixture.db_path)) as con:
            self.assertEqual(con.execute('SELECT revision_uid FROM phase1_journal_current_revision_ids').fetchone()[0], legacy.revision_uid)
            self.assertEqual(con.execute('SELECT count(*) FROM phase1_journal_history_revisions').fetchone()[0], 2)
        activate_prior_history_revision(fixture.db_path, revision_uid=result.revision_uid)
        with duckdb.connect(str(fixture.db_path)) as con:
            con.execute("UPDATE phase1_journal_snapshot_history_revision_executions SET commission = commission + 1")
        with self.assertRaisesRegex(ValueError, 'content differs'):
            persist_schwab_history_revision(fixture.db_path, assembly, **kwargs)

    def test_weekend_dates_two_sources_and_exact_roundtrip(self):
        assembly = build_schwab_phase1_evidence_assembly_v3(**inputs(two_quotes=True))
        self.assertEqual(assembly.asof,date(2026,9,5))
        self.assertEqual(assembly.lifecycle_window_end,date(2026,9,6))
        self.assertEqual(assembly.snapshot_cutoff_utc,CUTOFF)
        quotes = next(f for f in assembly.families if f.family=='quotes')
        self.assertEqual(len(quotes.source_raw_sha256s),2)
        self.assertEqual({r['asof'] for r in quotes.records},{'2026-09-04'})
        self.assertEqual(assembly.reconciliation.quote_count,2)
        self.assertEqual(load_schwab_phase1_evidence_assembly_bytes(schwab_phase1_evidence_assembly_bytes(assembly)),assembly)
        plan = build_schwab_journal_lifecycle_reconciliation(assembly)
        self.assertEqual(plan.asof,assembly.asof)
        projection = build_schwab_execution_projection_from_assembly(assembly)
        self.assertTrue(projection.result_fingerprint)

    def test_post_snapshot_financial_rows_are_excluded_and_counted(self):
        assembly = build_schwab_phase1_evidence_assembly_v3(**inputs(late=True))
        families = {f.family:f for f in assembly.families}
        for name in ('transactions','fills','cash'):
            self.assertEqual(families[name].excluded_record_count,1)
            self.assertIn('after_snapshot_cutoff',families[name].exclusion_reasons)
        self.assertEqual(assembly.reconciliation.matched_fill_rows,1)
        self.assertEqual(assembly.final_status,'review_required')
        self.assertEqual(families['account'].records[0]['order_fill_rows_after_snapshot_cutoff'],1)

    def test_terminal_event_cutoff_includes_boundary_and_excludes_later_legs(self):
        request = inputs(events=True)
        window, = request['lifecycle_windows']
        event = {**window.lifecycle_events[0], 'event_at':CUTOFF.isoformat(), 'asof':CUTOFF.date().isoformat()}
        request['lifecycle_windows'] = (replace(window,lifecycle_events=(event,)),)
        boundary = build_schwab_phase1_evidence_assembly_v3(**request)
        self.assertEqual(next(f.normalized_record_count for f in boundary.families if f.family=='lifecycle_events'),1)
        request['lifecycle_windows'] = (replace(window,lifecycle_events=({**event,'event_at':(CUTOFF+timedelta(microseconds=1)).isoformat()},)),)
        later = build_schwab_phase1_evidence_assembly_v3(**request)
        for family in later.families:
            if family.family in ('lifecycle_events','lifecycle_event_legs'):
                self.assertEqual(family.normalized_record_count,0)
                self.assertEqual(family.excluded_record_count,1)
                self.assertIn('after_snapshot_cutoff',family.exclusion_reasons)

    def test_cutoff_date_scope_duplicate_quotes_and_future_mark_fail_closed(self):
        good = build_schwab_phase1_evidence_assembly_v3(**inputs())
        for bad in (replace(good,snapshot_cutoff_utc=None),replace(good,asof=date(2026,9,6)),
                    replace(good,lifecycle_window_end=date(2026,9,7))):
            with self.assertRaises(SchwabEvidenceAssemblyError):
                validate_schwab_phase1_evidence_assembly(bad)
        request = inputs()
        request['quotes'] = request['quotes'] * 2
        with self.assertRaisesRegex(SchwabEvidenceAssemblyError,'duplicate instruments'):
            build_schwab_phase1_evidence_assembly_v3(**request)
        request = inputs()
        snapshot = replace(request['position'].snapshot,retrieved_at=datetime(2026,9,4,14,tzinfo=UTC),asof=date(2026,9,4))
        request['position'] = replace(request['position'],snapshot=snapshot)
        with self.assertRaisesRegex(SchwabEvidenceAssemblyError,'quote evidence is after'):
            build_schwab_phase1_evidence_assembly_v3(**request)

    def test_migration_storage_replay_tamper_and_legacy_activation_boundary(self):
        assembly = build_schwab_phase1_evidence_assembly_v3(**inputs())
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory)/'journal.duckdb'
            apply_schema_migrations(db,migrations_dir=ROOT/'scripts/journal/migrations')
            legacy = assembly_fixture.synthetic_assembly(assembly_version=SCHWAB_PHASE1_EVIDENCE_ASSEMBLY_V2)
            persist_schwab_phase1_evidence_assembly_v2(db,legacy)
            first = persist_schwab_snapshot_evidence(db,assembly)
            second = persist_schwab_snapshot_evidence(db,assembly)
            self.assertTrue(first.created)
            self.assertTrue(second.replayed)
            self.assertEqual(load_schwab_snapshot_evidence(db,assembly_uid=assembly.assembly_uid),assembly)
            artifact = Path(directory)/'assembly.json'
            artifact.write_bytes(schwab_phase1_evidence_assembly_bytes(assembly))
            artifact.chmod(0o600)
            db.chmod(0o600)
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(assembly_fixture.operator_main(['--assembly',str(artifact),'--persist','--db',str(db)]),0)
            self.assertEqual(json.loads(output.getvalue())['operation'],'replayed')
            self.assertNotIn('AAPL',output.getvalue())
            error = StringIO()
            with patch('scripts.journal.ingest_schwab_phase1_evidence_assembly.persist_schwab_snapshot_evidence',
                       side_effect=duckdb.ConstraintException('AAPL synthetic private financial row')), redirect_stderr(error):
                self.assertEqual(assembly_fixture.operator_main(['--assembly',str(artifact),'--persist','--db',str(db)]),1)
            self.assertNotIn('AAPL',error.getvalue())
            self.assertIn('database validation failed',error.getvalue())
            with duckdb.connect(str(db)) as connection:
                self.assertEqual(connection.execute('SELECT result_fingerprint FROM phase1_schwab_evidence_v2_import_runs').fetchone(),
                                 (legacy.result_fingerprint,))
                with self.assertRaises(duckdb.ConstraintException):
                    connection.execute("UPDATE phase1_schwab_snapshot_evidence_imports SET asof_date = DATE '2026-09-06'")
                connection.execute("UPDATE phase1_schwab_snapshot_evidence_imports SET artifact_json = artifact_json || ' '")
            with self.assertRaisesRegex(ValueError,'checksum'):
                load_schwab_snapshot_evidence(db,assembly_uid=assembly.assembly_uid)
        absent = Path('/private/tmp/onejournal-test-never-created-v3.duckdb')
        with self.assertRaisesRegex(ValueError,'pre-existing non-symlink file'):
            persist_schwab_history_revision(absent,assembly,predecessor_materialization_uid='synthetic-predecessor')
        self.assertFalse(absent.exists())


class MultiBatchQuoteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = acquisition_fixture.ExternalProviderAcquisitionTests()
        self.fixture.setUp()
        document = json.loads(acquisition_fixture.batch_quote_body())
        bodies = [(json.dumps({s:document[s]},sort_keys=True,separators=(',',':'))+'\n').encode()
                  for s in ('AAPL','MSFT')]
        first = self.fixture.manifest.requests[0]
        requests = tuple(replace(first,request_uid=f'synthetic-batch-{i}',
            query=(ExternalAcquisitionQueryParameter('symbols',s),ExternalAcquisitionQueryParameter('fields','quote,reference')),
            response_filename=f'quote-{i}.json',response_byte_count=len(b),response_sha256=sha256(b).hexdigest())
            for i,(s,b) in enumerate(zip(('AAPL','MSFT'),bodies)))
        self.manifest = replace(self.fixture.manifest,profile=SCHWAB_MULTI_BATCH_QUOTES_EXTERNAL_ACQUISITION_PROFILE,
            requests=(*requests,self.fixture.manifest.requests[1]),
            controls=replace(self.fixture.manifest.controls,provider_get_count=3,response_count=3))
        self.responses = {**{r.response_filename:b for r,b in zip(requests,bodies)},
                          'market-hours-2026-08-31.json':self.fixture.schedule}
        self.mappings = tuple(ExternalSchwabBatchQuoteMapping(r.request_uid,
            (QuoteInstrumentRequest('stock|'+s,s,'stock','USD'),)) for r,s in zip(requests,('AAPL','MSFT')))

    def test_two_batches_keep_exact_response_lineage(self):
        acquisition = self.fixture.load(manifest=self.manifest,responses=self.responses)
        captures = convert_external_schwab_multi_batch_quotes(acquisition,mappings=self.mappings,
            evaluated_at_utc=self.fixture.evaluated_at,freshness_policy=self.fixture.freshness_policy)
        self.assertEqual(len(captures),2)
        for capture in captures:
            self.assertEqual(capture.capture.source.raw_sha256,sha256(capture.raw_response_bytes).hexdigest())
        with self.assertRaisesRegex(ExternalProviderAcquisitionError,'exactly cover'):
            convert_external_schwab_multi_batch_quotes(acquisition,mappings=self.mappings[:1],
                evaluated_at_utc=self.fixture.evaluated_at,freshness_policy=self.fixture.freshness_policy)

    def test_full_64_symbol_scope_and_operator_hash_only_audit(self):
        template = json.loads(acquisition_fixture.batch_quote_body())['AAPL']
        groups = (tuple(f'SYN{i:03}' for i in range(50)), tuple(f'SYN{i:03}' for i in range(50,64)))
        requests, mappings, responses = [], [], {'market-hours-2026-08-31.json':self.fixture.schedule}
        for index, symbols in enumerate(groups):
            body = (json.dumps({symbol:{**template,'symbol':symbol} for symbol in symbols},
                               sort_keys=True,separators=(',',':'))+'\n').encode()
            request = replace(self.manifest.requests[index],query=(
                ExternalAcquisitionQueryParameter('symbols',','.join(symbols)),
                ExternalAcquisitionQueryParameter('fields','quote,reference')),
                response_byte_count=len(body),response_sha256=sha256(body).hexdigest())
            requests.append(request)
            responses[request.response_filename] = body
            mappings.append(ExternalSchwabBatchQuoteMapping(request.request_uid,
                tuple(QuoteInstrumentRequest('stock|'+symbol,symbol,'stock','USD') for symbol in symbols)))
        manifest = replace(self.manifest,requests=(*requests,self.manifest.requests[-1]))
        acquisition = self.fixture.load(manifest=manifest,responses=responses)
        captures = convert_external_schwab_multi_batch_quotes(acquisition,mappings=tuple(mappings),
            evaluated_at_utc=self.fixture.evaluated_at,freshness_policy=self.fixture.freshness_policy)
        self.assertEqual([len(c.capture.quotes) for c in captures],[50,14])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root/'acquisition'
            bundle.mkdir(mode=0o700)
            for name, body in {**responses,'acquisition-manifest.json':external_provider_acquisition_manifest_bytes(manifest)}.items():
                path = bundle/name
                path.write_bytes(body)
                path.chmod(0o600)
            acknowledgement = root/'acknowledgement.json'
            acknowledgement.write_bytes(self.fixture.acknowledgement_bytes)
            acknowledgement.chmod(0o600)
            args = ['--acquisition-root',str(bundle),'--acknowledgement',str(acknowledgement),
                '--expected-run-uid',acquisition_fixture.RUN_UID,'--expected-approval-id',acquisition_fixture.APPROVAL_ID,
                '--expected-owner-uid',acquisition_fixture.OWNER_UID,'--expected-owner-epoch-uid',acquisition_fixture.OWNER_EPOCH_UID,
                '--evaluated-at',self.fixture.evaluated_at.isoformat(),
                '--normal-reference-date',acquisition_fixture.MARKET_DATE.isoformat(),
                '--schedule-valid-until',(self.fixture.evaluated_at+timedelta(days=1)).isoformat(),
                '--require-valuation-allowed']
            for mapping in mappings:
                for item in mapping.instruments:
                    args.extend(['--quote-mapping',mapping.request_uid,item.instrument_key,
                                 item.provider_instrument_id,item.asset_class,item.currency,'equity'])
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(acquisition_fixture.external_acquisition_operator_main(args),0)
            audit = json.loads(output.getvalue())
            self.assertEqual(audit['quote_count'],64)
            self.assertFalse(audit['materialized_private'])
            self.assertTrue(all(len(q['instrument_key_sha256'])==64 for q in audit['quotes']))
            self.assertNotIn('SYN000',output.getvalue())
            self.assertNotIn('instrument_key"',output.getvalue())

    def test_legacy_cap_overlap_and_order_are_not_widened(self):
        with self.assertRaises(ExternalProviderAcquisitionError):
            self.fixture.load(manifest=replace(self.manifest,profile=SCHWAB_BATCH_QUOTES_EXTERNAL_ACQUISITION_PROFILE),responses=self.responses)
        for quotes in ((self.manifest.requests[1],self.manifest.requests[0]),
                       (self.manifest.requests[0],replace(self.manifest.requests[1],query=self.manifest.requests[0].query))):
            with self.assertRaisesRegex(ExternalProviderAcquisitionError,'disjoint and globally sorted'):
                self.fixture.load(manifest=replace(self.manifest,requests=(*quotes,self.manifest.requests[2])),responses=self.responses)


if __name__ == '__main__':
    unittest.main()
