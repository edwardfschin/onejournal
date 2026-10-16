"""The previously missing HTTP upload -> saved trade -> Journal note journey."""
import base64
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

import duckdb
from fastapi.testclient import TestClient

import test_external_schwab_lifecycle_acquisition as capture_fixture
import test_schwab_history_revision as history_fixture
from test_snapshot_cutoff_evidence import inputs
from onejournal.activity_rehearsal import disposable_journal, prepare_copy
from onejournal.api.local_owner_journal import create_local_owner_journal_app
from onejournal.brokers.schwab.position_binding import (
    SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA, SchwabPositionPrivateBinding,
    schwab_position_private_binding_bytes,
)
from onejournal.journal.schwab_evidence_assembly import build_schwab_phase1_evidence_assembly_v3
from onejournal.journal.schwab_history_revision import persist_schwab_history_revision
from onejournal.journal.schwab_journal_lifecycle_reconciliation import build_schwab_journal_lifecycle_reconciliation
from onejournal.journal.schwab_snapshot_evidence_repository import persist_schwab_snapshot_evidence
from onejournal.manual_capture_upload import ManualCaptureIntake
from onejournal.provider_connectors.external_acquisition import external_provider_acquisition_manifest_bytes
from onejournal.refresh_capture_authorization import AUTHORIZATION_VERSION


