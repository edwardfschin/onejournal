from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import duckdb

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
    AUTHORIZATION_FILENAME,
    Phase1ReportingPersistenceOperatorError,
    execute_reporting_release_persistence,
    prepare_owner_accepted_reporting_release,
    prepare_reporting_release_from_package,
    rehearse_reporting_release,
    write_private_release_package,
)
from onejournal.journal.phase1_reporting_repository import (
    RealizedHistoryItem,
    ReportingOmission,
    load_reporting_release,
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

    @contextmanager
    def _preparation_context(self, *, account: str = "private-account"):
        current_authorization = BrokerCurrentFinancialReleaseAuthorization(
            owner_acceptance_uid="current-acceptance",
            valuation_run_uid="current-run",
            result_fingerprint="a" * 64,
            accepted_at=datetime(2026, 9, 5, 2, 45, tzinfo=UTC),
            decision="accepted",
        )
        realized = self._realized(account=account)
        item = realized.items[0]
        omission = realized.omissions[0]
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
                return_value=(
                    RealizedHistoryItem(
                        item_uid=item.item_uid,
                        source_broker=item.source_broker,
                        source_account_id=item.source_account_id,
                        instrument_key=item.instrument_key,
                        symbol=item.symbol,
                        asset_class=item.asset_class,
                        close_market_date=item.close_market_date,
                        closed_at_utc=item.closed_at_utc,
                        currency=item.currency,
                        realized_pnl=item.realized_pnl,
                    ),
                ),
            ),
            patch(
                "onejournal.journal.phase1_reporting_persistence_operator.reporting_omissions",
                return_value=(
                    ReportingOmission(
                        omission_uid=omission.omission_uid,
                        source_broker=omission.source_broker,
                        source_account_id=omission.source_account_id,
                        close_market_date=omission.close_market_date,
                        symbol=omission.symbol,
                        reason_code=omission.reason_code,
                        item_status="incomplete",
                    ),
                ),
            ),
        ):
            yield

    def _prepare(self, *, account: str = "private-account"):
        with self._preparation_context(account=account):
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

    def _package(self):
        release = self._prepare()
        rehearsal = rehearse_reporting_release(
            source_db_path=self.db,
            rehearsal_db_path=self.root / "package-rehearsal.duckdb",
            release=release,
        )
        package = self.root / "package"
        write_private_release_package(
            output_dir=package, release=release, rehearsal=rehearsal
        )
        return release, package

    def _advance_source_to_0026(self) -> None:
        apply_schema_migrations(
            self.db, target_version="0026", migrations_dir=MIGRATIONS
        )
        self.db.chmod(0o600)

    def _backup(self) -> Path:
        backup = self.root / "verified-backup.duckdb"
        shutil.copy2(self.db, backup)
        backup.chmod(0o600)
        return backup

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

    def test_prepared_package_rebuilds_and_authorizes_exact_release(self) -> None:
        release, package = self._package()
        self._advance_source_to_0026()
        with self._preparation_context():
            rebuilt = prepare_reporting_release_from_package(
                db_path=self.db,
                broker_current_authorization_path=self.authorization_path,
                package_dir=package,
            )
        self.assertEqual(rebuilt, release)

    def test_tampered_package_fails_before_persistence(self) -> None:
        _, package = self._package()
        self._advance_source_to_0026()
        manifest_path = package / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["available_count"] += 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with (
            self._preparation_context(),
            self.assertRaisesRegex(
                Phase1ReportingPersistenceOperatorError,
                "does not match the rebuilt exact release",
            ),
        ):
            prepare_reporting_release_from_package(
                db_path=self.db,
                broker_current_authorization_path=self.authorization_path,
                package_dir=package,
            )

    def test_persistence_dry_run_is_read_only_and_privacy_safe(self) -> None:
        release, package = self._package()
        self._advance_source_to_0026()
        before = file_sha256(self.db)
        execution = execute_reporting_release_persistence(
            self.db,
            release=release,
            authorization_path=package / AUTHORIZATION_FILENAME,
            expected_database_sha256=before,
            expected_report_release_fingerprint=(
                release.report_release_fingerprint
            ),
        )
        self.assertEqual(execution.target_state_before, "would_create")
        self.assertFalse(execution.write_requested)
        self.assertEqual(execution.database_sha256_after, before)
        audit = json.dumps(execution.privacy_safe_audit(), sort_keys=True)
        self.assertNotIn("private-account", audit)
        self.assertNotIn("12.34", audit)
        self.assertIn('"api_restart_performed": false', audit)

    def test_persistence_requires_exact_backup_and_reads_back(self) -> None:
        release, package = self._package()
        self._advance_source_to_0026()
        backup = self._backup()
        before = file_sha256(self.db)
        execution = execute_reporting_release_persistence(
            self.db,
            release=release,
            authorization_path=package / AUTHORIZATION_FILENAME,
            expected_database_sha256=before,
            expected_report_release_fingerprint=(
                release.report_release_fingerprint
            ),
            persist=True,
            verified_backup_path=backup,
        )
        self.assertTrue(execution.created)
        self.assertFalse(execution.replayed)
        self.assertEqual(
            (
                execution.release_count,
                execution.account_count,
                execution.realized_item_count,
                execution.omission_count,
                execution.audit_count,
            ),
            (1, 1, 1, 1, 0),
        )
        self.assertEqual(file_sha256(backup), before)
        self.assertNotEqual(file_sha256(self.db), before)
        with duckdb.connect(str(self.db), read_only=True) as con:
            loaded = load_reporting_release(
                con, report_release_uid=release.report_release_uid
            )
        self.assertEqual(loaded, release)

    def test_persistence_rejects_wrong_migration_and_backup(self) -> None:
        release, package = self._package()
        before = file_sha256(self.db)
        with self.assertRaisesRegex(
            Phase1ReportingPersistenceOperatorError,
            "exactly at migration 0026",
        ):
            execute_reporting_release_persistence(
                self.db,
                release=release,
                authorization_path=package / AUTHORIZATION_FILENAME,
                expected_database_sha256=before,
                expected_report_release_fingerprint=(
                    release.report_release_fingerprint
                ),
            )

        self._advance_source_to_0026()
        before = file_sha256(self.db)
        backup = self._backup()
        backup.write_bytes(backup.read_bytes() + b"mismatch")
        with self.assertRaisesRegex(
            Phase1ReportingPersistenceOperatorError,
            "not byte-identical",
        ):
            execute_reporting_release_persistence(
                self.db,
                release=release,
                authorization_path=package / AUTHORIZATION_FILENAME,
                expected_database_sha256=before,
                expected_report_release_fingerprint=(
                    release.report_release_fingerprint
                ),
                persist=True,
                verified_backup_path=backup,
            )

    def test_persistence_rejects_changed_hashes_authorization_and_wal(self) -> None:
        release, package = self._package()
        self._advance_source_to_0026()
        before = file_sha256(self.db)
        common = {
            "release": release,
            "authorization_path": package / AUTHORIZATION_FILENAME,
            "expected_database_sha256": before,
            "expected_report_release_fingerprint": (
                release.report_release_fingerprint
            ),
        }
        with self.assertRaisesRegex(
            Phase1ReportingPersistenceOperatorError,
            "approved target",
        ):
            execute_reporting_release_persistence(
                self.db,
                **{
                    **common,
                    "expected_report_release_fingerprint": "f" * 64,
                },
            )
        with self.assertRaisesRegex(
            Phase1ReportingPersistenceOperatorError,
            "database checksum differs",
        ):
            execute_reporting_release_persistence(
                self.db,
                **{**common, "expected_database_sha256": "0" * 64},
            )

        authorization_path = package / AUTHORIZATION_FILENAME
        authorization = json.loads(authorization_path.read_text())
        authorization["report_release_fingerprint"] = "f" * 64
        authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "does not match"):
            execute_reporting_release_persistence(self.db, **common)
        self.assertEqual(file_sha256(self.db), before)

        authorization["report_release_fingerprint"] = (
            release.report_release_fingerprint
        )
        authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
        wal = Path(str(self.db) + ".wal")
        wal.write_bytes(b"not-quiescent")
        with self.assertRaisesRegex(
            Phase1ReportingPersistenceOperatorError, "WAL exists"
        ):
            execute_reporting_release_persistence(self.db, **common)
        self.assertEqual(file_sha256(self.db), before)


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
