import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onejournal.activity_live_binding import (
    CONTRACT,verify_bound_target,compatible_report_columns,backup_bound_target,target_state,
    verify_publication_readiness,PLAN,
)
from onejournal.mac_access_backup import private_output
from onejournal.mac_journal_backup import file_hash


class ActivityLiveBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.binding=self.root/'binding.json'
        self.state=dict(sha256={'journal':'a'*64},relation_count=5)
        self.receipt=dict(contract_version=CONTRACT,live_target_bound=True,live_state=self.state,
                          publication_authorized=False,runtime_activation_authorized=False)
        private_output(self.binding,json.dumps(self.receipt).encode())

    def test_binding_refuses_state_drift_and_publication_authority(self):
        with patch('onejournal.activity_live_binding.target_state',return_value=self.state):
            self.assertEqual(verify_bound_target(self.binding,self.root/'config.json',self.root),self.receipt)
        with patch('onejournal.activity_live_binding.target_state',return_value={'changed':True}),self.assertRaises(ValueError):
            verify_bound_target(self.binding,self.root/'config.json',self.root)
        altered=self.root/'altered.json'
        private_output(altered,json.dumps(dict(self.receipt,publication_authorized=True)).encode())
        with patch('onejournal.activity_live_binding.target_state',return_value=self.state),self.assertRaises(ValueError):
            verify_bound_target(altered,self.root/'config.json',self.root)

    def test_report_schema_precision_is_exact_not_just_version_number(self):
        columns=[['main','phase1_reporting_release_realized_items','realized_pnl',10,'DECIMAL(38,27)','NO',None]]
        compatible_report_columns({'columns':columns},{'columns':columns})
        changed=[[*columns[0][:4],'DECIMAL(38,10)',*columns[0][5:]]]
        with self.assertRaisesRegex(ValueError,'precision'):
            compatible_report_columns({'columns':changed},{'columns':columns})

    def test_read_only_state_hashes_native_migration_timestamps_without_conversion(self):
        from scripts.journal.init_journal_db import init_schema
        from onejournal.mac_journal_backup import file_hash
        db=self.root/'journal.duckdb'; init_schema(db); db.chmod(0o600)
        for name in ('broker.json','report.json'):
            private_output(self.root/name,b'{}')
        config=self.root/'config.json'
        private_output(config,json.dumps(dict(contract_version='onejournal.local-web.v1',
            journal_db_path=str(db),broker_current_authorization=str(self.root/'broker.json'),
            reporting_authorization=str(self.root/'report.json'))).encode())
        before=file_hash(db)
        state=target_state(config,Path(__file__).resolve().parents[1])
        self.assertEqual(len(state['migration_ledger_sha256']),64)
        self.assertEqual(target_state(config,Path(__file__).resolve().parents[1]),state)
        self.assertEqual(file_hash(db),before)

    def test_backup_receipt_requires_unchanged_bound_target_and_keeps_verified_image_on_drift(self):
        image=self.root/'image.dmg'; image.write_bytes(b'synthetic encrypted image')
        kwargs=dict(binding_path=self.binding,config_path=self.root/'config.json',project_root=self.root,
                    destination=image,password='synthetic-long-password',receipt_path=self.root/'backup.json')
        with patch('onejournal.activity_live_binding.target_state',return_value=self.state), \
             patch('onejournal.activity_live_binding.create_backup',return_value=5):
            result=backup_bound_target(**kwargs)
        self.assertFalse(result['publication_authorized'])
        self.assertEqual(result['live_journal_sha256'],'a'*64)
        with patch('onejournal.activity_live_binding.target_state',side_effect=[self.state,{'changed':True}]), \
             patch('onejournal.activity_live_binding.create_backup',return_value=5),self.assertRaises(ValueError):
            backup_bound_target(**dict(kwargs,receipt_path=self.root/'stale-backup.json'))
        self.assertTrue(image.exists())
        self.assertFalse((self.root/'stale-backup.json').exists())


class PublicationReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        self.package=self.root/'package'; self.package.mkdir(mode=0o700)
        self.publication=self.root/'publication'; self.publication.mkdir(mode=0o700)
        private_output(self.package/'journal.duckdb',b'synthetic journal')
        self.manifest=dict(package_fingerprint='p'*64,result_fingerprint='r'*64,
            checkpoint_uid='checkpoint',sha256={'journal.duckdb':file_hash(self.package/'journal.duckdb')})
        private_output(self.package/'manifest.json',json.dumps(self.manifest).encode())
        for name,document in (
            ('acceptance.json',{'publication_authorized':False}),
            ('recovery-receipt.json',{'status':'encrypted_draft_recovery_verified'}),
            ('prepared-report-draft.json',dict(release_status='draft',owner_acceptance_uid=None,
                                             owner_accepted_at_utc=None)),
        ):
            private_output(self.publication/name,json.dumps(document).encode())
        self.plan=dict(contract_version=PLAN,financial_result_owner_accepted=True,
            publication_authorized=False,runtime_activation_authorized=False,
            package_fingerprint=self.manifest['package_fingerprint'],
            result_fingerprint=self.manifest['result_fingerprint'],checkpoint_uid='checkpoint',
            snapshot_sha256=self.manifest['sha256']['journal.duckdb'],
            report_release_fingerprint='f'*64,reportable_count=2,withheld_count=1,
            current_valuation_mode='retain_exact_predecessor_no_refresh',
            sha256={p.name:file_hash(p) for p in self.publication.iterdir()})
        private_output(self.publication/'publication-plan.json',json.dumps(self.plan).encode())
        self.state=dict(sha256={'journal':'a'*64},relation_count=5,schema_version='0028')
        self.binding=dict(contract_version=CONTRACT,live_target_bound=True,live_state=self.state,
            publication_authorized=False,runtime_activation_authorized=False,
            publication_plan_sha256=file_hash(self.publication/'publication-plan.json'),
            **{k:self.plan[k] for k in ('package_fingerprint','result_fingerprint',
                'report_release_fingerprint','reportable_count','withheld_count')})
        private_output(self.root/'binding.json',json.dumps(self.binding).encode())
        private_output(self.root/'image.dmg',b'synthetic encrypted image')
        self.backup=dict(status='bound_live_journal_backup_verified',
            binding_sha256=file_hash(self.root/'binding.json'),live_journal_sha256='a'*64,
            image_sha256=file_hash(self.root/'image.dmg'),relation_count=5,
            publication_authorized=False,runtime_activation_authorized=False)
        private_output(self.root/'backup.json',json.dumps(self.backup).encode())
        self.kwargs=dict(binding_path=self.root/'binding.json',config_path=self.root/'config.json',
            project_root=self.root,package=self.package,publication_dir=self.publication,
            backup_receipt_path=self.root/'backup.json',backup_image=self.root/'image.dmg')
        self.target_patch=patch('onejournal.activity_live_binding.target_state',return_value=self.state)
        self.target=self.target_patch.start(); self.addCleanup(self.target_patch.stop)
        self.package_patch=patch('onejournal.activity_live_binding.verify_preparation',return_value=self.manifest)
        self.package_patch.start(); self.addCleanup(self.package_patch.stop)

    def test_ready_does_not_grant_authority_or_change_any_file(self):
        before={p:file_hash(p) for p in self.root.rglob('*') if p.is_file()}
        result=verify_publication_readiness(**self.kwargs)
        self.assertEqual(result['status'],'publication_preparation_ready')
        self.assertFalse(result['publication_authorized'])
        self.assertFalse(result['runtime_activation_authorized'])
        self.assertEqual({p:file_hash(p) for p in before},before)

    def test_changed_plan_draft_image_and_missing_image_are_refused(self):
        for path in (self.publication/'publication-plan.json',
                     self.publication/'prepared-report-draft.json',self.root/'image.dmg',
                     self.package/'journal.duckdb'):
            with self.subTest(path=path.name):
                original=path.read_bytes()
                try:
                    path.write_bytes(original+b' ')
                    with self.assertRaises(ValueError):
                        verify_publication_readiness(**self.kwargs)
                finally:
                    path.write_bytes(original)
        (self.root/'image.dmg').unlink()
        with self.assertRaises(ValueError):
            verify_publication_readiness(**self.kwargs)

    def test_wrong_backup_binding_target_count_and_authority_are_refused(self):
        for name,value in (('binding_sha256','b'*64),('live_journal_sha256','b'*64),
                           ('relation_count',True),('relation_count',6),
                           ('publication_authorized',True),('runtime_activation_authorized',True)):
            with self.subTest(field=name,value=value):
                path=self.root/'backup.json'
                path.write_bytes(json.dumps(dict(self.backup,**{name:value})).encode())
                with self.assertRaises(ValueError):
                    verify_publication_readiness(**self.kwargs)
        self.target.side_effect=[self.state,{'changed':True}]
        (self.root/'backup.json').write_bytes(json.dumps(self.backup).encode())
        with self.assertRaisesRegex(ValueError,'stale'):
            verify_publication_readiness(**self.kwargs)

    def test_cli_failure_is_redacted_and_nonzero(self):
        from contextlib import redirect_stderr
        from io import StringIO
        from scripts.web.check_activity_publication_ready import main
        arguments=[]
        for flag,key in (('binding','binding_path'),('web-config','config_path'),
                         ('package','package'),('publication-dir','publication_dir'),
                         ('backup-receipt','backup_receipt_path'),('backup-image','backup_image')):
            arguments.extend(['--'+flag,str(self.kwargs[key])])
        error=StringIO()
        with patch('scripts.web.check_activity_publication_ready.verify_publication_readiness',
                   side_effect=ValueError('PRIVATE VALUE')),redirect_stderr(error):
            self.assertEqual(main(arguments),1)
        self.assertNotIn('PRIVATE VALUE',error.getvalue())


if __name__=='__main__':
    unittest.main()
