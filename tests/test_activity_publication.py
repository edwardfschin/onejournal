from contextlib import redirect_stderr
from dataclasses import asdict, replace
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import duckdb

from onejournal.activity_publication import (
    AUTHORITY, REHEARSAL_PREFIX, _append_report, accepted_release,
    load_draft, main, publish,
)
from onejournal.activity_report_preparation import _json_bytes
from onejournal.activity_rehearsal import _proof
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.phase1_reporting_repository import (
    ReportingReleaseAuthorization, calculate_report_release_fingerprint,
    load_reporting_release, persist_reporting_release,
)
from onejournal.mac_access_backup import private_output
from onejournal.mac_journal_backup import file_hash
import test_phase1_reporting_repository as reporting_fixture


class GuardedActivityPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve(); self.db=self.root/'journal.duckdb'
        apply_schema_migrations(self.db,target_version='0028'); self.db.chmod(0o600)
        self.previous=reporting_fixture.Phase1ReportingRepositoryTests()._release()
        with duckdb.connect(str(self.db)) as con:
            persist_reporting_release(con,self.previous)
        self.predecessor=ReportingReleaseAuthorization(self.previous.report_release_uid,
            self.previous.report_release_fingerprint,self.previous.owner_acceptance_uid)
        draft=replace(self.previous,report_release_uid='new-draft',release_status='draft',
            owner_acceptance_uid=None,owner_accepted_at_utc=None,report_release_fingerprint='')
        self.draft=replace(draft,report_release_fingerprint=calculate_report_release_fingerprint(release=draft))
        self.publication=self.root/'publication'; self.publication.mkdir(mode=0o700)
        private_output(self.publication/'prepared-report-draft.json',_json_bytes(asdict(self.draft)))
        self.binding=self.root/'binding.json'; private_output(self.binding,b'{}')
        self.backup=self.root/'backup.json'; private_output(self.backup,b'{}')
        private_output(self.publication/'publication-plan.json',b'{}')
        self.authority=dict(contract_version=AUTHORITY,decision='accepted',
            accepted_scope='bound_report_only_persistence',approval_source='project_owner_explicit_request',
            binding_sha256=file_hash(self.binding),backup_receipt_sha256=file_hash(self.backup),
            publication_plan_sha256=file_hash(self.publication/'publication-plan.json'),
            owner_acceptance_uid='synthetic-new-report-acceptance',
            accepted_at_utc=datetime(2026,10,14,tzinfo=UTC).isoformat(),
            publication_authorized=True,runtime_activation_authorized=False)

    def release(self):
        return accepted_release(self.draft,self.authority,binding_path=self.binding,
            publication_dir=self.publication,backup_receipt_path=self.backup)

    def append(self,release,guard=lambda:None):
        return _append_report(self.db,release,self.predecessor,database_sha256=file_hash(self.db),
            schema_version='0028',input_guard=guard)

    def proof(self):
        with duckdb.connect(str(self.db),read_only=True) as con:
            names=[r[0] for r in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'").fetchall()]
            return _proof(con,names)

    def test_exact_draft_and_new_acceptance_leave_all_financial_values_unchanged(self):
        self.assertEqual(load_draft(self.publication),self.draft)
        result=self.release()
        self.assertEqual(result.items,self.draft.items)
        self.assertEqual(result.omissions,self.draft.omissions)
        self.assertEqual(result.current_result_fingerprint,self.draft.current_result_fingerprint)
        self.assertEqual(result.current_owner_acceptance_uid,self.draft.current_owner_acceptance_uid)
        self.assertEqual(result.realized_owner_acceptance_uid,self.draft.realized_owner_acceptance_uid)
        self.assertNotEqual(result.report_release_uid,self.draft.report_release_uid)

    def test_wrong_or_rehearsal_authority_cannot_become_live_acceptance(self):
        for key,value in (('publication_authorized',False),('runtime_activation_authorized',True),
                          ('binding_sha256','b'*64),('backup_receipt_sha256','b'*64),
                          ('publication_plan_sha256','b'*64),('approval_source','offline_rehearsal_only'),
                          ('owner_acceptance_uid',REHEARSAL_PREFIX+'owner'),
                          ('owner_acceptance_uid',self.draft.realized_owner_acceptance_uid),
                          ('accepted_at_utc','2026-01-01T00:00:00Z')):
            with self.subTest(field=key),self.assertRaises(ValueError):
                accepted_release(self.draft,dict(self.authority,**{key:value}),binding_path=self.binding,
                    publication_dir=self.publication,backup_receipt_path=self.backup)

    def test_atomic_readback_and_exact_replay_keep_previous_state(self):
        release=self.release()
        before=self.proof()
        with patch('socket.socket.connect',side_effect=AssertionError('Network forbidden')):
            self.assertTrue(self.append(release)['created'])
            after=self.proof()
            self.assertTrue(self.append(release)['replayed'])
        self.assertEqual(self.proof(),after)
        with duckdb.connect(str(self.db),read_only=True) as con:
            self.assertEqual(load_reporting_release(con,report_release_uid=self.previous.report_release_uid),self.previous)
            self.assertEqual(load_reporting_release(con,report_release_uid=release.report_release_uid),release)
        changed={n for n in before if before[n]!=after[n]}
        self.assertEqual(changed,{'phase1_reporting_releases','phase1_reporting_release_accounts',
                                  'phase1_reporting_release_realized_items'})

    def test_failure_after_insert_rolls_back_every_relation(self):
        before=self.proof(); checks=0
        def guard():
            nonlocal checks
            checks+=1
            if checks==2:
                raise ValueError('injected after insert')
        with self.assertRaisesRegex(ValueError,'injected'):
            self.append(self.release(),guard)
        self.assertEqual(checks,2)
        self.assertEqual(self.proof(),before)

    def test_bad_hash_wal_and_conflicting_release_fail_without_partial_append(self):
        before=self.proof()
        with self.assertRaisesRegex(ValueError,'changed'):
            _append_report(self.db,self.release(),self.predecessor,database_sha256='b'*64,
                schema_version='0028',input_guard=lambda:None)
        wal=Path(str(self.db)+'.wal'); private_output(wal,b'synthetic pending WAL')
        try:
            with self.assertRaisesRegex(ValueError,'WAL'):
                self.append(self.release())
        finally:
            wal.unlink()
        self.assertEqual(self.proof(),before)
        release=self.release(); self.append(release)
        altered=replace(release,items=(),report_release_fingerprint='')
        altered=replace(altered,report_release_fingerprint=calculate_report_release_fingerprint(release=altered))
        before=self.proof()
        with self.assertRaises(ValueError):
            self.append(altered)
        self.assertEqual(self.proof(),before)

    def test_preparation_receipt_refused_before_any_writer_and_cli_is_redacted(self):
        path=self.root/'preparation.json'; private_output(path,b'{"publication_authorized":false}')
        with (patch('onejournal.activity_publication._inputs',side_effect=AssertionError('No preparation/writer')),
              self.assertRaisesRegex(ValueError,'No explicit')):
            publish(authority_path=path)
        args=['publish']
        for name in ('binding','web-config','package','publication-dir','backup-receipt','backup-image'):
            args.extend(['--'+name,str(self.root)])
        error=StringIO()
        with redirect_stderr(error),patch('onejournal.activity_publication.publish',
            side_effect=AssertionError('Missing authority must not call writer')):
            self.assertEqual(main(args),1)
        self.assertNotIn(str(self.root),error.getvalue())

    def test_publish_entry_point_uses_exact_authority_on_synthetic_target_only(self):
        path=self.root/'authority.json'; private_output(path,_json_bytes(self.authority))
        before_authority=file_hash(path)
        prepared=(SimpleNamespace(journal_db=self.db),
            {'live_state':{'sha256':{'journal':file_hash(self.db)},'schema_version':'0028'}},
            self.draft,self.predecessor,{path:before_authority})
        with (patch('onejournal.activity_publication._inputs',return_value=prepared),
              patch('socket.socket.connect',side_effect=AssertionError('Network forbidden'))):
            result=publish(authority_path=path,binding_path=self.binding,
                publication_dir=self.publication,backup_receipt_path=self.backup)
        self.assertTrue(result['created'])
        self.assertFalse(result['runtime_activation_authorized'])
        self.assertEqual(file_hash(path),before_authority)
        with duckdb.connect(str(self.db),read_only=True) as con:
            self.assertEqual(load_reporting_release(con,report_release_uid=self.release().report_release_uid),self.release())

    def test_authority_revoked_during_readiness_cannot_be_used_from_an_earlier_read(self):
        path=self.root/'authority.json'; private_output(path,_json_bytes(self.authority))
        before=self.proof()
        def prepare(*args):
            path.write_bytes(_json_bytes(dict(self.authority,publication_authorized=False)))
            return (SimpleNamespace(journal_db=self.db),{},self.draft,self.predecessor,{path:file_hash(path)})
        with (patch('onejournal.activity_publication._inputs',side_effect=prepare),
              patch('onejournal.activity_publication._append_report',side_effect=AssertionError('No writer')),
              self.assertRaisesRegex(ValueError,'authority')):
            publish(authority_path=path,binding_path=self.binding,
                publication_dir=self.publication,backup_receipt_path=self.backup)
        self.assertEqual(self.proof(),before)


if __name__=='__main__':
    unittest.main()
