from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import duckdb

from onejournal.journal.domain import add_tag_event, create_entry, create_tag, save_review
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.workflows import build_review_queues, flatten_review_queues
from scripts.journal.init_journal_db import init_schema


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"


class JournalWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "journal.duckdb"
        init_schema(self.db_path)
        with duckdb.connect(str(self.db_path)) as con:
            for index, symbol in enumerate(("AAPL", "MSFT", "NVDA", "TSLA"), start=1):
                self._insert_episode(con, f"episode-{index}", symbol, index)

    @staticmethod
    def _insert_episode(
        con: duckdb.DuckDBPyConnection,
        episode_uid: str,
        symbol: str,
        day: int,
    ) -> None:
        con.execute(
            """
            INSERT INTO trade_episodes (
                episode_uid, source_broker, source_account_id, primary_symbol,
                asset_class, strategy_type, strategy_label, opened_at, status,
                fill_count, leg_count, updated_at
            ) VALUES (?, 'manual_csv', 'account-1', ?, 'stock', 'stock_long',
                      'Stock Long', ?, 'closed', 2, 1, ?)
            """,
            [
                episode_uid,
                symbol,
                datetime(2026, 1, day, 10, 0),
                datetime(2026, 1, day, 11, 0),
            ],
        )

    def test_queues_use_explicit_deterministic_reason_codes(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            save_review(
                con,
                episode_uid="episode-2",
                review_status="needs_review",
                setup_quality="poor",
                source="streamlit",
            )
            save_review(
                con,
                episode_uid="episode-3",
                review_status="mistake_review",
                setup_quality="mistake",
                source="streamlit",
            )
            save_review(
                con,
                episode_uid="episode-4",
                review_status="reviewed",
                setup_quality="good",
                source="streamlit",
            )
            entry = create_entry(
                con,
                entry_type="mistake",
                body="private narrative must not enter queue payload",
                created_source="streamlit",
                episode_uid="episode-4",
            )
            risk_tag = create_tag(con, tag_type="general", name="Risk")
            add_tag_event(con, entry_uid=entry.entry_uid, tag_uid=risk_tag, action="assign")

            queues = build_review_queues(con, asof=date(2026, 1, 31))

        self.assertEqual([row["episode_uid"] for row in queues["unreviewed"]], ["episode-1"])
        self.assertEqual(queues["unreviewed"][0]["reason_codes"], ["missing_review"])
        self.assertEqual([row["episode_uid"] for row in queues["incomplete"]], ["episode-2"])
        self.assertEqual(queues["incomplete"][0]["reason_codes"], ["needs_review_status"])
        self.assertEqual(
            [row["episode_uid"] for row in queues["mistake"]],
            ["episode-4", "episode-3"],
        )
        risk_row = next(row for row in queues["risk_flagged"] if row["episode_uid"] == "episode-4")
        self.assertEqual(risk_row["reason_codes"], ["active_risk_tag", "active_mistake_entry"])
        flattened = flatten_review_queues(queues)
        self.assertNotIn("body", repr(flattened))
        self.assertNotIn("private narrative", repr(flattened))

    def test_queue_asof_excludes_later_episode(self) -> None:
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            queues = build_review_queues(con, asof=date(2026, 1, 2))
        self.assertEqual(
            [row["episode_uid"] for row in queues["unreviewed"]],
            ["episode-2", "episode-1"],
        )

    def test_pre_0005_database_uses_review_projection_only(self) -> None:
        legacy_db = Path(self.tmp.name) / "legacy.duckdb"
        apply_schema_migrations(legacy_db, target_version="0004", migrations_dir=MIGRATIONS_DIR)
        with duckdb.connect(str(legacy_db)) as con:
            self._insert_episode(con, "legacy-episode", "AMD", 1)
            queues = build_review_queues(con)
        self.assertEqual(queues["unreviewed"][0]["reason_codes"], ["missing_review"])
        self.assertEqual(queues["risk_flagged"], [])


if __name__ == "__main__":
    unittest.main()
