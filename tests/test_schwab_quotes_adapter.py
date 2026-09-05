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
OFFICIAL_SANITIZED_FIXTURE = (
    PROJECT_DIR
    / "docs/examples/schwab_quotes_json/quotes_official_sanitized_no_session.json"
)


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

    def test_synthetic_listed_option_shape_preserves_exact_identity(self) -> None:
        provider_symbol = "AAPL  260116C00200000"
        payload = load_quotes_json(FIXTURE)
        payload[provider_symbol] = payload.pop("AAPL")
        payload[provider_symbol]["symbol"] = provider_symbol
        payload[provider_symbol]["assetMainType"] = "OPTION"
        request = SchwabQuoteRequest(
            provider_symbol=provider_symbol,
            instrument_key="option|AAPL|2026-01-16|call|200",
            asset_class="option",
            currency="USD",
        )

        (quote,) = self.normalize(payload=payload, request=request)

        self.assertEqual(quote.provider_instrument_id, provider_symbol)
        self.assertEqual(quote.symbol, provider_symbol)
        self.assertEqual(quote.instrument_key, "option|AAPL|2026-01-16|call|200")
        self.assertEqual(quote.asset_class, "option")
        self.assertEqual(quote.bid, Decimal("199.90"))
        self.assertEqual(quote.ask, Decimal("200.10"))

    def test_canonical_pnl03_identity_prefixes_are_accepted(self) -> None:
        equity_request = SchwabQuoteRequest(
            provider_symbol="AAPL",
            instrument_key="instrument.v1|equity|US|USD|AAPL",
            asset_class="stock",
            currency="USD",
        )
        (equity,) = self.normalize(request=equity_request)
        self.assertEqual(equity.instrument_key, equity_request.instrument_key)

        provider_symbol = "AAPL  260116C00200000"
        payload = load_quotes_json(FIXTURE)
        payload[provider_symbol] = payload.pop("AAPL")
        payload[provider_symbol]["symbol"] = provider_symbol
        payload[provider_symbol]["assetMainType"] = "OPTION"
        option_request = SchwabQuoteRequest(
            provider_symbol=provider_symbol,
            instrument_key=(
                "instrument.v1|option|US|USD|AAPL|2026-01-16|CALL|200|100"
            ),
            asset_class="option",
            currency="USD",
        )
        (option,) = self.normalize(payload=payload, request=option_request)
        self.assertEqual(option.instrument_key, option_request.instrument_key)

    def test_missing_all_prices_fails_closed(self) -> None:
        payload = load_quotes_json(FIXTURE)
        payload["AAPL"]["quote"]["bidPrice"] = None
        payload["AAPL"]["quote"]["askPrice"] = None
        payload["AAPL"]["quote"]["lastPrice"] = None

        with self.assertRaisesRegex(ValueError, "at least one of bid, ask, or last"):
            self.normalize(payload=payload)

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

        with self.assertRaisesRegex(SchwabQuoteAdapterError, "stock identity prefix"):
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

    def test_sanitized_official_shape_fails_closed_without_session(self) -> None:
        payload = load_quotes_json(OFFICIAL_SANITIZED_FIXTURE)
        request = SchwabQuoteRequest(
            provider_symbol="TEST",
            instrument_key="stock|TEST",
            asset_class="stock",
            currency="USD",
        )
        (quote,) = normalized_quotes_from_payload(
            payload,
            requests=(request,),
            connection_uid="local-schwab-primary",
            asof=date(2026, 8, 27),
            received_at=datetime(2026, 8, 27, 14, 30, 1, tzinfo=UTC),
            raw_path="data/raw/schwab/2026-08-27/quotes/official-sanitized.json",
            raw_sha256="b" * 64,
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=quote.provider_quote_at + timedelta(seconds=1),
        )

        self.assertEqual(quote.bid, Decimal("99.90"))
        self.assertEqual(quote.ask, Decimal("100.10"))
        self.assertEqual(quote.last, Decimal("100.00"))
        self.assertEqual(quote.data_mode, "real_time")
        self.assertEqual(quote.entitlement_status, "entitled")
        self.assertEqual(quote.market_session, "unknown")
        self.assertEqual(assessment.status, "unavailable")
        self.assertEqual(assessment.reason, "provider market session is unknown")
        self.assertFalse(assessment.valuation_allowed)

    def test_closed_security_status_is_frozen_and_requires_authority(self) -> None:
        payload = load_quotes_json(FIXTURE)
        payload["AAPL"]["quote"]["securityStatus"] = "Closed"

        (quote,) = self.normalize(payload=payload)
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=quote.provider_quote_at + timedelta(seconds=1),
        )

        self.assertEqual(quote.data_mode, "frozen")
        self.assertEqual(quote.entitlement_status, "entitled")
        self.assertEqual(quote.market_session, "unknown")
        self.assertEqual(assessment.status, "unavailable")
        self.assertEqual(assessment.reason, "provider market session is unknown")
        self.assertFalse(assessment.valuation_allowed)

    def test_unsafe_or_unsupported_security_status_is_rejected(self) -> None:
        payload = load_quotes_json(FIXTURE)
        for security_status in ("Halted", "Unknown", ""):
            with self.subTest(security_status=security_status):
                payload["AAPL"]["quote"]["securityStatus"] = security_status
                with self.assertRaisesRegex(SchwabQuoteAdapterError, "unsupported"):
                    self.normalize(payload=payload)

        payload["AAPL"]["quote"]["securityStatus"] = 1
        with self.assertRaisesRegex(SchwabQuoteAdapterError, "must be a string"):
            self.normalize(payload=payload)


if __name__ == "__main__":
    unittest.main()
