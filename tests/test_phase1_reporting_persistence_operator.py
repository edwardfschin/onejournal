from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from onejournal.api.broker_current_position_contracts import (
    BrokerCurrentFinancialReleaseAuthorization,
)
from onejournal.journal.broker_current_position_valuation_repository import (
    BrokerCurrentPositionValuationReadBack,
)
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.phase1_reporting_calculation import (
    ActiveHistoryAuthority,
    BoundedRealizedResult,
    RealizedAllocationResult,
    RealizedScopeOmission,
)
from onejournal.journal.phase1_reporting_persistence_operator import (
    Phase1ReportingPersistenceOperatorError,
    prepare_owner_accepted_reporting_release,
    rehearse_reporting_release,
    write_private_release_package,
)


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "scripts" / "journal" / "migrations"
NOW = datetime(2026, 9, 9, 2, 26, 29, 207000, tzinfo=UTC)


class Phase1ReportingPersistenceOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.db = self.root / "journal.duckdb"
        apply_schema_migrations(
            self.db, target_version="0025", migrations_dir=MIGRATIONS
        )
        self.db.chmod(0o600)
        self.authorization_path = self.root / "current-authorization.json"
        self.authorization_path.write_text("{}", encoding="utf-8")
        self.authorization_path.chmod(0o600)

    def _current(self) -> BrokerCurrentPositionValuationReadBack:
        return BrokerCurrentPositionValuationReadBack(
            valuation_run_uid="current-run",
            contract_version="onejournal.broker-current-position-valuation.v1",
            basis_method="broker_reconciled_current_position",
            snapshot_uid="snapshot-1",
            source_broker="schwab",
            connection_uid="connection-1",
            source_account_id="private-account",
            asof=date(2026, 9, 4),
            retrieved_at_utc="2026-09-04T20:00:00Z",
            evaluated_at_utc="2026-09-04T20:01:00Z",
            max_snapshot_age_seconds=3600,
            snapshot_age_seconds=Decimal("60"),
            currency_quantum_by_currency={"USD": Decimal("0.01")},
            position_count=1,
            cost_basis_available_count=1,
            market_value_available_count=1,
            unrealized_pnl_available_count=1,
            complete_portfolio_cost_basis_available=True,
            complete_portfolio_market_value_available=True,
            complete_portfolio_unrealized_pnl_available=True,
            financial_acceptance=False,
            result_fingerprint="a" * 64,
            final_status="complete",
            positions=(),
            portfolio_totals=(),
        )

    def _realized(self, *, account: str = "private-account") -> BoundedRealizedResult:
        authority = ActiveHistoryAuthority(
            revision_uid="history-1",
            result_fingerprint="b" * 64,
            source_broker="schwab",
            source_account_id=account,
            history_window_start=date(2026, 3, 6),
            history_window_end=date(2026, 9, 4),
            asof_date=date(2026, 9, 4),
            fill_count=2,
            episode_count=1,
            execution_count=2,
            lifecycle_resolved_scope_count=1,
            review_required_scope_count=0,
            closed_count=1,
            open_count=0,
            review_required_count=0,
            lifecycle_final_status="reconciled",
        )
        item = RealizedAllocationResult(
            item_uid="item-1",
            source_broker="schwab",
            source_account_id=account,
            instrument_key="equity:ABC",
            symbol="ABC",
            asset_class="equity",
            close_market_date=date(2026, 9, 1),
            closed_at_utc=datetime(2026, 9, 1, 20, tzinfo=UTC),
            currency="USD",
            realized_pnl=Decimal("12.34"),
            direction="long",
            quantity=Decimal("1"),
            multiplier=Decimal("1"),
            open_fill_uid="open-1",
            close_fill_uid="close-1",
            source_event_uid=None,
        )
        omission = RealizedScopeOmission(
            omission_uid="omit-1",
            source_broker="schwab",
            source_account_id=account,
            episode_uid="episode-1",
            close_market_date=date(2026, 8, 1),
            symbol="XYZ",
            reason_code="opening_history_missing",
            source_fill_uids=("fill-1",),
        )
        return BoundedRealizedResult(
            calculation_run_id="phase1-realized:" + "c" * 64,
            calculation_version="onejournal.pnl.test",
            calculated_at_utc=NOW,
            coverage_start_date=date(2026, 3, 6),
            coverage_end_date=date(2026, 9, 4),
            authorities=(authority,),
            fill_input_fingerprint="d" * 64,
            lifecycle_input_fingerprint="e" * 64,
            items=(item,),
            omissions=(omission,),
            result_fingerprint="c" * 64,
        )

    def _prepare(self, *, account: str = "private-account"):
        current_authorization = BrokerCurrentFinancialReleaseAuthorization(
            owner_acceptance_uid="current-acceptance",
            valuation_run_uid="current-run",
            result_fingerprint="a" * 64,
            accepted_at=datetime(2026, 9, 5, 2, 45, tzinfo=UTC),
            decision="accepted",
        )
        realized = self._realized(account=account)
        with (
            patch(
                "onejournal.journal.phase1_reporting_persistence_operator.load_broker_current_financial_release_authorization",
                return_value=current_authorization,
            ),
            patch(
                "onejournal.journal.phase1_reporting_persistence_operator.load_broker_current_position_valuation_run",
                return_value=self._current(),
            ),
            patch(
                "onejournal.journal.phase1_reporting_persistence_operator.build_broker_current_position_valuation_response"
            ),
            patch(
                "onejournal.journal.phase1_reporting_persistence_operator.calculate_bounded_realized_result",
                return_value=realized,
            ),
            patch(
                "onejournal.journal.phase1_reporting_persistence_operator.authorize_realized_result"
            ),
            patch(
                "onejournal.journal.phase1_reporting_persistence_operator.reporting_items",
                return_value=(),
            ),
            patch(
                "onejournal.journal.phase1_reporting_persistence_operator.reporting_omissions",
                return_value=(),
            ),
        ):
            return prepare_owner_accepted_reporting_release(
                db_path=self.db,
                broker_current_authorization_path=self.authorization_path,
                account_alias="Primary",
                expected_realized_result_fingerprint="c" * 64,
                realized_owner_acceptance_uid="realized-acceptance",
                realized_owner_accepted_at_utc=NOW,
                report_release_uid="report-release-1",
                generated_at_utc=NOW,
                report_owner_acceptance_uid="report-acceptance",
                report_owner_accepted_at_utc=NOW,
            )

    def test_preparation_binds_alias_and_separate_acceptances(self) -> None:
        release = self._prepare()
        self.assertEqual(release.accounts[0].account_alias, "Primary")
        self.assertEqual(release.current_owner_acceptance_uid, "current-acceptance")
        self.assertEqual(release.realized_owner_acceptance_uid, "realized-acceptance")
        self.assertEqual(release.owner_acceptance_uid, "report-acceptance")
        self.assertEqual(len(release.report_release_fingerprint), 64)

    def test_preparation_rejects_account_scope_mismatch(self) -> None:
        with self.assertRaisesRegex(
            Phase1ReportingPersistenceOperatorError, "identical account scope"
        ):
            self._prepare(account="different-private-account")

    def test_rehearsal_is_idempotent_and_leaves_source_unchanged(self) -> None:
        release = self._prepare()
        rehearsal_db = self.root / "rehearsal.duckdb"
        result = rehearse_reporting_release(
            source_db_path=self.db,
            rehearsal_db_path=rehearsal_db,
            release=release,
        )
        self.assertTrue(result.identical_replay_verified)
        self.assertEqual((result.release_count, result.account_count), (1, 1))
        self.assertEqual(result.migration_version, "0026")
        self.assertEqual(result.source_database_sha256, result.rehearsal_copy_before_sha256)

        package = self.root / "package"
        write_private_release_package(
            output_dir=package, release=release, rehearsal=result
        )
        self.assertEqual(stat_mode(package), 0o700)
        self.assertEqual(stat_mode(package / "manifest.json"), 0o600)
        document = json.loads((package / "manifest.json").read_text())
        self.assertEqual(document["account_aliases"], ["Primary"])
        serialized = json.dumps(document)
        self.assertNotIn("private-account", serialized)
        self.assertNotIn("12.34", serialized)
        self.assertFalse(document["database_write_performed"])


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
