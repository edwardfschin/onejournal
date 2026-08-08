from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from scripts.journal.build_dashboard_payload_from_db import build_payload
from scripts.journal.check_db_dashboard_contract import validate_payload
from scripts.journal.import_journal_to_db import import_to_db
from scripts.journal.init_journal_db import init_schema


PROJECT_DIR = Path(__file__).resolve().parents[1]
FILLS_FIXTURE = PROJECT_DIR / "docs/examples/manual_csv/fills_template.csv"
REVIEWS_FIXTURE = PROJECT_DIR / "data/journal/reviews/manual_reviews.csv"


class JournalPipelineIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "onejournal_test.duckdb"
        init_schema(self.db_path)

    def test_import_and_dashboard_build_use_only_temporary_database(self) -> None:
        counts = import_to_db(
            self.db_path,
            FILLS_FIXTURE,
            REVIEWS_FIXTURE,
            replace=True,
            asof=date(2026, 6, 2),
        )

        self.assertEqual(
            counts,
            {
                "import_runs": 1,
                "normalized_fills": 12,
                "trade_episodes": 8,
                "trade_episode_legs": 12,
                "manual_reviews": 8,
            },
        )

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            duplicate_fills = con.execute(
                "SELECT COUNT(*) FROM (SELECT fill_uid FROM normalized_fills GROUP BY fill_uid HAVING COUNT(*) > 1)"
            ).fetchone()[0]
            self.assertEqual(duplicate_fills, 0)
            linked_imports = con.execute(
                "SELECT COUNT(*) FROM normalized_fills WHERE import_run_id IS NOT NULL"
            ).fetchone()[0]
            self.assertEqual(linked_imports, 12)

        payload = build_payload(self.db_path, "2026-06-02")
        self.assertEqual(payload["metadata"]["source"], "duckdb")
        self.assertEqual(payload["metadata"]["auto_trade"], "disabled")
        self.assertEqual(payload["metadata"]["record_counts"]["trade_episode_previews"], 8)
        self.assertEqual(payload["trade_summary"]["gross_cashflow"], "-10415.00")
        self.assertEqual(payload["trade_summary"]["realized_pnl_by_currency"], {"USD": "0.00"})
        self.assertEqual(payload["trade_summary"]["unrealized_pnl_by_currency"], {"USD": None})
        self.assertEqual(validate_payload(payload, "2026-06-02", self.db_path), 0)

        reviewed = next(
            row
            for row in payload["recent_trade_episodes"]
            if row["episode_uid"] == "manual_csv:DEMO_ACCOUNT:option:AAPL_SELL_PUT_001"
        )
        self.assertEqual(reviewed["review_status"], "reviewed")
        self.assertEqual(reviewed["setup_quality"], "acceptable")

    def test_import_rejects_asof_mismatch_before_writing_rows(self) -> None:
        with self.assertRaisesRegex(ValueError, "asof different"):
            import_to_db(
                self.db_path,
                FILLS_FIXTURE,
                REVIEWS_FIXTURE,
                replace=True,
                asof=date(2026, 6, 3),
            )

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM normalized_fills").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0], 0)

    def test_dashboard_contract_rejects_duplicate_episode_ids(self) -> None:
        import_to_db(
            self.db_path,
            FILLS_FIXTURE,
            REVIEWS_FIXTURE,
            replace=True,
            asof=date(2026, 6, 2),
        )
        payload = build_payload(self.db_path, "2026-06-02")
        invalid = copy.deepcopy(payload)
        invalid["recent_trade_episodes"].append(copy.deepcopy(invalid["recent_trade_episodes"][0]))

        with self.assertLogs("onejournal.db_dashboard_contract", level="ERROR") as captured:
            self.assertEqual(validate_payload(invalid, "2026-06-02", self.db_path), 1)
        self.assertIn("duplicate episode_uid", "\n".join(captured.output))


if __name__ == "__main__":
    unittest.main()
