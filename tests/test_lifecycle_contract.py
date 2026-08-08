from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import unittest

from onejournal.brokers.normalized import NormalizedFill
from onejournal.journal.lifecycle import (
    LifecycleContractError,
    build_lifecycle_fill_events,
)


class LifecycleContractTests(unittest.TestCase):
    def _fill(
        self,
        fill_uid: str,
        side: str,
        quantity: str,
        fill_price: str,
        source_order_id: str,
        *,
        open_close: str | None = None,
        asset_class: str = "stock",
        symbol: str = "AAPL",
        episode_group_id: str | None = None,
        currency: str = "USD",
        source_account_id: str = "demo",
    ) -> NormalizedFill:
        return NormalizedFill(
            fill_uid=fill_uid,
            source_broker="manual_csv",
            source_account_id=source_account_id,
            source_fill_id=f"{fill_uid}-src",
            source_order_id=source_order_id,
            episode_group_id=episode_group_id,
            asof=datetime(2026, 1, 1).date(),
            filled_at=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            asset_class=asset_class,
            symbol=symbol,
            side=side,
            quantity=Decimal(quantity),
            fill_price=Decimal(fill_price),
            commission=Decimal("0"),
            fees=Decimal("0"),
            currency=currency,
            fetched_at=datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc),
            raw_path="tests/fixtures/lifecycle",
            open_close=open_close,
            execution_venue=None,
            liquidity_flag=None,
        )

    def test_partial_fills_preserve_fill_granularity(self) -> None:
        fills = [
            self._fill("fill-1a", "BUY_TO_OPEN", "40", "10", source_order_id="ord-1"),
            self._fill("fill-1b", "BUY_TO_OPEN", "60", "10", source_order_id="ord-1"),
        ]
        result = build_lifecycle_fill_events(fills)
        self.assertEqual(len(result.events), 2)
        self.assertEqual(result.events[0].fill_uid, "fill-1a")
        self.assertEqual(result.events[1].fill_uid, "fill-1b")
        self.assertEqual(result.events[0].fill_quantity, Decimal("40"))
        self.assertEqual(result.events[1].fill_quantity, Decimal("60"))

    def test_partial_exit_leaves_open_inventory(self) -> None:
        fills = [
            self._fill("buy-open", "BUY_TO_OPEN", "100", "10", source_order_id="ord-open"),
            self._fill("sell-close-partial", "SELL_TO_CLOSE", "40", "12", source_order_id="ord-close-1"),
            self._fill("sell-close-remaining", "SELL_TO_CLOSE", "30", "13", source_order_id="ord-close-2"),
        ]
        result = build_lifecycle_fill_events(fills)
        self.assertEqual(result.events[0].status, "open")
        self.assertEqual(result.events[1].status, "close_full")
        self.assertEqual(result.events[1].matched_open_quantity, Decimal("40"))
        self.assertEqual(result.events[1].open_quantity_after, Decimal("60"))
        self.assertEqual(result.events[2].status, "close_full")
        self.assertEqual(result.events[2].matched_open_quantity, Decimal("30"))
        self.assertEqual(result.events[2].open_quantity_after, Decimal("30"))
        key = result.events[0].scope_key
        self.assertEqual(result.scope_open_quantity[key], (Decimal("30"), Decimal("0")))

    def test_over_closing_fill_fails_when_not_allowed(self) -> None:
        fills = [
            self._fill("open", "BUY_TO_OPEN", "50", "10", source_order_id="ord-open"),
            self._fill("close", "SELL_TO_CLOSE", "80", "11", source_order_id="ord-close"),
        ]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

    def test_over_closing_fill_is_partial_when_allowed(self) -> None:
        fills = [
            self._fill("open", "BUY_TO_OPEN", "50", "10", source_order_id="ord-open"),
            self._fill("close", "SELL_TO_CLOSE", "80", "11", source_order_id="ord-close"),
        ]
        result = build_lifecycle_fill_events(fills, allow_unmatched_close=True)
        self.assertEqual(result.events[1].status, "close_partial")
        self.assertEqual(result.events[1].matched_open_quantity, Decimal("50"))
        self.assertEqual(result.events[1].unmatched_close_quantity, Decimal("30"))
        self.assertEqual(result.events[1].open_quantity_after, Decimal("0"))
        self.assertEqual(result.scope_open_quantity[result.events[1].scope_key], (Decimal("0"), Decimal("0")))

    def test_unsupported_side_is_rejected(self) -> None:
        fills = [self._fill("bad", "HOLD", "10", "10", source_order_id="ord-bad")]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

    def test_sell_to_open_with_close_flag_is_rejected(self) -> None:
        fills = [
            self._fill(
                "bad", "SELL_TO_OPEN", "10", "10", source_order_id="ord-bad", open_close="CLOSE"
            )
        ]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

    def test_short_close_consume_short_inventory(self) -> None:
        fills = [
            self._fill(
                "short-open-1",
                "SELL_TO_OPEN",
                "75",
                "4",
                source_order_id="ord-short-open",
            ),
            self._fill(
                "short-close-1",
                "BUY_TO_CLOSE",
                "25",
                "3",
                source_order_id="ord-short-close",
            ),
        ]
        result = build_lifecycle_fill_events(fills)
        self.assertEqual(result.events[1].status, "close_full")
        self.assertEqual(result.events[1].direction, "SHORT")
        self.assertEqual(result.events[1].matched_open_quantity, Decimal("25"))
        self.assertEqual(result.scope_open_quantity[result.events[0].scope_key], (Decimal("0"), Decimal("50")))

    def test_buy_to_close_short_is_supported(self) -> None:
        fills = [
            self._fill(
                "short-open",
                "SELL_TO_OPEN",
                "30",
                "4",
                source_order_id="ord-short-open",
            ),
            self._fill(
                "short-close",
                "BUY",
                "10",
                "3.5",
                source_order_id="ord-short-close",
                open_close="CLOSE",
            ),
        ]
        result = build_lifecycle_fill_events(fills)
        self.assertEqual(result.events[1].status, "close_full")
        self.assertEqual(result.events[1].direction, "SHORT")
        self.assertEqual(result.events[1].fill_uid, "short-close")
        self.assertEqual(result.events[1].matched_open_quantity, Decimal("10"))
        self.assertEqual(result.scope_open_quantity[result.events[1].scope_key], (Decimal("0"), Decimal("20")))

    def test_buy_to_close_default_is_supported_when_open_close_not_explicit(self) -> None:
        fills = [
            self._fill(
                "short-open",
                "SELL_TO_OPEN",
                "30",
                "4",
                source_order_id="ord-short-open",
            ),
            self._fill(
                "short-close-default",
                "BUY_TO_CLOSE",
                "10",
                "3.5",
                source_order_id="ord-short-close",
            ),
        ]
        result = build_lifecycle_fill_events(fills)
        self.assertEqual(result.events[1].status, "close_full")
        self.assertEqual(result.events[1].direction, "SHORT")
        self.assertEqual(result.events[1].fill_uid, "short-close-default")
        self.assertEqual(result.events[1].matched_open_quantity, Decimal("10"))
        self.assertEqual(result.scope_open_quantity[result.events[1].scope_key], (Decimal("0"), Decimal("20")))

    def test_account_is_part_of_lifecycle_matching_scope(self) -> None:
        fills = [
            self._fill(
                "acct1-open",
                "BUY_TO_OPEN",
                "100",
                "10",
                source_order_id="ord-acct1-open",
                source_account_id="acct-1",
            ),
            self._fill(
                "acct2-close",
                "SELL_TO_CLOSE",
                "100",
                "11",
                source_order_id="ord-acct2-close",
                source_account_id="acct-2",
            ),
        ]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

    def test_symbol_is_part_of_lifecycle_matching_scope(self) -> None:
        fills = [
            self._fill(
                "aapl-open",
                "BUY_TO_OPEN",
                "100",
                "10",
                source_order_id="ord-aapl-open",
                symbol="AAPL",
            ),
            self._fill(
                "msft-close",
                "SELL_TO_CLOSE",
                "20",
                "11",
                source_order_id="ord-msft-close",
                symbol="MSFT",
            ),
        ]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

    def test_currency_is_part_of_lifecycle_matching_scope(self) -> None:
        fills = [
            self._fill(
                "usd-open",
                "BUY_TO_OPEN",
                "100",
                "10",
                source_order_id="ord-usd-open",
                currency="USD",
            ),
            self._fill(
                "aud-close",
                "SELL_TO_CLOSE",
                "20",
                "11",
                source_order_id="ord-aud-close",
                currency="AUD",
            ),
        ]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

    def test_episode_group_id_unifies_matching_scope_when_present(self) -> None:
        fills = [
            self._fill(
                "aapl-open",
                "BUY_TO_OPEN",
                "20",
                "10",
                source_order_id="ord-aapl-open",
                symbol="AAPL",
                episode_group_id="V0001",
            ),
            self._fill(
                "msft-open",
                "BUY_TO_OPEN",
                "20",
                "12",
                source_order_id="ord-msft-open",
                symbol="MSFT",
                episode_group_id="V0001",
            ),
            self._fill(
                "close",
                "SELL_TO_CLOSE",
                "40",
                "11",
                source_order_id="ord-cross-close",
                symbol="AAPL",
                episode_group_id="V0001",
            ),
        ]
        result = build_lifecycle_fill_events(fills)
        self.assertEqual(len(result.events), 3)
        self.assertEqual(result.events[2].status, "close_full")
        self.assertEqual(result.events[2].matched_open_quantity, Decimal("40"))
        self.assertEqual(result.events[2].unmatched_close_quantity, Decimal("0"))
        self.assertEqual(
            result.scope_open_quantity[result.events[2].scope_key], (Decimal("0"), Decimal("0"))
        )

    def test_episode_group_id_required_to_unify_cross_symbol_matching(self) -> None:
        fills = [
            self._fill(
                "aapl-open",
                "BUY_TO_OPEN",
                "20",
                "10",
                source_order_id="ord-aapl-open",
                symbol="AAPL",
            ),
            self._fill(
                "msft-open",
                "BUY_TO_OPEN",
                "20",
                "12",
                source_order_id="ord-msft-open",
                symbol="MSFT",
            ),
            self._fill(
                "close",
                "SELL_TO_CLOSE",
                "40",
                "11",
                source_order_id="ord-cross-close",
                symbol="AAPL",
            ),
        ]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

    def test_negative_or_zero_quantity_is_rejected(self) -> None:
        fills = [self._fill("bad", "BUY_TO_OPEN", "0", "10", source_order_id="ord-zero")]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

        fills = [self._fill("bad", "SELL_TO_CLOSE", "-1", "10", source_order_id="ord-negative")]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)

    def test_case_and_whitespace_side_is_normalized(self) -> None:
        fills = [
            self._fill(
                "open",
                "  buy_to_open ",
                "10",
                "10",
                source_order_id="ord-open",
                open_close=" open ",
            ),
            self._fill(
                "close",
                "  sell_to_close ",
                "10",
                "11",
                source_order_id="ord-close",
            ),
        ]
        result = build_lifecycle_fill_events(fills)
        self.assertEqual(result.events[0].status, "open")
        self.assertEqual(result.events[1].status, "close_full")
        self.assertEqual(result.events[1].matched_open_quantity, Decimal("10"))

    def test_fill_order_is_preserved_when_timestamps_match(self) -> None:
        fills = [
            self._fill("close-later", "SELL_TO_CLOSE", "10", "12", source_order_id="ord-close"),
            self._fill("open-first", "BUY_TO_OPEN", "20", "10", source_order_id="ord-open"),
        ]
        with self.assertRaises(LifecycleContractError):
            build_lifecycle_fill_events(fills)


if __name__ == "__main__":
    unittest.main()
