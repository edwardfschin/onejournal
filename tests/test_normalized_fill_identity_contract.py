from __future__ import annotations

import unittest
from datetime import date, datetime
from decimal import Decimal

from onejournal.brokers.normalized import NormalizedFill
from onejournal.journal.identity import (
    build_fill_identity_key,
    build_fill_identity_signature,
    dedupe_identical_fills,
)


class NormalizedFillIdentityContractTests(unittest.TestCase):
    def _fill(
        self,
        fill_uid: str,
        *,
        source_broker: str = "manual_csv",
        source_account_id: str = "DEMO_ACCOUNT",
        source_fill_id: str = "FILL-001",
        source_order_id: str | None = None,
        filled_at: datetime | None = None,
        commission: str | Decimal = "1.00",
        fees: str | Decimal = "0.25",
    ) -> NormalizedFill:
        return NormalizedFill(
            fill_uid=fill_uid,
            source_broker=source_broker,
            source_account_id=source_account_id,
            source_fill_id=source_fill_id,
            source_order_id=source_order_id,
            episode_group_id=None,
            asof=date(2026, 6, 2),
            filled_at=filled_at or datetime(2026, 6, 2, 9, 30, 0),
            asset_class="stock",
            symbol="AAPL",
            side="BUY",
            quantity=Decimal("1"),
            fill_price=Decimal("150"),
            commission=Decimal(str(commission)),
            fees=Decimal(str(fees)),
            currency="USD",
            fetched_at=datetime(2026, 6, 2, 12, 0, 0),
            raw_path=None,
            option_symbol=None,
            underlying_symbol=None,
            option_type=None,
            expiry=None,
            strike=None,
            multiplier=None,
            open_close=None,
            execution_venue=None,
            liquidity_flag=None,
        )

    def test_build_fill_identity_key(self) -> None:
        fill = self._fill(
            fill_uid="manual_csv:DEMO_ACCOUNT:FILL-001",
            source_broker="manual_csv",
            source_account_id="DEMO_ACCOUNT",
            source_fill_id="FILL-001",
        )
        self.assertEqual(
            build_fill_identity_key(fill),
            ("manual_csv", "DEMO_ACCOUNT", "FILL-001"),
        )

    def test_identical_fill_replays_are_deduplicated(self) -> None:
        fill_a = self._fill(fill_uid="u1")
        fill_b = self._fill(fill_uid="u1")
        self.assertEqual(dedupe_identical_fills([fill_a, fill_b]), [fill_a])

    def test_conflicting_fill_replays_raise(self) -> None:
        fill_a = self._fill(fill_uid="u1", commission="1.00")
        fill_b = self._fill(fill_uid="u1", commission="2.00")
        with self.assertRaisesRegex(
            ValueError,
            "conflicting normalized fill payload for identity key",
        ):
            dedupe_identical_fills([fill_a, fill_b])

    def test_signature_ignores_fill_uid_and_raw_path(self) -> None:
        fill_a = self._fill(fill_uid="u1", source_fill_id="FILL-001")
        fill_b = self._fill(fill_uid="u2", source_fill_id="FILL-001")
        self.assertEqual(build_fill_identity_signature(fill_a), build_fill_identity_signature(fill_b))


if __name__ == "__main__":
    unittest.main()
