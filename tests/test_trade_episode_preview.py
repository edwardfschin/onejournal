from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from datetime import datetime, timezone

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
from onejournal.brokers.normalized import NormalizedFill
from onejournal.journal.episodes import build_episode_previews_from_fills


PROJECT_DIR = Path(__file__).resolve().parents[1]
FILLS_FIXTURE = PROJECT_DIR / "docs/examples/manual_csv/fills_template.csv"


class TradeEpisodePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fills = parse_manual_fills_csv(FILLS_FIXTURE)
        cls.episodes = build_episode_previews_from_fills(cls.fills)

    def test_reference_fixture_groups_and_classifies_expected_strategies(self) -> None:
        expected = {
            "AAPL_SELL_PUT_001": ("AAPL", "Sell Put", Decimal("235.00"), 1),
            "IWM_CALL_CREDIT_VERTICAL_001": ("IWM", "Call Credit Vertical", Decimal("340.00"), 2),
            "MSFT_BUY_CALL_001": ("MSFT", "Buy Call", Decimal("-420.00"), 1),
            "NVDA_CALL_DEBIT_VERTICAL_001": ("NVDA", "Call Debit Vertical", Decimal("-510.00"), 2),
            "QQQ_PUT_DEBIT_VERTICAL_001": ("QQQ", "Put Debit Vertical", Decimal("-440.00"), 2),
            "SPY_PUT_VERTICAL_001": ("SPY", "Put Credit Vertical", Decimal("380.00"), 2),
            "AAPL_STOCK_LONG_001": ("AAPL", "Stock Long", Decimal("-19000.00"), 1),
            "TSLA_STOCK_SHORT_001": ("TSLA", "Stock Short", Decimal("9000.00"), 1),
        }

        self.assertEqual(len(self.episodes), len(expected))
        for episode in self.episodes:
            group_id = episode.episode_uid.rsplit(":", 1)[-1]
            symbol, label, cashflow, leg_count = expected[group_id]
            self.assertEqual(episode.primary_symbol, symbol)
            self.assertEqual(episode.strategy_label, label)
            self.assertEqual(episode.gross_cashflow, cashflow)
            self.assertEqual(episode.leg_count, leg_count)
            self.assertEqual(episode.status, "open")

    def test_reference_fixture_totals_remain_cashflow_not_pnl(self) -> None:
        self.assertEqual(sum((e.gross_cashflow for e in self.episodes), Decimal("0")), Decimal("-10415.00"))
        self.assertEqual(sum((e.total_commission for e in self.episodes), Decimal("0")), Decimal("6.50"))
        self.assertEqual(sum((e.total_fees for e in self.episodes), Decimal("0")), Decimal("0.52"))

    def test_unsupported_side_fails_instead_of_guessing(self) -> None:
        invalid = replace(self.fills[0], side="HOLD")
        with self.assertRaisesRegex(ValueError, "Unsupported fill side"):
            build_episode_previews_from_fills([invalid])


