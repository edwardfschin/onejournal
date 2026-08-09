from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

import duckdb

from onejournal.journal.domain import create_entry, create_strategy, save_review
from onejournal.journal.search import (
    JournalSearchFilters,
    create_saved_view,
    load_saved_view,
    list_saved_views,
    search_journal,
)
from scripts.journal.init_journal_db import init_schema


class JournalSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "journal.duckdb"
        init_schema(self.db_path)
        with duckdb.connect(str(self.db_path)) as con:
            self._insert_episode(con, "episode-a", "AAPL", "acct-1", 1, "stock_long")
            self._insert_episode(con, "episode-b", "MSFT", "acct-2", 2, "call_debit_vertical")
            save_review(
                con,
                episode_uid="episode-a",
                review_status="reviewed",
                setup_quality="good",
                source="streamlit",
            )
            save_review(
                con,
                episode_uid="episode-b",
                review_status="needs_review",
                setup_quality="poor",
                source="streamlit",
            )
            strategy_uid = create_strategy(con, name="Breakout")
            create_entry(
                con,
                entry_type="entry_thesis",
                title="Volume confirmation",
                body="Wait for the breakout above resistance.",
                created_source="operator",
                episode_uid="episode-a",
                strategy_uid=strategy_uid,
                occurred_at=datetime(2026, 1, 1, 9, 0),
            )
            create_entry(
                con,
                entry_type="execution_review",
                title="Risk review",
                body="Entry timing needs improvement.",
                created_source="operator",
                episode_uid="episode-b",
                occurred_at=datetime(2026, 1, 2, 12, 0),
            )
            create_entry(
                con,
                entry_type="note",
                title="General note",
                body="Unlinked private journal entry.",
                created_source="operator",
                occurred_at=datetime(2026, 1, 3, 12, 0),
            )
            self.strategy_uid = strategy_uid

    @staticmethod
    def _insert_episode(
        con: duckdb.DuckDBPyConnection,
        episode_uid: str,
        symbol: str,
        account: str,
        day: int,
        strategy_type: str,
    ) -> None:
        con.execute(
            """
            INSERT INTO trade_episodes (
                episode_uid, source_broker, source_account_id, primary_symbol,
                asset_class, strategy_type, strategy_label, opened_at, status,
                fill_count, leg_count, updated_at
            ) VALUES (?, 'manual_csv', ?, ?, 'stock', ?, ?, ?, 'closed', 2, 1, ?)
            """,
            [
                episode_uid,
                account,
                symbol,
                strategy_type,
                strategy_type.replace("_", " ").title(),
                datetime(2026, 1, day, 10, 0),
                datetime(2026, 1, day, 11, 0),
            ],
        )

    def test_search_combines_structured_episode_and_private_entry_filters(self) -> None:
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            result = search_journal(
                con,
                JournalSearchFilters(
                    query_text="breakout",
                    symbol="aapl",
                    journal_strategy_uid=self.strategy_uid,
                    review_status="reviewed",
                    date_from=date(2026, 1, 1),
                    date_to=date(2026, 1, 1),
                ),
            )
        self.assertEqual([row["episode_uid"] for row in result.episodes], ["episode-a"])
        self.assertEqual([str(row["entry_uid"]) for row in result.entries], [str(result.entries[0]["entry_uid"])])
        self.assertEqual(result.entries[0]["body"], "Wait for the breakout above resistance.")

    def test_review_queue_filter_returns_traceable_incomplete_scope(self) -> None:
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            result = search_journal(
                con,
                JournalSearchFilters(review_queue="incomplete"),
            )
        self.assertEqual([row["episode_uid"] for row in result.episodes], ["episode-b"])
        self.assertEqual([row["episode_uid"] for row in result.entries], ["episode-b"])

    def test_unlinked_entries_remain_searchable(self) -> None:
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            result = search_journal(
                con,
                JournalSearchFilters(query_text="unlinked private"),
            )
        self.assertEqual(result.episodes, [])
        self.assertEqual(len(result.entries), 1)
        self.assertIsNone(result.entries[0]["episode_uid"])

    def test_saved_view_round_trips_structured_filters_only(self) -> None:
        filters = JournalSearchFilters(
            symbol="aapl",
            review_status="reviewed",
            entry_type="entry_thesis",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        )
        with duckdb.connect(str(self.db_path)) as con:
            saved_view_uid = create_saved_view(con, name="AAPL Reviews", filters=filters)
            listed = list_saved_views(con)
            name, loaded = load_saved_view(con, saved_view_uid)
        self.assertEqual(listed, [{"saved_view_uid": saved_view_uid, "name": "AAPL Reviews"}])
        self.assertEqual(name, "AAPL Reviews")
        self.assertEqual(loaded, JournalSearchFilters(
            symbol="AAPL",
            review_status="reviewed",
            entry_type="entry_thesis",
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
        ))


if __name__ == "__main__":
    unittest.main()
