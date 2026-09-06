from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

import duckdb
from fastapi.testclient import TestClient

from onejournal.api.app import app as demo_app
from onejournal.api.local_owner_journal import create_local_owner_journal_app
from onejournal.journal.migrations import apply_schema_migrations
from scripts.journal.init_journal_db import init_schema


class LocalOwnerJournalApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "journal.duckdb"
        init_schema(self.db_path)
        self.db_path.chmod(0o600)
        with duckdb.connect(str(self.db_path)) as con:
            con.execute(
                """
                INSERT INTO trade_episodes (
                    episode_uid, source_broker, source_account_id, primary_symbol,
                    asset_class, strategy_type, strategy_label, opened_at, status,
                    fill_count, leg_count, updated_at
                ) VALUES (
                    'episode-1', 'manual_csv', 'private-account-should-not-leak', 'AAPL',
                    'stock', 'stock_long', 'Stock Long', TIMESTAMP '2026-01-01 10:00:00',
                    'closed', 2, 1, TIMESTAMP '2026-01-02 10:00:00'
                )
                """
            )
            con.execute(
                """
                INSERT INTO trade_episode_legs (
                    episode_uid, leg_index, asset_class, symbol, side, quantity
                ) VALUES ('episode-1', 1, 'stock', 'AAPL', 'BUY', 10)
                """
            )
        self.client = TestClient(create_local_owner_journal_app(journal_db_path=self.db_path))

    def test_search_queue_and_lifecycle_are_private_versioned_and_audited(self) -> None:
        search = self.client.get("/api/v5/local-owner/journal/search", params={"symbol": "AAPL"})
        queues = self.client.get("/api/v5/local-owner/journal/review-queues")
        lifecycle = self.client.get("/api/v5/local-owner/journal/trades/episode-1")

        self.assertEqual(search.status_code, 200)
        self.assertEqual(queues.status_code, 200)
        self.assertEqual(lifecycle.status_code, 200)
        self.assertEqual(search.json()["metadata"]["contract_version"], "onejournal.local-owner-journal.v5")
        self.assertEqual(search.json()["metadata"]["mode"], "local_owner")
        self.assertTrue(search.json()["episodes"][0]["opened_at"].endswith("Z"))
        self.assertEqual(search.json()["episodes"][0]["primary_symbol"], "AAPL")
        self.assertEqual(search.json()["episodes"][0]["asset_class"], "stock")
        self.assertEqual(
            search.json()["episodes"][0]["position_reconciliation_status"],
            "not_applicable",
        )
        self.assertEqual(queues.json()["queues"]["unreviewed"][0]["reason_codes"], ["missing_review"])
        self.assertEqual(queues.json()["queues"]["unreviewed"][0]["asset_class"], "stock")
        self.assertEqual(
            queues.json()["queues"]["unreviewed"][0]["instrument_summary"],
            "Unverified legacy grouping",
        )
        self.assertEqual(lifecycle.json()["trade"]["instrument_summary"], "Unverified legacy grouping")
        self.assertEqual(lifecycle.json()["instruments"], [])
        self.assertEqual(lifecycle.json()["executions"], [])
        self.assertEqual(search.json()["presentation_groups"], [])
        self.assertEqual(queues.json()["presentation_groups"], [])
        self.assertEqual(search.json()["lifecycle_stories"], [])
        self.assertEqual(queues.json()["lifecycle_stories"], [])
        self.assertIsNone(lifecycle.json()["presentation_group"])
        self.assertIsNone(lifecycle.json()["lifecycle_story"])
        combined = repr([search.json(), queues.json(), lifecycle.json()])
        self.assertNotIn("private-account-should-not-leak", combined)
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            rows = con.execute(
                "SELECT action, request_sha256 FROM local_owner_api_audit_events ORDER BY occurred_at"
            ).fetchall()
        self.assertEqual([row[0] for row in rows], ["journal_search", "review_queue_read", "trade_lifecycle_read"])
        self.assertTrue(all(len(row[1]) == 64 for row in rows))

    def test_review_and_entry_writes_are_append_only_and_replay_safe(self) -> None:
        review_operation = str(uuid4())
        review_payload = {
            "episode_uid": "episode-1",
            "review_status": "reviewed",
            "setup_quality": "good",
            "entry_reason": "planned",
            "notes": "private review narrative",
        }
        first_review = self.client.post(
            "/api/v5/local-owner/journal/reviews",
            headers={"X-OneJournal-Operation-Id": review_operation},
            json=review_payload,
        )
        replay_review = self.client.post(
            "/api/v5/local-owner/journal/reviews",
            headers={"X-OneJournal-Operation-Id": review_operation},
            json=review_payload,
        )
        self.assertEqual(first_review.status_code, 200)
        self.assertFalse(first_review.json()["replayed"])
        self.assertEqual(replay_review.status_code, 200)
        self.assertTrue(replay_review.json()["replayed"])
        self.assertEqual(first_review.json()["resource_uid"], replay_review.json()["resource_uid"])

        create_operation = str(uuid4())
        created = self.client.post(
            "/api/v5/local-owner/journal/entries",
            headers={"X-OneJournal-Operation-Id": create_operation},
            json={
                "entry_type": "entry_thesis",
                "episode_uid": "episode-1",
                "title": "AAPL thesis",
                "body": "private entry body",
            },
        )
        self.assertEqual(created.status_code, 200)
        entry_uid = created.json()["resource_uid"]
        search_with_entry = self.client.get(
            "/api/v5/local-owner/journal/search", params={"q": "AAPL thesis"}
        )
        self.assertEqual(search_with_entry.status_code, 200)
        self.assertEqual(search_with_entry.json()["entries"][0]["entry_status"], "active")
        self.assertNotIn("body", search_with_entry.json()["entries"][0])
        self.assertNotIn("title", search_with_entry.json()["entries"][0])
        opened_entry = self.client.get(
            f"/api/v5/local-owner/journal/entries/{entry_uid}"
        )
        self.assertEqual(opened_entry.status_code, 200)
        self.assertEqual(opened_entry.json()["entry"]["body"], "private entry body")
        revised = self.client.post(
            f"/api/v5/local-owner/journal/entries/{entry_uid}/revisions",
            headers={"X-OneJournal-Operation-Id": str(uuid4())},
            json={
                "entry_type": "entry_thesis",
                "episode_uid": "episode-1",
                "title": "AAPL thesis revised",
                "body": "private revised body",
                "change_reason": "clarified thesis",
            },
        )
        self.assertEqual(revised.status_code, 200)
        self.assertEqual(revised.json()["revision_no"], 2)
        lifecycle = self.client.get("/api/v5/local-owner/journal/trades/episode-1")
        self.assertEqual(lifecycle.status_code, 200)
        self.assertEqual(lifecycle.json()["entries"][0]["body"], "private revised body")

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM journal_reviews").fetchone()[0], 1)
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM journal_entry_revisions WHERE entry_uid = ?", [entry_uid]).fetchone()[0],
                2,
            )
            audit_repr = repr(con.execute("SELECT * FROM local_owner_api_audit_events").fetchall())
        self.assertNotIn("private review narrative", audit_repr)
        self.assertNotIn("private entry body", audit_repr)

    def test_invalid_or_reused_operation_identity_fails_closed(self) -> None:
        invalid = self.client.post(
            "/api/v5/local-owner/journal/reviews",
            headers={"X-OneJournal-Operation-Id": "not-a-uuid"},
            json={"episode_uid": "episode-1", "review_status": "reviewed", "setup_quality": "good"},
        )
        self.assertEqual(invalid.status_code, 400)
        operation = str(uuid4())
        accepted = self.client.post(
            "/api/v5/local-owner/journal/reviews",
            headers={"X-OneJournal-Operation-Id": operation},
            json={"episode_uid": "episode-1", "review_status": "reviewed", "setup_quality": "good"},
        )
        conflict = self.client.post(
            "/api/v5/local-owner/journal/reviews",
            headers={"X-OneJournal-Operation-Id": operation},
            json={"episode_uid": "episode-1", "review_status": "needs_review", "setup_quality": "poor"},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(conflict.status_code, 409)

    def test_concurrent_identical_write_is_serialized_and_replayed(self) -> None:
        operation = str(uuid4())
        payload = {
            "episode_uid": "episode-1",
            "review_status": "reviewed",
            "setup_quality": "good",
        }

        def write_review(_: int):
            return self.client.post(
                "/api/v5/local-owner/journal/reviews",
                headers={"X-OneJournal-Operation-Id": operation},
                json=payload,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(write_review, range(2)))

        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(sorted(response.json()["replayed"] for response in responses), [False, True])
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM journal_reviews").fetchone()[0], 1)

    def test_demo_app_never_registers_private_routes_and_factory_requires_existing_db(self) -> None:
        self.assertEqual(
            TestClient(demo_app).get("/api/v5/local-owner/journal/search").status_code,
            404,
        )
        with self.assertRaisesRegex(ValueError, "must already exist"):
            create_local_owner_journal_app(journal_db_path=Path(self.tmp.name) / "missing.duckdb")
        unsafe_mode_path = Path(self.tmp.name) / "unsafe-mode.duckdb"
        init_schema(unsafe_mode_path)
        unsafe_mode_path.chmod(0o644)
        with self.assertRaisesRegex(ValueError, "mode 0600"):
            create_local_owner_journal_app(journal_db_path=unsafe_mode_path)
        safe_target_path = Path(self.tmp.name) / "safe-target.duckdb"
        init_schema(safe_target_path)
        safe_target_path.chmod(0o600)
        symlink_path = Path(self.tmp.name) / "journal-link.duckdb"
        symlink_path.symlink_to(safe_target_path)
        with self.assertRaisesRegex(ValueError, "must not be a symlink"):
            create_local_owner_journal_app(journal_db_path=symlink_path)
        unmigrated_path = Path(self.tmp.name) / "unmigrated.duckdb"
        apply_schema_migrations(unmigrated_path, target_version="0016")
        unmigrated_path.chmod(0o600)
        with self.assertRaisesRegex(ValueError, "local API audit migrations"):
            create_local_owner_journal_app(journal_db_path=unmigrated_path)


if __name__ == "__main__":
    unittest.main()
