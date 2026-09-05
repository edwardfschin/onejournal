from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.api.app import app
from onejournal.api.broker_current_position_contracts import (
    BrokerCurrentApiContractError,
    BrokerCurrentFinancialReleaseAuthorization,
    build_broker_current_position_valuation_response,
)
from onejournal.instruments import InstrumentIdentity
from onejournal.journal.broker_current_position_valuation_repository import (
    calculate_broker_current_position_result_fingerprint,
    load_broker_current_position_valuation_run,
    persist_broker_current_position_valuation_run,
)
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.pnl.broker_current_position_valuation import (
    build_broker_current_position_valuation,
)
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
)


class BrokerCurrentPositionPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.asof = date(2026, 9, 4)
        self.evaluated_at = datetime(2026, 9, 4, 20, 0, tzinfo=UTC)
        equity = InstrumentIdentity(
            asset_class="equity",
            market_scope="US",
            currency="USD",
            symbol="TRNF",
        )
        option = InstrumentIdentity(
            asset_class="option",
            market_scope="US",
            currency="USD",
            underlying_symbol="OPTX",
            expiry=date(2027, 1, 15),
            option_right="CALL",
            strike=Decimal("250"),
            multiplier=Decimal("100"),
        )
        self.snapshot = BrokerPositionSnapshot(
            snapshot_uid="broker-position-snapshot:" + "a" * 64,
            source_broker="schwab",
            connection_uid="connection:schwab:synthetic",
            source_account_id="account:synthetic",
            asof=self.asof,
            retrieved_at=self.evaluated_at,
            raw_path="private/synthetic/positions.json",
            raw_sha256="b" * 64,
            account_complete=True,
            adapter_version="schwab-position-json-v3",
            positions=(
                BrokerPositionRecord(
                    identity=equity,
                    quantity=Decimal("125"),
                    broker_average_cost=Decimal("12.3456"),
                    broker_market_value=Decimal("2000"),
                    broker_unrealized_pnl=Decimal("456.80"),
                    broker_tax_lot_average_price=Decimal("12.3456"),
                ),
                BrokerPositionRecord(
                    identity=option,
                    quantity=Decimal("-1"),
                    broker_market_value=Decimal("-405"),
                    broker_unrealized_pnl=Decimal("-80.67"),
                    broker_tax_lot_average_price=Decimal("3.2433"),
                ),
            ),
        )
        self.run = build_broker_current_position_valuation(
            broker_snapshot=self.snapshot,
            evaluated_at=self.evaluated_at,
            max_snapshot_age_seconds=0,
            currency_quantum_by_currency={"USD": Decimal("0.01")},
        )

    def test_persists_reads_back_and_replays_in_temporary_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "broker-current.duckdb"
            apply_schema_migrations(db_path)
            first = persist_broker_current_position_valuation_run(
                db_path, run=self.run, broker_snapshot=self.snapshot
            )
            replay = persist_broker_current_position_valuation_run(
                db_path, run=self.run, broker_snapshot=self.snapshot
            )
            self.assertTrue(first.created)
            self.assertTrue(replay.replayed)
            read_back = load_broker_current_position_valuation_run(
                db_path, valuation_run_uid=self.run.run_uid
            )
            self.assertIsNotNone(read_back)
            assert read_back is not None
            self.assertEqual(read_back.position_count, 2)
            self.assertEqual(read_back.cost_basis_available_count, 2)
            self.assertEqual(read_back.market_value_available_count, 2)
            self.assertEqual(read_back.unrealized_pnl_available_count, 2)
            self.assertEqual(
                read_back.currency_quantum_by_currency,
                {"USD": Decimal("0.01")},
            )
            self.assertEqual(
                read_back.result_fingerprint,
                calculate_broker_current_position_result_fingerprint(self.run),
            )
            self.assertEqual(
                read_back.portfolio_totals[0]["portfolio_cost_basis"],
                Decimal("1218.8700000000"),
            )
            with duckdb.connect(str(db_path), read_only=True) as con:
                columns = {
                    row[1]
                    for row in con.execute(
                        "PRAGMA table_info(broker_position_snapshot_records)"
                    ).fetchall()
                }
                self.assertIn("broker_tax_lot_average_price", columns)
                self.assertEqual(
                    con.execute(
                        "SELECT COUNT(*) FROM pnl_broker_current_position_valuations"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    con.execute(
                        """SELECT COUNT(*)
                           FROM broker_position_snapshot_records
                           WHERE broker_tax_lot_average_price IS NOT NULL"""
                    ).fetchone()[0],
                    2,
                )

    def test_persistence_rejects_run_that_does_not_replay(self) -> None:
        drifted = replace(self.run, cost_basis_available_count=1)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "broker-current.duckdb"
            apply_schema_migrations(db_path)
            with self.assertRaisesRegex(ValueError, "exactly replay"):
                persist_broker_current_position_valuation_run(
                    db_path, run=drifted, broker_snapshot=self.snapshot
                )

    def test_partial_run_preserves_only_independently_complete_total(self) -> None:
        position = replace(
            self.snapshot.positions[0],
            broker_tax_lot_average_price=None,
        )
        snapshot = replace(self.snapshot, positions=(position,))
        run = build_broker_current_position_valuation(
            broker_snapshot=snapshot,
            evaluated_at=self.evaluated_at,
            max_snapshot_age_seconds=0,
            currency_quantum_by_currency={"USD": Decimal("0.01")},
        )
        self.assertEqual(run.final_status, "partial")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "broker-current.duckdb"
            apply_schema_migrations(db_path)
            persist_broker_current_position_valuation_run(
                db_path, run=run, broker_snapshot=snapshot
            )
            read_back = load_broker_current_position_valuation_run(
                db_path, valuation_run_uid=run.run_uid
            )
            assert read_back is not None
            (total,) = read_back.portfolio_totals
            self.assertIsNone(total["portfolio_cost_basis"])
            self.assertEqual(
                total["portfolio_market_value"], Decimal("2000.0000000000")
            )
            self.assertIsNone(total["portfolio_unrealized_pnl"])
            self.assertFalse(read_back.complete_portfolio_cost_basis_available)
            self.assertTrue(read_back.complete_portfolio_market_value_available)
            self.assertFalse(
                read_back.complete_portfolio_unrealized_pnl_available
            )

    def test_private_api_withholds_values_until_exact_owner_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "broker-current.duckdb"
            apply_schema_migrations(db_path)
            persist_broker_current_position_valuation_run(
                db_path, run=self.run, broker_snapshot=self.snapshot
            )
            read_back = load_broker_current_position_valuation_run(
                db_path, valuation_run_uid=self.run.run_uid
            )
            assert read_back is not None

            withheld = build_broker_current_position_valuation_response(read_back)
            self.assertEqual(withheld.metadata.release_status, "withheld")
            self.assertTrue(
                all(item.open_cost_basis is None for item in withheld.positions)
            )
            self.assertTrue(
                all(
                    item.portfolio_market_value is None
                    for item in withheld.portfolio_totals
                )
            )

            wrong = BrokerCurrentFinancialReleaseAuthorization(
                owner_acceptance_uid="owner-acceptance:synthetic",
                valuation_run_uid=self.run.run_uid,
                result_fingerprint="0" * 64,
                accepted_at=self.evaluated_at,
            )
            with self.assertRaisesRegex(
                BrokerCurrentApiContractError, "fingerprint"
            ):
                build_broker_current_position_valuation_response(
                    read_back, authorization=wrong
                )

            accepted = BrokerCurrentFinancialReleaseAuthorization(
                owner_acceptance_uid="owner-acceptance:synthetic",
                valuation_run_uid=self.run.run_uid,
                result_fingerprint=read_back.result_fingerprint,
                accepted_at=self.evaluated_at,
            )
            released = build_broker_current_position_valuation_response(
                read_back, authorization=accepted
            )
            self.assertEqual(released.metadata.release_status, "owner_accepted")
            self.assertEqual(released.positions[0].open_cost_basis, "1543.2000000000")
            self.assertEqual(
                released.portfolio_totals[0].portfolio_market_value,
                "1595.0000000000",
            )
            self.assertTrue(released.complete_portfolio_market_value_available)

    def test_private_contract_is_not_registered_as_an_active_route(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertNotIn("/api/v1/pnl/broker-current/positions", paths)


if __name__ == "__main__":
    unittest.main()
