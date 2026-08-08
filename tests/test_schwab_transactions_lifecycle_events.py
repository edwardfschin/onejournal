from __future__ import annotations

import unittest

from onejournal.brokers.schwab.transactions_json import extract_lifecycle_events_from_transactions


class TransactionsLifecycleEventTests(unittest.TestCase):
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
