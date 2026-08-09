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
        self.assertEqual(stats.unsupported_record_counts, {"record_type:TRANSFER": 1})
        self.assertEqual(stats.unsupported_items, 1)

    def test_invalid_status_transaction_is_counted_as_unsupported_record(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "INVALID",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "transferItems": [],
                    "activityType": "OPTION_EXERCISE",
                }
            ]
        )

        self.assertEqual(len(rows), 0)
        self.assertEqual(stats.trade_valid, 0)
        self.assertEqual(stats.unsupported_items, 1)
        self.assertEqual(stats.unsupported_record_counts, {"record_status:INVALID": 1})

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
        self.assertEqual(stats.unsupported_activity_counts, {"activityType:ASSIGNMENT": 1})

    def test_option_exercise_activity_type_is_normalized_as_exercise_for_lifecycle(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "OPTION_EXERCISE",
                    "activityId": "A1B",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-EX",
                    "positionId": "POS-EX",
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
        self.assertEqual(stats.unsupported_activity_counts, {"activityType:EXERCISE": 1})

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
        self.assertEqual(stats.unsupported_activity_counts, {"subType:EXERCISE": 1})

    def test_other_unsupported_activity_markers_are_skipped_as_unsupported(self) -> None:
        unsupported_markers = [
            ({"activityType": "EXERCISE"}, "activityType:EXERCISE"),
            ({"activityType": "CORPORATE_ACTION"}, "activityType:CORPORATE_ACTION"),
            ({"activityType": "DIVIDEND"}, "activityType:DIVIDEND"),
            ({"activityType": "EXPIRATION"}, "activityType:EXPIRATION"),
            ({"activityType": "ASSIGNMENT"}, "activityType:ASSIGNMENT"),
            ({"activityType": "INTEREST"}, "activityType:INTEREST"),
            ({"subType": "TRANSFER"}, "subType:TRANSFER"),
            ({"subType": "DIVIDEND"}, "subType:DIVIDEND"),
        ]
        for marker_payload, expected_key in unsupported_markers:
            with self.subTest(marker=expected_key):
                fields = {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "A6",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-006",
                    "positionId": "POS-006",
                    "transferItems": [
                        {
                            "amount": -1,
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
                fields.update(marker_payload)
                rows, stats = normalized_rows_from_transactions(
                    [fields],
                    asof="2026-07-01",
                )

                self.assertEqual(rows, [])
                self.assertEqual(stats.transactions, 1)
                self.assertEqual(stats.trade_valid, 0)
                self.assertEqual(stats.unsupported_items, 1)
                self.assertEqual(stats.unsupported_activity_counts, {expected_key: 1})

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
        self.assertEqual(stats.unsupported_activity_counts, {"activityType:ASSIGNMENT": 1})

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
        self.assertEqual(stats.unsupported_asset_counts, {"FUTURES": 1})

    def test_empty_transfer_items_is_unsupported_record(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "A6",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-006",
                    "positionId": "POS-006",
                    "transferItems": [],
                }
            ]
        )

        self.assertEqual(len(rows), 0)
        self.assertEqual(stats.unsupported_items, 1)
        self.assertEqual(stats.unsupported_record_counts, {"record_items:empty": 1})

    def test_non_list_transfer_items_is_unsupported_record(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "A7",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-007",
                    "positionId": "POS-007",
                    "transferItems": "not-a-list",
                }
            ]
        )

        self.assertEqual(len(rows), 0)
        self.assertEqual(stats.unsupported_items, 1)
        self.assertEqual(stats.unsupported_record_counts, {"record_items:non_list": 1})

    def test_transfer_item_without_instrument_is_unsupported_record(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "A8",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-008",
                    "positionId": "POS-008",
                    "transferItems": [
                        {
                            "amount": 1,
                            "cost": 50,
                        }
                    ],
                }
            ]
        )

        self.assertEqual(len(rows), 0)
        self.assertEqual(stats.unsupported_items, 2)
        self.assertEqual(stats.unsupported_record_counts, {"record_items:missing_instrument": 1, "record_security:unsupported_or_missing": 1})

    def test_non_dict_transfer_item_does_not_block_supported_leg(self) -> None:
        rows, stats = normalized_rows_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityId": "A9",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT1",
                    "orderId": "ORD-009",
                    "positionId": "POS-009",
                    "transferItems": [
                        "BAD_ITEM",
                        {
                            "amount": 1,
                            "cost": 100,
                            "price": 100,
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "MSFT",
                            },
                            "positionEffect": "OPENING",
                        },
                    ],
                }
            ]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["symbol"], "MSFT")
        self.assertEqual(stats.security_items, 1)
        self.assertEqual(stats.unsupported_items, 1)
        self.assertEqual(stats.unsupported_record_counts, {"record_items:non_object": 1})
