"""Focused missing journey: paired upload -> active Portfolio/Reports, restart and rollback."""
import base64
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import duckdb
from fastapi.testclient import TestClient

import test_activity_journal_upload as activity_fixture
import test_external_schwab_position_acquisition as position_fixture
import test_phase1_reporting_repository as report_fixture
from onejournal.activity_financial_preview import load_activity_financial_preview
from onejournal.api.local_owner_journal import create_local_owner_journal_app
from onejournal.brokers.schwab.position_binding import schwab_position_private_binding_bytes
from onejournal.journal.broker_current_position_valuation_repository import (
    persist_broker_current_position_valuation_run, calculate_broker_current_position_result_fingerprint,
)
from onejournal.journal.phase1_reporting_repository import (
    ReportingReleaseAuthorization, calculate_report_release_fingerprint, persist_reporting_release,
)
from onejournal.manual_financial_refresh import FinancialUploadPublisher, portfolio_authorization
from onejournal.pnl.broker_current_position_valuation import build_broker_current_position_valuation
from onejournal.provider_connectors.external_acquisition import external_provider_acquisition_manifest_bytes
from onejournal.refresh_activity import confirmed_import
from onejournal.brokers.schwab.account_binding import SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA, SchwabAccountPrivateBinding
from test_snapshot_cutoff_evidence import inputs


