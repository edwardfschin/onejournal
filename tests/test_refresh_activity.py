from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test_external_schwab_lifecycle_acquisition as capture_fixture
import test_schwab_history_revision as history_fixture
from test_snapshot_cutoff_evidence import inputs, CUTOFF
from onejournal.brokers.schwab.account_binding import schwab_account_private_binding_bytes
from onejournal.journal.schwab_evidence_assembly import build_schwab_phase1_evidence_assembly_v3
from onejournal.journal.schwab_history_revision import (
    persist_schwab_history_revision, activate_prior_history_revision,
)
from onejournal.journal.schwab_journal_lifecycle_reconciliation import build_schwab_journal_lifecycle_reconciliation
from onejournal.journal.schwab_snapshot_evidence_repository import persist_schwab_snapshot_evidence
from onejournal.provider_connectors.external_acquisition import (
    EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME, external_provider_acquisition_manifest_bytes,
)
from onejournal.refresh_activity import (
    ConfirmedActivityImport, activity_plan, confirmed_import, _review_delta, main,
)


class ActivityRefreshTests(unittest.TestCase):
    def setUp(self):
        self.request = inputs()
        self.assembly = build_schwab_phase1_evidence_assembly_v3(**self.request)
        self.baseline = ConfirmedActivityImport('synthetic-activation', 'synthetic-revision', self.assembly)
        capture = capture_fixture.ExternalSchwabLifecycleAcquisitionTests()
        self.binding = replace(capture.account_binding(), source_account_id=self.assembly.source_account_id,
                               connection_uid=self.assembly.connection_uid)

    def plan(self, baseline=None, **kwargs):
        return activity_plan(baseline or self.baseline, self.binding,
                             **dict(asof=date(2026, 9, 7), overlap_days=3, **kwargs))

    def window(self, **changes):
        return replace(self.request['lifecycle_windows'][0], window_start_date=date(2026, 9, 4),
                       window_end_date=date(2026, 9, 7), **changes)

    def test_partial_day_overlap_bounded_catchup_and_pinned_identity(self):
        plan = self.plan()
        self.assertEqual(plan['window_start'], '2026-09-04')
        self.assertEqual(plan['window_end'], '2026-09-07')
        self.assertFalse(plan['broker_execution_authorized'])
        smallest = activity_plan(self.baseline, self.binding, asof=CUTOFF.date(), overlap_days=1)
        self.assertEqual(smallest['window_start'], CUTOFF.date().isoformat())
        far = activity_plan(self.baseline, self.binding, asof=date(2026, 12, 1), overlap_days=29)
        self.assertTrue(far['more_windows_pending'])
        self.assertEqual((date.fromisoformat(far['window_end']) - date.fromisoformat(far['window_start'])).days, 29)
        self.assertGreater(date.fromisoformat(far['window_end']), CUTOFF.date())
        self.assertNotEqual(self.plan(replace(self.baseline, activation_uid='rollback-activation'))['plan_sha256'], plan['plan_sha256'])
        for days in (0, 30, True):
            with self.assertRaises(ValueError):
                activity_plan(self.baseline, self.binding, asof=CUTOFF.date(), overlap_days=days)
        with self.assertRaises(ValueError):
            activity_plan(self.baseline, self.binding, asof=date(2026, 9, 5), overlap_days=1)

    def test_identical_overlap_new_partial_day_fill_and_replay(self):
        original = self.window()
        unchanged = _review_delta(self.baseline, original, self.plan())
        self.assertEqual(unchanged['counts']['fills'], dict(new=0, unchanged=1, changed=0))
        self.assertTrue(all(c['new'] == c['changed'] == 0 for c in unchanged['counts'].values()))
        late = inputs(late=True)['lifecycle_windows'][0]
        incoming = replace(late, window_start_date=original.window_start_date, window_end_date=original.window_end_date)
        first = _review_delta(self.baseline, incoming, self.plan())
        self.assertEqual(first, _review_delta(self.baseline, incoming, self.plan()))
        # Two confirming order fills are not two additional transaction fills.
        self.assertEqual(first['counts']['fills'], dict(new=1, unchanged=1, changed=0))
        self.assertEqual(first['counts']['transactions']['new'], 1)
        self.assertEqual(first['counts']['cash']['new'], 1)
        self.assertFalse(first['cursor_advanced'])
        self.assertFalse(first['journal_written'])

    def test_corrections_block_and_absence_never_deletes(self):
        original = self.window()
        changed = replace(original, transaction_rows=({**original.transaction_rows[0], 'fill_price':'101'},))
        result = _review_delta(self.baseline, changed, self.plan())
        self.assertEqual(result['status'], 'review_required')
        self.assertEqual(result['counts']['fills'], dict(new=0, unchanged=0, changed=1))
        bad_pair = replace(original, reconciliation=replace(original.reconciliation, only_order_rows=1))
        self.assertEqual(_review_delta(self.baseline, bad_pair, self.plan())['status'], 'review_required')
        empty = replace(original, transaction_rows=(), order_records=(), transaction_records=(), cash_rows=())
        empty_result = _review_delta(self.baseline, empty, self.plan())
        self.assertTrue(all(c['new'] == c['changed'] == c['unchanged'] == 0 for c in empty_result['counts'].values()))
        for bad in (replace(original, source_account_id='wrong-account'),
                    replace(original, connection_uid='wrong-connection'),
                    replace(original, window_start_date=date(2026, 8, 1)),
                    replace(original, transaction_rows=(original.transaction_rows[0], changed.transaction_rows[0]))):
            with self.assertRaises(ValueError):
                _review_delta(self.baseline, bad, self.plan())

    def test_real_active_import_and_verified_cli_are_read_only(self):
        history = history_fixture.SchwabHistoryRevisionTests()
        history.setUp()
        self.addCleanup(history.doCleanups)
        legacy = persist_schwab_history_revision(history.db_path, history.v2,
                    predecessor_materialization_uid=history.legacy.materialization_uid)
        persist_schwab_snapshot_evidence(history.db_path, self.assembly)
        # Saving newer evidence alone does not advance confirmed coverage.
        with self.assertRaises(ValueError):
            confirmed_import(history.db_path, self.binding)
        current = persist_schwab_history_revision(history.db_path, self.assembly,
            predecessor_materialization_uid=build_schwab_journal_lifecycle_reconciliation(history.v2).source_materialization_uid)
        baseline = confirmed_import(history.db_path, self.binding)
        self.assertEqual(baseline.revision_uid, current.revision_uid)
        plan = self.plan(baseline)

        capture = capture_fixture.ExternalSchwabLifecycleAcquisitionTests()
        with patch.object(capture_fixture, 'CONNECTION_UID', self.binding.connection_uid):
            capture.setUp()
        order = capture.order_body.replace(b'2026-08-31', b'2026-09-04')
        transaction = capture.transaction_body.replace(b'2026-08-31', b'2026-09-04')
        requested = datetime(2026, 9, 7, 14, tzinfo=UTC)
        requests = []
        for old, body in zip(capture.manifest.requests, (order, transaction)):
            query = tuple(replace(q, value=('2026-09-04T00:00:00.000Z' if q.name in ('fromEnteredTime','startDate')
                else '2026-09-07T23:59:59.999Z' if q.name in ('toEnteredTime','endDate') else q.value)) for q in old.query)
            requests.append(replace(old, query=query, window_start_date=date(2026,9,4), window_end_date=date(2026,9,7),
                approved_market_date=date(2026,9,7), requested_at_utc=requested, received_at_utc=requested+timedelta(seconds=1),
                response_byte_count=len(body), response_sha256=sha256(body).hexdigest()))
        manifest = replace(capture.manifest, requests=tuple(requests), completed_at_utc=requested+timedelta(seconds=2))
        root = Path(history.tmp.name)
        bundle = root / 'bundle'
        bundle.mkdir(mode=0o700)
        def write(path, body):
            path.write_bytes(body)
            path.chmod(0o600)
        manifest_path = bundle / EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME
        write(manifest_path, external_provider_acquisition_manifest_bytes(manifest))
        write(bundle / 'orders.json', order)
        write(bundle / 'transactions.json', transaction)
        write(root / 'binding.json', schwab_account_private_binding_bytes(self.binding))
        write(root / 'ack.json', capture.acknowledgement_bytes)
        common = ['--db',str(history.db_path),'--account-binding',str(root/'binding.json'),
                  '--asof','2026-09-07','--overlap-days','3']
        review = ['review','--expected-plan-sha256',plan['plan_sha256'],
                  '--acquisition-root',str(bundle),'--acknowledgement',str(root/'ack.json'),
                  '--usage-policy','synthetic-policy.yaml','--expected-run-uid',capture_fixture.RUN_UID,
                  '--expected-approval-id',capture_fixture.APPROVAL_ID,
                  '--expected-owner-uid',capture_fixture.OWNER_UID,
                  '--expected-owner-epoch-uid',capture_fixture.OWNER_EPOCH_UID]
        before = history.db_path.read_bytes()
        def run(args):
            stream = StringIO()
            with patch('onejournal.refresh_activity.load_provider_usage_policy', return_value=capture.usage_policy), \
                 patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')), redirect_stdout(stream):
                code = main(common + args)
            self.assertNotIn(capture_fixture.PROVIDER_ACCOUNT_NUMBER, stream.getvalue())
            self.assertNotIn(self.binding.source_account_id, stream.getvalue())
            return code, stream.getvalue()
        code, output = run(['plan'])
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output), plan)
        code, output = run(review)
        self.assertEqual(code, 0, output)
        self.assertEqual(json.loads(output)['counts']['fills']['new'], 1)
        self.assertEqual(run(review), (code, output))
        # Wrong authority, wrong account and tampered bytes fail without exposing values.
        wrong_owner = review.copy()
        wrong_owner[wrong_owner.index('--expected-owner-uid')+1] = 'wrong-owner'
        self.assertEqual(run(wrong_owner)[0], 1)
        write(root/'binding.json', schwab_account_private_binding_bytes(replace(self.binding,provider_account_number='wrong-account')))
        self.assertEqual(run(review)[0], 1)
        write(root/'binding.json', schwab_account_private_binding_bytes(self.binding))
        write(bundle/'transactions.json', transaction+b' ')
        self.assertEqual(run(review)[0], 1)
        write(bundle/'transactions.json', transaction)
        self.assertEqual(history.db_path.read_bytes(), before)
        # Rolling away and back changes activation identity, even for same assembly.
        activate_prior_history_revision(history.db_path, revision_uid=legacy.revision_uid)
        self.assertEqual(run(review)[0], 1)
        activate_prior_history_revision(history.db_path, revision_uid=current.revision_uid)
        self.assertEqual(run(review)[0], 1)


if __name__ == '__main__':
    unittest.main()
