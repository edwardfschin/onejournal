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
    QuoteContractError,
    QuoteFreshnessPolicy,
    QuoteIngestionRun,
    assess_quote_freshness,
    build_quote_uid,
    load_latest_quotes,
    persist_quote_batch,
    validate_normalized_quote,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"


class MarketDataQuoteContractTests(unittest.TestCase):
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
            provider_quote_at=datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
            received_at=datetime(2026, 8, 11, 14, 30, 1, tzinfo=UTC),
            market_session="regular",
            data_mode="real_time",
            entitlement_status="entitled",
            asof=date(2026, 8, 11),
            raw_path="data/raw/schwab/2026-08-11/quotes/batch.json",
            raw_sha256="a" * 64,
            adapter_version="schwab-quote-v1",
        )
        quote = replace(base, **changes)
        return replace(quote, quote_uid=build_quote_uid(quote))

    def test_fresh_realtime_two_sided_quote_is_freshness_eligible(self) -> None:
        quote = self._quote()
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=quote.provider_quote_at + timedelta(seconds=30),
        )

        self.assertEqual(assessment.status, "live_fresh")
        self.assertTrue(assessment.valuation_allowed)

    def test_stale_quote_cannot_become_a_mark(self) -> None:
        quote = self._quote()
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=quote.provider_quote_at + timedelta(seconds=61),
        )

        self.assertFalse(assessment.valuation_allowed)
        self.assertEqual(assessment.status, "live_stale")

    def test_delayed_or_unentitled_quote_fails_closed(self) -> None:
        delayed = self._quote(data_mode="delayed", entitlement_status="delayed")
        denied = self._quote(entitlement_status="denied")

        delayed_result = assess_quote_freshness(
            delayed,
            evaluated_at=delayed.provider_quote_at + timedelta(seconds=1),
        )
        denied_result = assess_quote_freshness(
            denied,
            evaluated_at=denied.provider_quote_at + timedelta(seconds=1),
        )

        self.assertEqual(delayed_result.status, "delayed")
        self.assertFalse(delayed_result.valuation_allowed)
        self.assertEqual(denied_result.status, "unavailable")
        self.assertFalse(denied_result.valuation_allowed)

    def test_future_timestamp_and_crossed_market_are_rejected(self) -> None:
        future = self._quote()
        result = assess_quote_freshness(
            future,
            evaluated_at=future.provider_quote_at - timedelta(seconds=6),
        )
        self.assertEqual(result.status, "unavailable")

        crossed = replace(future, bid=Decimal("201"), ask=Decimal("200"))
        with self.assertRaisesRegex(QuoteContractError, "crossed quote"):
            validate_normalized_quote(crossed)

    def test_official_close_is_labelled_not_live(self) -> None:
        quote = self._quote(
            bid=None,
            ask=None,
            last=Decimal("198.50"),
            market_session="closed",
            data_mode="official_close",
        )
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=quote.provider_quote_at + timedelta(hours=4),
            expected_market_open=False,
        )

        self.assertTrue(assessment.valuation_allowed)
        self.assertEqual(assessment.status, "market_closed_last")

    def test_quote_requires_provider_scoped_raw_lineage(self) -> None:
        quote = self._quote()
        invalid = replace(quote, raw_path="data/raw/ibkr/quote.json")
        with self.assertRaisesRegex(QuoteContractError, "data/raw/schwab"):
            validate_normalized_quote(invalid)

        traversal = replace(
            quote,
            raw_path="data/raw/schwab/../../private/quote.json",
        )
        with self.assertRaisesRegex(QuoteContractError, "data/raw/schwab"):
            validate_normalized_quote(traversal)

    def test_unknown_session_cannot_inherit_extended_freshness(self) -> None:
        quote = self._quote(market_session="unknown")
        assessment = assess_quote_freshness(
            quote,
            evaluated_at=quote.provider_quote_at + timedelta(seconds=1),
        )

        self.assertEqual(assessment.status, "unavailable")
        self.assertFalse(assessment.valuation_allowed)

    def test_policy_defaults_match_safe_repository_configuration(self) -> None:
        config = yaml.safe_load(
            (PROJECT_ROOT / "config" / "marketdata.yaml").read_text(encoding="utf-8")
        )["marketdata"]
        policy = QuoteFreshnessPolicy(**config["freshness"])

        self.assertEqual(config["provider_sequence"], ["schwab", "ibkr", "moomoo"])
        self.assertEqual(config["provider_selection"], "account_broker")
        self.assertFalse(config["allow_cross_provider_fallback"])
        self.assertFalse(config["polling"]["background_enabled"])
        self.assertFalse(policy.delayed_quotes_are_current)

        acknowledgement = config["terms_acknowledgement"]
        self.assertTrue(acknowledgement["required_before_connection_activation"])
        self.assertTrue(acknowledgement["required_before_quote_retrieval"])
        self.assertTrue(acknowledgement["fail_closed_when_missing_or_outdated"])
        self.assertEqual(
            acknowledgement["acceptance_scope"], "user_provider_connection"
        )
        self.assertFalse(acknowledgement["onejournal_grants_market_data_rights"])
        self.assertTrue(
            acknowledgement["runtime_entitlement_verification_required"]
        )
        self.assertEqual(
            acknowledgement["enforcement_status"],
            "contract_only_until_auth_and_tenancy_are_approved",
        )

    def test_persistence_is_atomic_idempotent_and_lineage_preserving(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "onejournal.duckdb"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            quote = self._quote()
            run = QuoteIngestionRun(
                quote_run_uid="quote-run-1",
                provider="schwab",
                connection_uid="local-schwab-primary",
                asof=date(2026, 8, 11),
                started_at=datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
                completed_at=datetime(2026, 8, 11, 14, 30, 2, tzinfo=UTC),
                requested_instrument_count=1,
                adapter_version="schwab-quote-v1",
            )

            self.assertEqual(persist_quote_batch(db_path, run, (quote,)), 1)
            self.assertEqual(persist_quote_batch(db_path, run, (quote,)), 1)

            with duckdb.connect(str(db_path), read_only=True) as con:
                stored = con.execute(
                    """
                    SELECT provider, connection_uid, instrument_key, bid, ask,
                           last_price, data_mode, entitlement_status, raw_path,
                           raw_sha256
                    FROM normalized_market_quotes
                    """
                ).fetchall()
                run_count = con.execute(
                    "SELECT COUNT(*) FROM market_quote_ingestion_runs"
                ).fetchone()[0]

            self.assertEqual(run_count, 1)
            self.assertEqual(len(stored), 1)
            self.assertEqual(stored[0][0:3], ("schwab", "local-schwab-primary", "stock|AAPL"))
            self.assertEqual(stored[0][8], quote.raw_path)
            self.assertEqual(stored[0][9], quote.raw_sha256)

            loaded = load_latest_quotes(
                db_path,
                provider="schwab",
                connection_uid="local-schwab-primary",
                instrument_keys=("stock|AAPL", "stock|MISSING"),
                asof=date(2026, 8, 11),
            )
            self.assertEqual(loaded, (quote,))

            self.assertEqual(
                load_latest_quotes(
                    db_path,
                    provider="ibkr",
                    connection_uid="local-schwab-primary",
                    instrument_keys=("stock|AAPL",),
                    asof=date(2026, 8, 11),
                ),
                (),
            )

    def test_run_identity_conflict_is_rejected_without_partial_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "onejournal.duckdb"
            apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
            quote = self._quote()
            run = QuoteIngestionRun(
                quote_run_uid="quote-run-conflict",
                provider="schwab",
                connection_uid="local-schwab-primary",
                asof=date(2026, 8, 11),
                started_at=datetime(2026, 8, 11, 14, 30, tzinfo=UTC),
                completed_at=datetime(2026, 8, 11, 14, 30, 2, tzinfo=UTC),
                requested_instrument_count=1,
                adapter_version="schwab-quote-v1",
            )
            persist_quote_batch(db_path, run, (quote,))
            changed = self._quote(last=Decimal("201.00"), raw_sha256="b" * 64)

            with self.assertRaisesRegex(ValueError, "input changed"):
                persist_quote_batch(db_path, run, (changed,))

            with duckdb.connect(str(db_path), read_only=True) as con:
                count = con.execute("SELECT COUNT(*) FROM normalized_market_quotes").fetchone()[0]
            self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
