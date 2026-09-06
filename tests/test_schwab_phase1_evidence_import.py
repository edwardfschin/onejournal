from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import MappingProxyType
import unittest

import duckdb

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.brokers.schwab.orders_json import (
    SchwabOrdersJsonStats,
    normalized_order_evidence_from_orders,
)
from onejournal.brokers.schwab.transactions_json import (
    SchwabTransactionCurrencyConsensus,
    SchwabTransactionsJsonStats,
    normalized_cash_evidence_from_transactions,
    normalized_transaction_evidence_from_transactions,
)
from onejournal.instruments import InstrumentIdentity
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.journal.schwab_evidence_assembly import (
    SchwabEvidenceAssemblyError,
    build_schwab_phase1_evidence_assembly,
    load_schwab_phase1_evidence_assembly_bytes,
    privacy_safe_schwab_evidence_audit,
    schwab_phase1_evidence_assembly_bytes,
)
from onejournal.journal.schwab_evidence_import_repository import (
    load_schwab_phase1_evidence_assembly,
    persist_schwab_phase1_evidence_assembly,
)
from onejournal.market_data.ingestion import (
    QuoteCaptureEnvelope,
    QuoteEvidenceSource,
    QuoteInstrumentRequest,
)
from onejournal.market_data.quotes import QuoteFreshnessPolicy, build_quote_uid
from onejournal.market_data.sessions import (
    ProviderMarketSessionAuthority,
    build_provider_session_authority_uid,
)
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
)
from onejournal.provider_connectors.external_acquisition import (
    ConvertedExternalLifecycleEvidence,
    ConvertedExternalPositionSnapshot,
    ConvertedExternalQuoteCapture,
    ExternalLifecycleReconciliation,
)
from onejournal.provider_connectors.private_capture import (
    PRIVATE_CAPTURE_MANIFEST_SCHEMA,
    PrivateRawCaptureManifest,
)
from scripts.journal.ingest_schwab_phase1_evidence_assembly import main as operator_main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"
CONNECTION_UID = "connection:schwab:phase1-test"
ACCOUNT_UID = "account:schwab:phase1-test"
ASOF = date(2026, 9, 4)
EVALUATED_AT = datetime(2026, 9, 4, 14, 30, 2, tzinfo=UTC)


def _quote(identity: InstrumentIdentity, raw_sha: str) -> NormalizedQuote:
    candidate = NormalizedQuote(
        quote_uid="pending",
        provider="schwab",
        connection_uid=CONNECTION_UID,
        instrument_key=identity.key,
        provider_instrument_id="AAPL",
        symbol="AAPL",
        asset_class="stock",
        currency="USD",
        bid=Decimal("199.90"),
        ask=Decimal("200.10"),
        last=Decimal("200.00"),
        provider_quote_at=EVALUATED_AT - timedelta(seconds=2),
        received_at=EVALUATED_AT - timedelta(seconds=1),
        market_session="unknown",
        data_mode="real_time",
        entitlement_status="entitled",
        asof=ASOF,
        raw_path="data/raw/schwab/2026-09-04/quotes.json",
        raw_sha256=raw_sha,
        adapter_version="schwab-quote-v2",
    )
    return replace(candidate, quote_uid=build_quote_uid(candidate))


def _authority(quote: NormalizedQuote) -> ProviderMarketSessionAuthority:
    candidate = ProviderMarketSessionAuthority(
        authority_uid="pending",
        provider="schwab",
        connection_uid=CONNECTION_UID,
        quote_uid=quote.quote_uid,
        instrument_key=quote.instrument_key,
        provider_instrument_id=quote.provider_instrument_id,
        schedule_scope_id="schwab-equity-us",
        mic=None,
        venue_timezone="America/New_York",
        provider_quote_at=quote.provider_quote_at,
        evaluated_at=EVALUATED_AT,
        quote_market_date=ASOF,
        evaluation_market_date=ASOF,
        quote_market_session="regular",
        evaluation_market_session="regular",
        quote_trading_day_kind="regular",
        evaluation_trading_day_kind="regular",
        quote_phase_started_at=datetime(2026, 9, 4, 13, 30, tzinfo=UTC),
        quote_phase_ends_at=datetime(2026, 9, 4, 20, 0, tzinfo=UTC),
        evaluation_phase_started_at=datetime(2026, 9, 4, 13, 30, tzinfo=UTC),
        evaluation_phase_ends_at=datetime(2026, 9, 4, 20, 0, tzinfo=UTC),
        retrieved_at=EVALUATED_AT - timedelta(seconds=1),
        resolved_at=EVALUATED_AT,
        valid_until=EVALUATED_AT + timedelta(minutes=1),
        source_response_type="market_hours",
        provider_source_version=None,
        raw_path="data/raw/schwab/2026-09-04/market-hours.json",
        raw_sha256="d" * 64,
        adapter_version="schwab-market-hours-v1",
    )
    return replace(
        candidate,
        authority_uid=build_provider_session_authority_uid(candidate),
    )


