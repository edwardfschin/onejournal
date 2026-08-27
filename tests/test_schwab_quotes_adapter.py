from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import unittest

from onejournal.brokers.schwab.quotes_json import (
    SchwabQuoteAdapterError,
    SchwabQuoteRequest,
    load_quotes_json,
    normalized_quotes_from_payload,
)
from onejournal.market_data import assess_quote_freshness


PROJECT_DIR = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_DIR / "docs/examples/schwab_quotes_json/quotes_sample.json"


class SchwabQuotesAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = load_quotes_json(FIXTURE)
        self.request = SchwabQuoteRequest(
            provider_symbol="AAPL",
            instrument_key="stock|AAPL",
            asset_class="stock",
            currency="USD",
        )
        self.received_at = datetime(2026, 8, 11, 14, 30, 1, tzinfo=UTC)

    def normalize(self, payload=None, request=None):
        return normalized_quotes_from_payload(
            self.payload if payload is None else payload,
            requests=(self.request if request is None else request,),
            connection_uid="local-schwab-primary",
            asof=date(2026, 8, 11),
            received_at=self.received_at,
            raw_path="data/raw/schwab/2026-08-11/quotes/batch.json",
            raw_sha256="a" * 64,
        )

    def test_synthetic_quote_normalizes_with_exact_identity_and_decimals(self) -> None:
        (quote,) = self.normalize()

        self.assertEqual(quote.provider, "schwab")
        self.assertEqual(quote.instrument_key, "stock|AAPL")
        self.assertEqual(quote.provider_instrument_id, "AAPL")
        self.assertEqual(quote.bid, Decimal("199.90"))
        self.assertEqual(quote.ask, Decimal("200.10"))
        self.assertEqual(quote.last, Decimal("200.00"))
        self.assertEqual(
            quote.provider_quote_at,
            datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
        )
        self.assertEqual(quote.market_session, "regular")
        self.assertEqual(quote.data_mode, "real_time")
        self.assertEqual(quote.entitlement_status, "entitled")
        self.assertTrue(quote.quote_uid.startswith("quote:"))

    def test_unexpected_or_missing_symbol_rejects_the_whole_batch(self) -> None:
        payload = dict(self.payload)
        payload["MSFT"] = dict(payload["AAPL"], symbol="MSFT")

        with self.assertRaisesRegex(SchwabQuoteAdapterError, "scope mismatch"):
            self.normalize(payload=payload)
        with self.assertRaisesRegex(SchwabQuoteAdapterError, "scope mismatch"):
            self.normalize(payload={})

    def test_asset_class_must_match_explicit_onejournal_mapping(self) -> None:
        request = SchwabQuoteRequest(
            provider_symbol="AAPL",
            instrument_key="option|AAPL|example",
            asset_class="option",
            currency="USD",
        )
        with self.assertRaisesRegex(SchwabQuoteAdapterError, "mapping mismatch"):
            self.normalize(request=request)

        with self.assertRaisesRegex(SchwabQuoteAdapterError, "stock[|] prefix"):
            SchwabQuoteRequest(
                provider_symbol="AAPL",
                instrument_key="option|AAPL|example",
                asset_class="stock",
                currency="USD",
            )

    def test_request_identity_rejects_controls_commas_and_non_ascii_currency(self) -> None:
        with self.assertRaisesRegex(SchwabQuoteAdapterError, "commas or controls"):
            SchwabQuoteRequest(
                provider_symbol="AAPL,MSFT",
                instrument_key="stock|AAPL",
                asset_class="stock",
                currency="USD",
            )
        with self.assertRaisesRegex(SchwabQuoteAdapterError, "three-letter"):
            SchwabQuoteRequest(
                provider_symbol="AAPL",
                instrument_key="stock|AAPL",
                asset_class="stock",
                currency="ÜSD",
            )

    def test_float_and_crossed_prices_fail_closed(self) -> None:
        float_payload = dict(self.payload)
        float_payload["AAPL"] = dict(float_payload["AAPL"])
        float_payload["AAPL"]["quote"] = dict(float_payload["AAPL"]["quote"])
        float_payload["AAPL"]["quote"]["bidPrice"] = 199.9
        with self.assertRaisesRegex(SchwabQuoteAdapterError, "exact JSON decimal"):
            self.normalize(payload=float_payload)

        crossed_payload = load_quotes_json(FIXTURE)
        crossed_payload["AAPL"]["quote"]["bidPrice"] = Decimal("201")
        with self.assertRaisesRegex(ValueError, "crossed quote"):
            self.normalize(payload=crossed_payload)

    def test_realtime_flag_is_required_and_false_is_delayed(self) -> None:
        missing = load_quotes_json(FIXTURE)
        del missing["AAPL"]["realtime"]
        with self.assertRaisesRegex(SchwabQuoteAdapterError, "explicit boolean"):
            self.normalize(payload=missing)

        delayed = load_quotes_json(FIXTURE)
        delayed["AAPL"]["realtime"] = False
        (quote,) = self.normalize(payload=delayed)
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=quote.provider_quote_at + timedelta(seconds=1),
        )
        self.assertEqual(assessment.status, "delayed")
        self.assertFalse(assessment.valuation_allowed)

    def test_missing_provider_session_is_preserved_as_unknown(self) -> None:
        payload = load_quotes_json(FIXTURE)
        del payload["AAPL"]["quote"]["marketSession"]

        (quote,) = self.normalize(payload=payload)
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=quote.provider_quote_at + timedelta(seconds=1),
        )

        self.assertEqual(quote.market_session, "unknown")
        self.assertEqual(assessment.status, "unavailable")
        self.assertFalse(assessment.valuation_allowed)

    def test_non_normal_security_status_is_rejected(self) -> None:
        payload = load_quotes_json(FIXTURE)
        payload["AAPL"]["quote"]["securityStatus"] = "Halted"
        with self.assertRaisesRegex(SchwabQuoteAdapterError, "not NORMAL"):
            self.normalize(payload=payload)


if __name__ == "__main__":
    unittest.main()
