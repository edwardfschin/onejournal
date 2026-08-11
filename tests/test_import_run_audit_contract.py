from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest import mock

from scripts.journal.check_import_run_audit import main
from scripts.journal.import_journal_to_db import import_to_db
from scripts.journal.init_journal_db import init_schema

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FILLS_FIXTURE = PROJECT_ROOT / "docs/examples/manual_csv/fills_template.csv"
REVIEWS_FIXTURE = PROJECT_ROOT / "data/journal/reviews/manual_reviews.csv"


class ImportRunAuditContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.db_path = Path(self.temp_dir.name) / "onejournal_test.duckdb"
        init_schema(self.db_path)

    def _run_checker(self, args: list[str]) -> tuple[int, str]:
        out = io.StringIO()
        with mock.patch("sys.argv", ["check_import_run_audit.py", *args]), redirect_stdout(out):
            return main(), out.getvalue()

    def test_audit_passes_with_valid_import(self) -> None:
        import_to_db(
            self.db_path,
            FILLS_FIXTURE,
            REVIEWS_FIXTURE,
            replace=True,
            asof=date(2026, 6, 2),
        )

        rc, output = self._run_checker(["--db", str(self.db_path)])
        self.assertEqual(rc, 0)
        self.assertIn("STATUS    : OK", output)

    def test_audit_detects_orphaned_normalized_records(self) -> None:
        import_to_db(
            self.db_path,
            FILLS_FIXTURE,
            REVIEWS_FIXTURE,
            replace=True,
            asof=date(2026, 6, 2),
        )

        # Break lineage on one record in active tables we now enforce.
        import duckdb

        with duckdb.connect(str(self.db_path), read_only=False) as con:
            con.execute(
                "UPDATE normalized_accounts SET import_run_id = NULL WHERE source_account_id='DEMO_ACCOUNT'"
            )

        rc, output = self._run_checker(["--db", str(self.db_path)])
        self.assertEqual(rc, 1)
        self.assertIn("normalized_accounts has", output)
        self.assertIn("without import_run_id", output)

    def test_audit_detects_orphaned_normalized_lifecycle_records(self) -> None:
        fills_csv = Path(self.temp_dir.name) / "lifecycle_fills.csv"
        reviews_csv = Path(self.temp_dir.name) / "lifecycle_reviews.csv"
        lifecycle_csv = Path(self.temp_dir.name) / "lifecycle_rows.csv"
        lifecycle_legs_csv = Path(self.temp_dir.name) / "lifecycle_leg_rows.csv"
        fills_csv.write_text(
            """asof,source_broker,source_account_id,source_fill_id,filled_at,asset_class,symbol,side,quantity,fill_price,commission,fees,currency,source_order_id
2026-06-02,manual_csv,DEMO_ACCOUNT,FILL-001,2026-06-02T10:00:00+00:00,stock,AAPL,BUY,1,150,0,0,USD,ORDER-001
""",
            encoding="utf-8",
        )
        reviews_csv.write_text(
            "episode_uid,review_status,setup_quality,entry_reason,notes\n"
            "manual_csv:DEMO_ACCOUNT:stock:AAPL,reviewed,acceptable,,\n",
            encoding="utf-8",
        )
        lifecycle_csv.write_text(
            """event_uid,source_broker,source_account_id,source_activity_id,source_order_id,source_position_id,event_class,event_type,asof,event_at,event_name
swab:DEMO:evt:001,manual_csv,DEMO_ACCOUNT,ACT-001,ORDER-001,POS-001,TRANSACTION_LIFECYCLE,activityType:ASSIGNMENT,2026-06-02,2026-06-02T10:00:00+00:00,assignment
""",
            encoding="utf-8",
        )
        lifecycle_legs_csv.write_text(
            """event_leg_uid,event_uid,leg_index,leg_kind,asset_class,symbol,option_symbol,underlying_symbol,option_type,expiry,strike,multiplier,signed_quantity,price,cash_amount,position_effect,fee_type,currency,deliverable_json,evidence_status,evidence_notes
swab:DEMO:evt:001:item:0,swab:DEMO:evt:001,0,security,stock,AAPL,,,,,,,,1,,,,USD,,observed,
""",
            encoding="utf-8",
        )

        import_to_db(
            self.db_path,
            fills_csv,
            reviews_csv,
            replace=True,
            lifecycle_events=lifecycle_csv,
            lifecycle_event_legs=lifecycle_legs_csv,
            asof=date(2026, 6, 2),
        )

        import duckdb
        with duckdb.connect(str(self.db_path), read_only=False) as con:
            con.execute(
                "UPDATE normalized_lifecycle_events SET import_run_id = NULL WHERE event_uid='swab:DEMO:evt:001'"
            )
            con.execute(
                "UPDATE normalized_lifecycle_event_legs SET import_run_id = NULL WHERE event_leg_uid='swab:DEMO:evt:001:item:0'"
            )

        rc, output = self._run_checker(["--db", str(self.db_path)])
        self.assertEqual(rc, 1)
        self.assertIn("normalized_lifecycle_events has", output)
        self.assertIn("normalized_lifecycle_event_legs has", output)
        self.assertIn("without import_run_id", output)

    def test_audit_fails_when_import_status_not_ok(self) -> None:
        import_to_db(
            self.db_path,
            FILLS_FIXTURE,
            REVIEWS_FIXTURE,
            replace=True,
            asof=date(2026, 6, 2),
        )

        import duckdb
        with duckdb.connect(str(self.db_path), read_only=False) as con:
            con.execute("UPDATE import_runs SET status='error' WHERE 1=1")

        rc, output = self._run_checker(["--db", str(self.db_path)])
        self.assertEqual(rc, 1)
        self.assertIn("non-ok status", output)

    def test_audit_reports_missing_db(self) -> None:
        missing = self.db_path.parent / "missing.duckdb"
        rc, output = self._run_checker(["--db", str(missing)])
        self.assertEqual(rc, 1)
        self.assertIn("failed missing DB", output)


if __name__ == "__main__":
    unittest.main()
