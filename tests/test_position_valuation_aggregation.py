from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import unittest

from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.position_aggregation import (
    PositionAggregationError,
    StrategyValuationScope,
    build_portfolio_currency_valuation_summary,
    build_strategy_valuation_summary,
)
from onejournal.pnl.position_valuation import (
    CanonicalPositionValuation,
    PositionValuationRun,
)


class PositionValuationAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.when = datetime(2026, 8, 31, 14, 30, tzinfo=UTC)
        self.long_call = InstrumentIdentity(
            asset_class="option", market_scope="US", currency="USD",
            underlying_symbol="AAPL", expiry=date(2026, 9, 18),
            option_right="CALL", strike=Decimal("200"), multiplier=Decimal("100"),
        )
        self.short_call = InstrumentIdentity(
            asset_class="option", market_scope="US", currency="USD",
            underlying_symbol="AAPL", expiry=date(2026, 9, 18),
            option_right="CALL", strike=Decimal("210"), multiplier=Decimal("100"),
        )

    def position(self, identity, *, status="valid", value="100", pnl="10"):
        is_valid = status == "valid"
        return CanonicalPositionValuation(
            identity=identity, legacy_instrument_key=identity.key, direction="LONG",
            quantity=Decimal("1"), broker_quantity=Decimal("1"),
            open_cost_basis=Decimal("90"), reconciliation_status=(
                "valid" if is_valid else "reconciliation_pending"
            ),
            reconciliation_reason=None if is_valid else "synthetic mismatch",
            mark=None, market_value=Decimal(value) if is_valid else None,
            unrealized_pnl=Decimal(pnl) if is_valid else None,
            status=status, reason=None if is_valid else "synthetic failure",
        )

    def valuation_run(self, positions):
        return PositionValuationRun(
            valuation_run_uid="position-valuation:synthetic", snapshot_uid="snapshot-1",
            source_broker="schwab", connection_uid="conn", source_account_id="acct",
            asof=date(2026, 8, 31), evaluated_at=self.when,
            calculation_version="fifo.v1", fill_fingerprint="a" * 64,
            lifecycle_fingerprint="b" * 64, max_snapshot_age_seconds=60,
            positions=tuple(positions),
        )

    def scope(self):
        return StrategyValuationScope(
            "strategy:vertical-1", "USD",
            (self.long_call.key, self.short_call.key),
        )

    def test_two_valid_option_legs_produce_one_same_currency_strategy_total(self) -> None:
        summary = build_strategy_valuation_summary(
            self.valuation_run((self.position(self.long_call, value="250", pnl="50"),
                                self.position(self.short_call, value="-100", pnl="20"))),
            scope=self.scope(),
        )
        self.assertEqual(summary.status, "valid")
        self.assertEqual(summary.market_value, Decimal("150"))
        self.assertEqual(summary.unrealized_pnl, Decimal("70"))
        self.assertEqual(summary.valid_count, 2)
        self.assertEqual(summary.reason_codes, ())

    def test_unavailable_or_unreconciled_leg_blocks_entire_strategy_total(self) -> None:
        for status, expected_reason in (
            ("unavailable", "position_unavailable"),
            ("reconciliation_pending", "position_reconciliation_pending"),
        ):
            with self.subTest(status=status):
                summary = build_strategy_valuation_summary(
                    self.valuation_run((self.position(self.long_call),
                                        self.position(self.short_call, status=status))),
                    scope=self.scope(),
                )
                self.assertEqual(summary.status, "unavailable")
                self.assertIsNone(summary.market_value)
                self.assertIsNone(summary.unrealized_pnl)
                self.assertIn(expected_reason, summary.reason_codes)

    def test_missing_declared_leg_blocks_total_without_using_partial_subtotal(self) -> None:
        summary = build_strategy_valuation_summary(
            self.valuation_run((self.position(self.long_call),)), scope=self.scope()
        )
        self.assertEqual(summary.status, "unavailable")
        self.assertEqual(summary.missing_count, 1)
        self.assertIsNone(summary.market_value)
        self.assertIn("strategy_leg_missing", summary.reason_codes)

    def test_currency_mismatch_and_duplicate_scope_fail_closed(self) -> None:
        with self.assertRaisesRegex(PositionAggregationError, "currency"):
            build_strategy_valuation_summary(
                self.valuation_run((self.position(self.long_call), self.position(self.short_call))),
                scope=StrategyValuationScope(
                    "strategy:vertical-1", "CAD",
                    (self.long_call.key, self.short_call.key),
                ),
            )
        with self.assertRaisesRegex(PositionAggregationError, "duplicate"):
            StrategyValuationScope(
                "strategy:vertical-1", "USD", (self.long_call.key, self.long_call.key)
            )

    def test_portfolio_currency_total_is_all_or_nothing_and_not_false_zero(self) -> None:
        valid = build_portfolio_currency_valuation_summary(
            self.valuation_run((self.position(self.long_call, value="250", pnl="50"),
                                self.position(self.short_call, value="-100", pnl="20"))),
            currency="USD",
        )
        self.assertEqual(valid.status, "valid")
        self.assertEqual(valid.market_value, Decimal("150"))
        self.assertEqual(valid.unrealized_pnl, Decimal("70"))

        blocked = build_portfolio_currency_valuation_summary(
            self.valuation_run((self.position(self.long_call),
                                self.position(self.short_call, status="unavailable"))),
            currency="USD",
        )
        self.assertEqual(blocked.status, "unavailable")
        self.assertEqual(blocked.valid_count, 1)
        self.assertEqual(blocked.unavailable_count, 1)
        self.assertIsNone(blocked.market_value)
        self.assertIsNone(blocked.unrealized_pnl)

        empty = build_portfolio_currency_valuation_summary(self.valuation_run(()), currency="USD")
        self.assertEqual(empty.status, "unavailable")
        self.assertIsNone(empty.market_value)
        self.assertEqual(empty.reason_codes, ("no_positions_in_currency_scope",))


if __name__ == "__main__":
    unittest.main()
