from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest

from onejournal.brokers.normalized import NormalizedFill
from onejournal.instruments import InstrumentIdentity, InstrumentIdentityError


class InstrumentIdentityContractTests(unittest.TestCase):
    def test_equity_key_is_versioned_and_normalized(self) -> None:
        identity = InstrumentIdentity(
            asset_class="equity", market_scope="us", currency="usd", symbol="aapl"
        )
        self.assertEqual(identity.key, "instrument.v1|equity|US|USD|AAPL")

    def test_option_key_uses_contract_terms_not_provider_option_symbol(self) -> None:
        compact = InstrumentIdentity(
            asset_class="option", market_scope="US", currency="USD",
            underlying_symbol="AAPL", expiry=date(2026, 1, 16), option_right="call",
            strike=Decimal("200"), multiplier=Decimal("100"),
        )
        scaled = InstrumentIdentity(
            asset_class="option", market_scope="US", currency="USD",
            underlying_symbol="AAPL", expiry=date(2026, 1, 16), option_right="CALL",
            strike=Decimal("200.0000"), multiplier=Decimal("100.0000"),
        )
        self.assertEqual(compact.key, scaled.key)
        self.assertEqual(
            compact.key,
            "instrument.v1|option|US|USD|AAPL|2026-01-16|CALL|200|100",
        )

    def test_option_missing_contract_term_fails_closed(self) -> None:
        with self.assertRaisesRegex(InstrumentIdentityError, "strike and multiplier"):
            InstrumentIdentity(
                asset_class="option", market_scope="US", currency="USD",
                underlying_symbol="AAPL", expiry=date(2026, 1, 16), option_right="CALL",
                strike=Decimal("200"),
            )

    def test_fill_conversion_excludes_provider_option_symbol(self) -> None:
        fill = NormalizedFill(
            fill_uid="fill-1", source_broker="schwab", source_account_id="acct",
            source_fill_id="source-1", source_order_id=None, episode_group_id=None,
            asof=date(2026, 1, 2), filled_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            asset_class="option", symbol="AAPL  260116C00200000", side="BUY_TO_OPEN",
            quantity=Decimal("1"), fill_price=Decimal("2"), commission=Decimal("0"),
            fees=Decimal("0"), currency="USD", fetched_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            option_symbol="AAPL  260116C00200000", underlying_symbol="AAPL",
            option_type="CALL", expiry=date(2026, 1, 16), strike=Decimal("200"),
            multiplier=Decimal("100"),
        )
        self.assertEqual(
            InstrumentIdentity.from_fill(fill).key,
            "instrument.v1|option|US|USD|AAPL|2026-01-16|CALL|200|100",
        )
