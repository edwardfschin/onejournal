from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

import duckdb

from onejournal.journal.domain import JournalPolicyError
from onejournal.journal.migrations import apply_schema_migrations
from scripts.journal.init_journal_db import init_schema
from scripts.journal.upsert_journal_entry_to_db import read_private_body, write_entry


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"


class JournalEntryOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "journal.duckdb"
        init_schema(self.db_path)
        self.body_path = Path(self.tmp.name) / "private-note.txt"
        self.body_path.write_text("Private thesis text.\n", encoding="utf-8")

    def test_create_and_revise_append_snapshots_without_printing_body(self) -> None:
        create_args = argparse.Namespace(
            action="create",
            entry_type="entry_thesis",
            episode_uid=None,
            strategy_uid=None,
            title="Plan",
            occurred_at=None,
        )
        created = write_entry(self.db_path, create_args, read_private_body(str(self.body_path)))
        revise_args = argparse.Namespace(
            action="revise",
            entry_uid=created.entry_uid,
            entry_type=None,
            entry_status=None,
            change_reason="clarified trigger",
            episode_uid=None,
            strategy_uid=None,
            title=None,
            occurred_at=None,
        )
        revised = write_entry(self.db_path, revise_args, "Updated private thesis.")

        self.assertEqual(revised.revision_no, 2)
        self.assertEqual(revised.entry_type, "entry_thesis")
        self.assertEqual(revised.title, "Plan")
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            rows = con.execute(
                """
                SELECT revision_no, body, change_reason
                FROM journal_entry_revisions
                WHERE entry_uid = ? ORDER BY revision_no
                """,
                [created.entry_uid],
            ).fetchall()
        self.assertEqual(rows[0][1], "Private thesis text.")
        self.assertEqual(rows[1], (2, "Updated private thesis.", "clarified trigger"))

    def test_pre_0005_database_fails_closed(self) -> None:
        legacy_db = Path(self.tmp.name) / "legacy.duckdb"
        apply_schema_migrations(legacy_db, target_version="0004", migrations_dir=MIGRATIONS_DIR)
        args = argparse.Namespace(
            action="create",
            entry_type="note",
            episode_uid=None,
            strategy_uid=None,
            title=None,
            occurred_at=None,
        )
        with self.assertRaisesRegex(JournalPolicyError, "migration 0005"):
            write_entry(legacy_db, args, "content")


if __name__ == "__main__":
    unittest.main()
