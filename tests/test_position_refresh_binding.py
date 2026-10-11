from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
import json
import unittest

import test_external_schwab_position_acquisition as position_fixture
from test_current_position_lifecycle_coverage import fill_row, window

from onejournal.brokers.schwab.position_binding import (
    SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA,
    SchwabPositionPrivateBinding,
    schwab_position_private_binding_bytes,
)
from onejournal.brokers.schwab.positions_json import SchwabPositionMapping
from onejournal.instruments import InstrumentIdentity
from onejournal.provider_connectors.lifecycle_coverage import (
    CurrentPositionCoverageTarget,
    assemble_current_position_lifecycle_coverage,
    calculate_lifecycle_coverage_sha256,
)
from onejournal.provider_connectors.position_refresh import (
    PositionRefreshBindingError,
    prepare_position_refresh_binding,
)


class PositionRefreshBindingTests(unittest.TestCase):
    def setUp(self):
        self.case = position_fixture.ExternalSchwabPositionAcquisitionTests()
        self.case.setUp()
        self.acquisition = self.case.load()
        self.baseline = SchwabPositionPrivateBinding(
            SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA,
            position_fixture.CONNECTION_UID, position_fixture.SOURCE_ACCOUNT_ID,
            position_fixture.PROVIDER_ACCOUNT_HASH, position_fixture.PROVIDER_ACCOUNT_NUMBER,
            self.case.mappings(),
        )

    def coverage(self, *, currency="USD", with_fill=True, missing_order=False):
        row = fill_row(fill_id="synthetic-transaction-1", order_id="" if missing_order else "synthetic-order-1",
                       filled_at="2026-08-31T13:00:00Z", quantity="10", currency=currency)
        row["source_account_id"] = position_fixture.SOURCE_ACCOUNT_ID
        orders = (dict(row, source_fill_id="synthetic-order-fill-1"),) if with_fill and not missing_order else ()
        evidence = replace(window(digest_char="a", start=date(2026, 8, 31), end=date(2026, 8, 31),
                                  orders=orders, transactions=(row,) if with_fill else ()),
                           connection_uid=position_fixture.CONNECTION_UID,
                           source_account_id=position_fixture.SOURCE_ACCOUNT_ID)
        return assemble_current_position_lifecycle_coverage(
            (evidence,), (CurrentPositionCoverageTarget("AAPL", "equity", Decimal("10")),),
            evaluated_at=self.case.received_at,
        )

    def retired_baseline(self):
        return replace(self.baseline, mappings=(SchwabPositionMapping(
            "MSFT", InstrumentIdentity(asset_class="equity", market_scope="US", currency="USD", symbol="MSFT")
        ),))

    @staticmethod
    def fingerprint(coverage):
        return replace(coverage, assembly_sha256=calculate_lifecycle_coverage_sha256(coverage))

    def test_new_transaction_identity_retires_old_mapping_and_validates_snapshot(self):
        coverage = self.coverage()
        first = prepare_position_refresh_binding(self.acquisition, self.retired_baseline(), coverage)
        replay = prepare_position_refresh_binding(self.acquisition, self.retired_baseline(), coverage)
        self.assertEqual(first, replay)
        self.assertEqual((first.reused_mapping_count, first.new_mapping_count, first.retired_mapping_count), (0, 1, 1))
        self.assertEqual(first.binding.mappings, self.case.mappings())
        self.assertTrue(first.position.snapshot.account_complete)
        self.assertEqual(first.position.snapshot.retrieved_at, coverage.evaluated_at)
        self.assertEqual(first.binding.provider_account_hash, self.baseline.provider_account_hash)
        self.assertEqual(schwab_position_private_binding_bytes(first.binding), schwab_position_private_binding_bytes(self.baseline))

    def test_retained_mapping_without_fill_does_not_become_financially_eligible(self):
        coverage = self.coverage(with_fill=False)
        result = prepare_position_refresh_binding(self.acquisition, self.baseline, coverage)
        self.assertEqual(result.reused_mapping_count, 1)
        self.assertEqual(coverage.positions[0].status, "history_extension_required")
        self.assertFalse(result.privacy_safe_audit()["financial_acceptance"])

    def test_option_multiplier_comes_from_transaction_not_a_standard_default(self):
        symbol = "AAPL  261016C00200000"
        document = json.loads(self.case.body)
        position = document["securitiesAccount"]["positions"][0]
        position["longQuantity"] = 1
        position["instrument"] = {"assetType": "OPTION", "symbol": symbol,
                                  "underlyingSymbol": "AAPL", "putCall": "CALL"}
        self.case.body = json.dumps(document).encode()
        self.case.request = replace(self.case.request, response_byte_count=len(self.case.body),
                                    response_sha256=sha256(self.case.body).hexdigest())
        acquisition = self.case.load(manifest=self.case.make_manifest(), body=self.case.body)
        row = fill_row(fill_id="synthetic-option-fill", order_id="synthetic-option-order",
                       filled_at="2026-08-31T13:00:00Z", symbol=symbol,
                       asset_class="option", multiplier="50")
        row.update(source_account_id=position_fixture.SOURCE_ACCOUNT_ID, expiry="2026-10-16")
        evidence = replace(window(digest_char="c", start=date(2026, 8, 31), end=date(2026, 8, 31),
                                  orders=(dict(row, source_fill_id="synthetic-option-order-fill"),),
                                  transactions=(row,)),
                           connection_uid=position_fixture.CONNECTION_UID,
                           source_account_id=position_fixture.SOURCE_ACCOUNT_ID)
        coverage = assemble_current_position_lifecycle_coverage(
            (evidence,), (CurrentPositionCoverageTarget(symbol, "option", Decimal("1")),),
            evaluated_at=self.case.received_at)
        result = prepare_position_refresh_binding(acquisition, self.retired_baseline(), coverage)
        self.assertEqual(result.binding.mappings[0].identity.multiplier, Decimal("50"))
        self.assertEqual(result.binding.mappings[0].identity.currency, "USD")

    def test_new_mapping_requires_transaction_identity_and_explicit_currency(self):
        with self.assertRaisesRegex(PositionRefreshBindingError, "lacks transaction"):
            prepare_position_refresh_binding(self.acquisition, self.retired_baseline(), self.coverage(with_fill=False))
        with self.assertRaisesRegex(PositionRefreshBindingError, "retained identity conflicts"):
            prepare_position_refresh_binding(self.acquisition, self.baseline, self.coverage(currency="EUR"))

    def test_derived_identity_cannot_be_changed_without_accounting_proof(self):
        coverage = self.coverage()
        forged = replace(coverage.positions[0], identity=InstrumentIdentity(
            asset_class="equity", market_scope="US", currency="EUR", symbol="AAPL"))
        changed = replace(coverage, positions=(forged,))
        self.assertEqual(calculate_lifecycle_coverage_sha256(changed), coverage.assembly_sha256)
        with self.assertRaisesRegex(PositionRefreshBindingError, "differs from transaction"):
            prepare_position_refresh_binding(self.acquisition, self.retired_baseline(), changed)

    def test_scope_cutoff_and_fingerprint_fail_closed(self):
        coverage = self.coverage()
        for invalid in (
            self.fingerprint(replace(coverage, connection_uid="connection:schwab:other-0001")),
            self.fingerprint(replace(coverage, source_account_id="account:other:0001")),
            self.fingerprint(replace(coverage, evaluated_at=coverage.evaluated_at + timedelta(seconds=1))),
            replace(coverage, assembly_sha256="b" * 64),
        ):
            with self.assertRaises(PositionRefreshBindingError):
                prepare_position_refresh_binding(self.acquisition, self.baseline, invalid)

    def test_coverage_quantity_and_membership_must_equal_the_snapshot(self):
        coverage = self.coverage()
        wrong_quantity = replace(coverage.positions[0], broker_quantity=Decimal("20"))
        with self.assertRaisesRegex(PositionRefreshBindingError, "target differs"):
            prepare_position_refresh_binding(self.acquisition, self.baseline,
                self.fingerprint(replace(coverage, positions=(wrong_quantity,))))
        with self.assertRaisesRegex(PositionRefreshBindingError, "membership"):
            prepare_position_refresh_binding(self.acquisition, self.baseline,
                self.fingerprint(replace(coverage, positions=())))

    def test_missing_order_reference_stays_unresolved_after_identity_preparation(self):
        coverage = self.coverage(missing_order=True)
        result = prepare_position_refresh_binding(self.acquisition, self.retired_baseline(), coverage)
        self.assertEqual(coverage.positions[0].status, "review_required")
        self.assertIn("transaction_order_id_missing", coverage.positions[0].reason_codes)
        self.assertEqual(result.coverage_sha256, coverage.assembly_sha256)
        self.assertFalse(result.privacy_safe_audit()["financial_acceptance"])

    def test_audit_never_emits_private_symbols_accounts_or_values(self):
        result = prepare_position_refresh_binding(self.acquisition, self.baseline, self.coverage())
        rendered = json.dumps(result.privacy_safe_audit())
        for private in ("AAPL", position_fixture.PROVIDER_ACCOUNT_HASH,
                        position_fixture.PROVIDER_ACCOUNT_NUMBER, position_fixture.SOURCE_ACCOUNT_ID):
            self.assertNotIn(private, rendered)


if __name__ == "__main__":
    unittest.main()
