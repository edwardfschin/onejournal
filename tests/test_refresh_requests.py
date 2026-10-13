from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import patch
from fastapi import FastAPI
from fastapi.testclient import TestClient

from onejournal.refresh_requests import RefreshRequests, RefreshBusy, register_routes, PREFIX
import test_mac_passkey_access as access_fixture
import test_external_schwab_position_acquisition as capture_fixture


class RefreshRequestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'requests.sqlite'
        self.queue = RefreshRequests.initialize(self.path, 'schwab')

    def test_durable_single_claim_replay_scope_and_private_receipt(self):
        uid = str(uuid4())
        first = self.queue.request(uid)
        self.assertEqual(self.queue.request(uid), first)
        with self.assertRaises(RefreshBusy):
            self.queue.request(str(uuid4()))
        self.assertEqual(self.queue.claim()['scope'], 'current_positions')
        reopened = RefreshRequests(self.path, 'schwab')
        self.assertIsNone(reopened.claim())  # Restart must not repeat a GET.
        self.assertEqual(reopened.request(uid)['state'], 'capturing')
        fixture = capture_fixture.ExternalSchwabPositionAcquisitionTests()
        fixture.setUp()
        with self.assertRaises(ValueError):
            reopened.captured(uid, fixture.load(), expected_connection_uid=capture_fixture.CONNECTION_UID)
        with patch.object(capture_fixture, 'RUN_UID', uid):
            verified = fixture.load(manifest=replace(fixture.manifest, acquisition_run_uid=uid))
        with self.assertRaises(ValueError):
            reopened.captured(uid, verified, expected_connection_uid='wrong-account-binding')
        reopened.captured(uid, verified, expected_connection_uid=capture_fixture.CONNECTION_UID)
        self.assertEqual(reopened.status()['latest']['state'], 'captured')
        self.assertNotIn('sha256', str(reopened.status()))
        with self.assertRaises(RefreshBusy):
            reopened.request(str(uuid4()))
        reopened.finish_review(uid)
        self.assertEqual(reopened.request(uid)['state'], 'closed')
        next_uid = str(uuid4())
        reopened.request(next_uid)
        reopened.fail(next_uid)
        self.assertEqual(reopened.status()['latest']['state'], 'failed')
        # A later request must not erase the earlier request or capture receipt.
        self.assertEqual(reopened.request(uid)['state'], 'closed')
        with reopened.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM requests').fetchone()[0], 2)
            self.assertEqual(con.execute('SELECT manifest_sha256 FROM requests WHERE id=?', (uid,)).fetchone()[0], verified.manifest_sha256)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            RefreshRequests(self.path, 'ibkr')

    def test_unauthenticated_csrf_disabled_and_injected_parameters(self):
        fixture = access_fixture.MacPasskeyTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        register_routes(fixture.client.app, self.queue)
        body = {'request_id': str(uuid4())}
        self.assertEqual(fixture.client.get(PREFIX).status_code, 401)
        self.assertEqual(fixture.client.post(PREFIX, json=body, headers={'Origin': access_fixture.ORIGIN}).status_code, 401)
        csrf = fixture.ready()
        self.assertEqual(fixture.client.post(PREFIX, json=body, headers={'Origin': access_fixture.ORIGIN}).status_code, 403)
        headers = {'Origin': access_fixture.ORIGIN, 'X-OneJournal-CSRF': csrf}
        for extra in [{'provider': 'ibkr'}, {'account': 'other'}, {'url': 'https://attacker.invalid'}, {'from_date': '2000-01-01'},
                      {'mode': 'full'}, {'replace_existing': True}, {'reset': True}]:
            self.assertEqual(fixture.client.post(PREFIX, json={**body, **extra}, headers=headers).status_code, 422)
        self.assertEqual(fixture.client.post(PREFIX, json=body, headers=headers).status_code, 202)
        self.assertEqual(fixture.client.post(PREFIX, json=body, headers=headers).status_code, 202)
        self.assertEqual(fixture.client.post(PREFIX, json={'request_id': str(uuid4())}, headers=headers).status_code, 409)
        unprotected = FastAPI()
        register_routes(unprotected, self.queue)
        self.assertEqual(TestClient(unprotected).post(PREFIX, json=body).status_code, 403)
        disabled = FastAPI()
        register_routes(disabled)
        disabled.state.passkey_access = object()  # Only exercises disabled route; real gate tested above.
        self.assertFalse(TestClient(disabled).get(PREFIX).json()['enabled'])
        self.assertEqual(TestClient(disabled).post(PREFIX, json=body).status_code, 503)

    def test_competing_requests_cannot_enqueue_two_captures(self):
        from concurrent.futures import ThreadPoolExecutor
        def enqueue(_):
            try:
                return self.queue.request(str(uuid4()))['state']
            except RefreshBusy:
                return 'busy'
        with ThreadPoolExecutor(2) as pool:
            self.assertCountEqual(list(pool.map(enqueue, range(2))), ['queued', 'busy'])
