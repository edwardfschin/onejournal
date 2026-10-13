"""Focused copy lifetime, path binding and owned-child failure guards; no USB/live data."""
from contextlib import redirect_stderr
import io
import json
from pathlib import Path
import plistlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, MagicMock

from onejournal.mac_access_backup import FILES, hashes, restored_backup as access_copy
from onejournal.mac_journal_backup import restored_backup as journal_copy
from onejournal.mac_evidence_audit_backup import restored_backup as evidence_copy
from scripts.web import rehearse_mac_recovery as runner


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.root.chmod(0o700)
        self.image = self.root / 'synthetic.dmg'
        self.image.write_bytes(b'synthetic encrypted placeholder')
        self.image.chmod(0o600)

    def mounted(self, files, calls):
        def disk(arguments, password=None):
            calls.append(arguments)
            if arguments[0] == 'isencrypted':
                return plistlib.dumps({'encrypted': True})
            if arguments[0] == 'attach':
                mount = Path(arguments[arguments.index('-mountpoint') + 1])
                for name, value in files.items():
                    target = mount / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(value)
            return b''
        return disk

    def test_access_copy_is_private_scoped_and_cleaned_after_exception(self):
        values = {name: b'synthetic setup' for name in (*FILES, 'RECOVERY.txt')}
        manifest = {'contract_version': 'onejournal.mac-access-backup.v1', 'sha256': hashes(values)}
        calls = []
        with patch('onejournal.mac_access_backup.disk_image', side_effect=self.mounted(
                {**values, 'manifest.json': json.dumps(manifest).encode()}, calls)), \
             patch('onejournal.mac_access_backup.setup_snapshot'):
            with self.assertRaisesRegex(RuntimeError, 'consumer failure'):
                with access_copy(self.image, 'synthetic recovery password 123') as restored:
                    self.assertEqual((restored / FILES[0]).stat().st_mode & 0o777, 0o600)
                    self.assertFalse((restored / 'access.duckdb').exists())
                    raise RuntimeError('consumer failure')
        self.assertFalse(restored.exists())
        self.assertEqual(calls[-1][0], 'detach')
        self.assertIn('-readonly', next(call for call in calls if call[0] == 'attach'))

    def test_journal_copy_preserves_result_and_is_disposable(self):
        names = ['journal.duckdb', 'local-web.json', 'RECOVERY.txt']
        manifest = {'sha256': {name:'a'*64 for name in names}}
        calls = []
        with patch('onejournal.mac_journal_backup.disk_image', side_effect=self.mounted(
                {**{name:b'synthetic' for name in names}, 'manifest.json':json.dumps(manifest).encode()}, calls)), \
             patch('onejournal.mac_journal_backup.verify_restored', return_value=95) as verify:
            with journal_copy(self.image, 'synthetic recovery password 123', self.root) as (restored, observed, count):
                self.assertEqual(count, 95)
                self.assertEqual(observed, manifest)
                self.assertTrue((restored / 'journal.duckdb').exists())
            self.assertEqual(verify.call_count, 1)
        self.assertFalse(restored.exists())
        self.assertEqual(calls[-1][0], 'detach')

    def test_evidence_copy_yields_validated_counts_without_security_store(self):
        manifest = {'evidence_sha256': {'family/raw.json': 'a'*64}}
        calls = []
        with patch('onejournal.mac_evidence_audit_backup.disk_image', side_effect=self.mounted(
                {'manifest.json':json.dumps(manifest).encode(), 'audit.json':b'{}',
                 'RECOVERY.txt':b'synthetic', 'evidence/family/raw.json':b'{}'}, calls)), \
             patch('onejournal.mac_evidence_audit_backup.verify_restored', return_value=(1, 2)) as verify:
            with evidence_copy(self.image, 'synthetic recovery password 123') as (restored, _, counts):
                self.assertEqual(counts, (1, 2))
                self.assertFalse((restored / 'access.duckdb').exists())
            self.assertEqual(verify.call_count, 1)
        self.assertFalse(restored.exists())
        self.assertEqual(calls[-1][0], 'detach')

    def test_bad_manifest_fails_before_journal_path_copy_and_detaches(self):
        calls = []
        with patch('onejournal.mac_journal_backup.disk_image', side_effect=self.mounted(
                {'manifest.json':b'{"sha256":{"../live":"bad"}}'}, calls)), \
             patch('onejournal.mac_journal_backup.copy_private') as copy:
            with self.assertRaises(ValueError):
                with journal_copy(self.image, 'synthetic recovery password 123', self.root):
                    self.fail('Unsafe copy yielded')
            copy.assert_not_called()
        self.assertEqual(calls[-1][0], 'detach')

    def test_rebinding_changes_only_new_config_and_restored_locations(self):
        document = {'contract_version':'onejournal.local-web.v1', 'journal_db_path':'/synthetic/live',
                    'reporting_authorization':'/synthetic/live-authorization', 'web_port':4173}
        original = json.dumps(document).encode()
        (self.root / 'local-web.json').write_bytes(original)
        with patch.object(runner, 'parse_config') as parse:
            path = runner.rebound_config(self.root, {'sha256':{'reporting-authorization.json':'a'*64}}, 4174)
        self.assertEqual((self.root / 'local-web.json').read_bytes(), original)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        rebound = parse.call_args.args[0]
        self.assertEqual(rebound['journal_db_path'], str(self.root / 'journal.duckdb'))
        self.assertEqual(rebound['reporting_authorization'], str(self.root / 'reporting-authorization.json'))
        self.assertEqual(rebound['web_port'], 4174)
        with self.assertRaises(FileExistsError):
            with patch.object(runner, 'parse_config'):
                runner.rebound_config(self.root, {'sha256':{}}, 4174)

    def test_probe_failure_stops_only_new_child_and_never_runs_migration(self):
        args = SimpleNamespace(port=9443, tls_cert_sha256='a'*64,
                               runtime_python=Path('/synthetic/runtime/python'), release_dir=self.root / 'public')
        child = MagicMock()
        child.poll.return_value = None
        with patch.object(runner, 'file_hash', return_value='a'*64), \
             patch.object(runner, 'rebound_config', return_value=self.root / 'rehearsal-web.json'), \
             patch.object(runner, 'provision'), patch.object(runner.socket, 'socket'), \
             patch.object(runner.socket, 'create_connection'), \
             patch.object(runner.subprocess, 'Popen', return_value=child) as spawn, \
             patch.object(runner, 'probe', side_effect=RuntimeError('private response')):
            with self.assertRaises(RuntimeError):
                runner.serve_and_probe(args, self.root, self.root, {}, 'a'*64)
        child.terminate.assert_called_once()
        child.wait.assert_called_once()
        command = spawn.call_args.args[0]
        self.assertEqual(command[:4], ['/synthetic/runtime/python', '-B', '-m', 'onejournal.mac_static_site'])
        self.assertNotIn('PYTHONPATH', spawn.call_args.kwargs['env'])
        self.assertNotIn('recover', command)
        self.assertIn(str(self.root / 'rehearsal-access.duckdb'), command)

    def test_scoped_read_audits_are_allowed_but_unrelated_changes_fail(self):
        args = SimpleNamespace(port=9443, tls_cert_sha256='a'*64,
                               runtime_python=Path('/synthetic/runtime/python'), release_dir=self.root / 'public')
        before = dict(relations=[], columns=[], counts={'journal_entries':7, 'phase1_reporting_api_audit_events':4})
        for count, succeeds in ((7, True), (8, False)):
            after = {**before, 'counts':{'journal_entries':count, 'phase1_reporting_api_audit_events':7}}
            child = MagicMock()
            child.poll.return_value = None
            with patch.object(runner, 'file_hash', return_value='a'*64), \
                 patch.object(runner, 'rebound_config', return_value=self.root / 'rehearsal-web.json'), \
                 patch.object(runner, 'provision'), patch.object(runner.socket, 'socket'), \
                 patch.object(runner.socket, 'create_connection'), \
                 patch.object(runner.subprocess, 'Popen', return_value=child), \
                 patch.object(runner, 'probe'), patch('duckdb.connect'), \
                 patch.object(runner, 'inventory', return_value=after):
                if succeeds:
                    runner.serve_and_probe(args, self.root, self.root, {'inventory':before}, 'a'*64)
                else:
                    with self.assertRaisesRegex(ValueError, 'Unexpected restored journal'):
                        runner.serve_and_probe(args, self.root, self.root, {'inventory':before}, 'a'*64)
            child.terminate.assert_called_once()

    def test_noninteractive_failure_is_value_free_and_creates_no_receipt(self):
        output = io.StringIO()
        args = []
        for name in ('journal-image', 'access-image', 'evidence-image', 'runtime-python', 'release-dir', 'receipt'):
            args.extend(['--'+name, str(self.root / name)])
        for name in ('manifest-sha256', 'source-commit', 'tls-cert-sha256'):
            args.extend(['--'+name, 'a'*64])
        with patch.object(runner.sys.stdin, 'isatty', return_value=False), redirect_stderr(output):
            self.assertEqual(runner.main(args), 1)
        self.assertNotIn(str(self.root), output.getvalue())
        self.assertFalse((self.root / 'receipt').exists())

    def arguments(self, port=4174):
        args = []
        for name in ('journal-image', 'access-image', 'evidence-image', 'release-dir', 'receipt'):
            args.extend(['--'+name, str(self.root / name)])
        args.extend(['--runtime-python', sys.executable, '--port', str(port)])
        for name in ('manifest-sha256', 'source-commit', 'tls-cert-sha256'):
            args.extend(['--'+name, 'a'*64])
        return args

    def test_live_port_is_rejected_before_password_or_receipt(self):
        with patch.object(runner.sys.stdin, 'isatty', return_value=True), \
             patch.object(runner.getpass, 'getpass') as prompt, redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(self.arguments(4173)), 1)
        prompt.assert_not_called()
        self.assertFalse((self.root / 'receipt').exists())

    def test_existing_receipt_is_preserved_before_password_or_image_access(self):
        receipt = self.root / 'receipt'
        receipt.write_bytes(b'preserve existing evidence')
        with patch.object(runner.sys.stdin, 'isatty', return_value=True), \
             patch.object(runner.getpass, 'getpass') as prompt, \
             patch.object(runner, 'check_release') as check, redirect_stderr(io.StringIO()):
            self.assertEqual(runner.main(self.arguments()), 1)
        self.assertEqual(receipt.read_bytes(), b'preserve existing evidence')
        prompt.assert_not_called()
        check.assert_not_called()


if __name__ == '__main__':
    unittest.main()