def synthetic_assembly(
    *,
    cash_review_required: bool = False,
    include_unquoted_position: bool = False,
    repeated_order_observation: bool = False,
):
    identity = InstrumentIdentity(
        asset_class="equity", market_scope="US", currency="USD", symbol="AAPL"
    )
    unquoted_identity = InstrumentIdentity(
        asset_class="equity", market_scope="US", currency="USD", symbol="MSFT"
    )
    position_body = b'{"synthetic":"position"}\n'
    position_sha = sha256(position_body).hexdigest()
    snapshot = BrokerPositionSnapshot(
        snapshot_uid="broker-position-snapshot:phase1-test",
        source_broker="schwab",
        connection_uid=CONNECTION_UID,
        source_account_id=ACCOUNT_UID,
        asof=ASOF,
        retrieved_at=EVALUATED_AT - timedelta(minutes=1),
        raw_path="data/raw/schwab/2026-09-04/positions.json",
        raw_sha256=position_sha,
        account_complete=True,
        adapter_version="schwab-position-json-v3",
        positions=tuple(
            [
                BrokerPositionRecord(
                    identity=identity,
                    quantity=Decimal("2"),
                    broker_average_cost=Decimal("100"),
                    broker_market_value=Decimal("400"),
                    broker_unrealized_pnl=Decimal("200"),
                )
            ]
            + (
                [
                    BrokerPositionRecord(
                        identity=unquoted_identity,
                        quantity=Decimal("1"),
                        broker_average_cost=Decimal("300"),
                        broker_market_value=Decimal("325"),
                        broker_unrealized_pnl=Decimal("25"),
                    )
                ]
                if include_unquoted_position
                else []
            )
        ),
    )
    position = ConvertedExternalPositionSnapshot(
        external_manifest_sha256="a" * 64,
        external_request_uid="position-request-test",
        raw_response_bytes=position_body,
        snapshot=snapshot,
        account_record=MappingProxyType(
            {
                "account_uid": f"schwab:{ACCOUNT_UID}",
                "source_broker": "schwab",
                "connection_uid": CONNECTION_UID,
                "source_account_id": ACCOUNT_UID,
                "asof": ASOF,
                "retrieved_at_utc": snapshot.retrieved_at,
                "account_type": "MARGIN",
                "cash_balance": Decimal("2500.50"),
            }
        ),
    )
    fill = {
        "asof": ASOF.isoformat(),
        "source_broker": "schwab",
        "source_account_id": ACCOUNT_UID,
        "source_fill_id": "transaction-fill-1",
        "source_order_id": "order-1",
        "filled_at": "2026-09-04T14:00:00+00:00",
        "asset_class": "stock",
        "symbol": "AAPL",
        "side": "buy",
        "quantity": "2",
        "fill_price": "100",
        "commission": "0",
        "fees": "0",
        "currency": "USD",
        "option_symbol": "",
        "underlying_symbol": "",
        "option_type": "",
        "expiry": "",
        "strike": "",
        "multiplier": "",
        "open_close": "open",
        "execution_venue": "",
        "liquidity_flag": "",
        "episode_group_id": "",
    }
    lifecycle = ConvertedExternalLifecycleEvidence(
        external_manifest_sha256="b" * 64,
        source_broker="schwab",
        connection_uid=CONNECTION_UID,
        source_account_id=ACCOUNT_UID,
        window_start_date=date(2026, 8, 6),
        window_end_date=ASOF,
        raw_response_bytes={"orders.json": b"orders", "transactions.json": b"transactions"},
        order_rows=(MappingProxyType({**fill, "source_fill_id": "order-fill-1"}),),
        transaction_rows=(MappingProxyType(fill),),
        lifecycle_events=(),
        lifecycle_event_legs=(),
        order_stats=SchwabOrdersJsonStats(top_level_orders=1, fill_rows=1),
        transaction_stats=SchwabTransactionsJsonStats(
            transactions=1,
            fill_rows=1,
            currency_consensus_code="USD",
            currency_consensus_evidence_items=1,
            currency_consensus_resolved_records=1,
        ),
        reconciliation=ExternalLifecycleReconciliation(1, 0, 0),
        order_records=(
            MappingProxyType(
                {
                    "order_uid": f"schwab:{ACCOUNT_UID}:order:order-1",
                    "source_broker": "schwab",
                    "source_account_id": ACCOUNT_UID,
                    "source_order_id": "order-1",
                    "status": "FILLED",
                    "legs": ({"provider_symbol": "AAPL", "quantity": "2"},),
                }
            ),
        ),
        transaction_records=(
            MappingProxyType(
                {
                    "transaction_uid": f"schwab:{ACCOUNT_UID}:transaction:txn-1",
                    "source_broker": "schwab",
                    "source_account_id": ACCOUNT_UID,
                    "source_transaction_id": "txn-1",
                    "transaction_at_utc": "2026-09-04T14:00:00+00:00",
                    "currency": "USD",
                    "items": ({"provider_symbol": "AAPL", "cost": "-200"},),
                }
            ),
        ),
        cash_rows=(
            MappingProxyType(
                {
                    "cash_uid": f"schwab:{ACCOUNT_UID}:transaction:txn-1:net",
                    "source_broker": "schwab",
                    "source_account_id": ACCOUNT_UID,
                    "source_transaction_id": "txn-1",
                    "currency": "" if cash_review_required else "USD",
                    "cash_role": "transaction_net",
                    "cash_amount": "-200",
                    "evidence_status": (
                        "review_required" if cash_review_required else "observed"
                    ),
                    "evidence_reason": (
                        "missing_currency" if cash_review_required else ""
                    ),
                }
            ),
        ),
    )
    quote_body = b'{"synthetic":"quote"}\n'
    quote_sha = sha256(quote_body).hexdigest()
    normalized_quote = _quote(identity, quote_sha)
    source = QuoteEvidenceSource(
        storage_kind="external_private_vault",
        locator="schwab/2026-09-04/quote-captures/phase1/quote-response.json",
        raw_sha256=quote_sha,
    )
    capture = QuoteCaptureEnvelope(
        quote_run_uid="quote-run-phase1-test",
        provider="schwab",
        connection_uid=CONNECTION_UID,
        asof=ASOF,
        started_at=EVALUATED_AT - timedelta(seconds=3),
        received_at=normalized_quote.received_at,
        evaluated_at=EVALUATED_AT,
        requests=(QuoteInstrumentRequest(identity.key, "AAPL", "stock", "USD"),),
        source=source,
        adapter_version=normalized_quote.adapter_version,
        quotes=(normalized_quote,),
    )
    private_manifest = PrivateRawCaptureManifest(
        schema=PRIVATE_CAPTURE_MANIFEST_SCHEMA,
        provider="schwab",
        quote_run_uid=capture.quote_run_uid,
        connection_uid=CONNECTION_UID,
        approval_id="approval-phase1-test",
        acknowledgement_uid="acknowledgement-phase1-test",
        asof=ASOF,
        request_scope_sha256="e" * 64,
        started_at=capture.started_at,
        received_at=capture.received_at,
        completed_at=EVALUATED_AT,
        raw_sha256=quote_sha,
        raw_byte_count=len(quote_body),
        capture_envelope_sha256="f" * 64,
        final_status="captured_private_uningested",
    )
    quote = ConvertedExternalQuoteCapture(
        external_manifest_sha256="c" * 64,
        external_request_uid="quote-request-test",
        source=source,
        raw_response_bytes=quote_body,
        capture=capture,
        private_manifest=private_manifest,
        capture_artifact_bytes=b"synthetic-capture-artifact",
    )
    lifecycle_windows = (lifecycle,)
    if repeated_order_observation:
        earlier = replace(
            lifecycle,
            external_manifest_sha256="f" * 64,
            window_end_date=ASOF - timedelta(days=1),
            raw_response_bytes={
                "orders.json": b"earlier-orders",
                "transactions.json": b"earlier-transactions",
            },
            order_rows=(),
            transaction_rows=(),
            order_stats=SchwabOrdersJsonStats(top_level_orders=1, fill_rows=0),
            transaction_stats=SchwabTransactionsJsonStats(transactions=0, fill_rows=0),
            reconciliation=ExternalLifecycleReconciliation(0, 0, 0),
            transaction_records=(),
            cash_rows=(),
        )
        later = replace(lifecycle, window_start_date=ASOF)
        lifecycle_windows = (earlier, later)
    return build_schwab_phase1_evidence_assembly(
        position=position,
        lifecycle_windows=lifecycle_windows,
        quote=quote,
        session_authorities=(_authority(normalized_quote),),
        assembled_at_utc=EVALUATED_AT + timedelta(seconds=1),
        freshness_policy=QuoteFreshnessPolicy(),
    )


