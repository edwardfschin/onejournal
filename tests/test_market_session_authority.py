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


class LegacyMarketSessionAuthorityTests(unittest.TestCase):
    """The v1 value remains reproducible but cannot qualify provider quotes."""

    EVALUATED_AT = datetime(2026, 8, 11, 14, 30, 30, tzinfo=UTC)

    def _quote(self) -> NormalizedQuote:
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
        return replace(base, quote_uid=build_quote_uid(base))

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

    def test_v1_identity_and_validation_remain_deterministic(self) -> None:
        first = self._authority()
        second = self._authority()
        changed = self._authority(source_version="2026.08.12")

        validate_market_session_authority(first)
        self.assertEqual(first.authority_uid, second.authority_uid)
        self.assertNotEqual(first.authority_uid, changed.authority_uid)

    def test_v1_invalid_identity_is_still_rejected(self) -> None:
        authority = replace(
            self._authority(),
            authority_uid="session-authority:" + "0" * 64,
        )
        with self.assertRaises(SessionAuthorityError):
            validate_market_session_authority(authority)

    def test_v1_cannot_qualify_a_provider_quote(self) -> None:
        with self.assertRaisesRegex(
            SessionAuthorityError,
            "legacy or unsupported",
        ):
            assess_quote_freshness(
                self._quote(),
                evaluated_at=self.EVALUATED_AT,
                session_authority=self._authority(),  # type: ignore[arg-type]
            )


if __name__ == "__main__":
    unittest.main()
