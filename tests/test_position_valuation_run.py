from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.brokers.normalized import NormalizedFill, NormalizedQuote
from onejournal.instruments import InstrumentIdentity
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.position_valuation_repository import (
    load_position_valuation_run,
    persist_position_valuation_run,
)
from onejournal.market_data import assess_quote_freshness, build_quote_uid
from onejournal.pnl.position_reconciliation import BrokerPositionRecord, BrokerPositionSnapshot
from onejournal.pnl.position_valuation import build_position_valuation_run


class PositionValuationRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self.asof = date(2026, 8, 31)
        self.evaluated_at = datetime(2026, 8, 31, 14, 30, 30, tzinfo=UTC)
        self.identity = InstrumentIdentity(
            asset_class="equity", market_scope="US", currency="USD", symbol="AAPL"
        )

    def fill(self, *, quantity="10", side="BUY_TO_OPEN", price="10", fee="1"):
        return NormalizedFill(
            fill_uid="fill-1", source_broker="schwab", source_account_id="acct",
            source_fill_id="source-1", source_order_id=None, episode_group_id=None,
            asof=self.asof, filled_at=datetime(2026, 8, 31, 14, 0, tzinfo=UTC),
            asset_class="stock", symbol="AAPL", side=side, quantity=Decimal(quantity),
            fill_price=Decimal(price), commission=Decimal(fee), fees=Decimal("0"),
            currency="USD", fetched_at=datetime(2026, 8, 31, 14, 0, 1, tzinfo=UTC),
            raw_path="data/raw/schwab/fill.json",
        )

    def snapshot(self, quantity="10"):
        return BrokerPositionSnapshot(
            "snapshot-1", "schwab", "conn", "acct", self.asof,
            self.evaluated_at - timedelta(seconds=5), "private/positions.json",
            "b" * 64, True, "synthetic-position-v1",
            (BrokerPositionRecord(self.identity, Decimal(quantity)),),
        )

    def quote(self):
        base = NormalizedQuote(
            "pending", "schwab", "conn", self.identity.key, "AAPL", "AAPL", "stock", "USD",
            Decimal("11"), Decimal("11.2"), Decimal("11.1"),
            self.evaluated_at - timedelta(seconds=20),
            self.evaluated_at - timedelta(seconds=19), "regular", "real_time", "entitled",
            self.asof, "data/raw/schwab/quotes/aapl.json", "a" * 64, "test-v1",
        )
        quote = replace(base, quote_uid=build_quote_uid(base))
        return quote, assess_quote_freshness(quote, evaluated_at=self.evaluated_at)

    def test_reconciled_long_position_uses_fifo_marked_result(self) -> None:
        run = build_position_valuation_run(
            fills=(self.fill(),), lifecycle_events=(), broker_snapshot=self.snapshot(),
            quotes={self.identity: self.quote()}, source_broker="schwab",
            connection_uid="conn", source_account_id="acct", asof=self.asof,
            evaluated_at=self.evaluated_at, max_snapshot_age_seconds=60,
        )
        (position,) = run.positions
        self.assertEqual(position.status, "valid")
        self.assertEqual(position.mark.selected_field, "bid")
        self.assertEqual(position.market_value, Decimal("110"))
        self.assertEqual(position.unrealized_pnl, Decimal("9"))
        self.assertEqual(position.open_cost_basis, Decimal("101"))

    def test_quantity_mismatch_blocks_mark_and_financial_values(self) -> None:
        run = build_position_valuation_run(
            fills=(self.fill(),), lifecycle_events=(), broker_snapshot=self.snapshot("9"),
            quotes={self.identity: self.quote()}, source_broker="schwab",
            connection_uid="conn", source_account_id="acct", asof=self.asof,
            evaluated_at=self.evaluated_at, max_snapshot_age_seconds=60,
        )
        (position,) = run.positions
        self.assertEqual(position.status, "reconciliation_pending")
        self.assertIsNone(position.mark)
        self.assertIsNone(position.market_value)
        self.assertIsNone(position.unrealized_pnl)

    def test_reconciled_short_position_uses_ask_and_fifo_result(self) -> None:
        run = build_position_valuation_run(
            fills=(self.fill(side="SELL_TO_OPEN"),), lifecycle_events=(),
            broker_snapshot=self.snapshot("-10"), quotes={self.identity: self.quote()},
            source_broker="schwab", connection_uid="conn",
            source_account_id="acct", asof=self.asof,
            evaluated_at=self.evaluated_at, max_snapshot_age_seconds=60,
        )
        (position,) = run.positions
        self.assertEqual(position.status, "valid")
        self.assertEqual(position.mark.selected_field, "ask")
        self.assertEqual(position.market_value, Decimal("-112"))
        self.assertEqual(position.unrealized_pnl, Decimal("-13"))

    def test_extra_broker_position_remains_visible_and_blocks_that_scope(self) -> None:
        extra = InstrumentIdentity(
            asset_class="equity", market_scope="US", currency="USD", symbol="MSFT"
        )
        snapshot = replace(
            self.snapshot(),
            positions=(
                BrokerPositionRecord(self.identity, Decimal("10")),
                BrokerPositionRecord(extra, Decimal("3")),
            ),
        )
        run = build_position_valuation_run(
            fills=(self.fill(),), lifecycle_events=(), broker_snapshot=snapshot,
            quotes={self.identity: self.quote()}, source_broker="schwab",
            connection_uid="conn", source_account_id="acct", asof=self.asof,
            evaluated_at=self.evaluated_at, max_snapshot_age_seconds=60,
        )
        self.assertEqual(len(run.positions), 2)
        self.assertEqual(run.positions[1].identity, extra)
        self.assertEqual(run.positions[1].status, "reconciliation_pending")
        self.assertEqual(run.positions[1].broker_quantity, Decimal("3"))

    def test_option_valuation_uses_exact_contract_multiplier(self) -> None:
        option = InstrumentIdentity(
            asset_class="option", market_scope="US", currency="USD",
            underlying_symbol="AAPL", expiry=date(2026, 9, 18),
            option_right="CALL", strike=Decimal("200"), multiplier=Decimal("100"),
        )
        fill = replace(
            self.fill(quantity="1", price="2"), asset_class="option",
            symbol="AAPL  260918C00200000", option_symbol="AAPL  260918C00200000",
            underlying_symbol="AAPL", option_type="CALL", expiry=date(2026, 9, 18),
            strike=Decimal("200"), multiplier=Decimal("100"),
        )
        snapshot = replace(
            self.snapshot(), positions=(BrokerPositionRecord(option, Decimal("1")),)
        )
        base = replace(
            self.quote()[0], quote_uid="pending", instrument_key=option.key,
            provider_instrument_id="AAPL  260918C00200000",
            symbol="AAPL  260918C00200000", asset_class="option",
            bid=Decimal("2.5"), ask=Decimal("2.6"), last=Decimal("2.55"),
        )
        quote = replace(base, quote_uid=build_quote_uid(base))
        freshness = assess_quote_freshness(quote, evaluated_at=self.evaluated_at)
        run = build_position_valuation_run(
            fills=(fill,), lifecycle_events=(), broker_snapshot=snapshot,
            quotes={option: (quote, freshness)}, source_broker="schwab",
            connection_uid="conn", source_account_id="acct", asof=self.asof,
            evaluated_at=self.evaluated_at, max_snapshot_age_seconds=60,
        )
        (position,) = run.positions
        self.assertEqual(position.market_value, Decimal("250"))
        self.assertEqual(position.unrealized_pnl, Decimal("49"))

    def test_missing_quote_is_unavailable_not_zero(self) -> None:
        run = build_position_valuation_run(
            fills=(self.fill(),), lifecycle_events=(), broker_snapshot=self.snapshot(),
            quotes={}, source_broker="schwab", connection_uid="conn",
            source_account_id="acct", asof=self.asof, evaluated_at=self.evaluated_at,
            max_snapshot_age_seconds=60,
        )
        (position,) = run.positions
        self.assertEqual(position.status, "unavailable")
        self.assertIsNone(position.market_value)
        self.assertIsNone(position.unrealized_pnl)

    def test_temporary_database_persists_reads_back_and_replays_exactly(self) -> None:
        snapshot = self.snapshot()
        run = build_position_valuation_run(
            fills=(self.fill(),), lifecycle_events=(), broker_snapshot=snapshot,
            quotes={self.identity: self.quote()}, source_broker="schwab",
            connection_uid="conn", source_account_id="acct", asof=self.asof,
            evaluated_at=self.evaluated_at, max_snapshot_age_seconds=60,
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "acceptance.duckdb"
            apply_schema_migrations(db_path)
            first = persist_position_valuation_run(
                db_path, run=run, broker_snapshot=snapshot,
            )
            replay = persist_position_valuation_run(
                db_path, run=run, broker_snapshot=snapshot,
            )
            self.assertTrue(first.created)
            self.assertTrue(replay.replayed)
            read_back = load_position_valuation_run(
                db_path, valuation_run_uid=run.valuation_run_uid
            )
            self.assertEqual(read_back.status, "ok")
            self.assertEqual(read_back.positions[0]["market_value"], Decimal("110"))
            self.assertEqual(read_back.positions[0]["freshness_status"], "live_fresh")
            self.assertEqual(read_back.positions[0]["quote_market_session"], "regular")
            with duckdb.connect(str(db_path), read_only=True) as con:
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM broker_position_snapshot_runs").fetchone()[0], 1
                )
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM pnl_position_valuation_runs").fetchone()[0], 1
                )
                row = con.execute(
                    """SELECT instrument_key, selected_price_field, mark_price,
                              market_value, unrealized_pnl, position_status
                       FROM pnl_canonical_position_valuations"""
                ).fetchone()
                self.assertEqual(
                    row,
                    (self.identity.key, "bid", Decimal("11"), Decimal("110"), Decimal("9"), "valid"),
                )
            conflicting = replace(
                snapshot,
                positions=(BrokerPositionRecord(self.identity, Decimal("9")),),
            )
            with self.assertRaisesRegex(ValueError, "conflicting broker snapshot replay"):
                persist_position_valuation_run(
                    db_path, run=run, broker_snapshot=conflicting,
                )
