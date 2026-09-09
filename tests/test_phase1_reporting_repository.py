from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import json
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
    REPORTING_RELEASE_AUTHORIZATION_VERSION,
    calculate_report_release_fingerprint,
    load_reporting_release,
    load_reporting_release_authorization,
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
            current_owner_acceptance_uid="current-owner-acceptance-1",
            current_owner_accepted_at_utc=datetime(2026, 1, 31, 22, tzinfo=UTC),
            realized_calculation_run_id="realized-run-1",
            realized_result_fingerprint="b" * 64,
            realized_owner_acceptance_uid="realized-owner-acceptance-1",
            realized_owner_accepted_at_utc=datetime(2026, 1, 31, 23, tzinfo=UTC),
            history_revision_uid="history-revision-1",
            coverage_start_date=date(2026, 1, 1),
            coverage_end_date=date(2026, 1, 31),
            calculation_version="onejournal.pnl.v1",
            generated_at_utc=datetime(2026, 2, 1, tzinfo=UTC),
            release_status="owner_accepted",
            owner_acceptance_uid="owner-acceptance-1",
            owner_accepted_at_utc=datetime(2026, 2, 1, 1, tzinfo=UTC),
            accounts=(ReportingAccount("schwab", "private-account-id", "Primary"),),
            items=(RealizedHistoryItem("item-1", "schwab", "private-account-id", "instrument-1", "ABC", "equity", date(2026, 1, 12), datetime(2026, 1, 12, 20, tzinfo=UTC), "USD", Decimal("12.345678901234567890123456789")),),
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
        self.assertEqual(
            loaded.current_owner_acceptance_uid,
            "current-owner-acceptance-1",
        )
        self.assertEqual(
            loaded.realized_owner_acceptance_uid,
            "realized-owner-acceptance-1",
        )
        state, rows, reasons = realized_history(loaded, from_date=date(2026, 1, 1), to_date=date(2026, 1, 31))
        self.assertEqual(state, "incomplete")
        self.assertEqual(
            rows[0].realized_pnl,
            Decimal("12.345678901234567890123456789"),
        )
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

    def test_missing_financial_input_acceptance_is_rejected(self) -> None:
        release = self._release()
        missing_acceptance = ReportingRelease(
            **{
                **release.__dict__,
                "realized_owner_acceptance_uid": "",
            }
        )
        with duckdb.connect(str(self.path)) as con:
            with self.assertRaisesRegex(
                Phase1ReportingError,
                "separate owner acceptance identities",
            ):
                persist_reporting_release(con, missing_acceptance)

    def test_authorization_loader_requires_exact_private_document(self) -> None:
        authorization_path = Path(self.tmp.name) / "report-authorization.json"
        authorization_path.write_text(
            json.dumps(
                {
                    "contract_version": REPORTING_RELEASE_AUTHORIZATION_VERSION,
                    "report_release_uid": "report-release-1",
                    "report_release_fingerprint": "a" * 64,
                    "owner_acceptance_uid": "owner-acceptance-1",
                    "decision": "accepted",
                    "accepted_scope": "bounded_phase1_reporting",
                    "approval_source": "project_owner_explicit_proceed",
                }
            ),
            encoding="utf-8",
        )
        authorization_path.chmod(0o600)

        authorization = load_reporting_release_authorization(authorization_path)

        self.assertEqual(authorization.report_release_uid, "report-release-1")
        self.assertEqual(authorization.report_release_fingerprint, "a" * 64)
        authorization_path.chmod(0o644)
        with self.assertRaisesRegex(Phase1ReportingError, "mode 0600"):
            load_reporting_release_authorization(authorization_path)
        authorization_path.chmod(0o600)
        link_path = Path(self.tmp.name) / "report-authorization-link.json"
        link_path.symlink_to(authorization_path)
        with self.assertRaisesRegex(Phase1ReportingError, "symlink"):
            load_reporting_release_authorization(link_path)


if __name__ == "__main__":
    unittest.main()
