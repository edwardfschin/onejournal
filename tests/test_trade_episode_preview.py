from __future__ import annotations

import unittest
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
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


if __name__ == "__main__":
    unittest.main()
