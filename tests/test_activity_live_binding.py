import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onejournal.activity_live_binding import (
    CONTRACT,verify_bound_target,compatible_report_columns,backup_bound_target,target_state,
)
from onejournal.mac_access_backup import private_output


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


if __name__=='__main__':
    unittest.main()
