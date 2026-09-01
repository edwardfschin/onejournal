from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
import json
import unittest

from onejournal.brokers.schwab.orders_json import SchwabOrdersJsonStats
from onejournal.brokers.schwab.transactions_json import SchwabTransactionsJsonStats
from onejournal.provider_connectors import (
    ConvertedExternalLifecycleEvidence,
    CurrentPositionCoverageTarget,
    ExternalLifecycleReconciliation,
    LifecycleCoverageError,
    assemble_current_position_lifecycle_coverage,
)


def fill_row(
    *,
    fill_id: str,
    order_id: str,
    filled_at: str,
    symbol: str = "AAPL",
    side: str = "buy",
    quantity: str = "1",
    price: str = "100",
    asset_class: str = "stock",
    currency: str = "USD",
    multiplier: str = "",
) -> dict[str, str]:
    option = asset_class == "option"
    return {
        "asof": filled_at[:10],
        "source_broker": "schwab",
        "source_account_id": "account-private-0001",
        "source_fill_id": fill_id,
        "source_order_id": order_id,
        "filled_at": filled_at,
        "asset_class": asset_class,
        "symbol": "AAPL" if option else symbol,
        "side": side,
        "quantity": quantity,
        "fill_price": price,
        "commission": "0",
        "fees": "0",
        "currency": currency,
        "option_symbol": symbol if option else "",
        "underlying_symbol": "AAPL" if option else "",
        "option_type": "CALL" if option else "",
        "expiry": "2026-03-20" if option else "",
        "strike": "200" if option else "",
        "multiplier": multiplier if option else "",
        "open_close": "open",
        "execution_venue": "",
        "liquidity_flag": "",
        "episode_group_id": "",
    }


def lifecycle_event(*, event_uid: str, event_at: str) -> dict[str, str]:
    return {
        "event_uid": event_uid,
        "source_broker": "schwab",
        "source_account_id": "account-private-0001",
        "source_activity_id": "activity-private",
        "source_order_id": "",
        "source_position_id": "",
        "event_class": "option_lifecycle",
        "event_type": "EXPIRATION",
        "asof": event_at[:10],
        "event_at": event_at,
        "event_name": "EXPIRATION",
    }


def lifecycle_leg(
    *,
    event_uid: str,
    event_leg_uid: str,
    symbol: str,
    evidence_status: str = "observed",
) -> dict[str, str]:
    return {
        "event_leg_uid": event_leg_uid,
        "event_uid": event_uid,
        "leg_index": "0",
        "leg_kind": "security",
        "asset_class": "stock",
        "symbol": symbol,
        "option_symbol": "",
        "underlying_symbol": "",
        "option_type": "",
        "expiry": "",
        "strike": "",
        "multiplier": "",
        "signed_quantity": "1",
        "price": "",
        "cash_amount": "",
        "position_effect": "",
        "fee_type": "",
        "currency": "USD",
        "deliverable_json": "",
        "evidence_status": evidence_status,
        "evidence_notes": "",
    }


def window(
    *,
    digest_char: str,
    start: date,
    end: date,
    orders: tuple[dict[str, str], ...] = (),
    transactions: tuple[dict[str, str], ...] = (),
    events: tuple[dict[str, str], ...] = (),
    legs: tuple[dict[str, str], ...] = (),
    connection_uid: str = "connection:schwab:test-0001",
    excluded_order_rows: int = 0,
    excluded_transaction_rows: int = 0,
    excluded_events: int = 0,
    excluded_legs: int = 0,
) -> ConvertedExternalLifecycleEvidence:
    return ConvertedExternalLifecycleEvidence(
        external_manifest_sha256=digest_char * 64,
        source_broker="schwab",
        connection_uid=connection_uid,
        source_account_id="account-private-0001",
        window_start_date=start,
        window_end_date=end,
        raw_response_bytes={},
        order_rows=orders,
        transaction_rows=transactions,
        lifecycle_events=events,
        lifecycle_event_legs=legs,
        order_stats=SchwabOrdersJsonStats(fill_rows=len(orders)),
        transaction_stats=SchwabTransactionsJsonStats(fill_rows=len(transactions)),
        reconciliation=ExternalLifecycleReconciliation(0, len(orders), len(transactions)),
        excluded_out_of_window_order_fill_rows=excluded_order_rows,
        excluded_out_of_window_transaction_fill_rows=excluded_transaction_rows,
        excluded_out_of_window_lifecycle_events=excluded_events,
        excluded_out_of_window_lifecycle_event_legs=excluded_legs,
    )


