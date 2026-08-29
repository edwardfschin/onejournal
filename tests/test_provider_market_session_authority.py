from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import unittest

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.market_data import (
    ProviderMarketSessionAuthority,
    SessionAuthorityError,
    assess_quote_freshness,
    build_provider_session_authority_uid,
    build_quote_uid,
    resolve_provider_session_authority,
    validate_provider_session_authority,
)


class ProviderMarketSessionAuthorityTests(unittest.TestCase):
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

    def _authority(
        self,
        *,
        quote: NormalizedQuote | None = None,
        **changes,
    ) -> ProviderMarketSessionAuthority:
        quote = quote or self._quote()
        base = ProviderMarketSessionAuthority(
            authority_uid="pending",
            provider=quote.provider,
            connection_uid=quote.connection_uid,
            quote_uid=quote.quote_uid,
            instrument_key=quote.instrument_key,
            provider_instrument_id=quote.provider_instrument_id,
            schedule_scope_id="schwab-equity-us",
            mic=None,
            venue_timezone="America/New_York",
            provider_quote_at=quote.provider_quote_at,
            evaluated_at=self.EVALUATED_AT,
            quote_market_date=date(2026, 8, 11),
            evaluation_market_date=date(2026, 8, 11),
            quote_market_session="regular",
            evaluation_market_session="regular",
            quote_trading_day_kind="regular",
            evaluation_trading_day_kind="regular",
            quote_phase_started_at=datetime(2026, 8, 11, 13, 30, tzinfo=UTC),
            quote_phase_ends_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            evaluation_phase_started_at=datetime(
                2026, 8, 11, 13, 30, tzinfo=UTC
            ),
            evaluation_phase_ends_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            retrieved_at=self.EVALUATED_AT - timedelta(seconds=2),
            resolved_at=self.EVALUATED_AT - timedelta(seconds=1),
            valid_until=self.EVALUATED_AT + timedelta(minutes=1),
            source_response_type="market_hours",
            provider_source_version=None,
            raw_path="data/raw/schwab/2026-08-11/market-hours/response.json",
            raw_sha256="b" * 64,
            adapter_version="schwab-market-hours-v1",
        )
        authority = replace(base, **changes)
        return replace(
            authority,
            authority_uid=build_provider_session_authority_uid(authority),
        )

    def test_unknown_quote_session_uses_exact_same_provider_authority(self) -> None:
        quote = self._quote()
        authority = self._authority(quote=quote)

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=self.EVALUATED_AT,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "live_fresh")
        self.assertTrue(assessment.valuation_allowed)
        self.assertEqual(assessment.quote_market_session, "regular")
        self.assertEqual(assessment.evaluation_market_session, "regular")
        self.assertEqual(assessment.quote_session_source, "authority")
        self.assertEqual(assessment.evaluation_session_source, "authority")
        self.assertTrue(
            assessment.session_authority_uid.startswith(
                "provider-session-authority:"
            )
        )

    def test_matching_quote_and_schedule_preserve_both_sources(self) -> None:
        quote = self._quote(market_session="regular")
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=self.EVALUATED_AT,
            session_authority=self._authority(quote=quote),
        )

        self.assertEqual(assessment.status, "live_fresh")
        self.assertEqual(assessment.quote_session_source, "provider_and_authority")

    def test_identity_is_deterministic_and_mic_is_optional(self) -> None:
        first = self._authority()
        second = self._authority()
        changed = self._authority(mic="XNAS")

        validate_provider_session_authority(first)
        self.assertIsNone(first.mic)
        self.assertEqual(first.authority_uid, second.authority_uid)
        self.assertNotEqual(first.authority_uid, changed.authority_uid)

    def test_extended_session_uses_extended_threshold(self) -> None:
        evaluated_at = datetime(2026, 8, 11, 13, 29, tzinfo=UTC)
        quote = self._quote(
            provider_quote_at=datetime(2026, 8, 11, 13, 27, 1, tzinfo=UTC),
            received_at=datetime(2026, 8, 11, 13, 27, 2, tzinfo=UTC),
        )
        authority = self._authority(
            quote=quote,
            evaluated_at=evaluated_at,
            quote_market_session="pre_market",
            evaluation_market_session="pre_market",
            quote_phase_started_at=datetime(2026, 8, 11, 8, 0, tzinfo=UTC),
            quote_phase_ends_at=datetime(2026, 8, 11, 13, 30, tzinfo=UTC),
            evaluation_phase_started_at=datetime(2026, 8, 11, 8, 0, tzinfo=UTC),
            evaluation_phase_ends_at=datetime(2026, 8, 11, 13, 30, tzinfo=UTC),
            retrieved_at=evaluated_at - timedelta(seconds=2),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "live_fresh")
        self.assertEqual(assessment.age_seconds, Decimal("119.0"))

    def test_after_hours_uses_extended_threshold(self) -> None:
        evaluated_at = datetime(2026, 8, 11, 20, 30, tzinfo=UTC)
        quote = self._quote(
            provider_quote_at=evaluated_at - timedelta(seconds=120),
            received_at=evaluated_at - timedelta(seconds=119),
        )
        authority = self._authority(
            quote=quote,
            evaluated_at=evaluated_at,
            quote_market_session="after_hours",
            evaluation_market_session="after_hours",
            quote_phase_started_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            quote_phase_ends_at=datetime(2026, 8, 12, 0, 0, tzinfo=UTC),
            evaluation_phase_started_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            evaluation_phase_ends_at=datetime(2026, 8, 12, 0, 0, tzinfo=UTC),
            retrieved_at=evaluated_at - timedelta(seconds=2),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "live_fresh")
        self.assertEqual(assessment.age_seconds, Decimal("120.0"))

    def test_early_close_is_never_labelled_live(self) -> None:
        evaluated_at = datetime(2026, 8, 11, 21, 0, tzinfo=UTC)
        quote = self._quote(
            provider_quote_at=datetime(2026, 8, 11, 19, 59, 59, tzinfo=UTC),
            received_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
        )
        authority = self._authority(
            quote=quote,
            evaluated_at=evaluated_at,
            evaluation_market_session="closed",
            evaluation_trading_day_kind="early_close",
            evaluation_phase_started_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            evaluation_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            retrieved_at=evaluated_at - timedelta(seconds=2),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "market_closed_last")
        self.assertTrue(assessment.valuation_allowed)

    def test_holiday_and_unscheduled_closure_require_closed_sessions(self) -> None:
        evaluated_at = datetime(2026, 8, 11, 21, 0, tzinfo=UTC)
        quote = self._quote(
            provider_quote_at=evaluated_at - timedelta(seconds=30),
            received_at=evaluated_at - timedelta(seconds=29),
        )
        authority = self._authority(
            quote=quote,
            evaluated_at=evaluated_at,
            quote_market_session="closed",
            evaluation_market_session="closed",
            quote_trading_day_kind="holiday",
            evaluation_trading_day_kind="holiday",
            quote_phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
            quote_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            evaluation_phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
            evaluation_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            retrieved_at=evaluated_at - timedelta(seconds=2),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )
        self.assertEqual(assessment.status, "market_closed_last")

        invalid = replace(
            authority,
            evaluation_trading_day_kind="unscheduled_closure",
            evaluation_market_session="regular",
        )
        with self.assertRaises(SessionAuthorityError):
            validate_provider_session_authority(invalid)

        unscheduled = self._authority(
            quote=quote,
            evaluated_at=evaluated_at,
            quote_market_session="closed",
            evaluation_market_session="closed",
            quote_trading_day_kind="unscheduled_closure",
            evaluation_trading_day_kind="unscheduled_closure",
            quote_phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
            quote_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            evaluation_phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
            evaluation_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            retrieved_at=evaluated_at - timedelta(seconds=2),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=unscheduled,
        )
        self.assertEqual(assessment.status, "market_closed_last")
        self.assertTrue(assessment.valuation_allowed)

        closed_unspecified = self._authority(
            quote=quote,
            evaluated_at=evaluated_at,
            quote_market_session="closed",
            evaluation_market_session="closed",
            quote_trading_day_kind="closed_unspecified",
            evaluation_trading_day_kind="closed_unspecified",
            quote_phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
            quote_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            evaluation_phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
            evaluation_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            retrieved_at=evaluated_at - timedelta(seconds=2),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=closed_unspecified,
        )
        self.assertEqual(assessment.status, "market_closed_last")

        invalid_unspecified = replace(
            closed_unspecified,
            evaluation_market_session="regular",
        )
        with self.assertRaisesRegex(SessionAuthorityError, "closed-day kind"):
            validate_provider_session_authority(invalid_unspecified)

    def test_quote_schedule_conflict_fails_closed(self) -> None:
        quote = self._quote(market_session="regular")
        authority = self._authority(
            quote=quote,
            quote_market_session="closed",
            quote_phase_started_at=datetime(2026, 8, 11, 4, 0, tzinfo=UTC),
            quote_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
        )

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=self.EVALUATED_AT,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "unavailable")
        self.assertFalse(assessment.valuation_allowed)
        self.assertEqual(
            assessment.reason,
            "provider and authoritative market sessions conflict",
        )

    def test_schedule_authority_cannot_override_entitlement_or_delay(self) -> None:
        delayed = self._quote(
            data_mode="delayed",
            entitlement_status="delayed",
        )
        denied = self._quote(entitlement_status="denied")
        unknown = self._quote(entitlement_status="unknown")

        delayed_result = assess_quote_freshness(
            delayed,
            evaluated_at=self.EVALUATED_AT,
            session_authority=self._authority(quote=delayed),
        )
        denied_result = assess_quote_freshness(
            denied,
            evaluated_at=self.EVALUATED_AT,
            session_authority=self._authority(quote=denied),
        )
        unknown_result = assess_quote_freshness(
            unknown,
            evaluated_at=self.EVALUATED_AT,
            session_authority=self._authority(quote=unknown),
        )

        self.assertEqual(delayed_result.status, "delayed")
        self.assertFalse(delayed_result.valuation_allowed)
        self.assertEqual(denied_result.status, "unavailable")
        self.assertFalse(denied_result.valuation_allowed)
        self.assertEqual(unknown_result.status, "unavailable")
        self.assertFalse(unknown_result.valuation_allowed)

    def test_quote_and_evaluation_phases_are_separate_across_close(self) -> None:
        evaluated_at = datetime(2026, 8, 11, 20, 1, tzinfo=UTC)
        quote = self._quote(
            market_session="regular",
            provider_quote_at=datetime(2026, 8, 11, 19, 59, 59, tzinfo=UTC),
            received_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
        )
        authority = self._authority(
            quote=quote,
            evaluated_at=evaluated_at,
            evaluation_market_session="closed",
            evaluation_phase_started_at=datetime(2026, 8, 11, 20, 0, tzinfo=UTC),
            evaluation_phase_ends_at=datetime(2026, 8, 12, 4, 0, tzinfo=UTC),
            retrieved_at=evaluated_at - timedelta(seconds=2),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
        )

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(assessment.status, "market_closed_last")
        self.assertEqual(assessment.quote_market_session, "regular")
        self.assertEqual(assessment.evaluation_market_session, "closed")

    def test_exact_quote_provider_connection_and_instrument_binding(self) -> None:
        quote = self._quote()
        mismatches = (
            self._authority(
                quote=quote,
                provider="ibkr",
                raw_path="data/raw/ibkr/schedule.json",
            ),
            self._authority(quote=quote, connection_uid="other-connection"),
            self._authority(quote=quote, quote_uid="quote:" + "0" * 64),
            self._authority(quote=quote, instrument_key="stock|MSFT"),
            self._authority(quote=quote, provider_instrument_id="MSFT"),
            self._authority(
                quote=quote,
                provider_quote_at=quote.provider_quote_at - timedelta(seconds=1),
            ),
            self._authority(
                quote=quote,
                evaluated_at=self.EVALUATED_AT + timedelta(seconds=1),
                resolved_at=self.EVALUATED_AT,
            ),
        )
        for authority in mismatches:
            with self.subTest(authority=authority):
                with self.assertRaises(SessionAuthorityError):
                    assess_quote_freshness(
                        quote,
                        evaluated_at=self.EVALUATED_AT,
                        session_authority=authority,
                    )

        asof_mismatch = self._quote(asof=date(2026, 8, 12))
        with self.assertRaisesRegex(SessionAuthorityError, "quote_market_date"):
            assess_quote_freshness(
                asof_mismatch,
                evaluated_at=self.EVALUATED_AT,
                session_authority=self._authority(quote=asof_mismatch),
            )

    def test_expiry_source_timezone_date_and_lineage_fail_closed(self) -> None:
        valid = self._authority()
        invalid = (
            replace(valid, valid_until=self.EVALUATED_AT),
            replace(valid, venue_timezone="Not/A_Timezone"),
            replace(valid, quote_market_date=date(2026, 8, 12)),
            replace(valid, mic="NASDAQ"),
            replace(valid, raw_path="data/raw/ibkr/schedule.json"),
            replace(valid, raw_sha256="not-a-digest"),
            replace(valid, retrieved_at=self.EVALUATED_AT + timedelta(seconds=1)),
        )
        for authority in invalid:
            with self.subTest(authority=authority):
                with self.assertRaises(SessionAuthorityError):
                    validate_provider_session_authority(authority)

    def test_iana_timezone_handles_dst_schedule_shift(self) -> None:
        evaluated_at = datetime(2026, 11, 2, 15, 0, tzinfo=UTC)
        quote = self._quote(
            provider_quote_at=datetime(2026, 11, 2, 14, 59, 30, tzinfo=UTC),
            received_at=datetime(2026, 11, 2, 14, 59, 31, tzinfo=UTC),
            asof=date(2026, 11, 2),
            raw_path="data/raw/schwab/2026-11-02/quotes/batch.json",
        )
        authority = self._authority(
            quote=quote,
            evaluated_at=evaluated_at,
            quote_market_date=date(2026, 11, 2),
            evaluation_market_date=date(2026, 11, 2),
            quote_phase_started_at=datetime(2026, 11, 2, 14, 30, tzinfo=UTC),
            quote_phase_ends_at=datetime(2026, 11, 2, 21, 0, tzinfo=UTC),
            evaluation_phase_started_at=datetime(2026, 11, 2, 14, 30, tzinfo=UTC),
            evaluation_phase_ends_at=datetime(2026, 11, 2, 21, 0, tzinfo=UTC),
            retrieved_at=evaluated_at - timedelta(seconds=2),
            resolved_at=evaluated_at - timedelta(seconds=1),
            valid_until=evaluated_at + timedelta(minutes=1),
            raw_path="data/raw/schwab/2026-11-02/market-hours/response.json",
        )

        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )
        self.assertEqual(assessment.status, "live_fresh")

    def test_resolver_validates_output_and_fails_closed_on_outage(self) -> None:
        quote = self._quote()
        authority = self._authority(quote=quote)

        class Resolver:
            def resolve(self, **_kwargs):
                return authority

        class OutageResolver:
            def resolve(self, **_kwargs):
                raise TimeoutError("provider unavailable")

        self.assertEqual(
            resolve_provider_session_authority(
                Resolver(),
                quote=quote,
                evaluated_at=self.EVALUATED_AT,
            ),
            authority,
        )
        with self.assertRaisesRegex(SessionAuthorityError, "failed closed"):
            resolve_provider_session_authority(
                OutageResolver(),
                quote=quote,
                evaluated_at=self.EVALUATED_AT,
            )


if __name__ == "__main__":
    unittest.main()
