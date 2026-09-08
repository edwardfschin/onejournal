from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.phase1_reporting_repository import (
    Phase1ReportingError,
    RealizedHistoryItem,
    ReportingAccount,
    ReportingOmission,
    ReportingRelease,
    calculate_report_release_fingerprint,
    load_reporting_release,
    persist_reporting_release,
    realized_history,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "scripts" / "journal" / "migrations"


class Phase1ReportingRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "reporting.duckdb"
        apply_schema_migrations(self.path, migrations_dir=MIGRATIONS)

    def _release(self, *, omissions: tuple[ReportingOmission, ...] = ()) -> ReportingRelease:
        base = dict(
            report_release_uid="report-release-1",
            current_valuation_run_uid="current-run-1",
            current_result_fingerprint="a" * 64,
            realized_calculation_run_id="realized-run-1",
            realized_result_fingerprint="b" * 64,
            history_revision_uid="history-revision-1",
            coverage_start_date=date(2026, 1, 1),
            coverage_end_date=date(2026, 1, 31),
            calculation_version="onejournal.pnl.v1",
            generated_at_utc=datetime(2026, 2, 1, tzinfo=UTC),
            release_status="owner_accepted",
            owner_acceptance_uid="owner-acceptance-1",
            owner_accepted_at_utc=datetime(2026, 2, 1, 1, tzinfo=UTC),
            accounts=(ReportingAccount("schwab", "private-account-id", "Primary"),),
            items=(RealizedHistoryItem("item-1", "schwab", "private-account-id", "instrument-1", "ABC", "equity", date(2026, 1, 12), datetime(2026, 1, 12, 20, tzinfo=UTC), "USD", Decimal("12.34")),),
            omissions=omissions,
        )
        provisional = ReportingRelease(**base, report_release_fingerprint="")
        return ReportingRelease(**base, report_release_fingerprint=calculate_report_release_fingerprint(release=provisional))

    def test_persistence_is_immutable_and_history_fails_closed(self) -> None:
        release = self._release(omissions=(ReportingOmission("omit-1", "schwab", "private-account-id", date(2026, 1, 12), "ABC", "opening_history_missing", "incomplete"),))
        with duckdb.connect(str(self.path)) as con:
            persist_reporting_release(con, release)
            persist_reporting_release(con, release)
            loaded = load_reporting_release(con, report_release_uid=release.report_release_uid)
        self.assertEqual(loaded.report_release_fingerprint, release.report_release_fingerprint)
        state, rows, reasons = realized_history(loaded, from_date=date(2026, 1, 1), to_date=date(2026, 1, 31))
        self.assertEqual(state, "incomplete")
        self.assertEqual(rows[0].realized_pnl, Decimal("12.34"))
        self.assertEqual(reasons, {"opening_history_missing": 1})
        state, rows, reasons = realized_history(loaded, from_date=date(2026, 1, 13), to_date=date(2026, 1, 31))
        self.assertEqual((state, rows, reasons), ("valid", (), {}))
        state, rows, reasons = realized_history(loaded, from_date=date(2025, 12, 31), to_date=date(2026, 1, 31))
        self.assertEqual((state, rows, reasons), ("unavailable", (), {"outside_accepted_coverage": 1}))

    def test_alias_and_fingerprint_conflicts_are_rejected(self) -> None:
        release = self._release()
        with duckdb.connect(str(self.path)) as con:
            persist_reporting_release(con, release)
            altered = ReportingRelease(**{**release.__dict__, "current_result_fingerprint": "c" * 64})
            with self.assertRaises(Phase1ReportingError):
                persist_reporting_release(con, altered)


if __name__ == "__main__":
    unittest.main()