class CurrentPositionLifecycleCoverageTests(unittest.TestCase):
    evaluated_at = datetime(2026, 2, 1, 20, tzinfo=UTC)

    def target(
        self,
        symbol: str = "AAPL",
        quantity: str = "1",
        asset_class: str = "equity",
    ) -> CurrentPositionCoverageTarget:
        return CurrentPositionCoverageTarget(
            source_instrument_id=symbol,
            asset_class=asset_class,
            broker_quantity=Decimal(quantity),
        )

    def test_cross_window_match_proves_fill_flat_start(self) -> None:
        order = fill_row(
            fill_id="order-fill-1",
            order_id="order-1",
            filled_at="2026-01-31T15:00:00Z",
        )
        transaction = fill_row(
            fill_id="transaction-fill-1",
            order_id="order-1",
            filled_at="2026-01-31T15:00:00Z",
        )
        result = assemble_current_position_lifecycle_coverage(
            (
                window(
                    digest_char="a",
                    start=date(2026, 1, 1),
                    end=date(2026, 1, 30),
                    orders=(order,),
                ),
                window(
                    digest_char="b",
                    start=date(2026, 1, 31),
                    end=date(2026, 2, 1),
                    transactions=(transaction, transaction),
                ),
            ),
            (self.target(),),
            evaluated_at=self.evaluated_at,
        )

        self.assertTrue(result.reconciliation.exact)
        self.assertEqual(result.reconciliation.matched_rows, 1)
        self.assertEqual(result.deduplicated_transaction_rows, 1)
        self.assertEqual(result.positions[0].status, "fill_flat_start_proven")
        self.assertEqual(result.positions[0].identity.currency, "USD")
        audit = result.privacy_safe_audit()
        self.assertEqual(
            audit["position_status_counts"], {"fill_flat_start_proven": 1}
        )
        self.assertNotIn("AAPL", json.dumps(audit))

    def test_missing_order_id_remains_review_required(self) -> None:
        transaction = fill_row(
            fill_id="transaction-fill-1",
            order_id="",
            filled_at="2026-01-31T15:00:00Z",
        )
        result = assemble_current_position_lifecycle_coverage(
            (
                window(
                    digest_char="a",
                    start=date(2026, 1, 1),
                    end=date(2026, 2, 1),
                    transactions=(transaction,),
                ),
            ),
            (self.target(),),
            evaluated_at=self.evaluated_at,
        )

        coverage = result.positions[0]
        self.assertEqual(coverage.status, "review_required")
        self.assertEqual(
            coverage.reason_codes, ("transaction_order_id_missing",)
        )
        self.assertEqual(result.reconciliation.only_transaction_rows, 1)

        mismatched = assemble_current_position_lifecycle_coverage(
            (
                window(
                    digest_char="a",
                    start=date(2026, 1, 1),
                    end=date(2026, 2, 1),
                    transactions=(transaction,),
                ),
            ),
            (self.target(quantity="2"),),
            evaluated_at=self.evaluated_at,
        ).positions[0]
        self.assertEqual(mismatched.status, "review_required")
        self.assertEqual(
            mismatched.reason_codes,
            (
                "transaction_net_differs_from_broker_quantity",
                "transaction_order_id_missing",
            ),
        )

    def test_history_extends_for_missing_or_mismatched_fill_net(self) -> None:
        transaction = fill_row(
            fill_id="transaction-fill-1",
            order_id="order-1",
            filled_at="2026-01-31T15:00:00Z",
        )
        order = {**transaction, "source_fill_id": "order-fill-1"}
        result = assemble_current_position_lifecycle_coverage(
            (
                window(
                    digest_char="a",
                    start=date(2026, 1, 1),
                    end=date(2026, 2, 1),
                    orders=(order,),
                    transactions=(transaction,),
                ),
            ),
            (self.target(quantity="2"), self.target("MSFT", "3")),
            evaluated_at=self.evaluated_at,
        )

        by_symbol = {item.source_instrument_id: item for item in result.positions}
        self.assertEqual(by_symbol["AAPL"].status, "history_extension_required")
        self.assertEqual(
            by_symbol["AAPL"].reason_codes,
            ("transaction_net_differs_from_broker_quantity",),
        )
        self.assertEqual(by_symbol["MSFT"].status, "history_extension_required")
        self.assertEqual(
            by_symbol["MSFT"].reason_codes, ("no_transaction_fill_coverage",)
        )

    def test_lifecycle_evidence_blocks_financial_use(self) -> None:
        transaction = fill_row(
            fill_id="transaction-fill-1",
            order_id="order-1",
            filled_at="2026-01-31T15:00:00Z",
        )
        order = {**transaction, "source_fill_id": "order-fill-1"}
        event = lifecycle_event(
            event_uid="event-1", event_at="2026-01-31T16:00:00Z"
        )
        leg = lifecycle_leg(
            event_uid="event-1", event_leg_uid="event-leg-1", symbol="AAPL"
        )
        result = assemble_current_position_lifecycle_coverage(
            (
                window(
                    digest_char="a",
                    start=date(2026, 1, 1),
                    end=date(2026, 2, 1),
                    orders=(order,),
                    transactions=(transaction,),
                    events=(event,),
                    legs=(leg,),
                ),
            ),
            (self.target(),),
            evaluated_at=self.evaluated_at,
        )

        self.assertEqual(result.positions[0].status, "review_required")
        self.assertEqual(
            result.positions[0].reason_codes, ("lifecycle_review_required",)
        )

    def test_unscoped_review_marker_blocks_every_target(self) -> None:
        transaction = fill_row(
            fill_id="transaction-fill-1",
            order_id="order-1",
            filled_at="2026-01-31T15:00:00Z",
        )
        order = {**transaction, "source_fill_id": "order-fill-1"}
        event = lifecycle_event(
            event_uid="event-1", event_at="2026-01-31T16:00:00Z"
        )
        marker = lifecycle_leg(
            event_uid="event-1",
            event_leg_uid="event-leg-1",
            symbol="",
            evidence_status="review_required",
        )
        result = assemble_current_position_lifecycle_coverage(
            (
                window(
                    digest_char="a",
                    start=date(2026, 1, 1),
                    end=date(2026, 2, 1),
                    orders=(order,),
                    transactions=(transaction,),
                    events=(event,),
                    legs=(marker,),
                ),
            ),
            (self.target(),),
            evaluated_at=self.evaluated_at,
        )

        self.assertEqual(result.positions[0].status, "review_required")
        self.assertIn(
            "unscoped_lifecycle_review_required",
            result.positions[0].reason_codes,
        )

    def test_post_snapshot_activity_is_excluded(self) -> None:
        transaction = fill_row(
            fill_id="transaction-fill-1",
            order_id="order-1",
            filled_at="2026-02-01T21:00:00Z",
        )
        order = {**transaction, "source_fill_id": "order-fill-1"}
        event = lifecycle_event(
            event_uid="event-after-snapshot",
            event_at="2026-02-01T21:00:00Z",
        )
        leg = lifecycle_leg(
            event_uid="event-after-snapshot",
            event_leg_uid="event-after-snapshot:leg:0",
            symbol="MSFT",
        )
        result = assemble_current_position_lifecycle_coverage(
            (
                window(
                    digest_char="a",
                    start=date(2026, 1, 1),
                    end=date(2026, 2, 1),
                    orders=(order,),
                    transactions=(transaction,),
                    events=(event,),
                    legs=(leg,),
                ),
            ),
            (self.target(),),
            evaluated_at=self.evaluated_at,
        )

        self.assertEqual(result.excluded_post_evaluation_order_rows, 1)
        self.assertEqual(result.excluded_post_evaluation_transaction_rows, 1)
        self.assertEqual(result.excluded_post_evaluation_lifecycle_events, 1)
        self.assertEqual(result.excluded_post_evaluation_lifecycle_event_legs, 1)
        self.assertEqual(result.privacy_safe_audit()["excluded_post_evaluation_rows"], 4)
        self.assertEqual(result.positions[0].status, "history_extension_required")

    def test_source_window_exclusion_counts_are_bound_into_audit_and_digest(self) -> None:
        baseline = window(
            digest_char="a",
            start=date(2026, 1, 1),
            end=date(2026, 2, 1),
        )
        excluded = window(
            digest_char="a",
            start=date(2026, 1, 1),
            end=date(2026, 2, 1),
            excluded_order_rows=1,
            excluded_transaction_rows=2,
            excluded_events=3,
            excluded_legs=4,
        )
        baseline_result = assemble_current_position_lifecycle_coverage(
            (baseline,), (self.target(),), evaluated_at=self.evaluated_at
        )
        result = assemble_current_position_lifecycle_coverage(
            (excluded,), (self.target(),), evaluated_at=self.evaluated_at
        )

        audit = result.privacy_safe_audit()
        self.assertEqual(audit["excluded_out_of_window_order_fill_rows"], 1)
        self.assertEqual(audit["excluded_out_of_window_transaction_fill_rows"], 2)
        self.assertEqual(audit["excluded_out_of_window_lifecycle_events"], 3)
        self.assertEqual(audit["excluded_out_of_window_lifecycle_event_legs"], 4)
        self.assertNotEqual(result.assembly_sha256, baseline_result.assembly_sha256)

    def test_gap_overlap_scope_and_conflicting_replay_fail_closed(self) -> None:
        first = window(
            digest_char="a", start=date(2026, 1, 1), end=date(2026, 1, 15)
        )
        gap = window(
            digest_char="b", start=date(2026, 1, 17), end=date(2026, 2, 1)
        )
        overlap = window(
            digest_char="b", start=date(2026, 1, 15), end=date(2026, 2, 1)
        )
        wrong_scope = window(
            digest_char="b",
            start=date(2026, 1, 16),
            end=date(2026, 2, 1),
            connection_uid="connection:schwab:other-0001",
        )
        for second in (gap, overlap, wrong_scope):
            with self.subTest(second=second), self.assertRaises(
                LifecycleCoverageError
            ):
                assemble_current_position_lifecycle_coverage(
                    (first, second),
                    (self.target(),),
                    evaluated_at=self.evaluated_at,
                )

        transaction = fill_row(
            fill_id="transaction-fill-1",
            order_id="order-1",
            filled_at="2026-01-31T15:00:00Z",
        )
        conflicting = {**transaction, "fill_price": "101"}
        with self.assertRaisesRegex(LifecycleCoverageError, "conflicting"):
            assemble_current_position_lifecycle_coverage(
                (
                    window(
                        digest_char="a",
                        start=date(2026, 1, 1),
                        end=date(2026, 2, 1),
                        transactions=(transaction, conflicting),
                    ),
                ),
                (self.target(),),
                evaluated_at=self.evaluated_at,
            )

    def test_option_identity_conflict_fails_closed(self) -> None:
        symbol = "AAPL  260320C00200000"
        first = fill_row(
            fill_id="transaction-fill-1",
            order_id="order-1",
            filled_at="2026-01-30T15:00:00Z",
            symbol=symbol,
            asset_class="option",
            multiplier="100",
        )
        second = fill_row(
            fill_id="transaction-fill-2",
            order_id="order-2",
            filled_at="2026-01-31T15:00:00Z",
            symbol=symbol,
            asset_class="option",
            multiplier="50",
        )
        with self.assertRaisesRegex(LifecycleCoverageError, "conflicting canonical"):
            assemble_current_position_lifecycle_coverage(
                (
                    window(
                        digest_char="a",
                        start=date(2026, 1, 1),
                        end=date(2026, 2, 1),
                        transactions=(first, second),
                    ),
                ),
                (self.target(symbol, "2", "option"),),
                evaluated_at=self.evaluated_at,
            )


if __name__ == "__main__":
    unittest.main()
