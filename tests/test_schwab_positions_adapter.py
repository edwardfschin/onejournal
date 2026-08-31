from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import ast
import json
from pathlib import Path
import unittest

from onejournal.brokers.schwab.positions_json import (
    ADAPTER_VERSION,
    SchwabPositionAdapterError,
    SchwabPositionCaptureContext,
    SchwabPositionMapping,
    broker_position_snapshot_from_bytes,
)
from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.position_reconciliation import (
    CanonicalPositionQuantity,
    reconcile_account_positions,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_DIR / "src/onejournal/brokers/schwab/positions_json.py"


class SchwabPositionsAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.retrieved_at = datetime(2026, 8, 31, 14, 30, tzinfo=UTC)
        self.account_hash = "synthetic-account-hash"
        self.identity = InstrumentIdentity(
            asset_class="equity", market_scope="US", currency="USD", symbol="AAPL"
        )
        self.payload = {
            "securitiesAccount": {
                "accountNumber": "SYNTHETIC-ACCOUNT",
                "positions": [
                    {
                        "shortQuantity": 0,
                        "averagePrice": Decimal("100.25"),
                        "currentDayProfitLoss": Decimal("1.25"),
                        "currentDayProfitLossPercentage": Decimal("0.10"),
                        "longQuantity": Decimal("10"),
                        "settledLongQuantity": Decimal("10"),
                        "settledShortQuantity": 0,
                        "instrument": {"assetType": "EQUITY", "symbol": "AAPL"},
                        "marketValue": Decimal("1100"),
                        "maintenanceRequirement": Decimal("0"),
                        "longOpenProfitLoss": Decimal("97.50"),
                        "shortOpenProfitLoss": 0,
                    }
                ],
            }
        }

    def body(self, payload=None) -> bytes:
        return json.dumps(
            self.payload if payload is None else payload,
            default=lambda value: float(value) if isinstance(value, Decimal) else value,
            separators=(",", ":"),
        ).encode()

    def context(self, body: bytes, **changes) -> SchwabPositionCaptureContext:
        values = {
            "request_url": (
                "https://api.schwabapi.com/trader/v1/accounts/"
                f"{self.account_hash}?fields=positions"
            ),
            "provider_account_hash_sha256": sha256(self.account_hash.encode()).hexdigest(),
            "provider_account_number": "SYNTHETIC-ACCOUNT",
            "connection_uid": "local-schwab-primary",
            "source_account_id": "onejournal-account-1",
            "asof": date(2026, 8, 31),
            "retrieved_at": self.retrieved_at,
            "raw_path": "private/pnl03/positions.json",
            "raw_sha256": sha256(body).hexdigest(),
        }
        values.update(changes)
        return SchwabPositionCaptureContext(**values)

    def mapping(self) -> SchwabPositionMapping:
        return SchwabPositionMapping("AAPL", self.identity)

    def snapshot(self, payload=None, mappings=None, **context_changes):
        body = self.body(payload)
        return broker_position_snapshot_from_bytes(
            body,
            context=self.context(body, **context_changes),
            mappings=(self.mapping(),) if mappings is None else mappings,
        )

    def test_complete_equity_snapshot_preserves_exact_values_and_lineage(self) -> None:
        snapshot = self.snapshot()
        self.assertTrue(snapshot.account_complete)
        self.assertEqual(snapshot.adapter_version, ADAPTER_VERSION)
        self.assertEqual(snapshot.source_broker, "schwab")
        self.assertEqual(snapshot.source_account_id, "onejournal-account-1")
        self.assertTrue(snapshot.snapshot_uid.startswith("broker-position-snapshot:"))
        (position,) = snapshot.positions
        self.assertEqual(position.identity, self.identity)
        self.assertEqual(position.quantity, Decimal("10"))
        self.assertEqual(position.broker_average_cost, Decimal("100.25"))
        self.assertEqual(position.broker_market_value, Decimal("1100"))
        self.assertEqual(position.broker_unrealized_pnl, Decimal("97.50"))

        canonical = CanonicalPositionQuantity(
            "schwab", "local-schwab-primary", "onejournal-account-1",
            self.identity, Decimal("10"), date(2026, 8, 31), self.retrieved_at,
            "fifo.v1",
        )
        (reconciliation,) = reconcile_account_positions(
            (canonical,), snapshot, evaluated_at=self.retrieved_at,
            max_snapshot_age_seconds=0,
        )
        self.assertEqual(reconciliation.status, "valid")

    def test_short_option_requires_and_preserves_explicit_contract_identity(self) -> None:
        provider_symbol = "AAPL  260918P00200000"
        identity = InstrumentIdentity(
            asset_class="option", market_scope="US", currency="USD",
            underlying_symbol="AAPL", expiry=date(2026, 9, 18),
            option_right="PUT", strike=Decimal("200"), multiplier=Decimal("100"),
        )
        payload = {
            "securitiesAccount": {
                "accountNumber": "SYNTHETIC-ACCOUNT",
                "positions": [{
                    "longQuantity": 0,
                    "shortQuantity": Decimal("2"),
                    "averagePrice": Decimal("3.5"),
                    "marketValue": Decimal("-640"),
                    "longOpenProfitLoss": 0,
                    "shortOpenProfitLoss": Decimal("60"),
                    "instrument": {
                        "assetType": "OPTION", "symbol": provider_symbol,
                        "uniformSymbol": provider_symbol,
                        "underlyingSymbol": "AAPL", "putCall": "PUT",
                    },
                }],
            }
        }
        snapshot = self.snapshot(
            payload=payload, mappings=(SchwabPositionMapping(provider_symbol, identity),)
        )
        (position,) = snapshot.positions
        self.assertEqual(position.identity, identity)
        self.assertEqual(position.quantity, Decimal("-2"))
        self.assertEqual(position.broker_unrealized_pnl, Decimal("60"))

    def test_collective_investment_etf_maps_only_to_explicit_equity_identity(self) -> None:
        payload = json.loads(self.body(), parse_float=Decimal)
        payload["securitiesAccount"]["positions"][0]["instrument"] = {
            "assetType": "COLLECTIVE_INVESTMENT",
            "type": "EXCHANGE_TRADED_FUND",
            "symbol": "SPY",
            "uniformSymbol": "SPY",
        }
        identity = InstrumentIdentity(
            asset_class="equity", market_scope="US", currency="USD", symbol="SPY"
        )
        snapshot = self.snapshot(
            payload=payload,
            mappings=(SchwabPositionMapping("SPY", identity),),
        )
        self.assertEqual(snapshot.positions[0].identity, identity)

    def test_other_collective_investments_and_ambiguous_etfs_fail_closed(self) -> None:
        for collective_type in (
            None,
            "MUTUAL_FUND",
            "MONEY_MARKET_FUND",
            "exchange_traded_fund",
            " EXCHANGE_TRADED_FUND ",
        ):
            payload = json.loads(self.body(), parse_float=Decimal)
            instrument = payload["securitiesAccount"]["positions"][0]["instrument"]
            instrument["assetType"] = "COLLECTIVE_INVESTMENT"
            if collective_type is not None:
                instrument["type"] = collective_type
            with self.subTest(collective_type=collective_type), self.assertRaisesRegex(
                SchwabPositionAdapterError, "asset-class"
            ):
                self.snapshot(payload=payload)

        option_identity = InstrumentIdentity(
            asset_class="option", market_scope="US", currency="USD",
            underlying_symbol="AAPL", expiry=date(2026, 9, 18),
            option_right="PUT", strike=Decimal("200"), multiplier=Decimal("100"),
        )
        payload = json.loads(self.body(), parse_float=Decimal)
        instrument = payload["securitiesAccount"]["positions"][0]["instrument"]
        instrument.update({
            "assetType": "COLLECTIVE_INVESTMENT",
            "type": "EXCHANGE_TRADED_FUND",
            "symbol": "AAPL  260918P00200000",
        })
        with self.assertRaisesRegex(SchwabPositionAdapterError, "asset-class"):
            self.snapshot(
                payload=payload,
                mappings=(
                    SchwabPositionMapping("AAPL  260918P00200000", option_identity),
                ),
            )

    def test_occ_symbol_is_required_and_must_match_every_explicit_option_term(self) -> None:
        provider_symbol = "AAPL  260918P00200000"
        identity = InstrumentIdentity(
            asset_class="option", market_scope="US", currency="USD",
            underlying_symbol="AAPL", expiry=date(2026, 9, 18),
            option_right="PUT", strike=Decimal("200"), multiplier=Decimal("100"),
        )

        def payload_for(symbol: str = provider_symbol):
            return {
                "securitiesAccount": {
                    "accountNumber": "SYNTHETIC-ACCOUNT",
                    "positions": [{
                        "longQuantity": 1,
                        "shortQuantity": 0,
                        "instrument": {
                            "assetType": "OPTION",
                            "symbol": symbol,
                            "uniformSymbol": symbol,
                            "underlyingSymbol": "AAPL",
                            "putCall": "PUT",
                        },
                    }],
                }
            }

        cases = (
            ("AAPL260918P00200000", identity, "21-character OCC"),
            ("aapl  260918p00200000", identity, "21-character OCC"),
            (" AAPL  260918P00200000 ", identity, "exact OCC"),
            ("AAPL  261332P00200000", identity, "OCC expiry"),
            (
                provider_symbol,
                replace(identity, underlying_symbol="MSFT"),
                "underlying mapping",
            ),
            (
                provider_symbol,
                replace(identity, expiry=date(2026, 9, 19)),
                "expiry mapping",
            ),
            (
                provider_symbol,
                replace(identity, option_right="CALL"),
                "option-right mapping",
            ),
            (
                provider_symbol,
                replace(identity, strike=Decimal("201")),
                "strike mapping",
            ),
        )
        for symbol, mapped_identity, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(
                SchwabPositionAdapterError, message
            ):
                self.snapshot(
                    payload=payload_for(symbol),
                    mappings=(SchwabPositionMapping(symbol, mapped_identity),),
                )

        explicit_conflicts = (
            ({"expirationDate": "2026-09-19"}, "expiry mapping"),
            ({"strikePrice": Decimal("201")}, "strike mapping"),
            ({"uniformSymbol": "AAPL  260918C00200000"}, "uniformSymbol"),
        )
        for fields, message in explicit_conflicts:
            payload = payload_for()
            payload["securitiesAccount"]["positions"][0]["instrument"].update(fields)
            with self.subTest(message=message), self.assertRaisesRegex(
                SchwabPositionAdapterError, message
            ):
                self.snapshot(
                    payload=payload,
                    mappings=(SchwabPositionMapping(provider_symbol, identity),),
                )

    def test_explicit_empty_positions_list_is_a_complete_empty_account(self) -> None:
        payload = {
            "securitiesAccount": {
                "accountNumber": "SYNTHETIC-ACCOUNT", "positions": []
            }
        }
        snapshot = self.snapshot(payload=payload, mappings=())
        self.assertTrue(snapshot.account_complete)
        self.assertEqual(snapshot.positions, ())

    def test_missing_positions_or_mapping_scope_mismatch_fails_closed(self) -> None:
        payload = {"securitiesAccount": {"accountNumber": "SYNTHETIC-ACCOUNT"}}
        with self.assertRaisesRegex(SchwabPositionAdapterError, "explicit complete list"):
            self.snapshot(payload=payload)
        with self.assertRaisesRegex(SchwabPositionAdapterError, "scope mismatch"):
            self.snapshot(mappings=())
        with self.assertRaisesRegex(SchwabPositionAdapterError, "scope mismatch"):
            self.snapshot(
                mappings=(
                    self.mapping(),
                    SchwabPositionMapping(
                        "MSFT",
                        InstrumentIdentity(
                            asset_class="equity", market_scope="US", currency="USD",
                            symbol="MSFT",
                        ),
                    ),
                )
            )

    def test_account_endpoint_hash_query_response_and_checksum_are_bound(self) -> None:
        body = self.body()
        invalid_contexts = (
            {"request_url": "https://example.invalid/trader/v1/accounts/x?fields=positions"},
            {"request_url": f"https://api.schwabapi.com/trader/v1/accounts/{self.account_hash}?fields=orders"},
            {"provider_account_hash_sha256": "f" * 64},
            {"provider_account_number": "OTHER-ACCOUNT"},
            {"status_code": 206},
            {"attempt_count": 2},
            {"redirect_count": 1},
            {"raw_sha256": "f" * 64},
        )
        for changes in invalid_contexts:
            with self.subTest(changes=changes), self.assertRaises(
                SchwabPositionAdapterError
            ):
                broker_position_snapshot_from_bytes(
                    body, context=self.context(body, **changes),
                    mappings=(self.mapping(),),
                )

    def test_quantity_decimal_and_identity_ambiguity_fail_closed(self) -> None:
        mutations = []
        both_directions = json.loads(self.body(), parse_float=Decimal)
        both_directions["securitiesAccount"]["positions"][0]["shortQuantity"] = 1
        mutations.append((both_directions, "simultaneous"))
        zero = json.loads(self.body(), parse_float=Decimal)
        zero["securitiesAccount"]["positions"][0]["longQuantity"] = 0
        mutations.append((zero, "non-zero"))
        string_value = json.loads(self.body(), parse_float=Decimal)
        string_value["securitiesAccount"]["positions"][0]["longQuantity"] = "10.0"
        mutations.append((string_value, "exact JSON decimal"))
        wrong_asset = json.loads(self.body(), parse_float=Decimal)
        wrong_asset["securitiesAccount"]["positions"][0]["instrument"]["assetType"] = "OPTION"
        mutations.append((wrong_asset, "asset-class"))
        for payload, message in mutations:
            with self.subTest(message=message), self.assertRaisesRegex(
                SchwabPositionAdapterError, message
            ):
                self.snapshot(payload=payload)

    def test_module_has_no_provider_credential_database_or_process_capability(self) -> None:
        tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertTrue(
            {"requests", "httpx", "urllib3", "socket", "subprocess", "duckdb", "keyring"}.isdisjoint(imported)
        )


if __name__ == "__main__":
    unittest.main()
