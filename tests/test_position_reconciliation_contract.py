from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import unittest

from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord, BrokerPositionSnapshot, CanonicalPositionQuantity,
    reconcile_account_positions,
)


class PositionReconciliationContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = InstrumentIdentity(asset_class="equity", market_scope="US", currency="USD", symbol="AAPL")
        self.when = datetime(2026, 8, 31, 12, tzinfo=timezone.utc)

    def canonical(self, quantity="10"):
        return CanonicalPositionQuantity("schwab", "conn", "acct", self.identity, Decimal(quantity), date(2026, 8, 31), self.when, "fifo.v1")

    def broker(self, quantity="10", complete=True):
        return BrokerPositionSnapshot(
            "snapshot-1", "schwab", "conn", "acct", date(2026, 8, 31),
            self.when, "private/snapshot.json", "a" * 64, complete,
            "synthetic-v1", (BrokerPositionRecord(self.identity, Decimal(quantity)),),
        )

    def test_equal_quantity_is_valid(self) -> None:
        (result,) = reconcile_account_positions((self.canonical(),), self.broker(), evaluated_at=self.when, max_snapshot_age_seconds=60)
        self.assertEqual(result.status, "valid")

    def test_mismatch_fails_closed(self) -> None:
        (result,) = reconcile_account_positions((self.canonical(),), self.broker("9"), evaluated_at=self.when, max_snapshot_age_seconds=60)
        self.assertEqual(result.status, "reconciliation_pending")
        self.assertIn("differ", result.reason)

    def test_incomplete_broker_snapshot_blocks_all_positions(self) -> None:
        (result,) = reconcile_account_positions((self.canonical(),), self.broker(complete=False), evaluated_at=self.when, max_snapshot_age_seconds=60)
        self.assertEqual(result.status, "reconciliation_pending")
        self.assertIn("complete", result.reason)

    def test_extra_broker_position_is_visible_not_dropped(self) -> None:
        extra = InstrumentIdentity(asset_class="equity", market_scope="US", currency="USD", symbol="MSFT")
        broker = BrokerPositionSnapshot(
            "snapshot-1", "schwab", "conn", "acct", date(2026, 8, 31),
            self.when, "private/snapshot.json", "a" * 64, True,
            "synthetic-v1", (
                BrokerPositionRecord(self.identity, Decimal("10")),
                BrokerPositionRecord(extra, Decimal("3"), provider_position_id="msft"),
            ),
        )
        results = reconcile_account_positions((self.canonical(),), broker, evaluated_at=self.when, max_snapshot_age_seconds=60)
        self.assertEqual([item.status for item in results], ["valid", "reconciliation_pending"])

    def test_stale_snapshot_fails_closed_under_explicit_age_policy(self) -> None:
        stale = BrokerPositionSnapshot(
            "snapshot-1", "schwab", "conn", "acct", date(2026, 8, 31),
            self.when - timedelta(seconds=120), "private/snapshot.json",
            "a" * 64, True, "synthetic-v1",
            (BrokerPositionRecord(self.identity, Decimal("10")),),
        )
        (result,) = reconcile_account_positions(
            (self.canonical(),), stale, evaluated_at=self.when,
            max_snapshot_age_seconds=60,
        )
        self.assertEqual(result.status, "reconciliation_pending")
        self.assertIn("age limit", result.reason)

    def test_complete_empty_account_is_representable(self) -> None:
        empty = BrokerPositionSnapshot(
            "snapshot-empty", "schwab", "conn", "acct", date(2026, 8, 31),
            self.when, "private/empty.json", "c" * 64, True,
            "synthetic-v1", (),
        )
        self.assertEqual(
            reconcile_account_positions((), empty, evaluated_at=self.when, max_snapshot_age_seconds=60),
            (),
        )
