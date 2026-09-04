from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
import unittest

from onejournal.brokers.schwab.orders_json import SchwabOrdersJsonStats
from onejournal.brokers.schwab.position_binding import (
    SchwabPositionPrivateBinding,
    schwab_position_private_binding_bytes,
    schwab_position_private_binding_sha256,
)
from onejournal.brokers.schwab.positions_json import SchwabPositionMapping
from onejournal.brokers.schwab.transactions_json import SchwabTransactionsJsonStats
from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.bounded_reconciliation import (
    BoundedPnl03ReconciliationError,
    BoundedPnl03RouteSpec,
    INITIAL_BOUNDED_PNL03_ASSEMBLY_SHA256,
    initial_bounded_pnl03_route_spec,
    normalized_fill_from_lifecycle_transaction_row,
    run_bounded_pnl03_fifo_reconciliation,
)
from onejournal.pnl.calculations import build_fill_input_fingerprint
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
)
from onejournal.provider_connectors import (
    ConvertedExternalLifecycleEvidence,
    CurrentPositionCoverageTarget,
    ExternalLifecycleReconciliation,
    assemble_current_position_lifecycle_coverage,
    calculate_lifecycle_coverage_sha256,
)


def fill_row(
    *,
    source_fill_id: str,
    source_order_id: str,
    symbol: str,
    quantity: str,
    side: str = "buy",
    open_close: str = "open",
) -> dict[str, str]:
    return {
        "asof": "2026-02-01",
        "source_broker": "schwab",
        "source_account_id": "account-private-0001",
        "source_fill_id": source_fill_id,
        "source_order_id": source_order_id,
        "filled_at": "2026-02-01T15:00:00Z",
        "asset_class": "stock",
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "fill_price": "100",
        "commission": "0",
        "fees": "0",
        "currency": "USD",
        "option_symbol": "",
        "underlying_symbol": "",
        "option_type": "",
        "expiry": "",
        "strike": "",
        "multiplier": "",
        "open_close": open_close,
        "execution_venue": "",
        "liquidity_flag": "",
        "episode_group_id": "",
    }


