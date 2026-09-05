from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import ast
from pathlib import Path
import unittest

from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.broker_current_position_valuation import (
    BROKER_CURRENT_POSITION_VALUATION_CONTRACT_VERSION,
    BROKER_POSITION_BASIS_METHOD,
    BrokerCurrentPositionValuationError,
    build_broker_current_position_valuation,
)
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    PROJECT_DIR
    / "src/onejournal/pnl/broker_current_position_valuation.py"
)


class BrokerCurrentPositionValuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.asof = date(2026, 9, 4)
        self.evaluated_at = datetime(2026, 9, 4, 23, 56, tzinfo=UTC)
        self.transferred_equity = InstrumentIdentity(
            asset_class="equity",
            market_scope="US",
            currency="USD",
            symbol="TRNF",
        )
        self.synthetic_short_call = InstrumentIdentity(
            asset_class="option",
            market_scope="US",
            currency="USD",
            underlying_symbol="OPTX",
            expiry=date(2027, 1, 15),
            option_right="CALL",
            strike=Decimal("250"),
            multiplier=Decimal("100"),
        )

    def snapshot(
        self,
        *positions: BrokerPositionRecord,
        account_complete: bool = True,
        retrieved_at: datetime | None = None,
    ) -> BrokerPositionSnapshot:
        return BrokerPositionSnapshot(
            snapshot_uid="broker-position-snapshot:" + "a" * 64,
            source_broker="schwab",
            connection_uid="connection:schwab:synthetic",
            source_account_id="account:synthetic",
            asof=self.asof,
            retrieved_at=retrieved_at or self.evaluated_at,
            raw_path="private/synthetic/positions.json",
            raw_sha256="b" * 64,
            account_complete=account_complete,
            adapter_version="schwab-position-json-v3",
            positions=positions,
        )

    def build(self, snapshot: BrokerPositionSnapshot):
        return build_broker_current_position_valuation(
            broker_snapshot=snapshot,
            evaluated_at=self.evaluated_at,
            max_snapshot_age_seconds=60,
            currency_quantum_by_currency={"USD": Decimal("0.01")},
        )

    def test_transferred_equity_uses_schwab_tax_lot_basis_and_reconciles(self) -> None:
        position = BrokerPositionRecord(
            identity=self.transferred_equity,
            quantity=Decimal("125"),
            broker_average_cost=Decimal("12.3456"),
            broker_market_value=Decimal("2000"),
            broker_unrealized_pnl=Decimal("456.800000000002"),
            broker_tax_lot_average_price=Decimal("12.3456"),
        )
        first = self.build(self.snapshot(position))
        replay = self.build(self.snapshot(position))

        self.assertEqual(first, replay)
        self.assertEqual(
            first.contract_version,
            BROKER_CURRENT_POSITION_VALUATION_CONTRACT_VERSION,
        )
        self.assertEqual(first.basis_method, BROKER_POSITION_BASIS_METHOD)
        self.assertEqual(first.final_status, "complete")
        self.assertEqual(first.cost_basis_available_count, 1)
        self.assertEqual(first.market_value_available_count, 1)
        self.assertEqual(first.unrealized_pnl_available_count, 1)
        (valued,) = first.positions
        self.assertEqual(valued.open_cost_basis, Decimal("1543.2000"))
        self.assertEqual(valued.unrealized_pnl, Decimal("456.8000"))
        self.assertEqual(
            first.portfolio_cost_basis_by_currency,
            {"USD": Decimal("1543.2000")},
        )
        self.assertEqual(
            first.portfolio_market_value_by_currency,
            {"USD": Decimal("2000")},
        )
        self.assertEqual(
            first.portfolio_unrealized_pnl_by_currency,
            {"USD": Decimal("456.8000")},
        )
        self.assertFalse(first.financial_acceptance)

    def test_short_option_uses_signed_opening_credit_and_multiplier(self) -> None:
        position = BrokerPositionRecord(
            identity=self.synthetic_short_call,
            quantity=Decimal("-1"),
            broker_market_value=Decimal("-405"),
            broker_unrealized_pnl=Decimal("-80.67"),
            broker_tax_lot_average_price=Decimal("3.2433"),
        )
        run = self.build(self.snapshot(position))
        (valued,) = run.positions
        self.assertEqual(valued.open_cost_basis, Decimal("-324.3300"))
        self.assertEqual(valued.unrealized_pnl, Decimal("-80.6700"))
        self.assertEqual(valued.status, "available")

    def test_long_option_and_short_equity_use_directional_signed_basis(self) -> None:
        long_option = InstrumentIdentity(
            asset_class="option",
            market_scope="US",
            currency="USD",
            underlying_symbol="LONG",
            expiry=date(2027, 3, 19),
            option_right="PUT",
            strike=Decimal("40"),
            multiplier=Decimal("100"),
        )
        short_equity = InstrumentIdentity(
            asset_class="equity",
            market_scope="US",
            currency="USD",
            symbol="SHRT",
        )
        run = self.build(
            self.snapshot(
                BrokerPositionRecord(
                    identity=long_option,
                    quantity=Decimal("2"),
                    broker_market_value=Decimal("300"),
                    broker_unrealized_pnl=Decimal("50"),
                    broker_tax_lot_average_price=Decimal("1.25"),
                ),
                BrokerPositionRecord(
                    identity=short_equity,
                    quantity=Decimal("-10"),
                    broker_market_value=Decimal("-180"),
                    broker_unrealized_pnl=Decimal("20"),
                    broker_tax_lot_average_price=Decimal("20"),
                ),
            )
        )
        by_identity = {item.identity: item for item in run.positions}
        self.assertEqual(
            by_identity[long_option].open_cost_basis,
            Decimal("250.00"),
        )
        self.assertEqual(
            by_identity[short_equity].open_cost_basis,
            Decimal("-200"),
        )
        self.assertEqual(
            run.portfolio_unrealized_pnl_by_currency,
            {"USD": Decimal("70.00")},
        )

    def test_market_value_remains_available_when_basis_is_missing(self) -> None:
        position = BrokerPositionRecord(
            identity=self.transferred_equity,
            quantity=Decimal("125"),
            broker_market_value=Decimal("2000"),
            broker_unrealized_pnl=Decimal("456.80"),
        )
        run = self.build(self.snapshot(position))
        (valued,) = run.positions

        self.assertEqual(run.final_status, "partial")
        self.assertEqual(valued.status, "partial")
        self.assertEqual(valued.cost_basis_status, "unavailable")
        self.assertEqual(valued.market_value_status, "available")
        self.assertEqual(valued.unrealized_pnl_status, "unavailable")
        self.assertIsNone(run.portfolio_cost_basis_by_currency)
        self.assertEqual(
            run.portfolio_market_value_by_currency,
            {"USD": Decimal("2000")},
        )
        self.assertIsNone(run.portfolio_unrealized_pnl_by_currency)

    def test_unrealized_mismatch_does_not_suppress_other_complete_metrics(self) -> None:
        position = BrokerPositionRecord(
            identity=self.transferred_equity,
            quantity=Decimal("125"),
            broker_market_value=Decimal("2000"),
            broker_unrealized_pnl=Decimal("400"),
            broker_tax_lot_average_price=Decimal("12.3456"),
        )
        run = self.build(self.snapshot(position))
        (valued,) = run.positions

        self.assertEqual(valued.cost_basis_status, "available")
        self.assertEqual(valued.market_value_status, "available")
        self.assertEqual(valued.unrealized_pnl_status, "unavailable")
        self.assertIn("broker_unrealized_pnl_mismatch", valued.reason_codes)
        self.assertIsNotNone(run.portfolio_cost_basis_by_currency)
        self.assertIsNotNone(run.portfolio_market_value_by_currency)
        self.assertIsNone(run.portfolio_unrealized_pnl_by_currency)

    def test_invalid_snapshot_scope_and_currency_policy_fail_closed(self) -> None:
        position = BrokerPositionRecord(
            identity=self.transferred_equity,
            quantity=Decimal("125"),
            broker_market_value=Decimal("2000"),
            broker_unrealized_pnl=Decimal("456.80"),
            broker_tax_lot_average_price=Decimal("12.3456"),
        )
        with self.assertRaisesRegex(
            BrokerCurrentPositionValuationError,
            "complete broker account snapshot",
        ):
            self.build(self.snapshot(position, account_complete=False))
        with self.assertRaisesRegex(
            BrokerCurrentPositionValuationError,
            "empty broker position scope",
        ):
            self.build(self.snapshot())
        with self.assertRaisesRegex(
            BrokerCurrentPositionValuationError,
            "age limit",
        ):
            self.build(
                self.snapshot(
                    position,
                    retrieved_at=self.evaluated_at - timedelta(seconds=61),
                )
            )
        with self.assertRaisesRegex(
            BrokerCurrentPositionValuationError,
            "currency quantum scope",
        ):
            build_broker_current_position_valuation(
                broker_snapshot=self.snapshot(position),
                evaluated_at=self.evaluated_at,
                max_snapshot_age_seconds=60,
                currency_quantum_by_currency={},
            )

    def test_privacy_safe_audit_contains_no_values_or_instruments(self) -> None:
        position = BrokerPositionRecord(
            identity=self.transferred_equity,
            quantity=Decimal("125"),
            broker_market_value=Decimal("2000"),
            broker_unrealized_pnl=Decimal("456.80"),
            broker_tax_lot_average_price=Decimal("12.3456"),
        )
        audit = self.build(self.snapshot(position)).privacy_safe_audit()
        rendered = repr(audit)
        self.assertNotIn("TRNF", rendered)
        self.assertNotIn("1543", rendered)
        self.assertNotIn("2000", rendered)
        self.assertFalse(audit["financial_acceptance"])

    def test_module_has_no_provider_database_or_process_capability(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            {
                "requests",
                "httpx",
                "urllib3",
                "socket",
                "subprocess",
                "duckdb",
                "keyring",
            }.isdisjoint(imported)
        )


if __name__ == "__main__":
    unittest.main()
