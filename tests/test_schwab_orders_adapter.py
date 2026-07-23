from __future__ import annotations

import unittest
from pathlib import Path

from onejournal.brokers.schwab.orders_json import (
    load_orders_json,
    normalized_rows_from_orders,
    validate_asof,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
ORDERS_FIXTURE = PROJECT_DIR / "docs/examples/schwab_orders_json/orders_sample.json"


class SchwabOrdersAdapterContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.orders = load_orders_json(ORDERS_FIXTURE)

    def test_reference_orders_flatten_to_deterministic_fill_rows(self) -> None:
        rows, stats = normalized_rows_from_orders(self.orders, asof="2025-07-18")

        self.assertEqual(stats.top_level_orders, 2)
        self.assertEqual(stats.flattened_orders, 2)
        self.assertEqual(stats.fill_activities, 2)
        self.assertEqual(stats.fill_rows, 2)
        self.assertEqual(stats.skipped_unmatched_legs, 0)
        self.assertEqual([row["symbol"] for row in rows], ["ACN", "IBKR"])
        self.assertEqual(rows[0]["source_fill_id"], "schwab_order:1003754934184:activity:99817027898:leg:1")
        self.assertEqual(rows[0]["option_type"], "PUT")
        self.assertEqual(rows[0]["strike"], "267.5")
        self.assertEqual(rows[0]["multiplier"], "100")
        self.assertEqual(rows[0]["open_close"], "open")
        self.assertEqual(rows[1]["source_order_id"], "201")
        self.assertEqual(rows[1]["open_close"], "close")

    def test_asof_filter_excludes_other_market_dates(self) -> None:
        rows, stats = normalized_rows_from_orders(self.orders, asof="2025-07-17")
        self.assertEqual(rows, [])
        self.assertEqual(stats.fill_rows, 0)
        self.assertEqual(stats.fill_activities, 2)

    def test_invalid_asof_fails_explicitly(self) -> None:
        with self.assertRaises(ValueError):
            validate_asof("2025/07/18")


if __name__ == "__main__":
    unittest.main()
