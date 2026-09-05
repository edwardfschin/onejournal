from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

import duckdb

from onejournal.api.pnl03_contracts import (
    Pnl03ApiContractError,
    Pnl03FinancialReleaseAuthorization,
    build_pnl03_position_valuation_response,
)
from onejournal.api.app import app
from onejournal.brokers.normalized import NormalizedQuote
from onejournal.instruments import InstrumentIdentity
from onejournal.journal.bounded_pnl03_valuation_repository import (
    load_bounded_pnl03_valuation_run,
    persist_bounded_pnl03_valuation_run,
)
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.market_data import assess_quote_freshness, build_quote_uid
from onejournal.pnl.bounded_reconciliation import (
    BoundedPnl03FifoReconciliationRun,
    BoundedPnl03PositionResult,
)
from onejournal.pnl.bounded_valuation import (
    BoundedPnl03ValuationError,
    run_bounded_pnl03_valuation,
)
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
)


class BoundedPnl03ValuationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.evaluated_at = datetime(2026, 9, 4, 14, 30, 30, tzinfo=UTC)
        self.reconciliation = self.make_reconciliation(
            eligible_count=46,
            unavailable_count=7,
            route_version="pnl-03t-replacement-2026-09-04.v2",
        )
        self.quotes = {
            item.identity: self.quote(item.identity)
            for item in self.reconciliation.positions
            if item.status == "fifo_reconciled"
        }

    def make_reconciliation(
        self,
        *,
        eligible_count: int,
        unavailable_count: int,
        route_version: str,
    ) -> BoundedPnl03FifoReconciliationRun:
        eligible = []
        unavailable = []
        for index in range(eligible_count):
            identity = InstrumentIdentity(
                asset_class="equity",
                market_scope="US",
                currency="USD",
                symbol=f"E{index:02d}",
            )
            quantity = Decimal("-1") if index == 0 else Decimal("1")
            cost = Decimal("-10") if quantity < 0 else Decimal("10")
            eligible.append(
                BoundedPnl03PositionResult(
                    identity=identity,
                    coverage_status="fill_flat_start_proven",
                    coverage_reason_codes=(),
                    broker_quantity=quantity,
                    canonical_quantity=quantity,
                    open_cost_basis=cost,
                    reconciliation_status="valid",
                    status="fifo_reconciled",
                    reason_codes=(),
                )
            )
        for index in range(unavailable_count):
            identity = InstrumentIdentity(
                asset_class="equity",
                market_scope="US",
                currency="USD",
                symbol=f"U{index:02d}",
            )
            unavailable.append(
                BoundedPnl03PositionResult(
                    identity=identity,
                    coverage_status=(
                        "history_extension_required"
                        if index < max(0, unavailable_count - 4)
                        else "review_required"
                    ),
                    coverage_reason_codes=("bounded_source_incomplete",),
                    broker_quantity=Decimal("1"),
                    canonical_quantity=None,
                    open_cost_basis=None,
                    reconciliation_status="valid",
                    status="unavailable",
                    reason_codes=("coverage_unavailable",),
                )
            )
        positions = tuple(sorted((*eligible, *unavailable), key=lambda item: item.identity.key))
        return BoundedPnl03FifoReconciliationRun(
            contract_version="onejournal.bounded-pnl03-fifo-reconciliation.v1",
            route_version=route_version,
            run_uid="bounded-pnl03-fifo-reconciliation:" + "a" * 64,
            binding_sha256="b" * 64,
            snapshot_uid="broker-position-snapshot:" + "c" * 64,
            assembly_sha256="d" * 64,
            source_broker="schwab",
            connection_uid="connection:schwab:test-owner",
            source_account_id="account:test-owner",
            asof=date(2026, 9, 4),
            evaluated_at=self.evaluated_at,
            calculation_version="fifo-v1",
            fill_fingerprint="e" * 64,
            complete_position_count=eligible_count + unavailable_count,
            eligible_count=eligible_count,
            fifo_reconciled_count=eligible_count,
            reconciliation_pending_count=0,
            unavailable_count=unavailable_count,
            positions=positions,
            eligible_cost_basis_subtotal_by_currency={
                "USD": Decimal(eligible_count - 2) * Decimal("10")
            },
            portfolio_cost_basis_by_currency=None,
            subtotal_status="eligible_subtotal",
            complete_portfolio_totals_available=False,
            financial_acceptance=False,
            final_status="eligible_fifo_reconciled",
        )
    def quote(self, identity: InstrumentIdentity, *, seconds_old: int = 10):
        base = NormalizedQuote(
            quote_uid="pending",
            provider="schwab",
            connection_uid=self.reconciliation.connection_uid,
            instrument_key=identity.key,
            provider_instrument_id=identity.symbol or "OPTION",
            symbol=identity.symbol or "OPTION",
            asset_class="stock",
            currency="USD",
            bid=Decimal("11"),
            ask=Decimal("12"),
            last=Decimal("11.5"),
            provider_quote_at=self.evaluated_at - timedelta(seconds=seconds_old),
            received_at=self.evaluated_at - timedelta(seconds=1),
            market_session="regular",
            data_mode="real_time",
            entitlement_status="entitled",
            asof=self.evaluated_at.date(),
            raw_path="data/raw/schwab/2026-09-04/quotes/batch.json",
            raw_sha256="f" * 64,
            adapter_version="schwab-quote-json-v2",
        )
        quote = replace(base, quote_uid=build_quote_uid(base))
        return quote, assess_quote_freshness(
            quote,
            evaluated_at=self.evaluated_at,
        )

    def run_gate(self, *, quotes=None):
        return run_bounded_pnl03_valuation(
            reconciliation=self.reconciliation,
            quote_evidence_sha256="1" * 64,
            quotes=self.quotes if quotes is None else quotes,
            evaluated_at=self.evaluated_at,
            max_reconciliation_age_seconds=0,
        )

    def snapshot(
        self, reconciliation: BoundedPnl03FifoReconciliationRun | None = None
    ) -> BrokerPositionSnapshot:
        reconciliation = reconciliation or self.reconciliation
        return BrokerPositionSnapshot(
            snapshot_uid=reconciliation.snapshot_uid,
            source_broker=reconciliation.source_broker,
            connection_uid=reconciliation.connection_uid,
            source_account_id=reconciliation.source_account_id,
            asof=reconciliation.asof,
            retrieved_at=reconciliation.evaluated_at,
            raw_path="private/positions.json",
            raw_sha256="9" * 64,
            account_complete=True,
            adapter_version="synthetic-position-v1",
            positions=tuple(
                BrokerPositionRecord(item.identity, item.broker_quantity)
                for item in reconciliation.positions
            ),
        )

    def test_all_eligible_marks_produce_only_eligible_subtotals(self) -> None:
        first = self.run_gate()
        replay = self.run_gate()

        self.assertEqual(first, replay)
        self.assertEqual(first.final_status, "eligible_valued")
        self.assertEqual(first.valid_mark_count, 46)
        self.assertEqual(first.mark_unavailable_count, 0)
        self.assertEqual(first.unavailable_count, 7)
        self.assertIsNotNone(first.eligible_market_value_subtotal_by_currency)
        self.assertIsNotNone(first.eligible_unrealized_pnl_subtotal_by_currency)
        self.assertIsNone(first.portfolio_market_value_by_currency)
        self.assertIsNone(first.portfolio_unrealized_pnl_by_currency)
        self.assertFalse(first.complete_portfolio_totals_available)
        self.assertFalse(first.financial_acceptance)
        self.assertEqual(first.binding_sha256, self.reconciliation.binding_sha256)
        self.assertEqual(first.snapshot_uid, self.reconciliation.snapshot_uid)
        self.assertEqual(first.assembly_sha256, self.reconciliation.assembly_sha256)
        self.assertEqual(
            first.eligible_cost_basis_subtotal_by_currency,
            self.reconciliation.eligible_cost_basis_subtotal_by_currency,
        )
        valued = [item for item in first.positions if item.status == "valued"]
        unavailable = [item for item in first.positions if item.status == "unavailable"]
        self.assertEqual(len(valued), 46)
        self.assertEqual(len(unavailable), 7)
        short = next(item for item in valued if item.canonical_quantity < 0)
        self.assertEqual(short.mark.selected_field, "ask")
        self.assertEqual(short.market_value, Decimal("-12"))

        audit_text = json.dumps(first.privacy_safe_audit(), sort_keys=True)
        self.assertNotIn("E00", audit_text)
        self.assertNotIn("11.5", audit_text)
        self.assertNotIn("market_value_by_currency", audit_text)

    def test_current_58_position_route_uses_48_eligible_and_10_unavailable(self) -> None:
        reconciliation = self.make_reconciliation(
            eligible_count=48,
            unavailable_count=10,
            route_version="pnl-03u-58-position-2026-09-04.v3",
        )
        quotes = {
            item.identity: self.quote(item.identity)
            for item in reconciliation.positions
            if item.status == "fifo_reconciled"
        }

        result = run_bounded_pnl03_valuation(
            reconciliation=reconciliation,
            quote_evidence_sha256="2" * 64,
            quotes=quotes,
            evaluated_at=self.evaluated_at,
            max_reconciliation_age_seconds=0,
        )

        self.assertEqual(result.complete_position_count, 58)
        self.assertEqual(result.eligible_count, 48)
        self.assertEqual(result.valid_mark_count, 48)
        self.assertEqual(result.unavailable_count, 10)
        self.assertEqual(result.final_status, "eligible_valued")
        self.assertIsNotNone(result.eligible_market_value_subtotal_by_currency)
        self.assertIsNone(result.portfolio_market_value_by_currency)
        self.assertFalse(result.complete_portfolio_totals_available)

    def test_missing_or_stale_eligible_mark_makes_subtotals_unavailable(self) -> None:
        missing = dict(self.quotes)
        missing.pop(next(iter(missing)))
        missing_result = self.run_gate(quotes=missing)
        self.assertEqual(missing_result.final_status, "mark_unavailable")
        self.assertEqual(missing_result.valid_mark_count, 45)
        self.assertEqual(missing_result.mark_unavailable_count, 1)
        self.assertIsNone(missing_result.eligible_market_value_subtotal_by_currency)
        self.assertIsNone(missing_result.eligible_unrealized_pnl_subtotal_by_currency)

        stale = dict(self.quotes)
        identity = next(iter(stale))
        stale[identity] = self.quote(identity, seconds_old=600)
        stale_result = self.run_gate(quotes=stale)
        self.assertEqual(stale_result.final_status, "mark_unavailable")
        self.assertEqual(stale_result.mark_unavailable_count, 1)
        self.assertIsNone(stale_result.eligible_market_value_subtotal_by_currency)

    def test_noneligible_quote_and_route_drift_are_rejected(self) -> None:
        unresolved = next(
            item.identity
            for item in self.reconciliation.positions
            if item.status == "unavailable"
        )
        with_extra = dict(self.quotes)
        with_extra[unresolved] = self.quote(unresolved)
        with self.assertRaisesRegex(BoundedPnl03ValuationError, "non-eligible"):
            self.run_gate(quotes=with_extra)

        drifted = replace(self.reconciliation, eligible_count=45)
        with self.assertRaisesRegex(BoundedPnl03ValuationError, "bounded route"):
            run_bounded_pnl03_valuation(
                reconciliation=drifted,
                quote_evidence_sha256="1" * 64,
                quotes=self.quotes,
                evaluated_at=self.evaluated_at,
                max_reconciliation_age_seconds=0,
            )

    def test_stale_reconciliation_scope_is_rejected_before_valuation(self) -> None:
        later = self.evaluated_at + timedelta(seconds=1)
        with self.assertRaisesRegex(BoundedPnl03ValuationError, "age limit"):
            run_bounded_pnl03_valuation(
                reconciliation=self.reconciliation,
                quote_evidence_sha256="1" * 64,
                quotes=self.quotes,
                evaluated_at=later,
                max_reconciliation_age_seconds=0,
            )

    def test_bounded_result_persists_reads_back_and_replays_in_temporary_db(self) -> None:
        run = self.run_gate()
        snapshot = self.snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bounded-pnl03.duckdb"
            apply_schema_migrations(db_path)
            first = persist_bounded_pnl03_valuation_run(
                db_path, run=run, broker_snapshot=snapshot
            )
            replay = persist_bounded_pnl03_valuation_run(
                db_path, run=run, broker_snapshot=snapshot
            )
            self.assertTrue(first.created)
            self.assertTrue(replay.replayed)
            read_back = load_bounded_pnl03_valuation_run(
                db_path, valuation_run_uid=run.run_uid
            )
            self.assertIsNotNone(read_back)
            assert read_back is not None
            self.assertEqual(read_back.route_version, run.route_version)
            self.assertEqual(read_back.binding_sha256, run.binding_sha256)
            self.assertEqual(read_back.assembly_sha256, run.assembly_sha256)
            self.assertEqual(len(read_back.positions), 53)
            self.assertEqual(len(read_back.subtotals), 1)
            self.assertEqual(
                read_back.subtotals[0]["eligible_cost_basis"], Decimal("440")
            )
            self.assertFalse(read_back.complete_portfolio_totals_available)
            with duckdb.connect(str(db_path), read_only=True) as con:
                self.assertEqual(
                    con.execute(
                        "SELECT COUNT(*) FROM pnl_bounded_position_valuations"
                    ).fetchone()[0],
                    53,
                )

    def test_bounded_persistence_rejects_snapshot_quantity_drift(self) -> None:
        run = self.run_gate()
        snapshot = self.snapshot()
        first, *remaining = snapshot.positions
        drifted = replace(
            snapshot,
            positions=(
                replace(first, quantity=first.quantity + Decimal("1")),
                *remaining,
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bounded-pnl03.duckdb"
            apply_schema_migrations(db_path)
            with self.assertRaisesRegex(ValueError, "broker quantity"):
                persist_bounded_pnl03_valuation_run(
                    db_path, run=run, broker_snapshot=drifted
                )

    def test_bounded_snapshot_writer_remains_compatible_with_migration_0014(self) -> None:
        run = self.run_gate()
        snapshot = self.snapshot()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "migration-0014.duckdb"
            apply_schema_migrations(db_path, target_version="0014")
            result = persist_bounded_pnl03_valuation_run(
                db_path, run=run, broker_snapshot=snapshot
            )
            self.assertTrue(result.created)

    def test_private_api_withholds_values_until_matching_owner_acceptance(self) -> None:
        reconciliation = self.make_reconciliation(
            eligible_count=48,
            unavailable_count=10,
            route_version="pnl-03v-58-position-2026-09-04.v4",
        )
        quotes = {
            item.identity: self.quote(item.identity)
            for item in reconciliation.positions
            if item.status == "fifo_reconciled"
        }
        run = run_bounded_pnl03_valuation(
            reconciliation=reconciliation,
            quote_evidence_sha256="2" * 64,
            quotes=quotes,
            evaluated_at=self.evaluated_at,
            max_reconciliation_age_seconds=0,
        )
        snapshot = self.snapshot(reconciliation)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "bounded-pnl03.duckdb"
            apply_schema_migrations(db_path)
            persist_bounded_pnl03_valuation_run(
                db_path, run=run, broker_snapshot=snapshot
            )
            read_back = load_bounded_pnl03_valuation_run(
                db_path, valuation_run_uid=run.run_uid
            )
            assert read_back is not None

            withheld = build_pnl03_position_valuation_response(read_back)
            self.assertEqual(withheld.metadata.release_status, "withheld")
            self.assertTrue(
                all(item.market_value is None for item in withheld.positions)
            )
            self.assertTrue(
                all(
                    item.eligible_cost_basis is None
                    for item in withheld.eligible_subtotals
                )
            )
            self.assertIsNone(withheld.portfolio_market_value_by_currency)
            self.assertFalse(withheld.complete_portfolio_totals_available)

            wrong = Pnl03FinancialReleaseAuthorization(
                owner_acceptance_uid="owner-acceptance:test",
                valuation_run_uid="different-run",
                result_fingerprint=read_back.result_fingerprint,
                accepted_at=self.evaluated_at,
            )
            with self.assertRaisesRegex(Pnl03ApiContractError, "does not match"):
                build_pnl03_position_valuation_response(
                    read_back, authorization=wrong
                )

            wrong_fingerprint = Pnl03FinancialReleaseAuthorization(
                owner_acceptance_uid="owner-acceptance:test",
                valuation_run_uid=run.run_uid,
                result_fingerprint="0" * 64,
                accepted_at=self.evaluated_at,
            )
            with self.assertRaisesRegex(Pnl03ApiContractError, "fingerprint"):
                build_pnl03_position_valuation_response(
                    read_back, authorization=wrong_fingerprint
                )

            accepted = Pnl03FinancialReleaseAuthorization(
                owner_acceptance_uid="owner-acceptance:test",
                valuation_run_uid=run.run_uid,
                result_fingerprint=read_back.result_fingerprint,
                accepted_at=self.evaluated_at,
            )
            released = build_pnl03_position_valuation_response(
                read_back, authorization=accepted
            )
            self.assertEqual(released.metadata.release_status, "owner_accepted")
            self.assertEqual(
                released.eligible_subtotals[0].eligible_cost_basis, "460.0000000000"
            )
            self.assertEqual(len(released.positions), 58)
            self.assertEqual(
                sum(item.market_value is not None for item in released.positions), 48
            )
            self.assertEqual(
                sum(item.market_value is None for item in released.positions), 10
            )
            self.assertIsNone(released.portfolio_unrealized_pnl_by_currency)

    def test_private_pnl03_contract_is_not_registered_as_an_active_route(self) -> None:
        paths = {route.path for route in app.routes}
        self.assertNotIn("/api/v1/pnl03/positions", paths)


if __name__ == "__main__":
    unittest.main()
