from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from onejournal.brokers.normalized import NormalizedFill
from onejournal.pnl import (
    OPTION_LIFECYCLE_CALCULATION_VERSION,
    ApprovedOptionLifecycleEvent,
    LotAllocationError,
    build_instrument_key,
    calculate_fifo_pnl_with_lifecycle_events,
)


class PnLLifecycleAllocationTests(unittest.TestCase):
    def _fill(
        self,
        *,
        fill_uid: str,
        side: str,
        quantity: str,
        fill_price: str,
        filled_at: datetime,
        asset_class: str = "stock",
        symbol: str = "AAPL",
        open_close: str | None = None,
        commission: str = "0",
        fees: str = "0",
        option_symbol: str | None = None,
        underlying_symbol: str | None = None,
        option_type: str | None = None,
        expiry: date | None = None,
        strike: str | None = None,
        multiplier: str | None = None,
    ) -> NormalizedFill:
        return NormalizedFill(
            fill_uid=fill_uid,
            source_broker="manual_csv",
            source_account_id="DEMO",
            source_fill_id=f"{fill_uid}-source",
            source_order_id=None,
            episode_group_id=None,
            asof=filled_at.date(),
            filled_at=filled_at,
            asset_class=asset_class,
            symbol=symbol,
            side=side,
            quantity=Decimal(quantity),
            fill_price=Decimal(fill_price),
            commission=Decimal(commission),
            fees=Decimal(fees),
            currency="USD",
            fetched_at=filled_at,
            raw_path="tests/fixtures/lifecycle",
            option_symbol=option_symbol,
            underlying_symbol=underlying_symbol,
            option_type=option_type,
            expiry=expiry,
            strike=Decimal(strike) if strike is not None else None,
            multiplier=Decimal(multiplier) if multiplier is not None else None,
            open_close=open_close,
        )

    def _option_fill(
        self,
        *,
        fill_uid: str,
        side: str,
        option_type: str,
        fill_price: str = "2",
        commission: str = "1",
        quantity: str = "1",
        minute: int = 0,
    ) -> NormalizedFill:
        option_symbol = f"AAPL  260717{option_type[0]}00100000"
        return self._fill(
            fill_uid=fill_uid,
            side=side,
            quantity=quantity,
            fill_price=fill_price,
            filled_at=datetime(2026, 7, 1, 14, minute, tzinfo=timezone.utc),
            asset_class="option",
            symbol=option_symbol,
            option_symbol=option_symbol,
            underlying_symbol="AAPL",
            option_type=option_type,
            expiry=date(2026, 7, 17),
            strike="100",
            multiplier="100",
            open_close="OPEN",
            commission=commission,
        )

    def _event(
        self,
        option_fill: NormalizedFill,
        *,
        event_type: str,
        predecessor_direction: str,
        successor_action: str | None = None,
        successor_position_effect: str | None = None,
        successor_quantity: str | None = None,
        strike_cash_amount: str | None = None,
        event_fees: str = "0",
        contracts: str = "1",
        predecessor_open_fill_uids: tuple[str, ...] | None = None,
        evidence_status: str = "approved",
    ) -> ApprovedOptionLifecycleEvent:
        scope = (
            option_fill.source_broker,
            option_fill.source_account_id,
            build_instrument_key(option_fill),
            option_fill.currency,
        )
        return ApprovedOptionLifecycleEvent(
            event_uid=f"event:{option_fill.fill_uid}:{event_type.lower()}",
            event_type=event_type,
            source_broker=option_fill.source_broker,
            source_account_id=option_fill.source_account_id,
            currency=option_fill.currency,
            effective_at=datetime(2026, 7, 17, 20, 0, tzinfo=timezone.utc),
            option_scope_key=scope,
            predecessor_direction=predecessor_direction,
            contracts=Decimal(contracts),
            predecessor_open_fill_uids=(
                predecessor_open_fill_uids
                if predecessor_open_fill_uids is not None
                else (option_fill.fill_uid,)
            ),
            event_commission=Decimal("0"),
            event_fees=Decimal(event_fees),
            evidence_status=evidence_status,
            source_event_leg_uids=("event-leg:0",),
            successor_action=successor_action,
            successor_position_effect=successor_position_effect,
            successor_symbol=("AAPL" if successor_action else None),
            successor_quantity=(
                Decimal(successor_quantity)
                if successor_quantity is not None
                else None
            ),
            strike_cash_amount=(
                Decimal(strike_cash_amount)
                if strike_cash_amount is not None
                else None
            ),
        )

    def _group(self, result, fill: NormalizedFill):
        key = (
            fill.source_broker,
            fill.source_account_id,
            build_instrument_key(fill),
            fill.currency,
        )
        return result.groups[key]

    def test_long_call_exercise_carries_basis_into_long_stock(self) -> None:
        option = self._option_fill(
            fill_uid="long-call", side="BUY_TO_OPEN", option_type="CALL"
        )
        event = self._event(
            option,
            event_type="EXERCISE",
            predecessor_direction="LONG",
            successor_action="BUY",
            successor_position_effect="OPEN",
            successor_quantity="100",
            strike_cash_amount="10000",
        )

        result = calculate_fifo_pnl_with_lifecycle_events([option], [event])

        self.assertEqual(self._group(result, option).open_quantity, Decimal("0"))
        stock = self._fill(
            fill_uid="stock-key",
            side="BUY",
            quantity="100",
            fill_price="100",
            filled_at=event.effective_at,
        )
        self.assertEqual(self._group(result, stock).open_quantity, Decimal("100"))
        self.assertEqual(self._group(result, stock).open_cost_basis, Decimal("10201"))
        allocation = result.lifecycle_allocations[0]
        self.assertEqual(
            allocation.calculation_version,
            OPTION_LIFECYCLE_CALCULATION_VERSION,
        )
        self.assertEqual(allocation.net_option_basis, Decimal("201"))
        self.assertEqual(allocation.successor_effective_price, Decimal("102.01"))
        self.assertEqual(allocation.realized_pnl, Decimal("0"))

    def test_short_put_assignment_reduces_successor_stock_basis(self) -> None:
        option = self._option_fill(
            fill_uid="short-put", side="SELL_TO_OPEN", option_type="PUT"
        )
        event = self._event(
            option,
            event_type="ASSIGNMENT",
            predecessor_direction="SHORT",
            successor_action="BUY",
            successor_position_effect="OPEN",
            successor_quantity="100",
            strike_cash_amount="10000",
            event_fees="1",
        )

        result = calculate_fifo_pnl_with_lifecycle_events([option], [event])

        stock = self._fill(
            fill_uid="stock-key",
            side="BUY",
            quantity="100",
            fill_price="100",
            filled_at=event.effective_at,
        )
        self.assertEqual(self._group(result, stock).open_cost_basis, Decimal("9802"))
        allocation = result.lifecycle_allocations[0]
        self.assertEqual(allocation.net_option_basis, Decimal("-199"))
        self.assertEqual(allocation.successor_effective_price, Decimal("98.01"))
        self.assertEqual(allocation.allocated_event_fees, Decimal("1"))

    def test_long_put_exercise_adjusts_equity_disposal_proceeds(self) -> None:
        stock = self._fill(
            fill_uid="stock-open",
            side="BUY",
            quantity="100",
            fill_price="90",
            filled_at=datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc),
        )
        option = self._option_fill(
            fill_uid="long-put", side="BUY_TO_OPEN", option_type="PUT"
        )
        event = self._event(
            option,
            event_type="EXERCISE",
            predecessor_direction="LONG",
            successor_action="SELL",
            successor_position_effect="CLOSE",
            successor_quantity="100",
            strike_cash_amount="10000",
            event_fees="1",
        )

        result = calculate_fifo_pnl_with_lifecycle_events([stock, option], [event])

        self.assertEqual(self._group(result, stock).open_quantity, Decimal("0"))
        self.assertEqual(self._group(result, stock).realized_pnl, Decimal("798"))
        self.assertEqual(result.lifecycle_allocations[0].net_option_basis, Decimal("201"))
        self.assertEqual(result.closed_allocations[0].source_event_uid, event.event_uid)

    def test_short_call_assignment_adjusts_equity_disposal_proceeds(self) -> None:
        stock = self._fill(
            fill_uid="stock-open",
            side="BUY",
            quantity="100",
            fill_price="90",
            filled_at=datetime(2026, 7, 1, 13, 0, tzinfo=timezone.utc),
        )
        option = self._option_fill(
            fill_uid="short-call", side="SELL_TO_OPEN", option_type="CALL"
        )
        event = self._event(
            option,
            event_type="ASSIGNMENT",
            predecessor_direction="SHORT",
            successor_action="SELL",
            successor_position_effect="CLOSE",
            successor_quantity="100",
            strike_cash_amount="10000",
            event_fees="1",
        )

        result = calculate_fifo_pnl_with_lifecycle_events([stock, option], [event])

        self.assertEqual(self._group(result, stock).realized_pnl, Decimal("1198"))
        self.assertEqual(result.lifecycle_allocations[0].net_option_basis, Decimal("-199"))

    def test_long_and_short_expiration_realize_remaining_option_basis_once(self) -> None:
        long_option = self._option_fill(
            fill_uid="long-expiry", side="BUY_TO_OPEN", option_type="CALL"
        )
        short_option = self._option_fill(
            fill_uid="short-expiry", side="SELL_TO_OPEN", option_type="PUT"
        )
        long_event = self._event(
            long_option,
            event_type="EXPIRATION",
            predecessor_direction="LONG",
        )
        short_event = self._event(
            short_option,
            event_type="EXPIRATION",
            predecessor_direction="SHORT",
        )

        result = calculate_fifo_pnl_with_lifecycle_events(
            [long_option, short_option], [long_event, short_event]
        )

        allocations = {row.event_uid: row for row in result.lifecycle_allocations}
        self.assertEqual(allocations[long_event.event_uid].realized_pnl, Decimal("-201"))
        self.assertEqual(allocations[short_event.event_uid].realized_pnl, Decimal("199"))
        self.assertEqual(result.total_realized_pnl_by_currency["USD"], Decimal("-2"))

    def test_review_required_event_is_rejected(self) -> None:
        option = self._option_fill(
            fill_uid="review-only", side="BUY_TO_OPEN", option_type="CALL"
        )
        event = self._event(
            option,
            event_type="EXPIRATION",
            predecessor_direction="LONG",
            evidence_status="review_required",
        )

        with self.assertRaisesRegex(LotAllocationError, "not approved evidence"):
            calculate_fifo_pnl_with_lifecycle_events([option], [event])

    def test_lifecycle_predecessor_links_must_follow_fifo(self) -> None:
        first = self._option_fill(
            fill_uid="first", side="BUY_TO_OPEN", option_type="CALL", minute=0
        )
        second = self._option_fill(
            fill_uid="second", side="BUY_TO_OPEN", option_type="CALL", minute=1
        )
        event = self._event(
            first,
            event_type="EXPIRATION",
            predecessor_direction="LONG",
            predecessor_open_fill_uids=("second",),
        )

        with self.assertRaisesRegex(LotAllocationError, "violates FIFO"):
            calculate_fifo_pnl_with_lifecycle_events([first, second], [event])

    def test_unmatched_event_quantity_fails_closed(self) -> None:
        option = self._option_fill(
            fill_uid="one-contract", side="BUY_TO_OPEN", option_type="CALL"
        )
        event = self._event(
            option,
            event_type="EXPIRATION",
            predecessor_direction="LONG",
            contracts="2",
        )

        with self.assertRaisesRegex(LotAllocationError, "unmatched contract"):
            calculate_fifo_pnl_with_lifecycle_events([option], [event])

    def test_equity_close_without_inventory_fails_closed(self) -> None:
        option = self._option_fill(
            fill_uid="naked-long-put", side="BUY_TO_OPEN", option_type="PUT"
        )
        event = self._event(
            option,
            event_type="EXERCISE",
            predecessor_direction="LONG",
            successor_action="SELL",
            successor_position_effect="CLOSE",
            successor_quantity="100",
            strike_cash_amount="10000",
        )

        with self.assertRaisesRegex(LotAllocationError, "No matching open lot"):
            calculate_fifo_pnl_with_lifecycle_events([option], [event])


if __name__ == "__main__":
    unittest.main()
