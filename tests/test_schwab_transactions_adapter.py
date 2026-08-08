from __future__ import annotations

import unittest

from onejournal.brokers.schwab.transactions_json import normalized_rows_from_transactions


class TransactionsJsonAdapterTests(unittest.TestCase):
    def test_non_trade_transactions_are_ignored(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRANSFER",
                    "status": "VALID",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "transferItems": [
                        {
                            "amount": 1,
                            "instrument": {"assetType": "EQUITY", "symbol": "AAPL"},
                        }
                    ],
                }
            ]
        )

        self.assertEqual(len(rows), 0)
        self.assertEqual(stats.transactions, 1)
        self.assertEqual(stats.trade_valid, 0)
        self.assertEqual(stats.fill_rows, 0)

    def test_activity_type_that_requires_non_fill_support_is_skipped_as_unsupported(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "ASSIGNMENT",
                    "activityId": "A1",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-001",
                    "positionId": "POS-001",
                    "transferItems": [
                        {
                            "amount": 5,
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "AAPL",
                            },
                            "positionEffect": "OPENING",
                            "price": 10,
                            "cost": 50,
                        }
                    ],
                }
            ]
        )

        self.assertEqual(rows, [])
        self.assertEqual(stats.transactions, 1)
        self.assertEqual(stats.trade_valid, 0)
        self.assertEqual(stats.unsupported_items, 1)

    def test_sub_type_marked_as_lifecycle_activity_is_skipped_as_unsupported(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "subType": "EXERCISE",
                    "activityId": "A2",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-002",
                    "positionId": "POS-002",
                    "transferItems": [
                        {
                            "amount": -2,
                            "instrument": {
                                "assetType": "OPTION",
                                "symbol": "AAPL  250815C00150000",
                                "expirationDate": "2025-08-22",
                                "strikePrice": 150,
                                "putCall": "CALL",
                            },
                            "positionEffect": "CLOSING",
                            "price": 4,
                            "cost": -8,
                        }
                    ],
                }
            ]
        )

        self.assertEqual(rows, [])
        self.assertEqual(stats.trade_valid, 0)
        self.assertEqual(stats.unsupported_items, 1)

    def test_assignments_asof_filter_still_applies(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "ASSIGNMENT",
                    "activityId": "A3",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-003",
                    "positionId": "POS-003",
                    "transferItems": [
                        {
                            "amount": 5,
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "AAPL",
                            },
                            "positionEffect": "OPENING",
                            "price": 10,
                            "cost": 50,
                        }
                    ],
                }
            ],
            asof="2026-07-02",
        )

        self.assertEqual(rows, [])
        self.assertEqual(stats.transactions, 1)
        self.assertEqual(stats.trade_valid, 0)
        self.assertEqual(stats.unsupported_items, 1)

    def test_supported_activity_with_multiple_transfer_items_still_flattens_only_security_legs(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "A4",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-004",
                    "positionId": "POS-004",
                    "transferItems": [
                        {
                            "amount": 2,
                            "cost": 300,
                            "price": 150,
                            "feeType": "COMMISSION",
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "AAPL",
                            },
                            "positionEffect": "OPENING",
                        },
                        {
                            "amount": -2,
                            "cost": -100,
                            "price": 0,
                            "instrument": {
                                "assetType": "CURRENCY",
                                "symbol": "USD",
                            },
                            "positionEffect": "OPENING",
                        },
                    ],
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertTrue(
            rows[0]["source_fill_id"].startswith("schwab_txn:A4:order:ORD-004:position:POS-004:item:0")
        )
        self.assertEqual(rows[0]["symbol"], "AAPL")
        self.assertEqual(rows[0]["side"], "buy")
        self.assertEqual(rows[0]["quantity"], "2.0")
        self.assertEqual(rows[0]["fill_price"], "150")
        self.assertEqual(rows[0]["open_close"], "open")
        self.assertEqual(stats.security_items, 1)
        self.assertEqual(stats.currency_items, 1)
        self.assertEqual(stats.fill_rows, 1)

    def test_unsupported_security_asset_is_skipped_and_does_not_block_supported_legs(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "A5",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-005",
                    "positionId": "POS-005",
                    "transferItems": [
                        {
                            "amount": 1,
                            "cost": 50,
                            "price": 50,
                            "instrument": {
                                "assetType": "FUTURES",
                                "symbol": "ESZ6",
                            },
                            "positionEffect": "OPENING",
                        },
                        {
                            "amount": 2,
                            "cost": 300,
                            "price": 150,
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "AAPL",
                            },
                            "positionEffect": "OPENING",
                        },
                    ],
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "AAPL")
        self.assertEqual(rows[0]["source_fill_id"].startswith("schwab_txn:A5:order:ORD-005:position:POS-005:item:1"), True)
        self.assertEqual(stats.security_items, 1)
        self.assertEqual(stats.unsupported_items, 1)
