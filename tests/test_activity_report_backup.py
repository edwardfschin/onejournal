from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import json
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch

from onejournal.activity_report_backup import create_backup, verify_backup, main
from onejournal.mac_access_backup import private_output


class EncryptedDraftBackupTests(unittest.TestCase):
    def test_existing_destination_preserved_before_any_capture(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder).resolve()/'previous.dmg'
            target.write_bytes(b'previous encrypted image')
            with patch('onejournal.activity_report_backup.disk_image') as native:
                with self.assertRaises(ValueError):
                    create_backup(target.parent/'absent', target, 'synthetic-password-long-enough', require_usb=False)
            native.assert_not_called()
            self.assertEqual(target.read_bytes(), b'previous encrypted image')

    def test_invalid_draft_is_not_encrypted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            with patch('onejournal.activity_report_backup.disk_image') as native:
                with self.assertRaises(ValueError):
                    create_backup(root/'missing-package',root/'new.dmg','synthetic-password-long-enough',require_usb=False)
            native.assert_not_called()
            self.assertFalse((root/'new.dmg').exists())

    def test_unencrypted_image_rejected_before_mounting(self):
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder).resolve()/'plain.dmg'
            image.write_bytes(b'not encrypted')
            with patch('onejournal.activity_report_backup.disk_image',return_value=plistlib.dumps({'encrypted':False})) as native:
                with self.assertRaisesRegex(ValueError,'not encrypted'):
                    verify_backup(image,'synthetic-password-long-enough')
            self.assertEqual(native.call_count,1)

    def test_restoration_copies_exact_nested_files_and_detaches_on_failure(self):
        manifest = dict(sha256={'evidence/provider/window/bundle/orders.json':'a'*64},package_fingerprint='b'*64)
        with tempfile.TemporaryDirectory() as folder:
            image = Path(folder).resolve()/'encrypted.dmg'
            image.write_bytes(b'synthetic')
            def native(args,password=None):
                if args[0]=='isencrypted':
                    return plistlib.dumps({'encrypted':True})
                if args[0]=='attach':
                    package = Path(args[args.index('-mountpoint')+1])/'package'
                    package.mkdir(mode=0o700)
                    current = package
                    for name in ('evidence','provider','window','bundle'):
                        current = current/name
                        current.mkdir(mode=0o700)
                    private_output(current/'orders.json',b'{}')
                    private_output(package/'manifest.json',json.dumps(manifest).encode())
                return b''
            seen=[]
            def verified(path):
                seen.append(path)
                self.assertEqual((path/'evidence/provider/window/bundle/orders.json').read_bytes(),b'{}')
                current=path/'evidence/provider/window/bundle'
                while current!=path:
                    self.assertEqual(current.stat().st_mode&0o777,0o700)
                    current=current.parent
                return manifest
            with patch('onejournal.activity_report_backup.disk_image',side_effect=native) as disk, \
                 patch('onejournal.activity_report_backup.verify_preparation',side_effect=verified):
                self.assertEqual(verify_backup(image,'synthetic-password-long-enough',manifest),manifest)
                self.assertEqual(len(seen),2)
                self.assertTrue(all(not p.exists() for p in seen))
                self.assertEqual(disk.call_args.args[0][0],'detach')
                with self.assertRaisesRegex(ValueError,'differs'):
                    verify_backup(image,'synthetic-password-long-enough',{'wrong':'snapshot'})
                self.assertEqual(disk.call_args.args[0][0],'detach')

    def test_failed_final_usb_verification_removes_only_our_new_image(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve(); package = root/'package'; package.mkdir(mode=0o700)
            private_output(package/'manifest.json',b'{}')
            previous = root/'previous.dmg'; previous.write_bytes(b'keep')
            def native(args,password=None):
                if args[0]=='convert':
                    Path(args[args.index('-o')+1]).write_bytes(b'encrypted synthetic')
                return b''
            with patch('onejournal.activity_report_backup.disk_image',side_effect=native), \
                 patch('onejournal.activity_report_backup.verify_preparation',return_value={'sha256':{}}), \
                 patch('onejournal.activity_report_backup.verify_backup',side_effect=ValueError('invalid')):
                with self.assertRaises(ValueError):
                    create_backup(package,root/'new.dmg','synthetic-password-long-enough',require_usb=False)
            self.assertFalse((root/'new.dmg').exists())
            self.assertEqual(previous.read_bytes(),b'keep')

    def test_cli_requires_private_tty_and_redacts_validation_failure(self):
        output=StringIO()
        with patch('onejournal.activity_report_backup.sys.stdin.isatty',return_value=False), \
             patch('onejournal.activity_report_backup.getpass.getpass') as prompt, \
             redirect_stdout(output),redirect_stderr(output):
            self.assertEqual(main(['verify','--destination','/private/tmp/example.dmg']),1)
        prompt.assert_not_called()
        with patch('onejournal.activity_report_backup.sys.platform','darwin'), \
             patch('onejournal.activity_report_backup.sys.stdin.isatty',return_value=True), \
             patch('onejournal.activity_report_backup.getpass.getpass',side_effect=['synthetic-password-long-enough']), \
             patch('onejournal.activity_report_backup.verify_backup',side_effect=ValueError('private account information')), \
             redirect_stdout(output),redirect_stderr(output):
            self.assertEqual(main(['verify','--destination','/private/tmp/example.dmg']),1)
        self.assertNotIn('private account information',output.getvalue())


if __name__=='__main__':
    unittest.main()
