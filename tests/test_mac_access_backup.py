"""Synthetic access files only; native Mac disk-image recovery smoke."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest
from unittest.mock import patch

from onejournal.mac_access_backup import (FILES, create_backup, disk_image,
    password_bytes, setup_snapshot, validate_destination, verify_backup)


class BackupGuardTests(unittest.TestCase):
    def test_password_and_missing_usb_fail_before_copy(self):
        for value in ("short", "x" * 20 + "\0", "x" * 20 + "\n"):
            with self.assertRaises(ValueError):
                password_bytes(value)
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "not mounted"):
                validate_destination(Path(folder).resolve() / "new.dmg")

    def test_no_overwrite_and_no_symlink_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder).resolve()
            existing = root / "existing.dmg"
            existing.write_bytes(b"preserve")
            with self.assertRaises(ValueError):
                validate_destination(existing, require_usb=False)
            self.assertEqual(existing.read_bytes(), b"preserve")
            (root / "linked").symlink_to(root, target_is_directory=True)
            with self.assertRaises(ValueError):
                validate_destination(root / "linked/new.dmg", require_usb=False)

    def test_password_not_in_arguments_or_error(self):
        password = secrets.token_urlsafe(24)
        import subprocess
        with patch("onejournal.mac_access_backup.subprocess.run", side_effect=subprocess.CalledProcessError(1, [], stderr=password.encode())) as run:
            with self.assertRaises(ValueError) as error:
                disk_image(["verify", "synthetic.dmg", "-stdinpass"], password)
        args, kwargs = run.call_args
        self.assertNotIn(password, " ".join(args[0]))
        self.assertEqual(kwargs["input"], password.encode() + b"\0")
        self.assertNotIn(password, str(error.exception))

    def test_plain_image_is_rejected_before_mount(self):
        import plistlib
        with patch("onejournal.mac_access_backup.disk_image", return_value=plistlib.dumps({"encrypted": False})) as run:
            with self.assertRaisesRegex(ValueError, "not encrypted"):
                verify_backup(Path("/tmp/synthetic.dmg"), "synthetic recovery password 123")
        self.assertEqual(run.call_count, 1)


@unittest.skipUnless(sys.platform == "darwin", "Native encrypted image smoke requires macOS; no USB/private data used.")
class NativeBackupTests(unittest.TestCase):
    def test_encrypted_copy_restoration_wrong_password_and_allowlist(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        with tempfile.TemporaryDirectory(prefix="onejournal-synthetic-backup-") as folder:
            root = Path(folder).resolve()
            source = root / "source"
            source.mkdir(mode=0o700)
            key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic localhost")])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now-timedelta(minutes=1)).not_valid_after(now+timedelta(days=1))
                    .sign(key, hashes.SHA256()))
            values = {
                "local-web.json": json.dumps({"contract_version": "onejournal.local-web.v1", "journal_db_path": "/tmp/synthetic-journal.duckdb"}).encode(),
                "localhost-cert.pem": cert.public_bytes(serialization.Encoding.PEM),
                "OneJournal-localhost.cer": cert.public_bytes(serialization.Encoding.DER),
                "localhost-key.pem": key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
            }
            for filename, value in values.items():
                (source / filename).write_bytes(value)
                (source / filename).chmod(0o600)
            # Sensitive-lookalike files must never be swept up by a directory copy.
            for name in ("access.duckdb", "journal.duckdb", "enrollment.txt"):
                (source / name).write_bytes(b"excluded sentinel")
            snapshot = setup_snapshot(source)
            self.assertEqual(set(snapshot), {*FILES, "RECOVERY.txt"})
            password = secrets.token_urlsafe(24)
            image = root / "recovery.dmg"
            create_backup(source, image, password, require_usb=False)
            self.assertTrue(image.is_file())
            with self.assertRaises(ValueError):
                verify_backup(image, secrets.token_urlsafe(24))
            for filename, original in values.items():
                self.assertEqual((source / filename).read_bytes(), original)
            (source / "localhost-key.pem").chmod(0o644)
            with self.assertRaises(ValueError):
                setup_snapshot(source)


if __name__ == "__main__":
    unittest.main()