class LifecycleEpisodePreviewTests(unittest.TestCase):
    def _fill(
        self,
        *,
        fill_uid: str,
        side: str,
        quantity: str,
        fill_price: str,
        source_order_id: str,
        source_account_id: str = "acct",
        symbol: str = "AAPL",
        source_fill_id: str | None = None,
        open_close: str | None = None,
        episode_group_id: str | None = None,
        asset_class: str = "stock",
        option_symbol: str | None = None,
        underlying_symbol: str | None = None,
        option_type: str | None = None,
        expiry: datetime.date | None = None,
        strike: Decimal | None = None,
    ) -> NormalizedFill:
        fill_expiry = expiry
        return NormalizedFill(
            fill_uid=fill_uid,
            source_broker="manual_csv",
            source_account_id=source_account_id,
            source_fill_id=source_fill_id or f"{fill_uid}-src",
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
            currency="USD",
            fetched_at=datetime(2026, 1, 1, 10, 1, tzinfo=timezone.utc),
            raw_path="tests/fixtures/lifecycle",
            open_close=open_close,
            execution_venue=None,
            liquidity_flag=None,
            option_symbol=option_symbol,
            underlying_symbol=underlying_symbol,
            option_type=option_type,
            expiry=fill_expiry,
            strike=strike,
            multiplier=Decimal("100") if asset_class == "option" else None,
        )

    def test_lifecycle_reopen_splits_episodes_with_deterministic_ids(self) -> None:
        fills = [
            self._fill(
                fill_uid="fill-open-1",
                side="BUY",
                quantity="100",
                fill_price="10",
                source_order_id="ord-open-1",
            ),
            self._fill(
                fill_uid="fill-close-1",
                side="SELL_TO_CLOSE",
                quantity="100",
                fill_price="11",
                source_order_id="ord-close-1",
                open_close="CLOSE",
            ),
            self._fill(
                fill_uid="fill-open-2",
                side="BUY",
                quantity="30",
                fill_price="12",
                source_order_id="ord-open-2",
            ),
            self._fill(
                fill_uid="fill-close-2",
                side="SELL_TO_CLOSE",
                quantity="10",
                fill_price="13",
                source_order_id="ord-close-2",
                open_close="CLOSE",
            ),
        ]
        previews = build_episode_previews_from_fills(fills)
        self.assertEqual(len(previews), 2)
        self.assertEqual(previews[0].status, "closed")
        self.assertEqual(previews[0].fill_count, 2)
        self.assertEqual(previews[1].status, "open")
        self.assertEqual(previews[1].fill_count, 2)
        self.assertEqual(previews[0].episode_uid, "manual_csv:acct:stock:stock|AAPL")
        self.assertEqual(previews[1].episode_uid, "manual_csv:acct:stock:stock|AAPL:2")

    def test_partial_close_keeps_episode_open(self) -> None:
        fills = [
            self._fill(
                fill_uid="fill-open-partial",
                side="BUY",
                quantity="100",
                fill_price="10",
                source_order_id="ord-open-partial",
            ),
            self._fill(
                fill_uid="fill-close-partial",
                side="SELL_TO_CLOSE",
                quantity="40",
                fill_price="11",
                source_order_id="ord-close-partial",
                open_close="CLOSE",
            ),
        ]
        previews = build_episode_previews_from_fills(fills)
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0].status, "open")
        self.assertEqual(previews[0].fill_count, 2)

    def test_multi_leg_vertical_open_and_full_close_stays_in_single_episode(self) -> None:
        fills = [
            self._fill(
                fill_uid="vertical-open-1",
                side="SELL_TO_OPEN",
                quantity="1",
                fill_price="4.00",
                source_order_id="ord-vert-open-1",
                asset_class="option",
                symbol="SPY 2026-07-17 500P",
                episode_group_id="SPY_PUT_VERTICAL_001",
                option_symbol="SPY 2026-07-17 500P",
                underlying_symbol="SPY",
                option_type="PUT",
                expiry=datetime(2026, 7, 17).date(),
                strike=Decimal("500"),
            ),
            self._fill(
                fill_uid="vertical-open-2",
                side="BUY_TO_OPEN",
                quantity="1",
                fill_price="3.00",
                source_order_id="ord-vert-open-2",
                asset_class="option",
                symbol="SPY 2026-07-17 520P",
                episode_group_id="SPY_PUT_VERTICAL_001",
                option_symbol="SPY 2026-07-17 520P",
                underlying_symbol="SPY",
                option_type="PUT",
                expiry=datetime(2026, 7, 17).date(),
                strike=Decimal("520"),
            ),
            self._fill(
                fill_uid="vertical-close-1",
                side="BUY_TO_CLOSE",
                quantity="1",
                fill_price="4.10",
                source_order_id="ord-vert-close-1",
                asset_class="option",
                symbol="SPY 2026-07-17 500P",
                episode_group_id="SPY_PUT_VERTICAL_001",
                option_symbol="SPY 2026-07-17 500P",
                underlying_symbol="SPY",
                option_type="PUT",
                expiry=datetime(2026, 7, 17).date(),
                strike=Decimal("500"),
            ),
            self._fill(
                fill_uid="vertical-close-2",
                side="SELL_TO_CLOSE",
                quantity="1",
                fill_price="3.10",
                source_order_id="ord-vert-close-2",
                asset_class="option",
                symbol="SPY 2026-07-17 520P",
                episode_group_id="SPY_PUT_VERTICAL_001",
                option_symbol="SPY 2026-07-17 520P",
                underlying_symbol="SPY",
                option_type="PUT",
                expiry=datetime(2026, 7, 17).date(),
                strike=Decimal("520"),
            ),
        ]
        previews = build_episode_previews_from_fills(fills)
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0].status, "closed")
        self.assertEqual(previews[0].fill_count, 4)
        self.assertEqual(previews[0].strategy_label, "Multi-Leg Option")

    def test_multi_leg_partial_close_keeps_strategy_open(self) -> None:
        fills = [
            self._fill(
                fill_uid="vertical-open-a",
                side="SELL_TO_OPEN",
                quantity="1",
                fill_price="5.00",
                source_order_id="ord-vert-a-open-1",
                asset_class="option",
                symbol="QQQ 2026-08-14 500C",
                episode_group_id="QQQ_CALL_VERTICAL_001",
                option_symbol="QQQ 2026-08-14 500C",
                underlying_symbol="QQQ",
                option_type="CALL",
                expiry=datetime(2026, 8, 14).date(),
                strike=Decimal("500"),
            ),
            self._fill(
                fill_uid="vertical-open-b",
                side="BUY_TO_OPEN",
                quantity="1",
                fill_price="4.00",
                source_order_id="ord-vert-a-open-2",
                asset_class="option",
                symbol="QQQ 2026-08-14 480C",
                episode_group_id="QQQ_CALL_VERTICAL_001",
                option_symbol="QQQ 2026-08-14 480C",
                underlying_symbol="QQQ",
                option_type="CALL",
                expiry=datetime(2026, 8, 14).date(),
                strike=Decimal("480"),
            ),
            self._fill(
                fill_uid="vertical-close-a",
                side="BUY_TO_CLOSE",
                quantity="1",
                fill_price="5.10",
                source_order_id="ord-vert-a-close-1",
                asset_class="option",
                symbol="QQQ 2026-08-14 500C",
                episode_group_id="QQQ_CALL_VERTICAL_001",
                option_symbol="QQQ 2026-08-14 500C",
                underlying_symbol="QQQ",
                option_type="CALL",
                expiry=datetime(2026, 8, 14).date(),
                strike=Decimal("500"),
            ),
        ]
        previews = build_episode_previews_from_fills(fills)
        self.assertEqual(len(previews), 1)
        self.assertEqual(previews[0].status, "open")
        self.assertEqual(previews[0].fill_count, 3)


if __name__ == "__main__":
    unittest.main()
