from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

import duckdb
import yaml

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.market_data import (
    QuoteCaptureContractError,
    QuoteCaptureEnvelope,
    QuoteContractError,
    QuoteEvidenceSource,
    QuoteInstrumentRequest,
    QuoteIngestionRun,
    build_quote_capture_fingerprint,
    build_quote_uid,
    load_market_data_policy,
    persist_quote_batch,
    persist_quote_capture,
    validate_quote_capture,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"
POLICY_PATH = PROJECT_ROOT / "config" / "marketdata.yaml"


class QuoteCaptureIngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = load_market_data_policy(POLICY_PATH)

    def quote(
        self,
        *,
        provider: str = "schwab",
        connection_uid: str = "owner-primary",
        instrument_key: str = "stock|AAPL",
        provider_instrument_id: str = "AAPL",
        symbol: str = "AAPL",
        asof: date = date(2026, 8, 27),
        quote_at: datetime = datetime(2026, 8, 27, 14, 30, tzinfo=UTC),
        received_at: datetime = datetime(2026, 8, 27, 14, 30, 1, tzinfo=UTC),
        adapter_version: str | None = None,
    ) -> NormalizedQuote:
        quote = NormalizedQuote(
            quote_uid="pending",
            provider=provider,
            connection_uid=connection_uid,
            instrument_key=instrument_key,
            provider_instrument_id=provider_instrument_id,
            symbol=symbol,
            asset_class="stock",
            currency="USD",
            bid=Decimal("199.90"),
            ask=Decimal("200.10"),
            last=Decimal("200.00"),
            provider_quote_at=quote_at,
            received_at=received_at,
            market_session="regular",
            data_mode="real_time",
            entitlement_status="entitled",
            asof=asof,
            raw_path=f"data/raw/{provider}/external/capture-1/quote-response.json",
            raw_sha256="a" * 64,
            adapter_version=adapter_version or f"{provider}-quote-json-v1",
        )
        return replace(quote, quote_uid=build_quote_uid(quote))

    def capture(
        self,
        *,
        quote: NormalizedQuote | None = None,
        quote_run_uid: str = "quote-capture-1",
        requests: tuple[QuoteInstrumentRequest, ...] | None = None,
        started_at: datetime = datetime(2026, 8, 27, 14, 29, 59, tzinfo=UTC),
        received_at: datetime = datetime(2026, 8, 27, 14, 30, 1, tzinfo=UTC),
        evaluated_at: datetime = datetime(2026, 8, 27, 14, 30, 2, tzinfo=UTC),
        source: QuoteEvidenceSource | None = None,
    ) -> QuoteCaptureEnvelope:
        normalized = quote or self.quote(received_at=received_at)
        return QuoteCaptureEnvelope(
            quote_run_uid=quote_run_uid,
            provider=normalized.provider,
            connection_uid=normalized.connection_uid,
            asof=normalized.asof,
            started_at=started_at,
            received_at=received_at,
            evaluated_at=evaluated_at,
            requests=requests
            or (
                QuoteInstrumentRequest(
                    instrument_key=normalized.instrument_key,
                    provider_instrument_id=normalized.provider_instrument_id,
                    asset_class=normalized.asset_class,
                    currency=normalized.currency,
                ),
            ),
            source=source
            or QuoteEvidenceSource(
                storage_kind="external_private_vault",
                locator="quote-captures/capture-1/quote-response.json",
                raw_sha256=normalized.raw_sha256,
            ),
            adapter_version=normalized.adapter_version,
            quotes=(normalized,),
        )

    def test_complete_capture_persists_with_full_lineage_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "onejournal.duckdb"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            capture = self.capture()

            self.assertEqual(
                persist_quote_capture(db_path, capture, policy=self.policy.freshness),
                1,
            )
            self.assertEqual(
                persist_quote_capture(db_path, capture, policy=self.policy.freshness),
                1,
            )

            with duckdb.connect(str(db_path), read_only=True) as con:
                run = con.execute(
                    """
                    SELECT ingestion_contract_version, received_at_utc,
                           request_scope_json, source_storage_kind,
                           source_locator, source_raw_sha256, input_fingerprint,
                           requested_instrument_count, received_quote_count,
                           accepted_quote_count, rejected_quote_count
                    FROM market_quote_ingestion_runs
                    """
                ).fetchone()
                quote_count = con.execute(
                    "SELECT COUNT(*) FROM normalized_market_quotes"
                ).fetchone()[0]

            self.assertEqual(run[0], capture.contract_version)
            self.assertEqual(run[3], "external_private_vault")
            self.assertEqual(run[4], capture.source.locator)
            self.assertEqual(run[5], capture.source.raw_sha256)
            self.assertEqual(run[6], build_quote_capture_fingerprint(capture))
            self.assertEqual(run[7:11], (1, 1, 1, 0))
            self.assertEqual(quote_count, 1)

    def test_capture_contract_is_provider_independent(self) -> None:
        quote = self.quote(
            provider="ibkr",
            provider_instrument_id="AAPL@SMART",
            adapter_version="ibkr-quote-json-v1",
        )
        capture = self.capture(quote=quote)

        validate_quote_capture(capture, policy=self.policy.freshness)

    def test_migration_0012_preserves_legacy_0011_quote_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "onejournal.duckdb"
            apply_schema_migrations(
                db_path,
                target_version="0011",
                migrations_dir=MIGRATIONS_DIR,
            )
            quote = self.quote()
            run = QuoteIngestionRun(
                quote_run_uid="legacy-quote-run-1",
                provider=quote.provider,
                connection_uid=quote.connection_uid,
                asof=quote.asof,
                started_at=datetime(2026, 8, 27, 14, 29, 59, tzinfo=UTC),
                completed_at=datetime(2026, 8, 27, 14, 30, 2, tzinfo=UTC),
                requested_instrument_count=1,
                adapter_version=quote.adapter_version,
            )
            persist_quote_batch(db_path, run, (quote,))

            self.assertEqual(
                apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR),
                12,
            )
            with duckdb.connect(str(db_path), read_only=True) as con:
                preserved = con.execute(
                    """
                    SELECT r.quote_run_uid, q.quote_uid,
                           r.ingestion_contract_version, r.source_locator
                    FROM market_quote_ingestion_runs r
                    JOIN normalized_market_quotes q USING (quote_run_uid)
                    """
                ).fetchone()
            self.assertEqual(preserved, (run.quote_run_uid, quote.quote_uid, None, None))

    def test_partial_or_identity_mismatched_scope_fails_closed(self) -> None:
        quote = self.quote()
        missing_request = QuoteInstrumentRequest(
            instrument_key="stock|MSFT",
            provider_instrument_id="MSFT",
            asset_class="stock",
            currency="USD",
        )
        capture = self.capture(
            quote=quote,
            requests=(self.capture(quote=quote).requests[0], missing_request),
        )
        with self.assertRaisesRegex(QuoteCaptureContractError, "scope mismatch"):
            validate_quote_capture(capture, policy=self.policy.freshness)

        wrong_mapping = replace(
            self.capture(quote=quote),
            requests=(
                replace(
                    self.capture(quote=quote).requests[0],
                    provider_instrument_id="OTHER",
                ),
            ),
        )
        with self.assertRaisesRegex(QuoteCaptureContractError, "identity differs"):
            validate_quote_capture(wrong_mapping, policy=self.policy.freshness)

    def test_temporal_and_market_date_mismatches_fail_closed(self) -> None:
        quote = self.quote()
        with self.assertRaisesRegex(QuoteCaptureContractError, "started_at <="):
            validate_quote_capture(
                self.capture(
                    quote=quote,
                    started_at=datetime(2026, 8, 27, 14, 30, 2, tzinfo=UTC),
                ),
                policy=self.policy.freshness,
            )

        future_quote = self.quote(
            quote_at=datetime(2026, 8, 27, 14, 30, 7, tzinfo=UTC)
        )
        with self.assertRaisesRegex(QuoteCaptureContractError, "future tolerance"):
            validate_quote_capture(
                self.capture(quote=future_quote),
                policy=self.policy.freshness,
            )

        wrong_market_date = self.quote(asof=date(2026, 8, 26))
        with self.assertRaisesRegex(QuoteCaptureContractError, "market date"):
            validate_quote_capture(
                self.capture(quote=wrong_market_date),
                policy=self.policy.freshness,
            )

    def test_source_locator_and_full_envelope_replay_are_guarded(self) -> None:
        traversal = self.capture(
            source=QuoteEvidenceSource(
                storage_kind="external_private_vault",
                locator="../quote-response.json",
                raw_sha256="a" * 64,
            )
        )
        with self.assertRaisesRegex(QuoteCaptureContractError, "safe relative path"):
            validate_quote_capture(traversal, policy=self.policy.freshness)

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "onejournal.duckdb"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            capture = self.capture()
            persist_quote_capture(db_path, capture, policy=self.policy.freshness)
            changed = replace(
                capture,
                evaluated_at=capture.evaluated_at + timedelta(seconds=1),
            )
            with self.assertRaisesRegex(ValueError, "envelope changed"):
                persist_quote_capture(db_path, changed, policy=self.policy.freshness)

            different_run = replace(capture, quote_run_uid="quote-capture-2")
            with self.assertRaisesRegex(ValueError, "already belongs to run"):
                persist_quote_capture(
                    db_path,
                    different_run,
                    policy=self.policy.freshness,
                )

            with duckdb.connect(str(db_path), read_only=True) as con:
                self.assertEqual(
                    con.execute("SELECT COUNT(*) FROM normalized_market_quotes").fetchone()[0],
                    1,
                )

    def test_quote_identity_changes_when_received_or_entitlement_state_changes(self) -> None:
        quote = self.quote()
        later = replace(quote, received_at=quote.received_at + timedelta(seconds=1))
        later = replace(later, quote_uid=build_quote_uid(later))
        denied = replace(quote, entitlement_status="denied")
        denied = replace(denied, quote_uid=build_quote_uid(denied))

        self.assertNotEqual(quote.quote_uid, later.quote_uid)
        self.assertNotEqual(quote.quote_uid, denied.quote_uid)

    def test_policy_loader_fails_closed_on_unsafe_or_incomplete_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "marketdata.yaml"
            config = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
            config["marketdata"]["allow_cross_provider_fallback"] = True
            path.write_text(yaml.safe_dump(config), encoding="utf-8")
            with self.assertRaisesRegex(QuoteContractError, "fallback"):
                load_market_data_policy(path)


if __name__ == "__main__":
    unittest.main()