class BoundedPnl03FifoReconciliationTests(unittest.TestCase):
    evaluated_at = datetime(2026, 2, 1, 20, tzinfo=UTC)

    def setUp(self) -> None:
        self.aapl = InstrumentIdentity(
            asset_class="equity",
            market_scope="US",
            currency="USD",
            symbol="AAPL",
        )
        self.msft = InstrumentIdentity(
            asset_class="equity",
            market_scope="US",
            currency="USD",
            symbol="MSFT",
        )
        self.tsla = InstrumentIdentity(
            asset_class="equity",
            market_scope="US",
            currency="USD",
            symbol="TSLA",
        )
        binding = SchwabPositionPrivateBinding(
            schema="onejournal.schwab-position-private-binding.v1",
            connection_uid="connection:schwab:test-0001",
            source_account_id="account-private-0001",
            provider_account_hash="opaque-account-hash",
            provider_account_number="123456",
            mappings=(
                SchwabPositionMapping("AAPL", self.aapl),
                SchwabPositionMapping("MSFT", self.msft),
                SchwabPositionMapping("TSLA", self.tsla),
            ),
        )
        self.binding_bytes = schwab_position_private_binding_bytes(binding)

        order = fill_row(
            source_fill_id="order-fill-aapl",
            source_order_id="order-aapl",
            symbol="AAPL",
            quantity="2",
        )
        transaction = fill_row(
            source_fill_id="transaction-fill-aapl",
            source_order_id="order-aapl",
            symbol="AAPL",
            quantity="2",
        )
        review_transaction = fill_row(
            source_fill_id="transaction-fill-tsla",
            source_order_id="",
            symbol="TSLA",
            quantity="1",
        )
        window = ConvertedExternalLifecycleEvidence(
            external_manifest_sha256="b" * 64,
            source_broker="schwab",
            connection_uid="connection:schwab:test-0001",
            source_account_id="account-private-0001",
            window_start_date=date(2026, 1, 1),
            window_end_date=date(2026, 2, 1),
            raw_response_bytes={},
            order_rows=(order,),
            transaction_rows=(transaction, review_transaction),
            lifecycle_events=(),
            lifecycle_event_legs=(),
            order_stats=SchwabOrdersJsonStats(fill_rows=1),
            transaction_stats=SchwabTransactionsJsonStats(fill_rows=2),
            reconciliation=ExternalLifecycleReconciliation(1, 0, 1),
        )
        self.coverage = assemble_current_position_lifecycle_coverage(
            (window,),
            (
                CurrentPositionCoverageTarget("AAPL", "equity", Decimal("2")),
                CurrentPositionCoverageTarget("MSFT", "equity", Decimal("3")),
                CurrentPositionCoverageTarget("TSLA", "equity", Decimal("1")),
            ),
            evaluated_at=self.evaluated_at,
        )
        self.snapshot = BrokerPositionSnapshot(
            snapshot_uid="broker-position-snapshot:test-0001",
            source_broker="schwab",
            connection_uid="connection:schwab:test-0001",
            source_account_id="account-private-0001",
            asof=date(2026, 2, 1),
            retrieved_at=self.evaluated_at,
            raw_path="private/snapshot.json",
            raw_sha256="a" * 64,
            account_complete=True,
            adapter_version="schwab-position-json-v2",
            positions=(
                BrokerPositionRecord(self.aapl, Decimal("2")),
                BrokerPositionRecord(self.msft, Decimal("3")),
                BrokerPositionRecord(self.tsla, Decimal("1")),
            ),
        )
        self.fill = normalized_fill_from_lifecycle_transaction_row(
            transaction,
            fetched_at=self.evaluated_at + timedelta(days=1),
            raw_path="private/lifecycle-transactions.json",
        )
        self.spec = BoundedPnl03RouteSpec(
            route_version="synthetic-bounded-route.v1",
            expected_binding_sha256=schwab_position_private_binding_sha256(
                self.binding_bytes
            ),
            expected_snapshot_uid=self.snapshot.snapshot_uid,
            expected_assembly_sha256=self.coverage.assembly_sha256,
            expected_fill_fingerprint=build_fill_input_fingerprint((self.fill,)),
            expected_position_count=3,
            expected_eligible_count=1,
            expected_history_extension_count=1,
            expected_review_required_count=1,
        )

    def run_gate(self, **overrides):
        values = {
            "spec": self.spec,
            "private_binding_bytes": self.binding_bytes,
            "coverage": self.coverage,
            "broker_snapshot": self.snapshot,
            "eligible_transaction_fills": (self.fill,),
            "max_snapshot_age_seconds": 0,
        }
        values.update(overrides)
        return run_bounded_pnl03_fifo_reconciliation(**values)

    def test_exact_eligible_scope_reconciles_and_never_becomes_portfolio_total(self) -> None:
        result = self.run_gate()

        self.assertGreater(self.fill.fetched_at, self.coverage.evaluated_at)
        self.assertEqual(result.final_status, "eligible_fifo_reconciled")
        self.assertEqual(result.complete_position_count, 3)
        self.assertEqual(result.eligible_count, 1)
        self.assertEqual(result.fifo_reconciled_count, 1)
        self.assertEqual(result.reconciliation_pending_count, 0)
        self.assertEqual(result.unavailable_count, 2)
        self.assertEqual(
            result.eligible_cost_basis_subtotal_by_currency,
            {"USD": Decimal("200")},
        )
        self.assertIsNone(result.portfolio_cost_basis_by_currency)
        self.assertEqual(result.subtotal_status, "eligible_subtotal")
        self.assertFalse(result.complete_portfolio_totals_available)
        self.assertFalse(result.financial_acceptance)
        by_identity = {item.identity: item for item in result.positions}
        self.assertEqual(by_identity[self.aapl].status, "fifo_reconciled")
        self.assertEqual(by_identity[self.msft].status, "unavailable")
        self.assertEqual(by_identity[self.tsla].status, "unavailable")
        self.assertIsNone(by_identity[self.msft].open_cost_basis)
        self.assertIsNone(by_identity[self.tsla].canonical_quantity)

    def test_audit_is_deterministic_and_privacy_safe(self) -> None:
        first = self.run_gate()
        second = self.run_gate()

        self.assertEqual(first.run_uid, second.run_uid)
        self.assertEqual(first.privacy_safe_audit(), second.privacy_safe_audit())
        rendered = json.dumps(first.privacy_safe_audit(), sort_keys=True)
        for private_value in (
            "AAPL",
            "MSFT",
            "TSLA",
            "account-private-0001",
            "private/lifecycle-transactions.json",
        ):
            self.assertNotIn(private_value, rendered)
        self.assertFalse(first.privacy_safe_audit()["financial_values_emitted"])

    def test_transaction_fill_conversion_requires_exact_fields_and_lineage(self) -> None:
        row = dict(self.coverage.transaction_rows[0])
        row.pop("commission")
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "fields do not match"
        ):
            normalized_fill_from_lifecycle_transaction_row(
                row,
                fetched_at=self.evaluated_at,
                raw_path="private/lifecycle.json",
            )

        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "fetched_at must include"
        ):
            normalized_fill_from_lifecycle_transaction_row(
                self.coverage.transaction_rows[0],
                fetched_at=datetime(2026, 2, 2, 12),
                raw_path="private/lifecycle.json",
            )

        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "raw_path"
        ):
            normalized_fill_from_lifecycle_transaction_row(
                self.coverage.transaction_rows[0],
                fetched_at=self.evaluated_at,
                raw_path="",
            )

    def test_binding_snapshot_and_assembly_are_exact_route_inputs(self) -> None:
        wrong_digest_spec = replace(
            self.spec, expected_assembly_sha256="c" * 64
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "assembly"
        ):
            self.run_gate(spec=wrong_digest_spec)

        wrong_snapshot_spec = replace(
            self.spec, expected_snapshot_uid="broker-position-snapshot:other-0001"
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "snapshot"
        ):
            self.run_gate(spec=wrong_snapshot_spec)

        wrong_binding_spec = replace(
            self.spec, expected_binding_sha256="d" * 64
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "binding"
        ):
            self.run_gate(spec=wrong_binding_spec)

        wrong_fill_spec = replace(
            self.spec, expected_fill_fingerprint="e" * 64
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "fill fingerprint"
        ):
            self.run_gate(spec=wrong_fill_spec)

        tampered_row = {
            **self.coverage.transaction_rows[0],
            "fill_price": "101",
        }
        tampered_coverage = replace(
            self.coverage,
            transaction_rows=(
                tampered_row,
                *self.coverage.transaction_rows[1:],
            ),
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "content does not match"
        ):
            self.run_gate(coverage=tampered_coverage)

    def test_private_binding_must_cover_every_snapshot_position(self) -> None:
        incomplete = SchwabPositionPrivateBinding(
            schema="onejournal.schwab-position-private-binding.v1",
            connection_uid="connection:schwab:test-0001",
            source_account_id="account-private-0001",
            provider_account_hash="opaque-account-hash",
            provider_account_number="123456",
            mappings=(
                SchwabPositionMapping("AAPL", self.aapl),
                SchwabPositionMapping("MSFT", self.msft),
            ),
        )
        incomplete_bytes = schwab_position_private_binding_bytes(incomplete)
        incomplete_spec = replace(
            self.spec,
            expected_binding_sha256=schwab_position_private_binding_sha256(
                incomplete_bytes
            ),
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "binding count"
        ):
            self.run_gate(
                spec=incomplete_spec, private_binding_bytes=incomplete_bytes
            )

    def test_fill_scope_and_economics_cannot_be_widened_or_reinterpreted(self) -> None:
        mismatched_fill = replace(self.fill, symbol="MSFT")
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "symbol differs"
        ):
            self.run_gate(eligible_transaction_fills=(mismatched_fill,))

        extra_fill = replace(
            self.fill,
            fill_uid="schwab:account-private-0001:transaction-fill-tsla",
            source_fill_id="transaction-fill-tsla",
            source_order_id=None,
            symbol="TSLA",
            quantity=Decimal("1"),
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "scope does not exactly match"
        ):
            self.run_gate(eligible_transaction_fills=(self.fill, extra_fill))

    def test_broker_quantity_conflict_fails_before_fifo_acceptance(self) -> None:
        mismatched_snapshot = replace(
            self.snapshot,
            positions=(
                BrokerPositionRecord(self.aapl, Decimal("3")),
                BrokerPositionRecord(self.msft, Decimal("3")),
                BrokerPositionRecord(self.tsla, Decimal("1")),
            ),
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "quantities differ"
        ):
            self.run_gate(broker_snapshot=mismatched_snapshot)

    def test_fill_flat_coverage_does_not_bypass_fifo_allocation_rules(self) -> None:
        close_order = {**self.coverage.order_rows[0], "open_close": "close"}
        close_transaction = {
            **self.coverage.transaction_rows[0],
            "open_close": "close",
        }
        close_coverage = replace(
            self.coverage,
            order_rows=(close_order,),
            transaction_rows=(
                close_transaction,
                *self.coverage.transaction_rows[1:],
            ),
            assembly_sha256="",
        )
        close_coverage = replace(
            close_coverage,
            assembly_sha256=calculate_lifecycle_coverage_sha256(close_coverage),
        )
        close_fill = replace(self.fill, open_close="close")
        close_spec = replace(
            self.spec,
            expected_assembly_sha256=close_coverage.assembly_sha256,
            expected_fill_fingerprint=build_fill_input_fingerprint((close_fill,)),
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "failed FIFO allocation"
        ):
            self.run_gate(
                spec=close_spec,
                coverage=close_coverage,
                eligible_transaction_fills=(close_fill,),
            )

    def test_initial_route_factory_cannot_weaken_frozen_46_4_3_baseline(self) -> None:
        spec = initial_bounded_pnl03_route_spec(
            expected_binding_sha256="e" * 64,
            expected_snapshot_uid="broker-position-snapshot:private-0001",
            expected_fill_fingerprint="f" * 64,
        )
        self.assertEqual(spec.expected_assembly_sha256, INITIAL_BOUNDED_PNL03_ASSEMBLY_SHA256)
        self.assertEqual(
            (
                spec.expected_position_count,
                spec.expected_eligible_count,
                spec.expected_history_extension_count,
                spec.expected_review_required_count,
            ),
            (53, 46, 4, 3),
        )
        with self.assertRaisesRegex(
            BoundedPnl03ReconciliationError, "frozen 46/4/3"
        ):
            replace(spec, expected_eligible_count=45, expected_history_extension_count=5)


if __name__ == "__main__":
    unittest.main()
