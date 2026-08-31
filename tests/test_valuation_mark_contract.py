from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import unittest

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.instruments import InstrumentIdentity
from onejournal.market_data import assess_quote_freshness, build_quote_uid
from onejournal.pnl.valuation_marks import select_valuation_mark


class ValuationMarkContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = InstrumentIdentity(asset_class="equity", market_scope="US", currency="USD", symbol="AAPL")
        base = NormalizedQuote("pending", "schwab", "conn", self.identity.key, "AAPL", "AAPL", "stock", "USD", Decimal("10"), Decimal("11"), Decimal("10.5"), datetime(2026, 8, 31, 12, tzinfo=UTC), datetime(2026, 8, 31, 12, 0, 1, tzinfo=UTC), "regular", "real_time", "entitled", date(2026, 8, 31), "data/raw/schwab/2026-08-31/quotes/fixture.json", "a" * 64, "test")
        self.quote = replace(base, quote_uid=build_quote_uid(base))

    def select(self, direction="LONG", quote=None, seconds=30):
        quote = quote or self.quote
        freshness = assess_quote_freshness(quote, evaluated_at=quote.provider_quote_at + timedelta(seconds=seconds))
        return select_valuation_mark(identity=self.identity, direction=direction, quote=quote, freshness=freshness, expected_provider="schwab", expected_connection_uid="conn")

    def test_live_marks_use_liquidation_side(self) -> None:
        self.assertEqual(self.select().selected_field, "bid")
        self.assertEqual(self.select("SHORT").selected_field, "ask")

    def test_stale_or_identity_mismatch_is_unavailable(self) -> None:
        self.assertEqual(self.select(seconds=61).status, "unavailable")
        wrong = replace(self.quote, instrument_key="stock|AAPL")
        self.assertEqual(self.select(quote=wrong).status, "unavailable")

    def test_closed_session_uses_last_only(self) -> None:
        closed = replace(self.quote, market_session="closed", data_mode="frozen")
        result = self.select(quote=closed, seconds=1)
        self.assertEqual(result.selected_field, "last")
        self.assertEqual(result.price, Decimal("10.5"))

    def test_freshness_from_another_quote_cannot_be_reused(self) -> None:
        other = replace(self.quote, quote_uid="quote:other")
        freshness = assess_quote_freshness(
            self.quote,
            evaluated_at=self.quote.provider_quote_at + timedelta(seconds=30),
        )
        result = select_valuation_mark(
            identity=self.identity, direction="LONG", quote=other,
            freshness=freshness, expected_provider="schwab",
            expected_connection_uid="conn",
        )
        self.assertEqual(result.status, "unavailable")
        self.assertIn("not bound", result.reason)
