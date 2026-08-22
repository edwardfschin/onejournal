from __future__ import annotations

import unittest
from decimal import Decimal

from onejournal.brokers.schwab.transactions_json import (
    extract_lifecycle_event_legs_from_transactions,
    extract_lifecycle_events_from_transactions,
)


class TransactionsLifecycleEventTests(unittest.TestCase):
    def test_decimal_deliverable_evidence_serializes_without_precision_loss(self) -> None:
        legs = extract_lifecycle_event_legs_from_transactions(
            [
                {
                    "type": "RECEIVE_AND_DELIVER",
                    "status": "VALID",
                    "description": "Option expiration",
                    "activityId": "EVT-DECIMAL-DELIVERABLE",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "transferItems": [
                        {
                            "amount": Decimal("1.0"),
                            "cost": Decimal("0.0"),
                            "price": Decimal("0.0"),
                            "positionEffect": "CLOSING",
                            "instrument": {
                                "assetType": "OPTION",
                                "symbol": "AAPL  260717C00150000",
                                "optionPremiumMultiplier": Decimal("100.0"),
                                "optionDeliverables": [
                                    {
                                        "deliverableUnits": Decimal("100.0"),
                                        "strikePercent": Decimal("12.500000000000000001"),
                                    }
                                ],
                            },
                        }
                    ],
                }
            ]
        )

        self.assertIn('"deliverableUnits":100.0', legs[0]["deliverable_json"])
        self.assertIn(
            '"strikePercent":12.500000000000000001',
            legs[0]["deliverable_json"],
        )

    def test_extract_assignment_leg_evidence_without_financial_inference(self) -> None:
        legs = extract_lifecycle_event_legs_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "ASSIGNMENT",
                    "activityId": "EVT-LEGS-001",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "transferItems": [
                        {
                            "amount": -1,
                            "cost": 250,
                            "price": 2.5,
                            "positionEffect": "CLOSING",
                            "instrument": {
                                "assetType": "OPTION",
                                "symbol": "AAPL  260717C00150000",
                                "underlyingSymbol": "AAPL",
                                "putCall": "CALL",
                                "expirationDate": "2026-07-17T00:00:00",
                                "strikePrice": 150,
                                "optionPremiumMultiplier": 100,
                                "optionDeliverables": [
                                    {"deliverableUnits": 100, "symbol": "AAPL"}
                                ],
                            },
                        },
                        {
                            "amount": -0.65,
                            "cost": -0.65,
                            "feeType": "COMMISSION",
                            "instrument": {"assetType": "CURRENCY", "symbol": "USD"},
                        },
                    ],
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(legs), 2)
        option_leg, cash_leg = legs
        self.assertEqual(option_leg["event_leg_uid"], "schwab_txn:EVT-LEGS-001:event:TRADE:item:0")
        self.assertEqual(option_leg["signed_quantity"], "-1")
        self.assertEqual(option_leg["cash_amount"], "250")
        self.assertEqual(option_leg["multiplier"], "100")
        self.assertEqual(option_leg["evidence_status"], "observed")
        self.assertIn('"deliverableUnits":100', option_leg["deliverable_json"])
        self.assertEqual(cash_leg["leg_kind"], "cash")
        self.assertEqual(cash_leg["currency"], "USD")
        self.assertEqual(cash_leg["fee_type"], "COMMISSION")

    def test_option_lifecycle_leg_does_not_default_missing_multiplier(self) -> None:
        legs = extract_lifecycle_event_legs_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "EXPIRATION",
                    "activityId": "EVT-LEGS-002",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "transferItems": [
                        {
                            "amount": -1,
                            "positionEffect": "CLOSING",
                            "instrument": {
                                "assetType": "OPTION",
                                "symbol": "MSFT  260717P00100000",
                            },
                        }
                    ],
                }
            ]
        )

        self.assertEqual(legs[0]["multiplier"], "")
        self.assertEqual(legs[0]["evidence_status"], "review_required")
        self.assertIn("missing_option_multiplier", legs[0]["evidence_notes"])

    def test_empty_transfer_items_create_review_required_evidence_marker(self) -> None:
        legs = extract_lifecycle_event_legs_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "ASSIGNMENT",
                    "activityId": "EVT-LEGS-003",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "transferItems": [],
                }
            ]
        )

        self.assertEqual(len(legs), 1)
        self.assertEqual(legs[0]["leg_kind"], "unsupported")
        self.assertEqual(legs[0]["evidence_status"], "review_required")
        self.assertEqual(legs[0]["evidence_notes"], "transfer_items_empty")

    def test_description_only_assignment_is_unconfirmed_review_evidence(self) -> None:
        transaction = {
            "type": "TRADE",
            "status": "VALID",
            "description": "Option assignment generated equity activity",
            "activityId": "EVT-DESC-ASSIGNMENT",
            "tradeDate": "2026-07-01T12:00:00-05:00",
            "accountNumber": "ACCT-001",
            "positionId": "POS-001",
            "transferItems": [
                {
                    "amount": 100,
                    "cost": 15000,
                    "price": 150,
                    "positionEffect": "OPENING",
                    "instrument": {"assetType": "EQUITY", "symbol": "AAPL"},
                }
            ],
        }

        events = extract_lifecycle_events_from_transactions([transaction])
        legs = extract_lifecycle_event_legs_from_transactions([transaction])

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "description_hint:ASSIGNMENT")
        self.assertEqual(len(legs), 1)
        self.assertEqual(legs[0]["leg_kind"], "security")
        self.assertEqual(legs[0]["evidence_status"], "review_required")
        self.assertEqual(legs[0]["evidence_notes"], "unconfirmed_description_hint")

    def test_receive_and_deliver_expiration_is_unconfirmed_review_evidence(self) -> None:
        transaction = {
            "type": "RECEIVE_AND_DELIVER",
            "status": "VALID",
            "description": "Option expiration",
            "activityId": "EVT-DESC-EXPIRATION",
            "tradeDate": "2026-07-01T12:00:00-05:00",
            "accountNumber": "ACCT-001",
            "positionId": "POS-001",
            "transferItems": [
                {
                    "amount": -1,
                    "cost": 0,
                    "price": 0,
                    "positionEffect": "CLOSING",
                    "instrument": {
                        "assetType": "OPTION",
                        "symbol": "AAPL  260717C00150000",
                        "optionPremiumMultiplier": 100,
                    },
                }
            ],
        }

        events = extract_lifecycle_events_from_transactions([transaction])
        legs = extract_lifecycle_event_legs_from_transactions([transaction])

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "description_hint:EXPIRATION")
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-DESC-EXPIRATION:event:RECEIVE_AND_DELIVER")
        self.assertEqual(len(legs), 1)
        self.assertEqual(legs[0]["multiplier"], "100")
        self.assertEqual(legs[0]["evidence_status"], "review_required")
        self.assertEqual(legs[0]["evidence_notes"], "unconfirmed_description_hint")

    def test_unrelated_description_is_not_promoted_to_lifecycle_event(self) -> None:
        transaction = {
            "type": "TRADE",
            "status": "VALID",
            "description": "Ordinary equity trade",
            "activityId": "EVT-NOT-LIFECYCLE",
            "tradeDate": "2026-07-01T12:00:00-05:00",
            "transferItems": [],
        }

        self.assertEqual(extract_lifecycle_events_from_transactions([transaction]), [])
        self.assertEqual(
            extract_lifecycle_event_legs_from_transactions([transaction]), []
        )

    def test_extract_assignment_activity_event(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "ASSIGNMENT",
                    "activityId": "EVT-001",
                    "tradeDate": "2026-07-01T12:00:00-05:00",
                    "accountNumber": "ACCT-001",
                    "orderId": "ORD-001",
                    "positionId": "POS-001",
                    "transferItems": [
                        {
                            "amount": 10,
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "AAPL",
                            },
                            "positionEffect": "OPENING",
                        }
                    ],
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-001:event:TRADE")
        self.assertEqual(events[0]["event_class"], "TRANSACTION_LIFECYCLE")
        self.assertEqual(events[0]["event_type"], "activityType:ASSIGNMENT")
        self.assertEqual(events[0]["asof"], "2026-07-01")

    def test_extract_subtype_event_after_asof_filter(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "subType": "DIVIDEND",
                    "activityId": "EVT-002",
                    "tradeDate": "2026-07-01T09:30:00-05:00",
                },
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "subType": "DIVIDEND",
                    "activityId": "EVT-003",
                    "tradeDate": "2026-07-02T09:30:00-05:00",
                },
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["source_activity_id"], "EVT-002")
        self.assertEqual(events[0]["event_name"], "subType:DIVIDEND")

    def test_ignore_non_transaction_or_invalid_status_for_events(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRANSFER",
                    "status": "VALID",
                    "activityType": "ASSIGNMENT",
                    "activityId": "EVT-004",
                    "tradeDate": "2026-07-01T09:30:00-05:00",
                },
                {
                    "type": "TRADE",
                    "status": "PENDING",
                    "activityType": "EXERCISE",
                    "activityId": "EVT-005",
                    "tradeDate": "2026-07-01T09:30:00-05:00",
                },
            ],
            asof="2026-07-01",
        )

        self.assertEqual(events, [])

    def test_activity_type_takes_precedence_over_sub_type(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "ASSIGNMENT",
                    "subType": "DIVIDEND",
                    "activityId": "EVT-006",
                    "tradeDate": "2026-07-01T11:00:00-05:00",
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "activityType:ASSIGNMENT")

    def test_option_exercise_sub_type_is_normalized(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "subType": "OPTION_EXERCISE",
                    "activityId": "EVT-EX-002",
                    "tradeDate": "2026-07-01T11:45:00-05:00",
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "subType:EXERCISE")
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-EX-002:event:TRADE")

    def test_option_exercise_activity_type_is_normalized(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "OPTION_EXERCISE",
                    "activityId": "EVT-EX-001",
                    "tradeDate": "2026-07-01T11:30:00-05:00",
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "activityType:EXERCISE")
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-EX-001:event:TRADE")

    def test_extract_rollover_activity_event(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "ROLLOVER",
                    "activityId": "EVT-007",
                    "tradeDate": "2026-07-01T10:00:00-05:00",
                    "accountNumber": "ACCT-007",
                    "orderId": "ORD-007",
                    "positionId": "POS-007",
                    "transferItems": [
                        {
                            "amount": 1,
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "TSLA",
                            },
                            "positionEffect": "OPENING",
                        }
                    ],
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "activityType:ROLLOVER")
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-007:event:TRADE")

    def test_extract_roll_activity_event(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "ROLL",
                    "activityId": "EVT-008",
                    "tradeDate": "2026-07-01T10:30:00-05:00",
                    "accountNumber": "ACCT-008",
                    "orderId": "ORD-008",
                    "positionId": "POS-008",
                    "transferItems": [
                        {
                            "amount": 1,
                            "instrument": {
                                "assetType": "OPTION",
                                "symbol": "AAPL  250815P00150000",
                            },
                            "positionEffect": "OPENING",
                        }
                    ],
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "activityType:ROLL")
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-008:event:TRADE")

    def test_extract_expiration_activity_event(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "EXPIRATION",
                    "activityId": "EVT-009",
                    "tradeDate": "2026-07-01T13:00:00-05:00",
                    "accountNumber": "ACCT-009",
                    "orderId": "ORD-009",
                    "positionId": "POS-009",
                    "transferItems": [
                        {
                            "amount": -1,
                            "instrument": {
                                "assetType": "OPTION",
                                "symbol": "MSFT  250815C00100000",
                            },
                            "positionEffect": "CLOSING",
                        }
                    ],
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "activityType:EXPIRATION")
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-009:event:TRADE")

    def test_extract_transfer_subtype_event(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "subType": "TRANSFER",
                    "activityId": "EVT-010",
                    "tradeDate": "2026-07-01T15:00:00-05:00",
                    "accountNumber": "ACCT-010",
                    "orderId": "ORD-010",
                    "positionId": "POS-010",
                    "transferItems": [
                        {
                            "amount": 1,
                            "instrument": {
                                "assetType": "OPTION",
                                "symbol": "TSLA  250815C00600000",
                            },
                            "positionEffect": "OPENING",
                        }
                    ],
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "subType:TRANSFER")
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-010:event:TRADE")

    def test_extract_corporate_action_activity_event(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "activityType": "CORPORATE_ACTION",
                    "activityId": "EVT-011",
                    "tradeDate": "2026-07-01T09:15:00-05:00",
                    "accountNumber": "ACCT-011",
                    "orderId": "ORD-011",
                    "positionId": "POS-011",
                    "transferItems": [
                        {
                            "amount": 1,
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "NVDA",
                            },
                            "positionEffect": "OPENING",
                        }
                    ],
                }
            ],
            asof="2026-07-01",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "activityType:CORPORATE_ACTION")
        self.assertEqual(events[0]["event_uid"], "schwab_txn:EVT-011:event:TRADE")

    def test_fallback_uid_when_activity_id_missing(self) -> None:
        events = extract_lifecycle_events_from_transactions(
            [
                {
                    "type": "TRADE",
                    "status": "VALID",
                    "subType": "DIVIDEND",
                    "tradeDate": "2026-07-03T10:00:00-05:00",
                    "accountNumber": "ACCT-008",
                    "orderId": "ORD-008",
                    "positionId": "POS-008",
                    "transferItems": [
                        {
                            "amount": 1,
                            "instrument": {
                                "assetType": "EQUITY",
                                "symbol": "MSFT",
                            },
                            "positionEffect": "OPENING",
                        }
                    ],
                }
            ],
            asof="2026-07-03",
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_uid"], "schwab_txn:2026-07-03:event:TRADE:row:0")
        self.assertEqual(events[0]["source_activity_id"], "")


if __name__ == "__main__":
    unittest.main()
