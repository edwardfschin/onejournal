from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import unittest

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.market_data import (
    MarketSessionAuthority,
    SessionAuthorityError,
    assess_quote_freshness,
    build_quote_uid,
    build_session_authority_uid,
    validate_market_session_authority,
)


class MarketSessionAuthorityTests(unittest.TestCase):
    EVALUATED_AT = datetime(2026, 8, 11, 14, 30, 30, tzinfo=UTC)

    def _quote(self, **changes) -> NormalizedQuote:
        base = NormalizedQuote(
            quote_uid="pending",
            provider="schwab",
            connection_uid="local-schwab-primary",
            instrument_key="stock|AAPL",
            provider_instrument_id="AAPL",
            symbol="AAPL",
            asset_class="stock",
            currency="USD",
            bid=Decimal("199.90"),
            ask=Decimal("200.10"),
            last=Decimal("200.00"),
            provider_quote_at=self.EVALUATED_AT - timedelta(seconds=30),
            received_at=self.EVALUATED_AT - timedelta(seconds=29),
            market_session="unknown",
            data_mode="real_time",
            entitlement_status="entitled",
            asof=date(2026, 8, 11),
            raw_path="data/raw/schwab/2026-08-11/quotes/batch.json",
            raw_sha256="a" * 64,
            adapter_version="schwab-quote-v1",
        )
        quote = replace(base, **changes)
        return replace(quote, quote_uid=build_quote_uid(quote))

    def _authority(self, **changes) -> MarketSessionAuthority:
        base = MarketSessionAuthority(
            authority_uid="pending",
            instrument_key="stock|AAPL",
            venue_id="XNAS",
            calendar_id="us-equities-xnas",
            venue_timezone="America/New_York",
            market_date=date(2026, 8, 11),
            evaluated_at=self.EVALUATED_AT,
            market_session="regular",
            trading_day_kind="regular",
            phase_started_at=datetime(2026, 8, 11, 13, 30, tzinfo=UTC),
            phase_ends_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            resolved_at=self.EVALUATED_AT - timedelta(seconds=1),
            valid_until=self.EVALUATED_AT + timedelta(minutes=1),
            source="approved-calendar-fixture",
            source_version="2026.08.11",
        )
        authority = replace(base, **changes)
        return replace(
            authority,
            authority_uid=build_session_authority_uid(authority),
        )

    def test_unknown_provider_session_uses_exact_bound_authority(self) -> None:
        assessment = assess_quote_freshness(
            self._quote(),
            evaluated_at=self.EVALUATED_AT,
            session_authority=self._authority(),
        )

        self.assertEqual(assessment.status, "live_fresh")
        self.assertTrue(assessment.valuation_allowed)
        self.assertEqual(assessment.quote_market_session, "regular")
        self.assertEqual(assessment.evaluation_market_session, "regular")
        self.assertEqual(assessment.quote_session_source, "authority")
        self.assertEqual(assessment.evaluation_session_source, "authority")
        self.assertTrue(
            assessment.session_authority_uid.startswith("session-authority:")
        )

    def test_matching_provider_and_authority_sessions_preserve_both_sources(self) -> None:
        assessment = assess_quote_freshness(
            self._quote(market_session="regular"),
            evaluated_at=self.EVALUATED_AT,
            session_authority=self._authority(),
        )

        self.assertEqual(assessment.status, "live_fresh")
        self.assertEqual(assessment.quote_session_source, "provider_and_authority")

    def test_authority_identity_is_deterministic_and_content_bound(self) -> None:
        first = self._authority()
        second = self._authority()
        changed = self._authority(source_version="2026.08.12")

        self.assertEqual(first.authority_uid, second.authority_uid)
        self.assertNotEqual(first.authority_uid, changed.authority_uid)

    def test_extended_session_uses_extended_threshold(self) -> None:
        authority = self._authority(
            market_session="pre_market",
            phase_started_at=datetime(2026, 8, 11, 8, 0, tzinfo=UTC),
            phase_ends_at=datetime(2026, 8, 11, 13, 30, tzinfo=UTC),
            evaluated_at=datetime(2026, 8, 11, 13, 29, tzinfo=UTC),
            resolved_at=datetime(2026, 8, 11, 13, 28, 59, tzinfo=UTC),
            valid_until=datetime(2026, 8, 11, 13, 30, tzinfo=UTC),
        )
        quote = self._quote(
            provider_quote_at=datetime(2026, 8, 11, 13, 27, 1, tzinfo=UTC),
            received_at=datetime(2026, 8, 11, 13, 27, 2, tzinfo=UTC),
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=authority.evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "live_fresh")
        self.assertEqual(assessment.age_seconds, Decimal("119.0"))

    def test_closed_holiday_and_early_close_are_not_labelled_live(self) -> None:
        cases = (
            self._authority(
                market_session="closed",
                trading_day_kind="holiday",
                phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
                phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            ),
            self._authority(
                market_session="closed",
                trading_day_kind="early_close",
                evaluated_at=datetime(2026, 8, 11, 17, 30, tzinfo=UTC),
                phase_started_at=datetime(2026, 8, 11, 17, 0, tzinfo=UTC),
                phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
                resolved_at=datetime(2026, 8, 11, 17, 29, 59, tzinfo=UTC),
                valid_until=datetime(2026, 8, 11, 17, 31, tzinfo=UTC),
            ),
        )
        for authority in cases:
            with self.subTest(day_kind=authority.trading_day_kind):
                quote = self._quote(
                    provider_quote_at=authority.evaluated_at - timedelta(seconds=30),
                    received_at=authority.evaluated_at - timedelta(seconds=29),
                )
                assessment = assess_quote_freshness(
                    quote,
                    evaluated_at=authority.evaluated_at,
                    session_authority=authority,
                )
                self.assertEqual(assessment.status, "market_closed_last")
                self.assertTrue(assessment.valuation_allowed)
                self.assertNotEqual(assessment.status, "live_fresh")

    def test_provider_authority_conflict_fails_closed(self) -> None:
        authority = self._authority(
            market_session="closed",
            phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
            phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
        )
        assessment = assess_quote_freshness(
            self._quote(market_session="regular"),
            evaluated_at=self.EVALUATED_AT,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "unavailable")
        self.assertFalse(assessment.valuation_allowed)
        self.assertEqual(assessment.quote_session_source, "unavailable")
        self.assertEqual(
            assessment.reason,
            "provider and authoritative market sessions conflict",
        )

    def test_authority_outside_quote_phase_cannot_fill_unknown_quote_session(self) -> None:
        evaluated_at = datetime(2026, 8, 11, 20, 1, tzinfo=UTC)
        authority = self._authority(
            evaluated_at=evaluated_at,
            market_session="closed",
            phase_started_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )
        quote = self._quote(
            provider_quote_at=datetime(2026, 8, 11, 19, 59, 59, tzinfo=UTC),
            received_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
        )

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "unavailable")
        self.assertFalse(assessment.valuation_allowed)
        self.assertEqual(assessment.quote_market_session, "unknown")
        self.assertEqual(assessment.evaluation_market_session, "closed")

    def test_regular_quote_retained_after_close_is_not_a_false_conflict(self) -> None:
        evaluated_at = datetime(2026, 8, 11, 20, 1, tzinfo=UTC)
        authority = self._authority(
            evaluated_at=evaluated_at,
            market_session="closed",
            phase_started_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )
        quote = self._quote(
            market_session="regular",
            provider_quote_at=datetime(2026, 8, 11, 19, 59, 59, tzinfo=UTC),
            received_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
        )

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "market_closed_last")
        self.assertTrue(assessment.valuation_allowed)
        self.assertEqual(assessment.quote_market_session, "regular")
        self.assertEqual(assessment.evaluation_market_session, "closed")
        self.assertEqual(assessment.quote_session_source, "provider")
        self.assertEqual(assessment.evaluation_session_source, "authority")

    def test_expired_or_mismatched_authority_is_rejected(self) -> None:
        valid = self._authority()
        cases = (
            replace(valid, valid_until=self.EVALUATED_AT),
            self._authority(instrument_key="stock|MSFT"),
            replace(valid, market_date=date(2026, 8, 12)),
            self._authority(evaluated_at=self.EVALUATED_AT + timedelta(seconds=1)),
        )
        for authority in cases:
            with self.subTest(authority=authority):
                with self.assertRaises(SessionAuthorityError):
                    assess_quote_freshness(
                        self._quote(),
                        evaluated_at=self.EVALUATED_AT,
                        session_authority=authority,
                    )

    def test_unsupported_and_internally_invalid_authority_is_rejected(self) -> None:
        base = self._authority()
        cases = (
            replace(base, market_session="auction"),
            replace(base, trading_day_kind="holiday", market_session="regular"),
            replace(base, venue_timezone="Not/A_Timezone"),
            replace(base, authority_uid="session-authority:" + "0" * 64),
        )
        for authority in cases:
            with self.subTest(authority=authority):
                with self.assertRaises(SessionAuthorityError):
                    validate_market_session_authority(authority)


if __name__ == "__main__":
    unittest.main()
