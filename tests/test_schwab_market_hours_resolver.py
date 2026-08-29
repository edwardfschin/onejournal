from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import unittest

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.brokers.schwab.market_hours_json import market_hours_from_payload
from onejournal.brokers.schwab.market_hours_resolver import (
    SCHWAB_EQUITY_OPTION_SCOPE,
    SCHWAB_EQUITY_SCOPE,
    SchwabCombinedScheduleEvidence,
    SchwabMarketHoursResolver,
    SchwabMarketHoursResolverError,
    SchwabScheduleEvidence,
)
from onejournal.market_data import (
    assess_quote_freshness,
    build_quote_uid,
    resolve_provider_session_authority,
)

from tests.test_schwab_market_hours_adapter import closed_payload, normal_payload


CONNECTION_UID = "connection:schwab:test-owner"
MANIFEST_PATH = "data/raw/schwab/external/test-bundle/capture-manifest.json"


def shortened_payload() -> dict:
    payload = normal_payload()
    for products in payload.values():
        for item in products.values():
            item["date"] = "2026-11-27"
            for intervals in item["sessionHours"].values():
                for interval in intervals:
                    interval["start"] = interval["start"].replace(
                        "2026-08-31", "2026-11-27"
                    ).replace("-04:00", "-05:00")
                    interval["end"] = interval["end"].replace(
                        "2026-08-31", "2026-11-27"
                    ).replace("-04:00", "-05:00")
    payload["equity"]["EQ"]["sessionHours"]["regularMarket"][0]["end"] = (
        "2026-11-27T13:00:00-05:00"
    )
    payload["equity"]["EQ"]["sessionHours"]["postMarket"][0] = {
        "start": "2026-11-27T13:00:00-05:00",
        "end": "2026-11-27T17:00:00-05:00",
    }
    payload["option"]["EQO"]["sessionHours"]["regularMarket"][0]["end"] = (
        "2026-11-27T13:00:00-05:00"
    )
    payload["option"]["IND"]["sessionHours"]["regularMarket"][0]["end"] = (
        "2026-11-27T13:15:00-05:00"
    )
    return payload


class SchwabMarketHoursResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normal = market_hours_from_payload(
            normal_payload(),
            expected_date=date(2026, 8, 31),
        )
        self.closed = market_hours_from_payload(
            closed_payload(),
            expected_date=date(2026, 9, 7),
        )
        self.shortened = market_hours_from_payload(
            shortened_payload(),
            expected_date=date(2026, 11, 27),
        )
        self.retrieved_at = datetime(2026, 8, 28, 15, 25, tzinfo=UTC)
        self.valid_until = datetime(2026, 11, 28, 5, 0, tzinfo=UTC)

    def schedule(self, response, digest_character: str) -> SchwabScheduleEvidence:
        return SchwabScheduleEvidence(
            response=response,
            raw_path=(
                "data/raw/schwab/external/test-bundle/"
                f"market-hours-{response.market_date.isoformat()}.json"
            ),
            raw_sha256=digest_character * 64,
            retrieved_at=self.retrieved_at,
            valid_until=self.valid_until,
        )

    def evidence(self, **changes) -> SchwabCombinedScheduleEvidence:
        schedules = (
            self.schedule(self.normal, "a"),
            self.schedule(self.closed, "b"),
            self.schedule(self.shortened, "c"),
        )
        base = SchwabCombinedScheduleEvidence(
            normal_reference_date=date(2026, 8, 31),
            schedules=schedules,
            manifest_raw_path=MANIFEST_PATH,
            manifest_raw_sha256="f" * 64,
            manifest_member_sha256s=("a" * 64, "b" * 64, "c" * 64),
            provider_source_version="Schwab Market Data Production 1.0.0",
        )
        return replace(base, **changes)

    def quote(
        self,
        *,
        provider_quote_at: datetime,
        asset_class: str = "stock",
        provider: str = "schwab",
        connection_uid: str = CONNECTION_UID,
        data_mode: str = "real_time",
    ) -> NormalizedQuote:
        if asset_class == "stock":
            instrument_key = "stock|AAPL"
            provider_instrument_id = "AAPL"
        else:
            instrument_key = "option|AAPL|2026-09-18|call|315"
            provider_instrument_id = "AAPL  260918C00315000"
        base = NormalizedQuote(
            quote_uid="pending",
            provider=provider,
            connection_uid=connection_uid,
            instrument_key=instrument_key,
            provider_instrument_id=provider_instrument_id,
            symbol=provider_instrument_id,
            asset_class=asset_class,
            currency="USD",
            bid=Decimal("1.00"),
            ask=Decimal("1.10"),
            last=Decimal("1.05"),
            provider_quote_at=provider_quote_at,
            received_at=provider_quote_at + timedelta(milliseconds=200),
            market_session="unknown",
            data_mode=data_mode,
            entitlement_status="entitled",
            asof=provider_quote_at.astimezone().date(),
            raw_path=f"data/raw/{provider}/external/test-bundle/quote.json",
            raw_sha256="d" * 64,
            adapter_version="schwab-quote-json-v1",
        )
        # Every test timestamp is already expressed in the approved New York
        # offset, so its local date is the quote market date.
        base = replace(base, asof=provider_quote_at.date())
        return replace(base, quote_uid=build_quote_uid(base))

    def resolver(self, *, scope=SCHWAB_EQUITY_SCOPE, evidence=None):
        return SchwabMarketHoursResolver(
            connection_uid=CONNECTION_UID,
            scope=scope,
            evidence=evidence or self.evidence(),
        )

    def test_regular_schedule_resolves_with_combined_manifest_lineage(self) -> None:
        quote = self.quote(
            provider_quote_at=datetime.fromisoformat("2026-08-31T10:00:00-04:00")
        )
        evaluated_at = datetime.fromisoformat("2026-08-31T10:00:30-04:00")

        authority = resolve_provider_session_authority(
            self.resolver(),
            quote=quote,
            evaluated_at=evaluated_at,
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(authority.schedule_scope_id, "schwab:market-hours:equity:EQ")
        self.assertEqual(authority.venue_timezone, "America/New_York")
        self.assertEqual(authority.source_response_type, "combined")
        self.assertEqual(authority.raw_path, MANIFEST_PATH)
        self.assertEqual(authority.raw_sha256, "f" * 64)
        self.assertEqual(authority.quote_trading_day_kind, "regular")
        self.assertEqual(assessment.status, "live_fresh")
        self.assertTrue(assessment.valuation_allowed)

    def test_shortened_schedule_classifies_early_close_and_exact_phases(self) -> None:
        quote = self.quote(
            provider_quote_at=datetime.fromisoformat("2026-11-27T12:59:30-05:00")
        )
        evaluated_at = datetime.fromisoformat("2026-11-27T13:00:30-05:00")

        authority = self.resolver().resolve(
            quote=quote,
            evaluated_at=evaluated_at,
        )

        self.assertEqual(authority.quote_trading_day_kind, "early_close")
        self.assertEqual(authority.evaluation_trading_day_kind, "early_close")
        self.assertEqual(authority.quote_market_session, "regular")
        self.assertEqual(authority.evaluation_market_session, "after_hours")
        self.assertEqual(
            authority.quote_phase_ends_at,
            datetime.fromisoformat("2026-11-27T13:00:00-05:00"),
        )

    def test_listed_option_is_closed_after_shortened_regular_phase(self) -> None:
        quote = self.quote(
            provider_quote_at=datetime.fromisoformat("2026-11-27T12:59:30-05:00"),
            asset_class="option",
        )
        evaluated_at = datetime.fromisoformat("2026-11-27T13:00:30-05:00")

        authority = self.resolver(scope=SCHWAB_EQUITY_OPTION_SCOPE).resolve(
            quote=quote,
            evaluated_at=evaluated_at,
        )

        self.assertEqual(authority.quote_trading_day_kind, "early_close")
        self.assertEqual(authority.evaluation_market_session, "closed")

    def test_provider_closed_sentinel_remains_closed_unspecified(self) -> None:
        quote = self.quote(
            provider_quote_at=datetime.fromisoformat("2026-09-07T10:00:00-04:00")
        )
        evaluated_at = datetime.fromisoformat("2026-09-07T10:00:30-04:00")

        authority = self.resolver().resolve(
            quote=quote,
            evaluated_at=evaluated_at,
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=evaluated_at,
            session_authority=authority,
        )

        self.assertEqual(authority.quote_market_session, "closed")
        self.assertEqual(authority.quote_trading_day_kind, "closed_unspecified")
        self.assertEqual(authority.evaluation_trading_day_kind, "closed_unspecified")
        self.assertEqual(assessment.status, "market_closed_last")

    def test_frozen_security_quote_requires_effective_market_close(self) -> None:
        quote = self.quote(
            provider_quote_at=datetime.fromisoformat("2026-08-31T19:59:30-04:00"),
            data_mode="frozen",
        )

        open_evaluation = datetime.fromisoformat("2026-08-31T19:59:31-04:00")
        open_authority = self.resolver().resolve(
            quote=quote,
            evaluated_at=open_evaluation,
        )
        open_assessment = assess_quote_freshness(
            quote,
            evaluated_at=open_evaluation,
            session_authority=open_authority,
        )

        closed_evaluation = datetime.fromisoformat("2026-08-31T20:00:30-04:00")
        closed_authority = self.resolver().resolve(
            quote=quote,
            evaluated_at=closed_evaluation,
        )
        closed_assessment = assess_quote_freshness(
            quote,
            evaluated_at=closed_evaluation,
            session_authority=closed_authority,
        )

        self.assertEqual(open_authority.evaluation_market_session, "after_hours")
        self.assertEqual(open_assessment.status, "live_stale")
        self.assertFalse(open_assessment.valuation_allowed)
        self.assertEqual(closed_authority.evaluation_market_session, "closed")
        self.assertEqual(closed_assessment.status, "market_closed_last")
        self.assertTrue(closed_assessment.valuation_allowed)

    def test_offset_must_match_approved_iana_scope(self) -> None:
        payload = normal_payload()
        for products in payload.values():
            for item in products.values():
                for intervals in item["sessionHours"].values():
                    for interval in intervals:
                        interval["start"] = interval["start"].replace(
                            "-04:00", "-05:00"
                        )
                        interval["end"] = interval["end"].replace(
                            "-04:00", "-05:00"
                        )
        wrong_offset = market_hours_from_payload(payload, expected_date=date(2026, 8, 31))
        schedules = list(self.evidence().schedules)
        schedules[0] = self.schedule(wrong_offset, "a")

        with self.assertRaisesRegex(
            SchwabMarketHoursResolverError,
            "offset conflicts",
        ):
            self.resolver(evidence=self.evidence(schedules=tuple(schedules)))

        unapproved_scope = replace(
            SCHWAB_EQUITY_SCOPE,
            venue_timezone="UTC",
        )
        with self.assertRaisesRegex(
            SchwabMarketHoursResolverError,
            "not an approved exact mapping",
        ):
            self.resolver(scope=unapproved_scope)

    def test_unsupported_open_schedule_variation_fails_closed(self) -> None:
        payload = shortened_payload()
        payload["equity"]["EQ"]["sessionHours"]["preMarket"][0]["start"] = (
            "2026-11-27T08:00:00-05:00"
        )
        unsupported = market_hours_from_payload(
            payload,
            expected_date=date(2026, 11, 27),
        )
        schedules = list(self.evidence().schedules)
        schedules[2] = self.schedule(unsupported, "c")
        quote = self.quote(
            provider_quote_at=datetime.fromisoformat("2026-11-27T12:00:00-05:00")
        )

        with self.assertRaisesRegex(
            SchwabMarketHoursResolverError,
            "unsupported way",
        ):
            self.resolver(evidence=self.evidence(schedules=tuple(schedules))).resolve(
                quote=quote,
                evaluated_at=datetime.fromisoformat("2026-11-27T12:00:30-05:00"),
            )

    def test_manifest_membership_and_lineage_fail_closed(self) -> None:
        invalid = (
            self.evidence(manifest_member_sha256s=("a" * 64, "b" * 64)),
            self.evidence(manifest_raw_path="data/raw/ibkr/manifest.json"),
            self.evidence(manifest_raw_sha256="not-a-digest"),
        )
        for evidence in invalid:
            with self.subTest(evidence=evidence):
                with self.assertRaises(SchwabMarketHoursResolverError):
                    self.resolver(evidence=evidence)

    def test_missing_same_date_schedule_fails_closed(self) -> None:
        quote = self.quote(
            provider_quote_at=datetime.fromisoformat("2026-08-28T11:25:00-04:00")
        )
        with self.assertRaisesRegex(
            SchwabMarketHoursResolverError,
            "no exact Schwab schedule",
        ):
            self.resolver().resolve(
                quote=quote,
                evaluated_at=datetime.fromisoformat("2026-08-28T11:25:30-04:00"),
            )

    def test_provider_connection_asset_and_validity_mismatch_fail_closed(self) -> None:
        timestamp = datetime.fromisoformat("2026-08-31T10:00:00-04:00")
        cases = (
            self.quote(provider_quote_at=timestamp, provider="ibkr"),
            self.quote(provider_quote_at=timestamp, connection_uid="other"),
            self.quote(provider_quote_at=timestamp, asset_class="option"),
        )
        for quote in cases:
            with self.subTest(quote=quote):
                with self.assertRaises(SchwabMarketHoursResolverError):
                    self.resolver().resolve(
                        quote=quote,
                        evaluated_at=timestamp + timedelta(seconds=30),
                    )

        expired = tuple(
            replace(item, valid_until=self.retrieved_at + timedelta(seconds=1))
            for item in self.evidence().schedules
        )
        quote = self.quote(provider_quote_at=timestamp)
        with self.assertRaisesRegex(
            SchwabMarketHoursResolverError,
            "not valid",
        ):
            self.resolver(evidence=self.evidence(schedules=expired)).resolve(
                quote=quote,
                evaluated_at=timestamp + timedelta(seconds=30),
            )


if __name__ == "__main__":
    unittest.main()
