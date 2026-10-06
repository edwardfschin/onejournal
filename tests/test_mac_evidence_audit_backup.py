"""Focused synthetic checks for Mac-only source and audit recovery."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import secrets
import sys
import tempfile
import unittest

import duckdb

from onejournal.mac_evidence_audit_backup import (audit_history, create_backup,
    exact_evidence, snapshot, source_digests, verify_backup)
from onejournal.mac_journal_backup import file_hash
from onejournal.passkey_access import CONTRACT


PROJECT = Path(__file__).resolve().parents[1]


class EvidenceAuditBackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="onejournal-synthetic-evidence-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.root.chmod(0o700)
        self.raw = self.root / "private-raw"
        self.raw.mkdir(mode=0o700)
        family = self.raw / "family"
        family.mkdir(mode=0o700)
        self.sources = []
        for name in ("manifest.json", "response.json"):
            path = family / name
            path.write_text(json.dumps({"synthetic": name}))
            path.chmod(0o600)
            self.sources.append(hashlib.sha256(path.read_bytes()).hexdigest())
        self.journal = self.root / "journal.duckdb"
        with duckdb.connect(str(self.journal)) as con:
            for table in ("phase1_schwab_evidence_import_families", "phase1_schwab_evidence_v2_import_families"):
                con.execute(f"CREATE TABLE {table} (source_manifest_sha256s_json VARCHAR, source_raw_sha256s_json VARCHAR)")
            con.execute("INSERT INTO phase1_schwab_evidence_import_families VALUES (?, ?)",
                        [json.dumps([self.sources[0]]), json.dumps([self.sources[1]])])
        self.journal.chmod(0o600)
        self.config = self.root / "local-web.json"
        self.config.write_text(json.dumps({"contract_version": "onejournal.local-web.v1",
                                           "journal_db_path": str(self.journal)}))
        self.config.chmod(0o600)
        self.security = self.root / "access.duckdb"
        with duckdb.connect(str(self.security)) as con:
            con.execute("CREATE TABLE access_meta (version VARCHAR, origin VARCHAR, journal_digest VARCHAR)")
            con.execute("CREATE TABLE access_audit (occurred_at DOUBLE, action VARCHAR, outcome VARCHAR)")
            con.execute("CREATE TABLE passkeys (credential_id VARCHAR)")
            con.execute("INSERT INTO passkeys VALUES ('synthetic-private-credential')")
            con.execute("INSERT INTO access_meta VALUES (?, ?, ?)", [CONTRACT, "https://localhost:4173",
                        hashlib.sha256(str(self.journal.resolve()).encode()).hexdigest()])
            con.execute("INSERT INTO access_audit VALUES (1.0, 'login', 'accepted')")
        self.security.chmod(0o600)
        self.stage = self.root / "stage"
        self.stage.mkdir(mode=0o700)

    def test_exact_lineage_and_value_free_snapshot(self):
        before_journal, before_security = file_hash(self.journal), file_hash(self.security)
        self.assertEqual(source_digests(self.journal), set(self.sources))
        self.assertEqual(len(exact_evidence(self.raw, set(self.sources))), 2)
        manifest = snapshot(self.config, self.security, self.raw, self.stage, PROJECT)
        self.assertEqual(manifest["audit_events"], 1)
        self.assertEqual(len(manifest["evidence_sha256"]), 2)
        self.assertFalse((self.stage / "access.duckdb").exists())
        self.assertFalse((self.stage / "journal.duckdb").exists())
        self.assertNotIn(b"synthetic-private-credential", (self.stage / "audit.json").read_bytes())
        self.assertEqual((file_hash(self.journal), file_hash(self.security)), (before_journal, before_security))

    def test_missing_lineage_and_locked_audit_fail_closed(self):
        (self.raw / "family" / "response.json").unlink()  # Synthetic fixture only.
        with self.assertRaisesRegex(ValueError, "missing"):
            exact_evidence(self.raw, set(self.sources))
        with duckdb.connect(str(self.security)):
            with self.assertRaisesRegex(ValueError, "unavailable"):
                audit_history(self.security, self.journal, "https://localhost:4173")
        self.assertFalse(any(self.stage.iterdir()))

    @unittest.skipUnless(sys.platform == "darwin", "Native encrypted image requires macOS")
    def test_encrypted_round_trip_and_no_overwrite(self):
        image = self.root / "evidence.dmg"
        password = secrets.token_urlsafe(24)
        before_journal, before_security = file_hash(self.journal), file_hash(self.security)
        self.assertEqual(create_backup(self.config, self.security, self.raw, image, password, PROJECT, require_usb=False), (2, 1))
        self.assertEqual(verify_backup(image, password), (2, 1))
        with self.assertRaises(ValueError):
            verify_backup(image, secrets.token_urlsafe(24))
        image_hash = file_hash(image)
        with self.assertRaisesRegex(ValueError, "Nothing was overwritten"):
            create_backup(self.config, self.security, self.raw, image, password, PROJECT, require_usb=False)
        self.assertEqual(file_hash(image), image_hash)
        self.assertEqual((file_hash(self.journal), file_hash(self.security)), (before_journal, before_security))


if __name__ == "__main__":
    unittest.main()
