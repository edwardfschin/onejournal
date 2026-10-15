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
    ConfirmedActivityImport, activity_plan, confirmed_import, _review_delta,
    _prior_order_variants, _review_order_corrections, main,
)
from onejournal.activity_rehearsal import disposable_journal, prepare_copy
from onejournal.journal.activity_refresh_repository import append_activity_copy
import duckdb


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

    def test_accepted_prior_order_status_variants_do_not_hide_new_corrections(self):
        original = self.window()
        order_family = next(f for f in self.assembly.families if f.family == 'orders')
        prior_variant = {**order_family.records[0], 'status': 'WORKING'}
        families = tuple(replace(f, records=(*f.records, prior_variant)) if f.family == 'orders' else f
                         for f in self.assembly.families)
        baseline = replace(self.baseline, assembly=replace(self.assembly, families=families))
        known = _review_delta(baseline, original, self.plan(baseline))
        self.assertEqual(known['status'], 'candidate_only')
        self.assertEqual(known['counts']['orders'], dict(new=0, unchanged=1, changed=0))
        changed = replace(original, order_records=({**original.order_records[0], 'status': 'CANCELED'},))
        correction = _review_delta(baseline, changed, self.plan(baseline))
        self.assertEqual(correction['status'], 'review_required')
        self.assertEqual(correction['counts']['orders'], dict(new=0, unchanged=0, changed=1))
        with self.assertRaisesRegex(ValueError, 'Conflicting observations'):
            _review_delta(baseline, replace(original, order_records=(*original.order_records, *changed.order_records)),
                          self.plan(baseline))

    def test_unfilled_order_replacement_is_exactly_reviewed_and_other_changes_hold(self):
        original = self.window()
        pending = {**original.order_records[0], 'order_uid': 'synthetic-pending-order',
                   'source_order_id': 'synthetic-pending-order', 'status': 'PENDING_ACTIVATION',
                   'requested_quantity': '2', 'remaining_quantity': '2',
                   'filled_quantity': '0', 'closed_at_utc': '2026-09-05T10:00:00+00:00'}
        successor = {**pending, 'status': 'REPLACED', 'remaining_quantity': '0',
                     'closed_at_utc': '2026-09-06T10:00:00+00:00'}
        families = tuple(replace(f, records=(*f.records, pending)) if f.family == 'orders' else f
                         for f in self.assembly.families)
        baseline = replace(self.baseline, assembly=replace(self.assembly, families=families))
        captured = replace(original, order_records=(*original.order_records, successor))
        accepted = _review_delta(baseline, captured, self.plan(baseline))
        self.assertEqual(accepted['status'], 'candidate_only')
        self.assertEqual(accepted['counts']['orders']['changed'], 1)
        self.assertEqual(accepted['source_reviewed_order_correction_count'], 1)
        prior = _prior_order_variants((pending,))
        current = {successor['order_uid']: next(iter(_prior_order_variants((successor,))[successor['order_uid']]))}
        reviews = _review_order_corrections(prior, current, original.transaction_rows)
        self.assertEqual(len(reviews), 1)
        self.assertEqual(reviews[successor['order_uid']]['reason_code'], 'unfilled_pending_order_replaced')
        unset_close = {**pending, 'closed_at_utc': ''}
        self.assertEqual(len(_review_order_corrections(
            _prior_order_variants((unset_close,)), current, original.transaction_rows)), 1)
        for changed in ({**successor, 'requested_quantity': '3'},
                        {**successor, 'filled_quantity': '1'},
                        {**successor, 'status': 'FILLED'},
                        {**successor, 'closed_at_utc': '2026-09-04T10:00:00+00:00'}):
            held = _review_delta(baseline, replace(original, order_records=(*original.order_records, changed)),
                                 self.plan(baseline))
            self.assertEqual(held['status'], 'review_required')
            self.assertEqual(held['source_reviewed_order_correction_count'], 0)
        linked_fill = {**original.transaction_rows[0], 'source_order_id': successor['source_order_id']}
        self.assertFalse(_review_order_corrections(prior, current, (linked_fill,)))

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
        document = json.loads(transaction)
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
        # The website's verified staging area must feed the existing copy-only
        # financial path without changing the source journal.
        from onejournal.brokers.schwab.position_binding import (
            SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA, SchwabPositionPrivateBinding,
            schwab_position_private_binding_bytes,
        )
        from onejournal.manual_capture_upload import ManualCaptureIntake
        from onejournal.refresh_capture_authorization import AUTHORIZATION_VERSION
        from onejournal.staged_activity_rehearsal import rehearse_staged_activity
        position_binding = SchwabPositionPrivateBinding(
            SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA, self.binding.connection_uid,
            self.binding.source_account_id, self.binding.provider_account_hash,
            self.binding.provider_account_number, (),
        )
        write(root / 'position-binding.json', schwab_position_private_binding_bytes(position_binding))
        digest = sha256(manifest_path.read_bytes()).hexdigest()
        authorization = root / 'manual-authorization.json'
        write(authorization, json.dumps(dict(
            contract_version=AUTHORIZATION_VERSION, capture_scope='activity',
            manifest_sha256=digest, acquisition_run_uid=manifest.acquisition_run_uid,
            acquisition_approval_id=capture_fixture.APPROVAL_ID,
            owner_uid=capture_fixture.OWNER_UID,
            owner_epoch_uid=capture_fixture.OWNER_EPOCH_UID,
        )).encode())
        staging = root / 'manual-staging'
        staging.mkdir(mode=0o700)
        intake = ManualCaptureIntake(
            authorization_path=authorization, acknowledgement_path=root / 'ack.json',
            account_binding_path=root / 'position-binding.json',
            usage_policy=capture.usage_policy, staging_root=staging,
            project_root=Path(__file__).resolve().parents[1],
        )
        before_stage = history.db_path.read_bytes()
        with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
            self.assertEqual(intake.stage({p.name: p.read_bytes() for p in bundle.iterdir()})['scope'], 'activity')
            staged_result = rehearse_staged_activity(
                intake=intake, manifest_sha256=digest, source_db=history.db_path,
                asof=date(2026, 9, 7), overlap_days=3, account_alias='Primary',
            )
        self.assertEqual(staged_result['status'], 'copy_financial_preview_complete')
        self.assertGreater(staged_result['new_records'], 0)
        self.assertFalse(staged_result['live_journal_written'])
        self.assertTrue(staged_result['disposable_copy_appended'])
        self.assertFalse(staged_result['financial_publication_authorized'])
        self.assertEqual(history.db_path.read_bytes(), before_stage)
        with patch('onejournal.staged_activity_rehearsal.review_activity',
                   return_value={'status': 'review_required'}), \
             patch('onejournal.staged_activity_rehearsal.disposable_journal',
                   side_effect=AssertionError('Held evidence must not reach a writer')):
            held = rehearse_staged_activity(
                intake=intake, manifest_sha256=digest, source_db=history.db_path,
                asof=date(2026, 9, 7), overlap_days=3, account_alias='Primary',
            )
        self.assertEqual(held['status'], 'held_for_source_review')
        self.assertFalse(held['disposable_copy_appended'])
        self.assertFalse(held['financial_publication_authorized'])
        approved = authorization.read_bytes()
        write(authorization, approved.replace(digest.encode(), b'0' * 64))
        with self.assertRaises(ValueError):
            rehearse_staged_activity(
                intake=intake, manifest_sha256=digest, source_db=history.db_path,
                asof=date(2026, 9, 7), overlap_days=3, account_alias='Primary',
            )
        write(authorization, approved)
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
        rehearsal = ['rehearse', *review[1:]]
        rehearsal_code, rehearsal_output = run(rehearsal)
        self.assertEqual(rehearsal_code, 0, rehearsal_output)
        self.assertTrue(json.loads(rehearsal_output)['original_unchanged'])
        kwargs = dict(binding=self.binding, asof=date(2026,9,7), overlap_days=3,
            expected_plan_sha256=plan['plan_sha256'], acquisition_root=bundle,
            acknowledgement=root/'ack.json', usage_policy=capture.usage_policy,
            expected_run_uid=capture_fixture.RUN_UID, expected_approval_id=capture_fixture.APPROVAL_ID,
            expected_owner_uid=capture_fixture.OWNER_UID, expected_owner_epoch_uid=capture_fixture.OWNER_EPOCH_UID,
            evaluated_at=datetime(2026,9,8,15,tzinfo=UTC))
        # The writer cannot be pointed at the original (even this synthetic one).
        with self.assertRaises(ValueError):
            append_activity_copy(db=history.db_path, **kwargs)
        with disposable_journal(history.db_path) as target:
            prepare_copy(target)
            # An empty new ledger cannot reinterpret old accepted observations.
            with patch('onejournal.refresh_activity._index',side_effect=AssertionError('No increment to compare')):
                self.assertEqual(confirmed_import(target,self.binding).cutoff,CUTOFF)
            from onejournal.refresh_activity import _confirmed_import
            calls = 0
            def fail_readback(con, binding):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise ValueError('synthetic interrupted write')
                return _confirmed_import(con, binding)
            with patch('onejournal.refresh_activity._confirmed_import', side_effect=fail_readback):
                with self.assertRaisesRegex(ValueError, 'interrupted'):
                    append_activity_copy(db=target, **kwargs)
            with duckdb.connect(str(target), read_only=True) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM incremental_activity_imports').fetchone()[0], 0)
            self.assertEqual(confirmed_import(target, self.binding).cutoff, CUTOFF)
            with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
                saved = append_activity_copy(db=target, **kwargs)
                self.assertTrue(saved['created'])
                replay = append_activity_copy(db=target, **kwargs)
                self.assertTrue(replay['replayed'])
                self.assertEqual(saved['import_uid'], replay['import_uid'])
            latest = confirmed_import(target, self.binding)
            self.assertEqual(latest.cutoff, requested)  # NOT requested date's future midnight.
            self.assertEqual(len(latest.appended_records['fills']), 1)
            from onejournal.activity_financial_preview import load_activity_financial_preview, rehearse_financial_preview
            with patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')):
                financial = load_activity_financial_preview(target,self.binding,
                    expected_checkpoint_uid=saved['import_uid'],account_alias='Primary')
                self.assertEqual(len(financial.executions),2)
                financial_result = rehearse_financial_preview(target,self.binding,
                    expected_checkpoint_uid=saved['import_uid'],account_alias='Primary')
                self.assertEqual(financial_result['status'],'offline_financial_rehearsal_passed')
                self.assertFalse(financial_result['financial_publication_authorized'])
                from onejournal.activity_financial_preview import main as financial_main
                output = StringIO()
                with redirect_stdout(output):
                    code = financial_main(['--db',str(target),'--account-binding',str(root/'binding.json'),
                        '--expected-checkpoint-uid',saved['import_uid'],'--account-alias','Primary'])
                self.assertEqual(code,0,output.getvalue())
                self.assertNotIn(self.binding.source_account_id,output.getvalue())
                self.assertNotIn(self.binding.provider_account_number,output.getvalue())
            from onejournal.journal.activity_refresh_repository import activity_recovery_digests
            from onejournal.mac_evidence_audit_backup import source_digests
            from onejournal.activity_report_preparation import prepare_activity_release,verify_preparation,rehearse_recovery
            from onejournal.journal.phase1_reporting_repository import load_reporting_release_authorization
            with duckdb.connect(str(target),read_only=True) as con:
                required_activity = activity_recovery_digests(con)
            self.assertEqual(required_activity,{sha256(manifest_path.read_bytes()).hexdigest(),
                sha256(order).hexdigest(),sha256(transaction).hexdigest(),
                sha256(capture.acknowledgement_bytes).hexdigest(),sha256(schwab_account_private_binding_bytes(self.binding)).hexdigest()})
            self.assertTrue(required_activity.issubset(source_digests(target)))
            package = root/'prepared-report'
            raw_recovery = root/'source-evidence'
            raw_recovery.mkdir(mode=0o700)
            nested = raw_recovery
            for name in ('provider','window','bundle'):
                nested = nested/name
                nested.mkdir(mode=0o700)
            for name,body in ((EXTERNAL_PROVIDER_ACQUISITION_MANIFEST_FILENAME,manifest_path.read_bytes()),
                              ('orders.json',order),('transactions.json',transaction),
                              ('acknowledgement.json',capture.acknowledgement_bytes),
                              ('account-binding.json',schwab_account_private_binding_bytes(self.binding))):
                write(nested/name,body)
            preparation = dict(source_db=target,account_binding=root/'binding.json',raw_root=raw_recovery,
                expected_checkpoint_uid=saved['import_uid'],account_alias='Primary',output_dir=package)
            snapshot_before = target.read_bytes()
            # The legacy fixture declares placeholder raw hashes. This mock
            # limits only its baseline file selection; real-journal recovery
            # separately proves the complete legacy + incremental allowlist.
            with patch('onejournal.activity_report_preparation.source_digests',return_value=required_activity), \
                 patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
                result = prepare_activity_release(**preparation)
                self.assertFalse(result['publication_authorized'])
                document = verify_preparation(package)
                self.assertIsNone(document['owner_acceptance'])
                self.assertEqual(document['release_status'],'prepared_pending_owner_acceptance')
                self.assertTrue(rehearse_recovery(package))
                self.assertFalse((package/'report-release-authorization.json').exists())
                with self.assertRaises(ValueError):
                    load_reporting_release_authorization(package/'manifest.json')
                old_manifest = (package/'manifest.json').read_bytes()
                with self.assertRaises(ValueError):
                    prepare_activity_release(**preparation)
                self.assertEqual((package/'manifest.json').read_bytes(),old_manifest)
                with self.assertRaisesRegex(ValueError,'checkpoint'):
                    prepare_activity_release(**dict(preparation,expected_checkpoint_uid='stale',output_dir=root/'stale-package'))
                self.assertFalse((root/'stale-package').exists())
                report_before = (package/'report.json').read_bytes()
                write(package/'report.json',report_before+b' ')
                with self.assertRaisesRegex(ValueError,'checksum'):
                    verify_preparation(package)
                write(package/'report.json',report_before)
                evidence_file = next((package/'evidence').rglob('orders.json'))
                evidence_before = evidence_file.read_bytes()
                evidence_file.unlink()  # Disposable synthetic package only.
                with self.assertRaisesRegex(ValueError,'missing'):
                    verify_preparation(package)
                write(evidence_file,evidence_before)
                self.assertEqual(verify_preparation(package),document)
            self.assertEqual(target.read_bytes(),snapshot_before)
            with self.assertRaisesRegex(ValueError,'checkpoint'):
                load_activity_financial_preview(target,self.binding,expected_checkpoint_uid='stale',account_alias='Primary')
            # Same source identities, later confirmed coverage: no duplicated records.
            second_plan = activity_plan(latest, self.binding, asof=date(2026,9,8), overlap_days=5)
            later_requests = tuple(replace(r, window_end_date=date(2026,9,8),
                approved_market_date=date(2026,9,8), requested_at_utc=r.requested_at_utc+timedelta(days=1),
                received_at_utc=r.received_at_utc+timedelta(days=1),
                query=tuple(replace(q,value='2026-09-03T00:00:00.000Z') if q.name in ('startDate','fromEnteredTime')
                            else replace(q,value='2026-09-08T23:59:59.999Z') if q.name in ('endDate','toEnteredTime')
                            else q for q in r.query), window_start_date=date(2026,9,3)) for r in requests)
            later_manifest = replace(manifest, acquisition_run_uid='synthetic-second-increment',
                requests=later_requests, completed_at_utc=manifest.completed_at_utc+timedelta(days=1))
            write(manifest_path, external_provider_acquisition_manifest_bytes(later_manifest))
            next_args = dict(kwargs, asof=date(2026,9,8), overlap_days=5,
                expected_run_uid='synthetic-second-increment')
            with self.assertRaises(ValueError):  # stale predecessor cannot advance
                append_activity_copy(db=target, **next_args)
            # A new capture with a correction must not consume its run or checkpoint.
            altered = transaction.replace(b'5.25', b'5.26')
            write(bundle/'transactions.json', altered)
            corrected = (later_requests[0], replace(later_requests[1],
                response_byte_count=len(altered), response_sha256=sha256(altered).hexdigest()))
            write(manifest_path, external_provider_acquisition_manifest_bytes(replace(later_manifest,requests=corrected)))
            with self.assertRaisesRegex(ValueError, 'Unresolved'):
                append_activity_copy(db=target, **dict(next_args,expected_plan_sha256=second_plan['plan_sha256']))
            self.assertEqual(confirmed_import(target,self.binding).cutoff, requested)
            write(bundle/'transactions.json', transaction)
            write(manifest_path, external_provider_acquisition_manifest_bytes(later_manifest))
            second = append_activity_copy(db=target, **dict(next_args,expected_plan_sha256=second_plan['plan_sha256']))
            self.assertEqual(second['new_records'], 0)
            self.assertEqual(confirmed_import(target,self.binding).cutoff, requested+timedelta(days=1))
            write(manifest_path, external_provider_acquisition_manifest_bytes(manifest))
            self.assertTrue(append_activity_copy(db=target, **kwargs)['replayed'])
            # Changed content for a recorded run is rejected without overwrite.
            altered = transaction.replace(b'5.25', b'5.26')
            write(bundle/'transactions.json', altered)
            changed_requests = (requests[0], replace(requests[1], response_byte_count=len(altered), response_sha256=sha256(altered).hexdigest()))
            write(manifest_path, external_provider_acquisition_manifest_bytes(replace(manifest,requests=changed_requests)))
            with self.assertRaises(ValueError):
                append_activity_copy(db=target, **kwargs)
            write(bundle/'transactions.json', transaction)
            write(manifest_path, external_provider_acquisition_manifest_bytes(manifest))
            with duckdb.connect(str(target), read_only=True) as con:
                self.assertEqual(con.execute('SELECT count(*) FROM incremental_activity_imports').fetchone()[0], 2)
            activate_prior_history_revision(target, revision_uid=legacy.revision_uid)
            activate_prior_history_revision(target, revision_uid=current.revision_uid)
            with self.assertRaisesRegex(ValueError, 'lineage'):
                confirmed_import(target, self.binding)
            with duckdb.connect(str(target)) as con:
                con.execute("UPDATE incremental_activity_imports SET artifact_json=artifact_json || ' ' WHERE import_sequence=1")
            with duckdb.connect(str(target),read_only=True) as con:
                with self.assertRaisesRegex(ValueError,'artifact'):
                    activity_recovery_digests(con)
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
