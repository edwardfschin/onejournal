from dataclasses import replace
from datetime import UTC,datetime
from contextlib import redirect_stderr
from io import StringIO
import unittest
from unittest.mock import patch

import duckdb

from onejournal.activity_publication_preparation import (
    ACCEPTANCE,validate_acceptance,build_report_draft,rehearse_report_draft,prepare_publication,main,
    selected_predecessor,
)
from onejournal.journal.phase1_reporting_repository import persist_reporting_release,load_reporting_release
from onejournal.mac_journal_backup import file_hash
import test_activity_financial_preview as financial_fixture
import test_phase1_reporting_repository as reporting_fixture


class ActivityPublicationPreparationTests(unittest.TestCase):
    def setUp(self):
        financial=financial_fixture.ActivityFinancialPreviewTests(); financial.setUp()
        self.preview=financial.preview()
        self.at=datetime(2026,10,14,tzinfo=UTC)
        self.manifest={'package_fingerprint':'a'*64}
        self.acceptance=dict(contract_version=ACCEPTANCE,decision='accepted',
            accepted_scope='bounded_realized_activity_draft',approval_source='project_owner_explicit_request',
            acceptance_uid='synthetic-acceptance',recorded_at_utc=self.at.isoformat(),
            package_fingerprint='a'*64,result_fingerprint=self.preview.result_fingerprint,
            reportable_count=len(self.preview.items),withheld_count=len(self.preview.omissions),publication_authorized=False)
        repository=reporting_fixture.Phase1ReportingRepositoryTests(); repository.setUp()
        self.addCleanup(repository.doCleanups)
        self.path=repository.path.resolve(); self.path.chmod(0o600)
        previous=repository._release()
        self.predecessor=replace(previous,accounts=self.preview.accounts,
                                 items=tuple(replace(i,source_account_id=self.preview.accounts[0].source_account_id) for i in previous.items),
                                 report_release_fingerprint='')
        from onejournal.journal.phase1_reporting_repository import calculate_report_release_fingerprint
        self.predecessor=replace(self.predecessor,report_release_fingerprint=calculate_report_release_fingerprint(release=self.predecessor))
        with duckdb.connect(str(self.path)) as con:
            persist_reporting_release(con,self.predecessor)

    def draft(self):
        return build_report_draft(self.preview,self.predecessor,{'revision_uid':'synthetic-current-history'},self.acceptance,self.at)

    def test_acceptance_is_exact_and_cannot_grant_publication(self):
        self.assertEqual(validate_acceptance(self.acceptance,self.manifest,self.preview),self.at)
        for field,value in (('package_fingerprint','b'*64),('result_fingerprint','b'*64),
                            ('reportable_count',2),('withheld_count',1),('publication_authorized',True),
                            ('recorded_at_utc','2026-01-01T00:00:00Z'),('approval_source','broker_file')):
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_acceptance(dict(self.acceptance,**{field:value}),self.manifest,self.preview)

    def test_report_draft_preserves_current_authority_and_records_realized_acceptance(self):
        release=self.draft()
        self.assertEqual(release.current_result_fingerprint,self.predecessor.current_result_fingerprint)
        self.assertEqual(release.current_owner_acceptance_uid,self.predecessor.current_owner_acceptance_uid)
        self.assertEqual(release.realized_result_fingerprint,self.preview.result_fingerprint)
        self.assertEqual(release.realized_owner_acceptance_uid,self.acceptance['acceptance_uid'])
        self.assertEqual(release.release_status,'draft')
        self.assertIsNone(release.owner_acceptance_uid)
        self.assertEqual(release.items,self.preview.items)
        with self.assertRaisesRegex(ValueError,'account scope'):
            build_report_draft(replace(self.preview,accounts=()),self.predecessor,{},self.acceptance,self.at)

    def test_storage_is_copy_only_idempotent_and_not_runtime_authorized(self):
        before=file_hash(self.path)
        with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            result=rehearse_report_draft(self.path,self.draft())
        self.assertTrue(result['identical_replay_verified'])
        self.assertTrue(result['runtime_authorization_refused'])
        self.assertEqual(file_hash(self.path),before)
        with duckdb.connect(str(self.path),read_only=True) as con:
            self.assertEqual(load_reporting_release(con,report_release_uid=self.predecessor.report_release_uid),self.predecessor)
            self.assertEqual(con.execute('SELECT COUNT(*) FROM phase1_reporting_releases').fetchone()[0],1)
        with self.assertRaisesRegex(ValueError,'unpublished'):
            rehearse_report_draft(self.path,self.predecessor)

    def test_existing_output_and_live_write_flag_are_refused(self):
        with self.assertRaisesRegex(ValueError,'new absolute'):
            prepare_publication(package=self.path.parent,acceptance_path=self.path,
                recovery_receipt_path=self.path,output_dir=self.path.parent)
        with redirect_stderr(StringIO()),self.assertRaises(SystemExit) as stopped:
            main(['--persist'])
        self.assertEqual(stopped.exception.code,2)

    def test_explicit_active_predecessor_preserves_newer_current_without_changing_realized_acceptance(self):
        from onejournal.mac_access_backup import private_output
        from onejournal.journal.phase1_reporting_persistence_operator import report_authorization_document
        from onejournal.journal.phase1_reporting_repository import calculate_report_release_fingerprint
        from onejournal.activity_report_preparation import _json_bytes
        current=replace(self.predecessor,report_release_uid='synthetic-active-report',
            current_valuation_run_uid='synthetic-newer-valuation',current_result_fingerprint='c'*64,
            current_owner_acceptance_uid='synthetic-newer-current-acceptance',
            owner_acceptance_uid='synthetic-newer-report-acceptance',report_release_fingerprint='')
        current=replace(current,report_release_fingerprint=calculate_report_release_fingerprint(release=current))
        with duckdb.connect(str(self.path)) as con:
            persist_reporting_release(con,current)
        old_path=self.path.parent/'old.json'; active_path=self.path.parent/'active.json'
        private_output(old_path,_json_bytes(report_authorization_document(self.predecessor)))
        private_output(active_path,_json_bytes(report_authorization_document(current)))
        before=file_hash(self.path); old_bytes=old_path.read_bytes()
        self.assertEqual(selected_predecessor(self.path,old_path)[1],self.predecessor)
        authority,selected=selected_predecessor(self.path,old_path,active_path)
        self.assertEqual(selected,current)
        rebuilt=build_report_draft(self.preview,selected,{'revision_uid':'synthetic-current-history'},self.acceptance,self.at)
        self.assertEqual(rebuilt.current_result_fingerprint,current.current_result_fingerprint)
        self.assertEqual(rebuilt.current_valuation_run_uid,current.current_valuation_run_uid)
        self.assertEqual(rebuilt.current_owner_acceptance_uid,current.current_owner_acceptance_uid)
        self.assertEqual(rebuilt.items,self.draft().items)
        self.assertEqual(rebuilt.omissions,self.draft().omissions)
        self.assertEqual(rebuilt.realized_owner_acceptance_uid,self.acceptance['acceptance_uid'])
        self.assertEqual(file_hash(self.path),before)
        self.assertEqual(old_path.read_bytes(),old_bytes)


if __name__=='__main__':
    unittest.main()