class ManualFinancialRefreshTests(unittest.TestCase):
    def setUp(self):
        fixture = activity_fixture.ActivityJournalUploadTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.db = fixture.history.db_path
        from onejournal.journal.migrations import apply_schema_migrations
        apply_schema_migrations(self.db, target_version='0030')
        original = inputs()['position'].snapshot
        self.binding = fixture.intake.account_binding_path
        from onejournal.brokers.schwab.position_binding import load_schwab_position_private_binding_bytes
        private = load_schwab_position_private_binding_bytes(self.binding.read_bytes())
        self.account = SchwabAccountPrivateBinding(SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA,
            private.connection_uid, private.source_account_id, private.provider_account_hash, private.provider_account_number)
        source = position_fixture.ExternalSchwabPositionAcquisitionTests()
        with patch.object(position_fixture, 'CONNECTION_UID', original.connection_uid):
            source.setUp()
        self.binding.write_bytes(schwab_position_private_binding_bytes(replace(private, mappings=source.mappings())))
        # Existing report/valuation use the real saved history from the fixture.
        old = build_broker_current_position_valuation(broker_snapshot=original, evaluated_at=original.retrieved_at,
            max_snapshot_age_seconds=0, currency_quantum_by_currency={'USD': Decimal('0.01')})
        persist_broker_current_position_valuation_run(self.db, run=old, broker_snapshot=original)
        baseline = confirmed_import(self.db, self.account)
        preview = load_activity_financial_preview(self.db, self.account,
            expected_checkpoint_uid=baseline.checkpoint_uid or baseline.assembly.result_fingerprint, account_alias='Primary')
        template = report_fixture.Phase1ReportingRepositoryTests()._release()
        self.root = replace(template, current_valuation_run_uid=old.run_uid,
            current_result_fingerprint=calculate_broker_current_position_result_fingerprint(old),
            current_owner_accepted_at_utc=datetime(2026,9,6,3,tzinfo=UTC),
            realized_owner_accepted_at_utc=datetime(2026,9,6,3,tzinfo=UTC),
            generated_at_utc=datetime(2026,9,6,3,tzinfo=UTC), owner_accepted_at_utc=datetime(2026,9,6,3,tzinfo=UTC),
            accounts=preview.accounts, items=preview.items, omissions=preview.omissions,
            history_revision_uid=baseline.revision_uid, coverage_start_date=preview.coverage_start_date,
            coverage_end_date=preview.coverage_end_date, report_release_fingerprint='')
        self.root = replace(self.root, report_release_fingerprint=calculate_report_release_fingerprint(release=self.root))
        with duckdb.connect(str(self.db)) as con:
            persist_reporting_release(con, self.root)
        self.authority = ReportingReleaseAuthorization(self.root.report_release_uid,
            self.root.report_release_fingerprint, self.root.owner_acceptance_uid)
        # One confirmed partial stock close, not an option order or a synthetic
        # fake financial-calculation callback. All actual adapter checks run.
        orders = json.loads(fixture.files['orders.json'])
        order = orders[0]
        order['enteredTime'] = '2026-09-07T13:00:00Z'
        leg = order['orderLegCollection'][0]
        leg.update(instruction='SELL', positionEffect='CLOSING', instrument={'assetType':'EQUITY', 'symbol':'AAPL'})
        fill = order['orderActivityCollection'][0]['executionLegs'][0]
        fill.update(quantity=1, price='110', time='2026-09-07T13:01:00Z')
        transactions = json.loads(fixture.files['transactions.json'])
        transaction = transactions[0]
        transaction.update(tradeDate='2026-09-07T13:01:00Z', time='2026-09-07T13:01:00Z', netAmount='109.70')
        transaction['transferItems'][0].update(amount=-1, price='110', positionEffect='CLOSING',
            instrument={'assetType':'EQUITY', 'symbol':'AAPL'})
        transaction['transferItems'][1].update(amount='-0.30', cost='0.30')
        self.activity = self._rebuild(fixture.files, {'orders.json':self._bytes(orders),
            'transactions.json':self._bytes(transactions)})
        document = json.loads(source.body)
        row = document['securitiesAccount']['positions'][0]
        row.update(longQuantity=1, averagePrice=100, taxLotAverageLongPrice=100,
            marketValue=120, longOpenProfitLoss=20)
        body = self._bytes(document)
        requested = datetime(2026,9,7,13,59,58,tzinfo=UTC)
        request = replace(source.request, approved_market_date=date(2026,9,7),
            requested_at_utc=requested, received_at_utc=requested+timedelta(seconds=1),
            response_sha256=sha256(body).hexdigest(), response_byte_count=len(body))
        ack = fixture.intake.acknowledgement_path.read_bytes()
        manifest = replace(source.manifest, requests=(request,), completed_at_utc=requested+timedelta(seconds=2),
            acknowledgement_uid=json.loads(ack)['acknowledgement']['acknowledgement_uid'],
            acknowledgement_sha256=sha256(ack).hexdigest())
        self.positions = {'acquisition-manifest.json':external_provider_acquisition_manifest_bytes(manifest), 'positions.json':body}

    @staticmethod
    def _bytes(document):
        return (json.dumps(document, sort_keys=True, separators=(',', ':')) + '\n').encode()

    def _rebuild(self, files, responses):
        document = json.loads(files['acquisition-manifest.json'])
        # Parse through the production fixture model to preserve canonical bytes.
        from onejournal.provider_connectors.external_acquisition import _parse_manifest
        manifest = _parse_manifest(document)
        requests = tuple(replace(r, response_sha256=sha256(responses[r.response_filename]).hexdigest(),
            response_byte_count=len(responses[r.response_filename])) for r in manifest.requests)
        return {'acquisition-manifest.json': external_provider_acquisition_manifest_bytes(replace(manifest, requests=requests)), **responses}

    def app(self):
        return create_local_owner_journal_app(journal_db_path=self.db,
            broker_current_authorization=portfolio_authorization(self.root), reporting_authorization=self.authority,
            manual_capture_intake=self.fixture.intake, manual_capture_save_journal=True,
            manual_capture_publish_financials=True)

    def payload(self):
        def files(values):
            return {'files':[{'name':name,'content_base64':base64.b64encode(body).decode()} for name,body in values.items()]}
        return {'positions':files(self.positions), 'activity':files(self.activity)}

    def test_upload_publishes_financial_apis_csv_replay_and_restart(self):
        app = self.app(); client = TestClient(app)
        path = '/api/v1/local-owner/financial-upload'
        self.assertEqual(client.post(path, json=self.payload()).status_code, 403)
        app.state.passkey_access = object()
        with patch('socket.socket.connect', side_effect=AssertionError('No network allowed')):
            result = client.post(path, json=self.payload())
            self.assertEqual(result.status_code, 200, result.text)
            self.assertEqual(result.json()['portfolio_asof'], '2026-09-07')
            self.assertFalse(result.json()['replayed'])
            accounts = client.get('/api/v1/local-owner/reports/current/accounts')
            self.assertEqual(accounts.status_code, 200, accounts.text)
            self.assertEqual(accounts.json()['metadata']['report_release_uid'], result.json()['report_release_uid'])
            filters = dict(from_date=self.root.coverage_start_date.isoformat(), to_date='2026-09-07')
            report = client.get('/api/v1/local-owner/reports/realized-history', params=filters)
            self.assertEqual(Decimal(report.json()['items'][0]['realized_pnl']), Decimal('9.70'))
            exported = client.get('/api/v1/local-owner/reports/realized-history.csv', params=filters)
            self.assertIn('9.70', exported.text)
            from onejournal.api.local_owner_journal import LOCAL_OWNER_CURRENT_PORTFOLIO_API_PATH
            portfolio = client.get(LOCAL_OWNER_CURRENT_PORTFOLIO_API_PATH)
            self.assertEqual(portfolio.status_code, 200, portfolio.text)
            self.assertEqual(portfolio.json()['metadata']['asof'], '2026-09-07')
            replay = client.post(path, json=self.payload())
            self.assertTrue(replay.json()['replayed'], replay.text)
            restarted = TestClient(self.app())
            self.assertEqual(restarted.get('/api/v1/local-owner/reports/current/accounts').json()['metadata']['report_release_uid'], result.json()['report_release_uid'])
        backups = list(self.fixture.intake.staging_root.glob('rollback-*/journal.duckdb'))
        self.assertEqual(len(backups), 1)
        with duckdb.connect(str(backups[0]), read_only=True) as con:
            self.assertEqual(con.execute('SELECT count(*) FROM incremental_activity_imports').fetchone()[0], 0)

    def test_failed_financial_save_leaves_entire_live_journal_unchanged(self):
        before = self.db.read_bytes()
        publisher = FinancialUploadPublisher(self.fixture.intake, self.authority)
        with patch('onejournal.manual_financial_refresh.persist_reporting_release', side_effect=ValueError('Injected failure after financial write')):
            with self.assertRaisesRegex(ValueError, 'Injected failure'):
                publisher.publish(self.db, self.positions, self.activity)
        self.assertEqual(self.db.read_bytes(), before)
        self.assertEqual(publisher.selected_release(self.db), self.root)

    def test_bad_bytes_wrong_owner_and_older_positions_do_not_change_saved_data(self):
        publisher = FinancialUploadPublisher(self.fixture.intake, self.authority)
        before = self.db.read_bytes()
        wrong = dict(self.positions, **{'positions.json': b'{}'})
        with self.assertRaises(ValueError):
            publisher.publish(self.db, wrong, self.activity)
        manifest = json.loads(self.positions['acquisition-manifest.json'])
        manifest['source_owner']['owner_uid'] = 'unapproved-source-owner'
        with self.assertRaises(ValueError):
            publisher.publish(self.db, {**self.positions, 'acquisition-manifest.json':self._bytes(manifest)}, self.activity)
        self.assertEqual(self.db.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