class SchwabDirectFamilyAdapterTests(unittest.TestCase):
    def test_orders_preserve_parent_child_and_leg_detail_privately(self) -> None:
        rows = normalized_order_evidence_from_orders(
            [
                {
                    "accountNumber": "12345678",
                    "orderId": 10,
                    "status": "WORKING",
                    "enteredTime": "2026-09-04T13:00:00Z",
                    "childOrderStrategies": [
                        {
                            "orderId": 11,
                            "status": "FILLED",
                            "orderLegCollection": [
                                {
                                    "orderLegId": 1,
                                    "instruction": "BUY",
                                    "quantity": 2,
                                    "instrument": {
                                        "assetType": "EQUITY",
                                        "symbol": "AAPL",
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
            provider_account_number="12345678",
            source_account_id=ACCOUNT_UID,
        )

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["parent_order_id"], "10")
        self.assertEqual(rows[1]["legs"][0]["provider_symbol"], "AAPL")
        self.assertNotIn("12345678", json.dumps(rows))

    def test_transactions_and_cash_preserve_exact_source_roles_privately(self) -> None:
        transactions = [
            {
                "accountNumber": "12345678",
                "activityId": 99,
                "orderId": 11,
                "time": "2026-09-04T14:00:00Z",
                "type": "TRADE",
                "status": "VALID",
                "netAmount": Decimal("-201.25"),
                "transferItems": [
                    {
                        "amount": Decimal("2"),
                        "price": Decimal("100"),
                        "cost": Decimal("-200"),
                        "instrument": {"assetType": "EQUITY", "symbol": "AAPL"},
                    },
                    {
                        "amount": Decimal("-1.25"),
                        "feeType": "COMMISSION",
                        "instrument": {"assetType": "CURRENCY", "symbol": "USD"},
                    },
                ],
            }
        ]
        consensus = SchwabTransactionCurrencyConsensus("USD", 1)
        normalized = normalized_transaction_evidence_from_transactions(
            transactions,
            provider_account_number="12345678",
            source_account_id=f" {ACCOUNT_UID} ",
            currency_consensus=consensus,
        )
        cash = normalized_cash_evidence_from_transactions(
            transactions,
            provider_account_number="12345678",
            source_account_id=f" {ACCOUNT_UID} ",
            currency_consensus=consensus,
        )

        self.assertEqual(normalized[0]["items"][0]["cost"], "-200")
        self.assertEqual(
            {row["cash_role"] for row in cash},
            {"transaction_net", "security_cost", "fee"},
        )
        self.assertTrue(all(row["source_account_id"] == ACCOUNT_UID for row in cash))
        self.assertNotIn("12345678", json.dumps(normalized) + json.dumps(cash))

        missing_currency = normalized_cash_evidence_from_transactions(
            [
                {
                    **transactions[0],
                    "type": "RECEIVE_AND_DELIVER",
                    "transferItems": [transactions[0]["transferItems"][0]],
                }
            ],
            provider_account_number="12345678",
            source_account_id=ACCOUNT_UID,
        )
        self.assertTrue(
            all(row["evidence_status"] == "review_required" for row in missing_currency)
        )


class SchwabPhase1EvidenceImportTests(unittest.TestCase):
    def test_build_artifact_roundtrip_and_audit_cover_all_families(self) -> None:
        assembly = synthetic_assembly()
        replay = load_schwab_phase1_evidence_assembly_bytes(
            schwab_phase1_evidence_assembly_bytes(assembly)
        )

        self.assertEqual(replay, assembly)
        self.assertEqual(assembly.final_status, "ready")
        self.assertEqual(
            tuple(family.family for family in assembly.families),
            (
                "account",
                "positions",
                "orders",
                "transactions",
                "fills",
                "cash",
                "quotes",
                "sessions",
            ),
        )
        audit = privacy_safe_schwab_evidence_audit(assembly)
        self.assertEqual(audit["family_counts"]["positions"], 1)
        self.assertNotIn("AAPL", json.dumps(dict(audit)))
        self.assertNotIn(ACCOUNT_UID, json.dumps(dict(audit)))

    def test_artifact_rejects_tampered_family_content(self) -> None:
        assembly = synthetic_assembly()
        artifact = json.loads(schwab_phase1_evidence_assembly_bytes(assembly))
        artifact["families"][0]["records"][0]["cash_balance"] = "2501.50"
        with self.assertRaisesRegex(
            SchwabEvidenceAssemblyError, "family fingerprint"
        ):
            load_schwab_phase1_evidence_assembly_bytes(
                (json.dumps(artifact) + "\n").encode()
            )

    def test_missing_cash_currency_remains_visible_and_review_required(self) -> None:
        assembly = synthetic_assembly(cash_review_required=True)

        self.assertEqual(assembly.final_status, "review_required")
        self.assertEqual(assembly.reconciliation.cash_review_required_rows, 1)
        self.assertEqual(
            privacy_safe_schwab_evidence_audit(assembly)[
                "cash_review_required_rows"
            ],
            1,
        )

    def test_unquoted_position_remains_visible_without_blocking_ready_assembly(self) -> None:
        assembly = synthetic_assembly(include_unquoted_position=True)

        self.assertEqual(assembly.final_status, "ready")
        self.assertEqual(assembly.reconciliation.position_count, 2)
        self.assertEqual(assembly.reconciliation.quote_count, 1)
        self.assertEqual(assembly.reconciliation.positions_without_quotes, 1)
        self.assertFalse(assembly.reconciliation.all_positions_have_quotes)
        self.assertEqual(
            privacy_safe_schwab_evidence_audit(assembly)["positions_without_quotes"],
            1,
        )

    def test_repeated_logical_order_preserves_distinct_window_observations(self) -> None:
        assembly = synthetic_assembly(repeated_order_observation=True)
        orders = next(
            family.records for family in assembly.families if family.family == "orders"
        )

        self.assertEqual(assembly.final_status, "ready")
        self.assertEqual(len(orders), 2)
        self.assertEqual(orders[0]["order_uid"], orders[1]["order_uid"])
        self.assertNotEqual(
            orders[0]["order_observation_uid"],
            orders[1]["order_observation_uid"],
        )

    def test_atomic_persistence_exact_replay_and_readback(self) -> None:
        assembly = synthetic_assembly()
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / "journal.duckdb"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)

            first = persist_schwab_phase1_evidence_assembly(db_path, assembly)
            second = persist_schwab_phase1_evidence_assembly(db_path, assembly)
            loaded = load_schwab_phase1_evidence_assembly(
                db_path, assembly_uid=assembly.assembly_uid
            )

            self.assertTrue(first.created)
            self.assertTrue(second.replayed)
            self.assertEqual(loaded, assembly)
            with duckdb.connect(str(db_path), read_only=True) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM phase1_schwab_evidence_import_runs"
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM phase1_schwab_evidence_import_families"
                    ).fetchone()[0],
                    8,
                )

    def test_repository_refuses_missing_or_unmigrated_database(self) -> None:
        assembly = synthetic_assembly()
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            missing = root / "missing.duckdb"
            with self.assertRaisesRegex(ValueError, "pre-existing"):
                persist_schwab_phase1_evidence_assembly(missing, assembly)
            self.assertFalse(missing.exists())
            unmigrated = root / "unmigrated.duckdb"
            duckdb.connect(str(unmigrated)).close()
            with self.assertRaisesRegex(ValueError, "migration 0016"):
                persist_schwab_phase1_evidence_assembly(unmigrated, assembly)

    def test_replay_rejects_changed_stored_family_content(self) -> None:
        assembly = synthetic_assembly()
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / "journal.duckdb"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            persist_schwab_phase1_evidence_assembly(db_path, assembly)
            with duckdb.connect(str(db_path)) as connection:
                connection.execute(
                    """
                    UPDATE phase1_schwab_evidence_import_families
                    SET records_json = '[]'
                    WHERE assembly_uid = ? AND family = 'cash'
                    """,
                    [assembly.assembly_uid],
                )

            with self.assertRaisesRegex(ValueError, "family set"):
                persist_schwab_phase1_evidence_assembly(db_path, assembly)

    def test_family_insert_failure_rolls_back_the_run(self) -> None:
        assembly = synthetic_assembly()
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / "journal.duckdb"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            with duckdb.connect(str(db_path)) as connection:
                connection.execute("DROP TABLE phase1_schwab_evidence_import_families")
                connection.execute(
                    """
                    CREATE TABLE phase1_schwab_evidence_import_families (
                        assembly_uid VARCHAR NOT NULL,
                        family VARCHAR NOT NULL CHECK (family != 'cash'),
                        source_manifest_sha256s_json VARCHAR NOT NULL,
                        source_raw_sha256s_json VARCHAR NOT NULL,
                        source_record_count INTEGER NOT NULL,
                        normalized_record_count INTEGER NOT NULL,
                        excluded_record_count INTEGER NOT NULL,
                        exclusion_reasons_json VARCHAR NOT NULL,
                        records_json VARCHAR NOT NULL,
                        family_fingerprint VARCHAR NOT NULL,
                        PRIMARY KEY (assembly_uid, family)
                    )
                    """
                )

            with self.assertRaises(duckdb.ConstraintException):
                persist_schwab_phase1_evidence_assembly(db_path, assembly)
            with duckdb.connect(str(db_path), read_only=True) as connection:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM phase1_schwab_evidence_import_runs"
                    ).fetchone()[0],
                    0,
                )
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM phase1_schwab_evidence_import_families"
                    ).fetchone()[0],
                    0,
                )

    def test_operator_defaults_to_validation_and_requires_private_permissions(self) -> None:
        assembly = synthetic_assembly()
        with tempfile.TemporaryDirectory() as temporary_dir:
            artifact_path = Path(temporary_dir) / "assembly.json"
            artifact_path.write_bytes(schwab_phase1_evidence_assembly_bytes(assembly))
            artifact_path.chmod(0o600)
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = operator_main(["--assembly", str(artifact_path)])
            audit = json.loads(stdout.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(audit["operation"], "validated")
            self.assertNotIn("AAPL", stdout.getvalue())

            artifact_path.chmod(0o644)
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = operator_main(["--assembly", str(artifact_path)])
            self.assertEqual(result, 1)
            self.assertIn("0600", stderr.getvalue())

    def test_operator_persists_and_verifies_readback(self) -> None:
        assembly = synthetic_assembly()
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            artifact_path = root / "assembly.json"
            db_path = root / "journal.duckdb"
            artifact_path.write_bytes(schwab_phase1_evidence_assembly_bytes(assembly))
            artifact_path.chmod(0o600)
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            db_path.chmod(0o600)
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = operator_main(
                    [
                        "--assembly",
                        str(artifact_path),
                        "--persist",
                        "--db",
                        str(db_path),
                    ]
                )
            audit = json.loads(stdout.getvalue())
            self.assertEqual(result, 0)
            self.assertEqual(audit["operation"], "persisted")
            self.assertTrue(audit["readback_verified"])


if __name__ == "__main__":
    unittest.main()