class ActivityJournalUploadTests(unittest.TestCase):
    def setUp(self):
        history = history_fixture.SchwabHistoryRevisionTests()
        history.setUp()
        self.addCleanup(history.doCleanups)
        self.history = history
        assembly = build_schwab_phase1_evidence_assembly_v3(**inputs())
        persist_schwab_history_revision(history.db_path, history.v2,
            predecessor_materialization_uid=history.legacy.materialization_uid)
        persist_schwab_snapshot_evidence(history.db_path, assembly)
        persist_schwab_history_revision(history.db_path, assembly,
            predecessor_materialization_uid=build_schwab_journal_lifecycle_reconciliation(history.v2).source_materialization_uid)
        capture = capture_fixture.ExternalSchwabLifecycleAcquisitionTests()
        with patch.object(capture_fixture, 'CONNECTION_UID', assembly.connection_uid):
            capture.setUp()
        order = capture.order_body.replace(b'2026-08-31', b'2026-09-04')
        document = json.loads(capture.transaction_body.replace(b'2026-08-31', b'2026-09-04'))
        document[0]['netAmount'] = '-1051.30'
        transaction = capture_fixture.canonical_json_bytes(document)
        requested = datetime(2026, 9, 7, 14, tzinfo=UTC)
        requests = []
        for old, body in zip(capture.manifest.requests, (order, transaction)):
            query = tuple(replace(q, value=('2026-09-04T00:00:00.000Z' if q.name in ('fromEnteredTime','startDate')
                else '2026-09-07T23:59:59.999Z' if q.name in ('toEnteredTime','endDate') else q.value)) for q in old.query)
            requests.append(replace(old, query=query, window_start_date=date(2026,9,4), window_end_date=date(2026,9,7),
                approved_market_date=date(2026,9,7), requested_at_utc=requested, received_at_utc=requested+timedelta(seconds=1),
                response_byte_count=len(body), response_sha256=sha256(body).hexdigest()))
        manifest = replace(capture.manifest, requests=tuple(requests), completed_at_utc=requested+timedelta(seconds=2))
        self.files = {'acquisition-manifest.json': external_provider_acquisition_manifest_bytes(manifest),
                      'orders.json': order, 'transactions.json': transaction}
        root = Path(history.tmp.name)
        def write(name, body):
            path = root / name
            path.write_bytes(body)
            path.chmod(0o600)
            return path
        authorization = write('upload-authority.json', json.dumps(dict(
            contract_version=AUTHORIZATION_VERSION, capture_scope='activity',
            manifest_sha256=sha256(self.files['acquisition-manifest.json']).hexdigest(),
            acquisition_run_uid=manifest.acquisition_run_uid, acquisition_approval_id=capture_fixture.APPROVAL_ID,
            owner_uid=capture_fixture.OWNER_UID, owner_epoch_uid=capture_fixture.OWNER_EPOCH_UID)).encode())
        binding = replace(capture.account_binding(), source_account_id=assembly.source_account_id,
                          connection_uid=assembly.connection_uid)
        private = SchwabPositionPrivateBinding(SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA,
            binding.connection_uid, binding.source_account_id, binding.provider_account_hash,
            binding.provider_account_number, ())
        staging = root / 'staging'
        staging.mkdir(mode=0o700)
        self.intake = ManualCaptureIntake(authorization_path=authorization,
            acknowledgement_path=write('ack.json', capture.acknowledgement_bytes),
            account_binding_path=write('position-binding.json', schwab_position_private_binding_bytes(private)),
            usage_policy=capture.usage_policy, staging_root=staging, project_root=Path(__file__).resolve().parents[1])

    def payload(self):
        return {'files': [dict(name=name, content_base64=base64.b64encode(body).decode())
                          for name, body in self.files.items()]}

    def test_upload_saves_current_trade_note_and_replays_without_duplicates(self):
        source = self.history.db_path.read_bytes()
        with disposable_journal(self.history.db_path) as db:
            prepare_copy(db)
            app = create_local_owner_journal_app(journal_db_path=db,
                manual_capture_intake=self.intake, manual_capture_save_journal=True)
            app.state.passkey_access = object()
            client = TestClient(app)
            prefix = '/api/v5/local-owner/journal'
            with duckdb.connect(str(db), read_only=True) as con:
                before = con.execute('SELECT count(*) FROM normalized_fills').fetchone()[0]
            with patch('socket.socket.connect', side_effect=AssertionError('Broker/network forbidden')):
                first = client.post('/api/v1/local-owner/manual-capture', json=self.payload())
                self.assertEqual(first.status_code, 202, first.text)
                self.assertEqual(first.json()['state'], 'journal_saved')
                self.assertTrue(first.json()['journal_written'])
                self.assertFalse(first.json()['financial_publication_authorized'])
                search = client.get(prefix + '/search')
                self.assertEqual(search.status_code, 200, search.text)
                trades = [client.get(prefix + '/trades/' + e['episode_uid']) for e in search.json()['episodes']]
                for trade in trades:
                    self.assertEqual(trade.status_code, 200, trade.text)
                self.assertEqual(sum(len(t.json()['executions']) for t in trades), 2)
                trade_uid = search.json()['episodes'][0]['episode_uid']
                review = client.post(prefix + '/reviews', headers={'X-OneJournal-Operation-Id':str(uuid4())},
                    json=dict(episode_uid=trade_uid, review_status='reviewed', setup_quality='good',
                              entry_reason='Synthetic entry reason.'))
                self.assertEqual(review.status_code, 200, review.text)
                note = client.post(prefix + '/entries', headers={'X-OneJournal-Operation-Id':str(uuid4())},
                    json=dict(episode_uid=trade_uid, entry_type='lesson', body='Synthetic lesson from the new activity.'))
                self.assertEqual(note.status_code, 200, note.text)
                reopened = client.get(prefix + '/entries/' + note.json()['resource_uid'])
                self.assertEqual(reopened.json()['entry']['body'], 'Synthetic lesson from the new activity.')
                replay = client.post('/api/v1/local-owner/manual-capture', json=self.payload())
                self.assertEqual(replay.status_code, 202, replay.text)
                self.assertTrue(replay.json()['replayed'])
            with duckdb.connect(str(db), read_only=True) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM normalized_fills').fetchone()[0], before+1)
                self.assertEqual(con.execute('SELECT count(*) FROM incremental_activity_imports').fetchone()[0], 1)
            # A fresh app reads the retained view after a restart as well.
            restarted = TestClient(create_local_owner_journal_app(journal_db_path=db))
            self.assertEqual(len(restarted.get(prefix + '/search').json()['episodes']), len(search.json()['episodes']))
        self.assertEqual(self.history.db_path.read_bytes(), source)

    def test_failed_journal_save_rolls_back_fills_and_checkpoint(self):
        with disposable_journal(self.history.db_path) as db:
            prepare_copy(db)
            with duckdb.connect(str(db), read_only=True) as con:
                before = con.execute('SELECT count(*) FROM normalized_fills').fetchone()[0]
            from onejournal.journal.activity_refresh_repository import _save_journal
            def fail_after_fills(*args):
                _save_journal(*args)
                self.assertGreater(args[0].execute('SELECT count(*) FROM normalized_fills').fetchone()[0], before)
                raise ValueError('Synthetic failure after financial validation')
            with patch('onejournal.journal.activity_refresh_repository._save_journal', side_effect=fail_after_fills):
                with self.assertRaises(ValueError):
                    self.intake.stage(self.files, journal_db=db)
            with duckdb.connect(str(db), read_only=True) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM normalized_fills').fetchone()[0], before)
                self.assertEqual(con.execute('SELECT count(*) FROM incremental_activity_imports').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
