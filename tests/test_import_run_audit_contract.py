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

        # Break lineage on one record in a new table we now actively
        # enforce in JRN-02.
        import duckdb

        with duckdb.connect(str(self.db_path), read_only=False) as con:
            con.execute(
                "UPDATE normalized_accounts SET import_run_id = NULL WHERE source_account_id='DEMO_ACCOUNT'"
            )

        rc, output = self._run_checker(["--db", str(self.db_path)])
        self.assertEqual(rc, 1)
        self.assertIn("normalized_accounts has", output)
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
