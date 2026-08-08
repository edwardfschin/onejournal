from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from onejournal.brokers.normalized import NormalizedFill
from onejournal.pnl import (
    PnLCalculationResult,
    PnLGroupResult,
    LotAllocationError,
    calculate_fifo_pnl_from_fills,
    build_instrument_key,
)


class PnLFifoContractTests(unittest.TestCase):
    def _group_for_instrument(
        self,
        result: PnLCalculationResult,
        fill: NormalizedFill,
    ) -> PnLGroupResult:
        key = (fill.source_broker, fill.source_account_id, build_instrument_key(fill), fill.currency)
        group = result.groups.get(key)
        if group is not None:
            return group
        raise AssertionError(
            f"Scope key {key} not found in result groups: {list(result.groups.keys())}"
        )

    def _fill(
              self,
              fill_uid: str,
              side: str,
              quantity: str,
              fill_price: str,
              asset_class: str = "stock",
              symbol: str = "AAPL",
              option_symbol: str | None = None,
              underlying_symbol: str | None = None,
              option_type: str | None = None,
              expiry=None,
              strike: str | None = None,
              multiplier: str | None = None,
              open_close: str | None = None,
              commission: str = "0",
              fees: str = "0",
              source_account_id: str = "demo",
              ) -> NormalizedFill:
        return NormalizedFill(
            fill_uid=fill_uid,
            source_broker="manual_csv",
            source_account_id=source_account_id,
            source_fill_id=f"{fill_uid}-src",
            source_order_id=fill_uid,
            episode_group_id=None,
            asof=datetime(2026, 1, 1).date(),
            filled_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            asset_class=asset_class,
            symbol=symbol,
            side=side,
            quantity=Decimal(quantity),
            fill_price=Decimal(fill_price),
            commission=Decimal(commission),
            fees=Decimal(fees),
            currency="USD",
            fetched_at=datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc),
            raw_path="tests/fixtures/pnl",
            option_symbol=option_symbol,
            underlying_symbol=underlying_symbol,
            option_type=option_type,
            expiry=expiry,
            strike=Decimal(strike) if strike is not None else None,
            multiplier=Decimal(multiplier) if multiplier is not None else None,
            open_close=open_close,
            execution_venue=None,
            liquidity_flag=None,
        )

    def test_works_for_fully_closed_long_trade(self) -> None:
        fills = [
            self._fill(
                fill_uid="buy-1",
                side="BUY",
                quantity="100",
                fill_price="10",
                commission="1",
                fees="0",
            ),
            self._fill(
                fill_uid="sell-1",
                side="SELL_TO_CLOSE",
                quantity="100",
                fill_price="12",
                commission="1",
                fees="0",
            ),
        ]
        result = calculate_fifo_pnl_from_fills(fills)
        group = self._group_for_instrument(result, fills[0])
        self.assertEqual(group.realized_pnl, Decimal("198"))
        self.assertEqual(group.open_quantity, Decimal("0"))
        self.assertEqual(result.total_realized_pnl_by_currency["USD"], Decimal("198"))

    def test_partial_exit_leaves_open_cost_basis(self) -> None:
        fills = [
            self._fill(fill_uid="buy-2", side="BUY", quantity="100", fill_price="10"),
            self._fill(
                fill_uid="sell-2",
                side="SELL_TO_CLOSE",
                quantity="40",
                fill_price="12",
            ),
        ]
        result = calculate_fifo_pnl_from_fills(fills)
        group = self._group_for_instrument(result, fills[0])
        self.assertEqual(group.realized_pnl, Decimal("80"))
        self.assertEqual(group.open_quantity, Decimal("60"))
        self.assertEqual(group.open_cost_basis, Decimal("600"))

    def test_short_option_with_multiplier_and_fees(self) -> None:
        fills = [
            self._fill(
                fill_uid="option-open",
                side="SELL_TO_OPEN",
                quantity="1",
                fill_price="2.00",
                asset_class="option",
                symbol="XYZ240315C100",
                option_symbol="XYZ240315C100",
                underlying_symbol="XYZ",
                option_type="CALL",
                expiry=datetime(2024, 3, 15, tzinfo=timezone.utc).date(),
                strike="100",
                multiplier="100",
                commission="0",
            ),
            self._fill(
                fill_uid="option-close",
                side="BUY_TO_CLOSE",
                quantity="1",
                fill_price="1.20",
                asset_class="option",
                symbol="XYZ240315C100",
                option_symbol="XYZ240315C100",
                underlying_symbol="XYZ",
                option_type="CALL",
                expiry=datetime(2024, 3, 15, tzinfo=timezone.utc).date(),
                strike="100",
                multiplier="100",
                fees="2",
            ),
        ]
        result = calculate_fifo_pnl_from_fills(fills)
        group = self._group_for_instrument(result, fills[0])
        self.assertEqual(group.realized_pnl, Decimal("78"))
        self.assertEqual(group.open_quantity, Decimal("0"))

    def test_buy_side_with_explicit_close_open_close(self) -> None:
        fills = [
            self._fill(
                fill_uid="buy-open",
                side="BUY_TO_OPEN",
                quantity="1",
                fill_price="10",
                asset_class="stock",
                symbol="AAPL",
                commission="1",
            ),
            self._fill(
                fill_uid="buy-close",
                side="BUY",
                quantity="1",
                fill_price="9",
                asset_class="stock",
                symbol="AAPL",
                open_close="close",
                commission="1",
            ),
        ]
        result = calculate_fifo_pnl_from_fills(fills)
        group = self._group_for_instrument(result, fills[0])
        self.assertEqual(group.realized_pnl, Decimal("-3"))
        self.assertEqual(group.open_quantity, Decimal("0"))

    def test_unrealized_uses_mark_when_available(self) -> None:
        fill = self._fill(fill_uid="open", side="BUY", quantity="100", fill_price="10", symbol="MSFT")
        mark_key = build_instrument_key(fill)
        result = calculate_fifo_pnl_from_fills([fill], marks={mark_key: Decimal("11")})
        group = self._group_for_instrument(result, fill)
        self.assertEqual(group.unrealized_pnl, Decimal("100"))
        self.assertEqual(result.total_unrealized_pnl_by_currency["USD"], Decimal("100"))

    def test_unrealized_marks_can_be_shared_across_accounts(self) -> None:
        fill_acct1 = self._fill(
            fill_uid="acct1-open",
            side="BUY",
            quantity="100",
            fill_price="10",
            symbol="MSFT",
            source_account_id="acct_1",
        )
        fill_acct2 = self._fill(
            fill_uid="acct2-open",
            side="BUY",
            quantity="100",
            fill_price="10",
            symbol="MSFT",
            source_account_id="acct_2",
        )
        result = calculate_fifo_pnl_from_fills(
            [fill_acct1, fill_acct2],
            marks={build_instrument_key(fill_acct1): Decimal("11")},
        )
        self.assertEqual(self._group_for_instrument(result, fill_acct1).unrealized_pnl, Decimal("100"))
        self.assertEqual(self._group_for_instrument(result, fill_acct2).unrealized_pnl, Decimal("100"))
        self.assertEqual(result.total_unrealized_pnl_by_currency["USD"], Decimal("200"))

    def test_unrealized_is_none_when_mark_missing(self) -> None:
        fill = self._fill(fill_uid="open-missing-mark", side="BUY", quantity="100", fill_price="10")
        result = calculate_fifo_pnl_from_fills([fill])
        group = self._group_for_instrument(result, fill)
        self.assertIsNone(group.unrealized_pnl)
        self.assertIsNone(result.total_unrealized_pnl_by_currency["USD"])

    def test_unrealized_mixed_mark_coverage_fails_closed(self) -> None:
        fill_with_mark = self._fill(fill_uid="open-mark", side="BUY", quantity="100", fill_price="10", symbol="AAPL")
        fill_without_mark = self._fill(fill_uid="open-no-mark", side="BUY", quantity="100", fill_price="10", symbol="MSFT")
        result = calculate_fifo_pnl_from_fills(
            [fill_with_mark, fill_without_mark],
            marks={build_instrument_key(fill_with_mark): Decimal("11")},
        )
        self.assertEqual(result.total_realized_pnl_by_currency["USD"], Decimal("0"))
        self.assertEqual(self._group_for_instrument(result, fill_with_mark).unrealized_pnl, Decimal("100"))
        self.assertIsNone(self._group_for_instrument(result, fill_without_mark).unrealized_pnl)
        self.assertIsNone(result.total_unrealized_pnl_by_currency["USD"])

    def test_close_without_matching_open_lot_fails_closed(self) -> None:
        close_only = [self._fill(fill_uid="sell-only", side="SELL_TO_CLOSE", quantity="1", fill_price="50")]
        with self.assertRaises(LotAllocationError):
            calculate_fifo_pnl_from_fills(close_only)

    def test_unmatched_close_can_be_skipped_for_non_strict_pnl(self) -> None:
        close_only = [self._fill(fill_uid="sell-only", side="SELL_TO_CLOSE", quantity="1", fill_price="50")]
        result = calculate_fifo_pnl_from_fills(close_only, allow_unmatched_close=True)
        self.assertEqual(result.unmatched_close_fill_uids, ("sell-only",))
        self.assertEqual(result.total_realized_pnl_by_currency, {"USD": Decimal("0")})
        self.assertEqual(result.total_unrealized_pnl_by_currency, {"USD": None})
        group = self._group_for_instrument(result, close_only[0])
        self.assertEqual(group.realized_pnl, Decimal("0"))
        self.assertEqual(group.open_quantity, Decimal("0"))

    def test_unsupported_fill_side_fails_closed(self) -> None:
        unsupported = self._fill(fill_uid="unsupported", side="UNKNOWN", quantity="1", fill_price="10")
        with self.assertRaises(LotAllocationError):
            calculate_fifo_pnl_from_fills([unsupported])


if __name__ == "__main__":
    unittest.main()
