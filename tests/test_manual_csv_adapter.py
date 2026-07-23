from __future__ import annotations

import tempfile
import unittest
from datetime import date
from decimal import Decimal
from pathlib import Path

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv


PROJECT_DIR = Path(__file__).resolve().parents[1]
FILLS_FIXTURE = PROJECT_DIR / "docs/examples/manual_csv/fills_template.csv"


class ManualCsvAdapterTests(unittest.TestCase):
    def test_reference_fixture_normalizes_expected_fill_contract(self) -> None:
        fills = parse_manual_fills_csv(FILLS_FIXTURE)

        self.assertEqual(len(fills), 12)
        first = fills[0]
        self.assertEqual(first.fill_uid, "manual_csv:DEMO_ACCOUNT:FILL-001")
        self.assertEqual(first.asof, date(2026, 6, 2))
        self.assertEqual(first.side, "SELL")
        self.assertEqual(first.quantity, Decimal("1"))
        self.assertEqual(first.fill_price, Decimal("2.35"))
        self.assertEqual(first.multiplier, Decimal("100"))
        self.assertEqual(first.underlying_symbol, "AAPL")
        self.assertEqual(first.episode_group_id, "AAPL_SELL_PUT_001")
        self.assertEqual(first.raw_path, str(FILLS_FIXTURE))

    def test_missing_required_columns_fail_with_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad_csv = Path(tmp) / "missing_columns.csv"
            bad_csv.write_text("asof,source_broker\n2026-06-02,manual_csv\n", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "missing required column"):
                parse_manual_fills_csv(bad_csv)


if __name__ == "__main__":
    unittest.main()
