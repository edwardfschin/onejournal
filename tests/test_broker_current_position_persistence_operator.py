from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest

import duckdb

from onejournal.instruments import InstrumentIdentity
from onejournal.journal.broker_current_position_persistence_operator import (
    ACCEPTANCE_PACKAGE_SCHEMA,
    AUTHORIZATION_CONTRACT_VERSION,
    FINANCIAL_AUTHORIZATION_FILENAME,
    PRIVATE_RESULT_FILENAME,
    PRIVATE_RESULT_SCHEMA,
    PRIVACY_AUDIT_FILENAME,
    RESULT_PACKAGE_SCHEMA,
    SOURCE_LINEAGE_FILENAME,
    SOURCE_LINEAGE_SCHEMA,
    BrokerCurrentPersistenceOperatorError,
    execute_broker_current_position_persistence,
    validate_broker_current_position_persistence_packages,
)
from onejournal.journal.broker_current_position_valuation_repository import (
    broker_current_position_valuation_run_document,
    calculate_broker_current_position_result_fingerprint,
)
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.pnl.broker_current_position_valuation import (
    build_broker_current_position_valuation,
)
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
)


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("utf-8")


def _digest(body: bytes) -> str:
    return sha256(body).hexdigest()


def _file_digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


class BrokerCurrentPositionPersistenceOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluated_at = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)
        equity = InstrumentIdentity(
            asset_class="equity",
            market_scope="US",
            currency="USD",
            symbol="SAFE",
        )
        option = InstrumentIdentity(
            asset_class="option",
            market_scope="US",
            currency="USD",
            underlying_symbol="BOUND",
            expiry=date(2027, 1, 15),
            option_right="PUT",
            strike=Decimal("100"),
            multiplier=Decimal("100"),
        )
        self.snapshot = BrokerPositionSnapshot(
            snapshot_uid="broker-position-snapshot:" + "a" * 64,
            source_broker="schwab",
            connection_uid="connection:schwab:synthetic",
            source_account_id="account:synthetic",
            asof=date(2026, 9, 5),
            retrieved_at=self.evaluated_at,
            raw_path="data/raw/schwab/external/synthetic/positions.json",
            raw_sha256="b" * 64,
            account_complete=True,
            adapter_version="schwab-position-json-v3",
            positions=(
                BrokerPositionRecord(
                    identity=equity,
                    quantity=Decimal("10"),
                    broker_average_cost=Decimal("5"),
                    broker_market_value=Decimal("60"),
                    broker_unrealized_pnl=Decimal("10"),
                    broker_tax_lot_average_price=Decimal("5"),
                ),
                BrokerPositionRecord(
                    identity=option,
                    quantity=Decimal("-1"),
                    broker_average_cost=Decimal("2"),
                    broker_market_value=Decimal("-150"),
                    broker_unrealized_pnl=Decimal("50"),
                    broker_tax_lot_average_price=Decimal("2"),
                ),
            ),
        )
        self.run = build_broker_current_position_valuation(
            broker_snapshot=self.snapshot,
            evaluated_at=self.evaluated_at,
            max_snapshot_age_seconds=0,
            currency_quantum_by_currency={"USD": Decimal("0.01")},
        )
        self.acquisition_sha256 = "c" * 64
        self.binding_sha256 = "d" * 64
        (
            self.result_manifest,
            self.result_files,
            self.acceptance_manifest,
            self.acceptance_files,
        ) = self._packages()

    def _packages(self):
        result_fingerprint = (
            calculate_broker_current_position_result_fingerprint(self.run)
        )
        private_result = _json_bytes(
            {
                "schema": PRIVATE_RESULT_SCHEMA,
                "result_fingerprint": result_fingerprint,
                "run": broker_current_position_valuation_run_document(self.run),
            }
        )
        audit = self.run.privacy_safe_audit()
        audit.update(
            {
                "acquisition_manifest_sha256": self.acquisition_sha256,
                "position_binding_sha256": self.binding_sha256,
                "adapter_version": self.snapshot.adapter_version,
                "raw_sha256": self.snapshot.raw_sha256,
                "result_fingerprint": result_fingerprint,
            }
        )
        audit_bytes = _json_bytes(audit)
        supersedes = "synthetic-prior-package"
        lineage_bytes = _json_bytes(
            {
                "schema": SOURCE_LINEAGE_SCHEMA,
                "valuation_contract_version": self.run.contract_version,
                "basis_method": self.run.basis_method,
                "snapshot_uid": self.run.snapshot_uid,
                "adapter_version": self.snapshot.adapter_version,
                "raw_sha256": self.snapshot.raw_sha256,
                "acquisition_manifest_sha256": self.acquisition_sha256,
                "position_binding_sha256": self.binding_sha256,
                "currency_quantum_by_currency": {"USD": "0.01"},
                "result_fingerprint": result_fingerprint,
                "supersedes_package": supersedes,
                "historical_evidence_preserved": True,
                "financial_acceptance": False,
                "provider_call_performed": False,
                "credential_access_performed": False,
                "database_write_performed": False,
            }
        )
        result_files = {
            PRIVATE_RESULT_FILENAME: private_result,
            PRIVACY_AUDIT_FILENAME: audit_bytes,
            SOURCE_LINEAGE_FILENAME: lineage_bytes,
        }
        result_manifest = _json_bytes(
            {
                "schema": RESULT_PACKAGE_SCHEMA,
                "package_version": 2,
                "supersedes_package": supersedes,
                "files": [
                    {
                        "filename": name,
                        "mode": "0600",
                        "sha256": _digest(result_files[name]),
                    }
                    for name in (
                        PRIVATE_RESULT_FILENAME,
                        PRIVACY_AUDIT_FILENAME,
                        SOURCE_LINEAGE_FILENAME,
                    )
                ],
                "run_uid": self.run.run_uid,
                "snapshot_uid": self.run.snapshot_uid,
                "result_fingerprint": result_fingerprint,
                "position_count": 2,
                "cost_basis_available_count": 2,
                "market_value_available_count": 2,
                "unrealized_pnl_available_count": 2,
                "complete_portfolio_cost_basis_available": True,
                "complete_portfolio_market_value_available": True,
                "complete_portfolio_unrealized_pnl_available": True,
                "financial_acceptance": False,
                "final_status": "complete",
                "historical_evidence_preserved": True,
                "provider_call_performed": False,
                "credential_access_performed": False,
                "database_write_performed": False,
                "manifest_written_last": True,
            }
        )
        accepted_at = (self.evaluated_at + timedelta(minutes=1)).isoformat()
        owner_uid = "owner-acceptance:synthetic"
        authorization = _json_bytes(
            {
                "contract_version": AUTHORIZATION_CONTRACT_VERSION,
                "owner_acceptance_uid": owner_uid,
                "valuation_run_uid": self.run.run_uid,
                "result_fingerprint": result_fingerprint,
                "accepted_at": accepted_at,
                "accepted_scope": "broker_reconciled_current_position",
                "approval_source": "project_owner_explicit_proceed",
                "decision": "accepted",
                "fifo_history_reinterpreted": False,
            }
        )
        acceptance_files = {FINANCIAL_AUTHORIZATION_FILENAME: authorization}
        acceptance_manifest = _json_bytes(
            {
                "schema": ACCEPTANCE_PACKAGE_SCHEMA,
                "accepted_result_manifest_sha256": _digest(result_manifest),
                "financial_release_authorization_sha256": _digest(authorization),
                "files": [
                    {
                        "filename": FINANCIAL_AUTHORIZATION_FILENAME,
                        "mode": "0600",
                        "sha256": _digest(authorization),
                    }
                ],
                "owner_acceptance_uid": owner_uid,
                "valuation_run_uid": self.run.run_uid,
                "result_fingerprint": result_fingerprint,
                "accepted_scope": "broker_reconciled_current_position",
                "decision": "accepted",
                "fifo_history_reinterpreted": False,
                "provider_call_performed": False,
                "credential_access_performed": False,
                "database_write_performed": False,
                "manifest_written_last": True,
                "final_status": "owner_accepted",
            }
        )
        return (
            result_manifest,
            result_files,
            acceptance_manifest,
            acceptance_files,
        )

    def _plan(self, **changes):
        values = {
            "broker_snapshot": self.snapshot,
            "acquisition_manifest_sha256": self.acquisition_sha256,
            "position_binding_sha256": self.binding_sha256,
            "result_manifest_bytes": self.result_manifest,
            "result_files": self.result_files,
            "acceptance_manifest_bytes": self.acceptance_manifest,
            "acceptance_files": self.acceptance_files,
        }
        values.update(changes)
        return validate_broker_current_position_persistence_packages(**values)

    def _database(self, root: Path) -> Path:
        root.chmod(0o700)
        database = root / "journal.duckdb"
        apply_schema_migrations(database, target_version="0023")
        database.chmod(0o600)
        return database

    def test_exact_packages_rebuild_and_bind_the_accepted_result(self) -> None:
        plan = self._plan()
        self.assertEqual(plan.run, self.run)
        self.assertEqual(plan.broker_snapshot, self.snapshot)
        self.assertEqual(plan.owner_acceptance.valuation_run_uid, self.run.run_uid)
        self.assertEqual(
            plan.owner_acceptance.result_fingerprint,
            calculate_broker_current_position_result_fingerprint(self.run),
        )

    def test_tampered_result_and_acceptance_fail_closed(self) -> None:
        tampered_result = json.loads(self.result_files[PRIVATE_RESULT_FILENAME])
        tampered_result["run"]["positions"][0]["quantity"] = "999"
        files = dict(self.result_files)
        files[PRIVATE_RESULT_FILENAME] = _json_bytes(tampered_result)
        with self.assertRaisesRegex(
            BrokerCurrentPersistenceOperatorError,
            "differs from the accepted private result",
        ):
            self._plan(result_files=files)

        tampered_auth = json.loads(
            self.acceptance_files[FINANCIAL_AUTHORIZATION_FILENAME]
        )
        tampered_auth["result_fingerprint"] = "0" * 64
        tampered_auth_bytes = _json_bytes(tampered_auth)
        acceptance_files = {
            FINANCIAL_AUTHORIZATION_FILENAME: tampered_auth_bytes
        }
        acceptance_manifest = json.loads(self.acceptance_manifest)
        acceptance_manifest["financial_release_authorization_sha256"] = _digest(
            tampered_auth_bytes
        )
        acceptance_manifest["files"][0]["sha256"] = _digest(tampered_auth_bytes)
        with self.assertRaisesRegex(
            BrokerCurrentPersistenceOperatorError,
            "authorization does not match",
        ):
            self._plan(
                acceptance_files=acceptance_files,
                acceptance_manifest_bytes=_json_bytes(acceptance_manifest),
            )

    def test_dry_run_is_default_and_does_not_change_database(self) -> None:
        plan = self._plan()
        with tempfile.TemporaryDirectory() as tmp:
            database = self._database(Path(tmp))
            before = _file_digest(database)
            result = execute_broker_current_position_persistence(
                database,
                plan=plan,
                expected_database_sha256=before,
            )
            self.assertFalse(result.write_requested)
            self.assertFalse(result.created)
            self.assertFalse(result.replayed)
            self.assertEqual(result.target_state_before, "would_create")
            self.assertEqual(_file_digest(database), before)
            with duckdb.connect(str(database), read_only=True) as con:
                self.assertEqual(
                    con.execute(
                        "SELECT COUNT(*) FROM pnl_broker_current_valuation_runs"
                    ).fetchone()[0],
                    0,
                )

    def test_persist_requires_backup_then_creates_and_exactly_replays(self) -> None:
        plan = self._plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            before = _file_digest(database)
            with self.assertRaisesRegex(
                BrokerCurrentPersistenceOperatorError,
                "requires a verified backup",
            ):
                execute_broker_current_position_persistence(
                    database,
                    plan=plan,
                    expected_database_sha256=before,
                    persist=True,
                )
            self.assertEqual(_file_digest(database), before)

            backup = root / "journal.pre-persist.duckdb"
            shutil.copy2(database, backup)
            backup.chmod(0o600)
            created = execute_broker_current_position_persistence(
                database,
                plan=plan,
                expected_database_sha256=before,
                persist=True,
                verified_backup_path=backup,
            )
            self.assertTrue(created.created)
            self.assertFalse(created.replayed)
            audit = created.privacy_safe_audit()
            self.assertEqual(audit["final_status"], "persisted")
            self.assertTrue(audit["database_write_performed"])
            self.assertNotIn("positions", audit)
            self.assertNotIn("portfolio_totals", audit)

            after_create = _file_digest(database)
            replay_backup = root / "journal.pre-replay.duckdb"
            shutil.copy2(database, replay_backup)
            replay_backup.chmod(0o600)
            replayed = execute_broker_current_position_persistence(
                database,
                plan=plan,
                expected_database_sha256=after_create,
                persist=True,
                verified_backup_path=replay_backup,
            )
            self.assertFalse(replayed.created)
            self.assertTrue(replayed.replayed)
            self.assertEqual(_file_digest(database), after_create)

    def test_checksum_permissions_and_backup_identity_fail_closed(self) -> None:
        plan = self._plan()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = self._database(root)
            before = _file_digest(database)
            with self.assertRaisesRegex(
                BrokerCurrentPersistenceOperatorError,
                "checksum differs",
            ):
                execute_broker_current_position_persistence(
                    database,
                    plan=plan,
                    expected_database_sha256="0" * 64,
                )
            self.assertEqual(_file_digest(database), before)

            database.chmod(0o644)
            with self.assertRaisesRegex(
                BrokerCurrentPersistenceOperatorError,
                "mode 0600",
            ):
                execute_broker_current_position_persistence(
                    database,
                    plan=plan,
                    expected_database_sha256=before,
                )
            database.chmod(0o600)

            with self.assertRaisesRegex(
                BrokerCurrentPersistenceOperatorError,
                "distinct file",
            ):
                execute_broker_current_position_persistence(
                    database,
                    plan=plan,
                    expected_database_sha256=before,
                    persist=True,
                    verified_backup_path=database,
                )


if __name__ == "__main__":
    unittest.main()
