from contextlib import redirect_stdout
from dataclasses import replace
from datetime import timedelta
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from onejournal.brokers.schwab.position_binding import schwab_position_private_binding_bytes
from onejournal.provider_connectors.external_acquisition import external_provider_acquisition_manifest_bytes
from onejournal.refresh_intake import main, receive_position_refresh
from onejournal.refresh_requests import RefreshRequests
import test_external_schwab_position_acquisition as fixture_module


class RefreshIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fixture = fixture_module.ExternalSchwabPositionAcquisitionTests()
        self.fixture.setUp()
        self.queue = RefreshRequests.initialize(self.root / 'requests.sqlite', 'schwab')
        self.uid = str(uuid4())
        self.enqueue(self.uid)
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir(mode=0o700)
        self.binding = self.root / 'binding.json'
        self.ack = self.root / 'ack.json'
        self.write(self.binding, schwab_position_private_binding_bytes(self.fixture.private_binding()))
        self.write(self.ack, self.fixture.acknowledgement_bytes)
        self.manifest = replace(self.fixture.manifest, acquisition_run_uid=self.uid)
        self.save_bundle()

    @staticmethod
    def write(path, body):
        path.write_bytes(body)
        path.chmod(0o600)

    def enqueue(self, uid):
        with patch('onejournal.refresh_requests.datetime') as clock:
            clock.now.return_value = self.fixture.started_at - timedelta(seconds=1)
            self.queue.request(uid)

    def save_bundle(self, body=None):
        self.write(self.bundle / 'acquisition-manifest.json', external_provider_acquisition_manifest_bytes(self.manifest))
        self.write(self.bundle / 'positions.json', body if body is not None else self.fixture.body)

    def receive(self, **changes):
        args = dict(request_id=self.uid, acquisition_root=self.bundle, acknowledgement=self.ack,
                    position_binding=self.binding, usage_policy=self.fixture.usage_policy,
                    expected_approval_id=fixture_module.APPROVAL_ID,
                    expected_owner_uid=fixture_module.OWNER_UID,
                    expected_owner_epoch_uid=fixture_module.OWNER_EPOCH_UID,
                    evaluated_at=self.fixture.completed_at + timedelta(seconds=1))
        args.update(changes)
        return receive_position_refresh(self.queue, **args)

    def test_claim_receive_restart_and_exact_replay_preserve_evidence(self):
        evidence_before = {p: p.read_bytes() for p in (self.binding, self.ack, *self.bundle.iterdir())}
        with self.assertRaises(ValueError):
            self.receive()  # Cannot bypass the claim.
        self.queue.claim()
        self.assertTrue(self.receive())
        self.assertEqual(self.queue.get(self.uid)['state'], 'captured')
        self.queue = RefreshRequests(self.queue.path, 'schwab')
        self.assertFalse(self.receive())
        self.queue.finish_review(self.uid)
        self.assertFalse(self.receive())  # Replay must not reopen completed review.
        next_uid = str(uuid4())
        self.enqueue(next_uid)
        self.assertFalse(self.receive())  # Old replay must not alter the new job.
        self.assertEqual(self.queue.get(next_uid)['state'], 'queued')
        self.assertEqual(self.queue.get(self.uid)['state'], 'closed')
        self.assertEqual(evidence_before, {p: p.read_bytes() for p in evidence_before})
        with self.queue.connection() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM requests').fetchone()[0], 2)

    def test_wrong_scope_owner_stale_capture_and_account_fail_without_state_change(self):
        self.queue.claim()
        for override in ({'expected_owner_uid': 'another-owner'},
                         {'expected_owner_epoch_uid': 'another-epoch'},
                         {'expected_approval_id': 'another-approval'}, {'request_id': str(uuid4())}):
            with self.subTest(override=override), self.assertRaises(ValueError):
                self.receive(**override)
        original = self.binding.read_bytes()
        self.write(self.binding, schwab_position_private_binding_bytes(
            replace(self.fixture.private_binding(), provider_account_number='WRONG-ACCOUNT')))
        with self.assertRaises(ValueError):
            self.receive()
        self.write(self.binding, original)
        with self.queue.connection() as con:
            con.execute('UPDATE requests SET requested_at=? WHERE id=?', (self.fixture.completed_at.isoformat(), self.uid))
        with self.assertRaisesRegex(ValueError, 'predates'):
            self.receive()
        self.assertEqual(self.queue.get(self.uid)['state'], 'capturing')

    def test_tampering_incomplete_mapping_and_changed_replay_are_rejected(self):
        self.queue.claim()
        self.write(self.bundle / 'positions.json', b'{}')
        with self.assertRaises(ValueError):
            self.receive()
        self.save_bundle()
        self.write(self.binding, schwab_position_private_binding_bytes(replace(self.fixture.private_binding(), mappings=())))
        with self.assertRaises(ValueError):
            self.receive()
        self.write(self.binding, schwab_position_private_binding_bytes(self.fixture.private_binding()))
        self.assertTrue(self.receive())
        document = json.loads(self.fixture.body)
        document['securitiesAccount']['positions'][0]['longQuantity'] = 8
        changed = json.dumps(document).encode()
        self.manifest = replace(self.manifest, requests=(replace(self.fixture.request,
            response_byte_count=len(changed), response_sha256=sha256(changed).hexdigest()),))
        self.save_bundle(changed)
        with self.assertRaises(ValueError):
            self.receive()
        self.assertEqual(self.queue.get(self.uid)['state'], 'captured')

    def test_cli_handoff_once_receive_and_redacted_failure_without_network(self):
        args = ['--request-store', str(self.queue.path)]
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([*args, 'claim']), 0)
            handoff = json.loads(output.getvalue())
            self.assertEqual(handoff['request']['request_id'], self.uid)
            self.assertEqual(handoff['request']['scope'], 'current_positions')
            self.assertFalse(handoff['broker_execution_authorized'])
            output = StringIO()
            with redirect_stdout(output):
                self.assertEqual(main([*args, 'claim']), 0)
            self.assertIsNone(json.loads(output.getvalue())['request'])
            receive = [*args, 'receive', '--request-id', self.uid,
                       '--acquisition-root', str(self.bundle), '--acknowledgement', str(self.ack),
                       '--position-binding', str(self.binding), '--usage-policy', 'synthetic-policy.yaml',
                       '--expected-approval-id', fixture_module.APPROVAL_ID,
                       '--expected-owner-uid', fixture_module.OWNER_UID,
                       '--expected-owner-epoch-uid', fixture_module.OWNER_EPOCH_UID]
            output = StringIO()
            with patch('onejournal.refresh_intake.load_provider_usage_policy', return_value=self.fixture.usage_policy), redirect_stdout(output):
                self.assertEqual(main(receive), 0)
                self.assertEqual(main(receive), 0)
                self.binding.chmod(0o644)
                self.assertEqual(main(receive), 1)
            for private in (str(self.root), fixture_module.PROVIDER_ACCOUNT_NUMBER, fixture_module.PROVIDER_ACCOUNT_HASH, 'AAPL'):
                self.assertNotIn(private, output.getvalue())
            self.assertIn('nothing changed', output.getvalue())
            self.assertEqual(self.queue.get(self.uid)['state'], 'captured')


if __name__ == '__main__':
    unittest.main()
