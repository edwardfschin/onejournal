from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from onejournal.brokers.schwab.orders_json import (
    load_orders_json,
    normalized_rows_from_orders,
)
from onejournal.brokers.schwab.transactions_json import (
    load_transactions_json,
    normalized_rows_from_transactions,
)


class SchwabDecimalBoundaryTests(unittest.TestCase):
    def test_json_loaders_preserve_decimal_tokens_exactly(self) -> None:
        with TemporaryDirectory() as root:
            transactions_path = Path(root) / "transactions.json"
            orders_path = Path(root) / "orders.json"
            payload = '[{"amount":0.1,"price":0.1234567890123456789}]'
            transactions_path.write_text(payload, encoding="utf-8")
            orders_path.write_text(payload, encoding="utf-8")

            transactions = load_transactions_json(transactions_path)
            orders = load_orders_json(orders_path)

        for parsed in (transactions, orders):
            self.assertEqual(parsed[0]["amount"], Decimal("0.1"))
            self.assertEqual(parsed[0]["price"], Decimal("0.1234567890123456789"))

    def test_high_precision_derived_price_remains_decimal_exact(self) -> None:
        rows, _ = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "DECIMAL-1",
                    "tradeDate": "2026-07-01T12:00:00-04:00",
                    "transferItems": [
                        {
                            "amount": Decimal("3"),
                            "cost": Decimal("30.0000000000000003"),
                            "instrument": {
                                "assetType": "OPTION",
                                "symbol": "AAPL  260717C00150000",
                                "underlyingSymbol": "AAPL",
                                "optionPremiumMultiplier": Decimal("100"),
                            },
                        },
                        self._currency_item("CURRENCY_USD"),
                    ],
                }
            ]
        )

        self.assertEqual(rows[0]["quantity"], "3")
        self.assertEqual(rows[0]["fill_price"], "0.100000000000000001")
        self.assertEqual(rows[0]["multiplier"], "100")
        self.assertEqual(rows[0]["strike"], "150")

    def test_fee_residual_is_deterministic_and_reconciles(self) -> None:
        security_items = [
            {
                "amount": Decimal("1"),
                "cost": Decimal("10"),
                "price": Decimal("10"),
                "instrument": {"assetType": "EQUITY", "symbol": symbol},
            }
            for symbol in ("AAA", "BBB", "CCC")
        ]
        commission = self._currency_item("CURRENCY_USD")
        commission.update(
            {
                "amount": Decimal("1.00"),
                "cost": Decimal("-1.00"),
                "feeType": "COMMISSION",
            }
        )
        rows, _ = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "FEES-1",
                    "tradeDate": "2026-07-01T12:00:00-04:00",
                    "transferItems": security_items + [commission],
                }
            ]
        )

        self.assertEqual([row["commission"] for row in rows], ["0.34", "0.33", "0.33"])
        self.assertEqual(
            sum((Decimal(row["commission"]) for row in rows), Decimal("0")),
            Decimal("1.00"),
        )

    def test_missing_or_mixed_currency_evidence_fails_closed(self) -> None:
        security = {
            "amount": Decimal("1"),
            "cost": Decimal("10"),
            "price": Decimal("10"),
            "instrument": {"assetType": "EQUITY", "symbol": "AAPL"},
        }
        base = self._transaction([security])
        with self.assertRaisesRegex(ValueError, "Missing Schwab transaction currency"):
            normalized_rows_from_transactions([base])

        mixed = self._transaction(
            [security, self._currency_item("CURRENCY_USD"), self._currency_item("CURRENCY_EUR")]
        )
        with self.assertRaisesRegex(ValueError, "Mixed Schwab transaction currencies"):
            normalized_rows_from_transactions([mixed])

    def test_float_non_finite_and_missing_multiplier_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact decimal value"):
            normalized_rows_from_transactions(
                [
                    self._transaction(
                        [
                            {
                                "amount": 0.1,
                                "price": Decimal("1"),
                                "instrument": {"assetType": "EQUITY", "symbol": "AAPL"},
                            },
                            self._currency_item("CURRENCY_USD"),
                        ]
                    )
                ]
            )
        with self.assertRaisesRegex(ValueError, "non-finite"):
            normalized_rows_from_transactions(
                [
                    self._transaction(
                        [
                            {
                                "amount": Decimal("1"),
                                "price": Decimal("NaN"),
                                "instrument": {"assetType": "EQUITY", "symbol": "AAPL"},
                            },
                            self._currency_item("CURRENCY_USD"),
                        ]
                    )
                ]
            )
        with self.assertRaisesRegex(ValueError, "option multiplier"):
            normalized_rows_from_transactions(
                [
                    self._transaction(
                        [
                            {
                                "amount": Decimal("1"),
                                "price": Decimal("1"),
                                "instrument": {
                                    "assetType": "OPTION",
                                    "symbol": "AAPL  260717C00150000",
                                },
                            },
                            self._currency_item("CURRENCY_USD"),
                        ]
                    )
                ]
            )

    def test_orders_float_and_missing_multiplier_fail_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "exact decimal value"):
            normalized_rows_from_orders(
                [self._order({"assetType": "EQUITY", "symbol": "AAPL"}, price=0.1)]
            )
        with self.assertRaisesRegex(ValueError, "option multiplier"):
            normalized_rows_from_orders(
                [
                    self._order(
                        {
                            "assetType": "OPTION",
                            "symbol": "AAPL  260717C00150000",
                            "underlyingSymbol": "AAPL",
                        }
                    )
                ]
            )

    @staticmethod
    def _currency_item(symbol: str) -> dict:
        return {
            "amount": Decimal("0"),
            "cost": Decimal("0"),
            "instrument": {"assetType": "CURRENCY", "symbol": symbol},
        }

    @staticmethod
    def _transaction(items: list[dict]) -> dict:
        return {
            "type": "TRADE",
            "status": "VALID",
            "activityId": "BOUNDARY-1",
            "tradeDate": "2026-07-01T12:00:00-04:00",
            "transferItems": items,
        }

    @staticmethod
    def _order(instrument: dict, *, price: object = Decimal("1")) -> dict:
        return {
            "orderId": "ORDER-1",
            "accountNumber": "ACCOUNT-1",
            "orderLegCollection": [
                {
                    "legId": 1,
                    "instruction": "BUY_TO_OPEN",
                    "positionEffect": "OPENING",
                    "instrument": instrument,
                }
            ],
            "orderActivityCollection": [
                {
                    "activityId": "ACTIVITY-1",
                    "executionType": "FILL",
                    "executionLegs": [
                        {
                            "legId": 1,
                            "quantity": Decimal("1"),
                            "price": price,
                            "time": "2026-07-01T12:00:00-04:00",
                        }
                    ],
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
