from __future__ import annotations

import copy
import tempfile
import unittest
from datetime import date
from decimal import Decimal
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
                "normalized_accounts": 1,
                "normalized_orders": 8,
                "normalized_positions": 12,
                "normalized_transactions": 12,
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
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM normalized_accounts WHERE import_run_id IS NOT NULL"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM normalized_orders WHERE import_run_id IS NOT NULL"
                ).fetchone()[0],
                8,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM normalized_positions WHERE import_run_id IS NOT NULL"
                ).fetchone()[0],
                12,
            )
            self.assertEqual(
                con.execute(
                    "SELECT COUNT(*) FROM normalized_transactions WHERE import_run_id IS NOT NULL"
                ).fetchone()[0],
                12,
            )

        payload = build_payload(self.db_path, "2026-06-02")
        self.assertEqual(payload["metadata"]["source"], "duckdb")
        self.assertEqual(payload["metadata"]["auto_trade"], "disabled")
        self.assertEqual(payload["metadata"]["quality"]["overall_status"], "valid")
        self.assertEqual(payload["metadata"]["trade_summary_status"]["gross_cashflow"], "valid")
        self.assertEqual(payload["metadata"]["trade_summary_status"]["realized_pnl_by_currency"], "valid")
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

    def test_payload_quality_flags_incomplete_for_missing_asof(self) -> None:
        import_to_db(
            self.db_path,
            FILLS_FIXTURE,
            REVIEWS_FIXTURE,
            replace=True,
            asof=date(2026, 6, 2),
        )
        payload = build_payload(self.db_path, "2026-06-03")
        self.assertEqual(payload["metadata"]["quality"]["overall_status"], "stale")
        self.assertEqual(payload["metadata"]["quality"]["checks"]["asof"]["status"], "stale")
        self.assertEqual(payload["metadata"]["trade_summary_status"]["gross_cashflow"], "stale")

    def test_payload_quality_flags_failed_for_bad_import_status(self) -> None:
        import_to_db(
            self.db_path,
            FILLS_FIXTURE,
            REVIEWS_FIXTURE,
            replace=True,
            asof=date(2026, 6, 2),
        )
        with duckdb.connect(str(self.db_path), read_only=False) as con:
            con.execute("UPDATE import_runs SET status='error' WHERE 1=1")

        payload = build_payload(self.db_path, "2026-06-02")
        self.assertEqual(payload["metadata"]["quality"]["overall_status"], "failed")
        self.assertEqual(payload["metadata"]["quality"]["checks"]["import"]["status"], "failed")
        self.assertEqual(payload["metadata"]["quality"]["checks"]["import"]["reason"], "import status 'error' is not accepted")
        self.assertEqual(payload["metadata"]["trade_summary_status"]["fees"], "failed")

    def test_import_accepts_lifecycle_side_variants(self) -> None:
        fills_csv = Path(self.temp_dir.name) / "lifecycle_side_fills.csv"
        reviews_csv = Path(self.temp_dir.name) / "lifecycle_side_reviews.csv"
        fills_csv.write_text(
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id
2026-01-01,manual_csv,DEMO_ACCOUNT,F-LONG-OPEN,2026-01-01T10:00:00+00:00,stock,AAPL,BUY_TO_OPEN,1,100,0,0,USD,ORD-1
2026-01-01,manual_csv,DEMO_ACCOUNT,F-LONG-CLOSE,2026-01-01T11:00:00+00:00,stock,AAPL,SELL_TO_CLOSE,1,110,0,0,USD,ORD-2
2026-01-01,manual_csv,DEMO_ACCOUNT,F-SHORT-OPEN,2026-01-01T10:15:00+00:00,stock,TSLA,SELL_TO_OPEN,1,50,0,0,USD,ORD-3
2026-01-01,manual_csv,DEMO_ACCOUNT,F-SHORT-CLOSE,2026-01-01T11:30:00+00:00,stock,TSLA,BUY_TO_CLOSE,1,50,0,0,USD,ORD-4
""",
            encoding="utf-8",
        )
        reviews_csv.write_text(
            "episode_uid,review_status,setup_quality,entry_reason,notes\n"
            "manual_csv:DEMO_ACCOUNT:stock:AAPL,reviewed,acceptable,,\n"
            "manual_csv:DEMO_ACCOUNT:stock:TSLA,reviewed,acceptable,,\n",
            encoding="utf-8",
        )

        counts = import_to_db(
            self.db_path,
            fills_csv,
            reviews_csv,
            replace=True,
            asof=date(2026, 1, 1),
        )

        self.assertEqual(counts["normalized_fills"], 4)
        self.assertEqual(counts["normalized_positions"], 2)
        self.assertEqual(counts["normalized_transactions"], 4)

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            positions = con.execute(
                "SELECT symbol, quantity FROM normalized_positions ORDER BY symbol"
            ).fetchall()
            self.assertEqual(
                positions,
                [
                    ("AAPL", Decimal("0")),
                    ("TSLA", Decimal("0")),
                ],
            )

            txns = con.execute(
                "SELECT symbol, amount FROM normalized_transactions ORDER BY symbol, transaction_at"
            ).fetchall()
            self.assertEqual(
                txns,
                [
                    ("AAPL", Decimal("-100")),
                    ("AAPL", Decimal("110")),
                    ("TSLA", Decimal("50")),
                    ("TSLA", Decimal("-50")),
                ],
            )

    def test_import_rejects_conflicting_fill_replays_without_replace(self) -> None:
        base_fills_csv = Path(self.temp_dir.name) / "base_fills.csv"
        conflict_fills_csv = Path(self.temp_dir.name) / "conflict_fills.csv"
        reviews_csv = Path(self.temp_dir.name) / "reviews.csv"

        base_fills_csv.write_text(
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id,option_symbol,underlying_symbol,option_type,expiry,strike,multiplier,open_close,execution_venue,liquidity_flag,episode_group_id
2026-06-02,manual_csv,DEMO_ACCOUNT,FILL-001,2026-06-02T10:00:00+00:00,stock,AAPL,BUY,1,150,0.10,0.20,USD,ORDER-001,,,,,,,,,,
""",
            encoding="utf-8",
        )
        conflict_fills_csv.write_text(
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id,option_symbol,underlying_symbol,option_type,expiry,strike,multiplier,open_close,execution_venue,liquidity_flag,episode_group_id
2026-06-02,manual_csv,DEMO_ACCOUNT,FILL-001,2026-06-02T10:00:00+00:00,stock,AAPL,BUY,1,150,1.99,0.20,USD,ORDER-001,,,,,,,,,,
""",
            encoding="utf-8",
        )
        reviews_csv.write_text(
            "episode_uid,review_status,setup_quality,entry_reason,notes\n"
            "manual_csv:DEMO_ACCOUNT:stock:AAPL,reviewed,acceptable,,\n",
            encoding="utf-8",
        )

        import_to_db(
            self.db_path,
            base_fills_csv,
            reviews_csv,
            replace=True,
            asof=date(2026, 6, 2),
        )

        with self.assertRaisesRegex(
            ValueError, "conflicting fill replays detected; run import with --replace"
        ):
            import_to_db(
                self.db_path,
                conflict_fills_csv,
                reviews_csv,
                replace=False,
                asof=date(2026, 6, 2),
            )

    def test_replace_reimport_tracks_fill_revisions_and_preserves_manual_reviews(self) -> None:
        base_fills_csv = Path(self.temp_dir.name) / "base_fills.csv"
        corrected_fills_csv = Path(self.temp_dir.name) / "corrected_fills.csv"
        reviews_csv = Path(self.temp_dir.name) / "reviews.csv"

        base_fills_csv.write_text(
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id,option_symbol,underlying_symbol,option_type,expiry,strike,multiplier,open_close,execution_venue,liquidity_flag,episode_group_id
2026-06-02,manual_csv,DEMO_ACCOUNT,FILL-001,2026-06-02T10:00:00+00:00,stock,AAPL,BUY,1,150,0.10,0.20,USD,ORDER-001,,,,,,,,,,
""",
            encoding="utf-8",
        )
        corrected_fills_csv.write_text(
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id,option_symbol,underlying_symbol,option_type,expiry,strike,multiplier,open_close,execution_venue,liquidity_flag,episode_group_id
2026-06-02,manual_csv,DEMO_ACCOUNT,FILL-001,2026-06-02T10:00:00+00:00,stock,AAPL,BUY,1,150,0.15,0.20,USD,ORDER-001,,,,,,,,,,
""",
            encoding="utf-8",
        )
        reviews_csv.write_text(
            "episode_uid,review_status,setup_quality,entry_reason,notes\n"
            "manual_csv:DEMO_ACCOUNT:stock:AAPL,reviewed,acceptable,,\n",
            encoding="utf-8",
        )

        import_to_db(
            self.db_path,
            base_fills_csv,
            reviews_csv,
            replace=True,
            asof=date(2026, 6, 2),
        )
        with duckdb.connect(str(self.db_path), read_only=True) as con:
            first_reviews_expected = con.execute(
                "SELECT COUNT(*) FROM manual_reviews"
            ).fetchone()[0]

        import_to_db(
            self.db_path,
            corrected_fills_csv,
            reviews_csv,
            replace=True,
            asof=date(2026, 6, 2),
        )

        with duckdb.connect(str(self.db_path), read_only=True) as con:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM manual_reviews").fetchone()[0],
                first_reviews_expected,
            )
            revisions = con.execute(
                """
                SELECT event_type, prior_signature, next_signature, prior_payload_json, next_payload_json
                FROM normalized_fill_revisions
                """
            ).fetchall()
            self.assertEqual(len(revisions), 1)
            self.assertEqual(revisions[0][0], "correction_rewrite")
            self.assertIsNotNone(revisions[0][3])
            self.assertIsNotNone(revisions[0][4])
            self.assertNotEqual(revisions[0][1], revisions[0][2])
            self.assertEqual(
                con.execute(
                    "SELECT commission FROM normalized_fills WHERE source_fill_id='FILL-001'"
                ).fetchone()[0],
                Decimal("0.15"),
            )

if __name__ == "__main__":
    unittest.main()
