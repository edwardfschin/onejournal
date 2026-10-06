"""Focused recovery guards and one native round trip; synthetic journal only."""
import copy
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

import duckdb

from onejournal.mac_journal_backup import (create_backup, file_hash, snapshot,
    verify_backup, verify_restored)
from scripts.journal.init_journal_db import init_schema

PROJECT = Path(__file__).resolve().parents[1]


class JournalBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="onejournal-synthetic-journal-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.root.chmod(0o700)
        self.db = self.root / "source.duckdb"
        init_schema(self.db)
        self.db.chmod(0o600)
        with duckdb.connect(str(self.db)) as con:
            con.execute("CREATE TABLE recovery_sentinel (value DECIMAL(38,27), note VARCHAR)")
            con.execute("INSERT INTO recovery_sentinel VALUES (0.123456789012345678901234567, 'synthetic private note')")
        self.config = self.root / "source.json"
        self.config.write_text(json.dumps({"contract_version": "onejournal.local-web.v1", "journal_db_path": str(self.db)}))
        self.config.chmod(0o600)
        self.stage = self.root / "snapshot"
        self.stage.mkdir(mode=0o700)

    def test_exact_snapshot_restores_all_relations_and_excludes_security_state(self):
        for name in ("access.duckdb", "enrollment.txt", "localhost-key.pem"):
            (self.root / name).write_bytes(b"excluded synthetic sentinel")
        before = file_hash(self.db)
        manifest = snapshot(self.config, self.stage, PROJECT)
        self.assertEqual(set(manifest["sha256"]), {"journal.duckdb", "local-web.json", "RECOVERY.txt"})
        self.assertEqual(file_hash(self.db), before)
        self.assertEqual(file_hash(self.stage / "journal.duckdb"), before)
        self.assertEqual(verify_restored(self.stage, manifest, PROJECT), len(manifest["inventory"]["relations"]))
        self.assertEqual(manifest["inventory"]["counts"]["recovery_sentinel"], 1)
        self.assertEqual((self.stage / "journal.duckdb").stat().st_mode & 0o777, 0o600)
        self.assertEqual(file_hash(self.db), before)

    def test_pending_log_and_writer_fail_closed_without_checkpoint(self):
        before = file_hash(self.db)
        wal = Path(str(self.db) + ".wal")
        wal.write_bytes(b"synthetic pending log")
        with self.assertRaisesRegex(ValueError, "write-ahead"):
            snapshot(self.config, self.stage, PROJECT)
        self.assertEqual(wal.read_bytes(), b"synthetic pending log")
        wal.unlink()  # Our synthetic test sentinel only.
        with duckdb.connect(str(self.db)):
            with self.assertRaisesRegex(ValueError, "read-only journal snapshot"):
                snapshot(self.config, self.stage, PROJECT)
        self.assertFalse(any(self.stage.iterdir()))
        self.assertEqual(file_hash(self.db), before)

    def test_manifest_tampering_missing_authority_and_unsafe_files_rejected(self):
        manifest = snapshot(self.config, self.stage, PROJECT)
        modified = copy.deepcopy(manifest)
        modified["sha256"]["../escape"] = "a" * 64
        with self.assertRaisesRegex(ValueError, "unsupported"):
            verify_restored(self.stage, modified, PROJECT)
        modified = copy.deepcopy(manifest)
        modified["inventory"]["counts"]["recovery_sentinel"] = 2
        with self.assertRaisesRegex(ValueError, "record counts"):
            verify_restored(self.stage, modified, PROJECT)
        document = json.loads((self.stage / "local-web.json").read_bytes())
        document["reporting_authorization"] = "/tmp/synthetic-missing-authorization.json"
        (self.stage / "local-web.json").write_text(json.dumps(document))
        manifest["sha256"]["local-web.json"] = file_hash(self.stage / "local-web.json")
        with self.assertRaisesRegex(ValueError, "release authority"):
            verify_restored(self.stage, manifest, PROJECT)
        (self.stage / "journal.duckdb").chmod(0o644)
        with self.assertRaises(ValueError):
            verify_restored(self.stage, manifest, PROJECT)

    @unittest.skipUnless(sys.platform == "darwin", "Native encrypted journal round trip requires macOS.")
    def test_encrypted_round_trip_wrong_password_and_no_overwrite(self):
        image = self.root / "journal-recovery.dmg"
        password = secrets.token_urlsafe(24)
        before = file_hash(self.db)
        count = create_backup(self.config, image, password, PROJECT, require_usb=False)
        self.assertGreater(count, 1)
        with self.assertRaises(ValueError):
            verify_backup(image, secrets.token_urlsafe(24), PROJECT)
        image_hash = file_hash(image)
        with self.assertRaisesRegex(ValueError, "Nothing was overwritten"):
            create_backup(self.config, image, password, PROJECT, require_usb=False)
        self.assertEqual(file_hash(image), image_hash)
        self.assertEqual(file_hash(self.db), before)


if __name__ == "__main__":
    unittest.main()
