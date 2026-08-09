from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import duckdb

from onejournal.journal.domain import (
    JournalPolicyError,
    JournalValidationError,
    add_tag_event,
    append_entry_revision,
    create_entry,
    create_strategy,
    create_tag,
    register_attachment_metadata,
    save_review,
    validate_attachment_metadata,
)
from onejournal.journal.migrations import apply_schema_migrations
from scripts.journal.init_journal_db import init_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"


class JournalDomainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "onejournal.duckdb"
        init_schema(self.db_path)
        with duckdb.connect(str(self.db_path)) as con:
            self._insert_episode(con)

    @staticmethod
    def _insert_episode(con: duckdb.DuckDBPyConnection, episode_uid: str = "episode-1") -> None:
        con.execute(
            """
            INSERT INTO trade_episodes (
                episode_uid, source_broker, source_account_id, primary_symbol,
                asset_class, strategy_type, strategy_label, opened_at, status,
                fill_count, leg_count, updated_at
            ) VALUES (?, 'manual_csv', 'account-1', 'AAPL', 'stock',
                      'stock_long', 'Stock Long', TIMESTAMP '2026-01-01 10:00:00',
                      'closed', 2, 1, TIMESTAMP '2026-01-02 10:00:00')
            """,
            [episode_uid],
        )

    def test_save_review_appends_history_and_updates_projection(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            first = save_review(
                con,
                episode_uid="episode-1",
                review_status="reviewed",
                setup_quality="good",
                entry_reason="planned",
                notes="kept risk small",
                source="streamlit",
                created_at=datetime(2026, 1, 2, 12, 0),
            )
            second = save_review(
                con,
                episode_uid="episode-1",
                review_status="mistake_review",
                setup_quality="mistake",
                entry_reason="late entry",
                notes="wait for confirmation",
                source="streamlit",
                created_at=datetime(2026, 1, 3, 12, 0),
            )

            self.assertTrue(first.history_written)
            self.assertTrue(second.history_written)
            rows = con.execute(
                """
                SELECT review_uid, supersedes_review_uid, review_status
                FROM journal_reviews ORDER BY created_at
                """
            ).fetchall()
            self.assertEqual(len(rows), 2)
            self.assertIsNone(rows[0][1])
            self.assertEqual(str(rows[1][1]), str(rows[0][0]))
            self.assertEqual(rows[1][2], "mistake_review")
            projection = con.execute(
                """
                SELECT review_status, setup_quality, entry_reason, notes
                FROM manual_reviews WHERE episode_uid = 'episode-1'
                """
            ).fetchone()
            self.assertEqual(
                projection,
                ("mistake_review", "mistake", "late entry", "wait for confirmation"),
            )

    def test_identical_import_review_is_idempotent(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            save_review(
                con,
                episode_uid="episode-1",
                review_status="reviewed",
                setup_quality="good",
                entry_reason="planned",
                notes="same evidence",
                source="import",
                skip_if_unchanged=True,
            )
            replay = save_review(
                con,
                episode_uid="episode-1",
                review_status="reviewed",
                setup_quality="good",
                entry_reason="planned",
                notes="same evidence",
                source="import",
                skip_if_unchanged=True,
            )
            self.assertTrue(replay.unchanged)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM journal_reviews").fetchone()[0], 1)

    def test_pre_migration_database_keeps_legacy_review_compatibility(self) -> None:
        legacy_db = Path(self.tmp.name) / "legacy.duckdb"
        apply_schema_migrations(
            legacy_db,
            target_version="0004",
            migrations_dir=MIGRATIONS_DIR,
        )
        with duckdb.connect(str(legacy_db)) as con:
            self._insert_episode(con)
            result = save_review(
                con,
                episode_uid="episode-1",
                review_status="reviewed",
                setup_quality="acceptable",
                source="streamlit",
            )
            self.assertTrue(result.compatibility_only)
            self.assertFalse(result.history_written)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM manual_reviews").fetchone()[0], 1)

    def test_entry_revisions_preserve_pretrade_and_link_history(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            strategy_uid = create_strategy(con, name="Breakout", description="Wait for confirmation")
            first = create_entry(
                con,
                entry_type="pre_trade_plan",
                body="Buy only above resistance.",
                title="AAPL plan",
                created_source="streamlit",
                strategy_uid=strategy_uid,
                created_at=datetime(2026, 1, 1, 8, 0),
            )
            second = append_entry_revision(
                con,
                entry_uid=first.entry_uid,
                entry_type="pre_trade_plan",
                body="Buy only above resistance with volume confirmation.",
                title="AAPL plan",
                episode_uid="episode-1",
                strategy_uid=strategy_uid,
                change_reason="linked confirmed trade",
                created_at=datetime(2026, 1, 2, 8, 0),
            )
            self.assertEqual(second.revision_no, 2)
            rows = con.execute(
                """
                SELECT revision_no, episode_uid, body
                FROM journal_entry_revisions WHERE entry_uid = ? ORDER BY revision_no
                """,
                [first.entry_uid],
            ).fetchall()
            self.assertEqual(rows[0], (1, None, "Buy only above resistance."))
            self.assertEqual(rows[1][0:2], (2, "episode-1"))

            con.execute("DELETE FROM trade_episodes WHERE episode_uid = 'episode-1'")
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM journal_entry_revisions WHERE entry_uid = ?",
                    [first.entry_uid],
                ).fetchone()[0],
                2,
            )

    def test_tag_events_are_ordered_and_reject_duplicate_state(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            entry = create_entry(
                con,
                entry_type="mistake",
                body="Entered late.",
                created_source="streamlit",
                episode_uid="episode-1",
            )
            tag_uid = create_tag(con, tag_type="mistake", name="Late Entry")
            add_tag_event(con, entry_uid=entry.entry_uid, tag_uid=tag_uid, action="assign")
            with self.assertRaisesRegex(JournalValidationError, "already in action state"):
                add_tag_event(con, entry_uid=entry.entry_uid, tag_uid=tag_uid, action="assign")
            add_tag_event(con, entry_uid=entry.entry_uid, tag_uid=tag_uid, action="remove")
            rows = con.execute(
                """
                SELECT sequence_no, action FROM journal_entry_tag_events
                WHERE entry_uid = ? AND tag_uid = ? ORDER BY sequence_no
                """,
                [entry.entry_uid, tag_uid],
            ).fetchall()
            self.assertEqual(rows, [(1, "assign"), (2, "remove")])

    def test_attachment_metadata_validates_but_write_remains_disabled(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            entry = create_entry(
                con,
                entry_type="note",
                body="Screenshot evidence.",
                created_source="streamlit",
            )
            metadata = validate_attachment_metadata(
                entry_uid=entry.entry_uid,
                storage_key="journal/2026/01/evidence.png",
                original_filename="evidence.png",
                media_type="image/png",
                byte_size=123,
                content_sha256="a" * 64,
            )
            self.assertEqual(metadata["storage_key"], "journal/2026/01/evidence.png")
            with self.assertRaises(JournalPolicyError):
                register_attachment_metadata(
                    con,
                    entry_uid=entry.entry_uid,
                    storage_key="journal/2026/01/evidence.png",
                    original_filename="evidence.png",
                    media_type="image/png",
                    byte_size=123,
                    content_sha256="a" * 64,
                )
            self.assertEqual(con.execute("SELECT COUNT(*) FROM journal_attachments").fetchone()[0], 0)

    def test_attachment_metadata_rejects_unsafe_filename_media_type_and_size(self) -> None:
        with self.assertRaisesRegex(JournalValidationError, "sanitized display filename"):
            validate_attachment_metadata(
                entry_uid="11111111-1111-4111-8111-111111111111",
                storage_key="journal/evidence.png",
                original_filename="../evidence.png",
                media_type="image/png",
                byte_size=10,
                content_sha256="a" * 64,
            )
        with self.assertRaisesRegex(JournalValidationError, "MIME type"):
            validate_attachment_metadata(
                entry_uid="11111111-1111-4111-8111-111111111111",
                storage_key="journal/evidence.png",
                original_filename="evidence.png",
                media_type="not-a-mime",
                byte_size=10,
                content_sha256="a" * 64,
            )
        with self.assertRaisesRegex(JournalValidationError, "non-negative integer"):
            validate_attachment_metadata(
                entry_uid="11111111-1111-4111-8111-111111111111",
                storage_key="journal/evidence.png",
                original_filename="evidence.png",
                media_type="image/png",
                byte_size=1.5,
                content_sha256="a" * 64,
            )

    def test_invalid_review_and_missing_episode_fail_without_projection_write(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            with self.assertRaises(JournalValidationError):
                save_review(
                    con,
                    episode_uid="episode-1",
                    review_status="done",
                    setup_quality="good",
                    source="streamlit",
                )
            with self.assertRaisesRegex(JournalValidationError, "episode_uid not found"):
                save_review(
                    con,
                    episode_uid="missing",
                    review_status="reviewed",
                    setup_quality="good",
                    source="streamlit",
                )
            self.assertEqual(con.execute("SELECT COUNT(*) FROM manual_reviews").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
