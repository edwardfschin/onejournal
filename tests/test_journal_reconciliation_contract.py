from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from scripts.journal.import_journal_to_db import import_to_db
from scripts.journal.init_journal_db import init_schema


class JournalReconciliationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "onejournal_reconciliation.duckdb"
        init_schema(self.db_path)

    def _write_csv(self, name: str, text: str) -> Path:
        path = Path(self.temp_dir.name) / name
        path.write_text(text, encoding="utf-8")
        return path

    def _write_review_file(self, episode: str = "manual_csv:DEMO_ACCOUNT:stock:AAPL") -> Path:
        path = Path(self.temp_dir.name) / "reviews.csv"
        path.write_text(
            "episode_uid,review_status,setup_quality,entry_reason,notes\n"
            f"{episode},reviewed,acceptable,,\n",
            encoding="utf-8",
        )
        return path

    def _run_reconciliation(self, *, asof: str, policy: str = "publish") -> tuple[int, str]:
        result = subprocess.run(
            [
                sys.executable,
                "scripts/journal/check_journal_reconciliation.py",
                "--db",
                str(self.db_path),
                "--asof",
                asof,
                "--policy",
                policy,
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        return result.returncode, result.stdout + result.stderr

    def test_publish_policy_passes_for_balanced_journal(self) -> None:
        fills_csv = self._write_csv(
            "fills.csv",
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id
2026-06-02,manual_csv,DEMO_ACCOUNT,FILL-001,2026-06-02T10:00:00+00:00,stock,AAPL,BUY,1,150.00,0.10,0.20,USD,ORDER-001
""",
        )

        code, output = self._run_reconciliation(asof="2026-06-02")
        self.assertEqual(code, 1)
        self.assertIn("failed no fills found for asof", output)

        import_to_db(self.db_path, fills_csv, self._write_review_file(), replace=True, asof=date(2026, 6, 2))

        code, output = self._run_reconciliation(asof="2026-06-02", policy="publish")
        self.assertEqual(code, 0)
        self.assertIn("ISSUES               : 0", output)

    def test_position_mismatch_blocks_publish_and_strict_publishes_zero(self) -> None:
        fills_csv = self._write_csv(
            "fills.csv",
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id
2026-06-02,manual_csv,DEMO_ACCOUNT,FILL-001,2026-06-02T10:00:00+00:00,stock,AAPL,BUY,1,150.00,0.10,0.20,USD,ORDER-001
""",
        )
        import_to_db(self.db_path, fills_csv, self._write_review_file(), replace=True, asof=date(2026, 6, 2))

        with duckdb.connect(str(self.db_path), read_only=False) as con:
            con.execute(
                """
                UPDATE normalized_positions
                SET quantity = 0
                WHERE source_broker='manual_csv' AND source_account_id='DEMO_ACCOUNT' AND asof_date='2026-06-02'
                """
            )

        code, output = self._run_reconciliation(asof="2026-06-02", policy="publish")
        self.assertEqual(code, 1)
        self.assertIn("BLOCKER", output)
        self.assertIn("position mismatch", output)

    def test_warning_only_mismatches_dont_block_publish(self) -> None:
        fills_csv = self._write_csv(
            "fills.csv",
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id
2026-06-02,manual_csv,DEMO_ACCOUNT,FILL-001,2026-06-02T10:00:00+00:00,stock,AAPL,BUY,1,150.00,0.10,0.20,USD,ORDER-001
""",
        )
        import_to_db(self.db_path, fills_csv, self._write_review_file(), replace=True, asof=date(2026, 6, 2))

        with duckdb.connect(str(self.db_path), read_only=False) as con:
            con.execute(
                """
                INSERT INTO normalized_transactions (
                    transaction_uid, source_broker, source_account_id, source_transaction_id,
                    asof_date, transaction_at, transaction_type, amount, currency,
                    fetched_at, raw_path, symbol, asset_class, quantity, price,
                    commission, fees, description, linked_order_id, linked_fill_id, import_run_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "manual_csv:DEMO_ACCOUNT:FEE-METADATA",
                    "manual_csv",
                    "DEMO_ACCOUNT",
                    "FEE-METADATA",
                    "2026-06-02",
                    "2026-06-02 10:00:00",
                    "FEE",
                    0,
                    "USD",
                    "2026-06-02 10:00:00",
                    "meta",
                    "AAPL",
                    "stock",
                    0,
                    0,
                    0,
                    0,
                    "metadata only",
                    None,
                    None,
                    None,
                ),
            )

        publish_code, publish_output = self._run_reconciliation(asof="2026-06-02", policy="publish")
        strict_code, strict_output = self._run_reconciliation(asof="2026-06-02", policy="strict")

        self.assertEqual(publish_code, 0)
        self.assertIn("WARNING", publish_output)
        self.assertEqual(strict_code, 1)
        self.assertIn("STATUS    : failed", strict_output)


if __name__ == "__main__":
    unittest.main()
