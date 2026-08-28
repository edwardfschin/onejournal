from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
from io import StringIO
from pathlib import Path
import json
import tempfile
import unittest

import duckdb

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.journal.migrations import apply_schema_migrations
from onejournal.market_data import (
    QuoteCaptureEnvelope,
    QuoteInstrumentRequest,
    build_quote_uid,
    load_market_data_policy,
)
from onejournal.market_data.capture_artifact import quote_capture_artifact_bytes
from onejournal.market_data.ingestion import request_scope_json
from onejournal.market_data.runtime import (
    DurableQuoteIngestionError,
    persist_durable_quote_capture,
)
from onejournal.provider_connectors import (
    PRIVATE_CAPTURE_ENVELOPE_FILENAME,
    PRIVATE_CAPTURE_MANIFEST_SCHEMA,
    LocalPrivateRawCaptureStore,
    PrivateRawCaptureError,
    PrivateRawCaptureManifest,
)
from scripts.journal.ingest_private_quote_capture import main as operator_main


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = PROJECT_ROOT / "scripts" / "journal" / "migrations"
POLICY_PATH = PROJECT_ROOT / "config" / "marketdata.yaml"


class DurableQuoteIngestionOperatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private_root = self.root / "private"
        self.private_root.mkdir(mode=0o700)
        self.private_root.chmod(0o700)
        self.store = LocalPrivateRawCaptureStore(private_root=self.private_root)
        self.policy = load_market_data_policy(POLICY_PATH).freshness
        self.asof = date(2026, 8, 28)
        self.started_at = datetime(2026, 8, 28, 14, 29, 59, tzinfo=UTC)
        self.received_at = datetime(2026, 8, 28, 14, 30, 1, tzinfo=UTC)
        self.evaluated_at = datetime(2026, 8, 28, 14, 30, 2, tzinfo=UTC)
        self.raw_body = b'{"synthetic":"private quote response"}'
        self.raw_sha256 = sha256(self.raw_body).hexdigest()
        self.source = self.store.source_for(
            provider="schwab",
            asof=self.asof,
            quote_run_uid="schwab-quote-run-0001",
            raw_sha256=self.raw_sha256,
        )
        request = QuoteInstrumentRequest(
            instrument_key="stock|AAPL",
            provider_instrument_id="AAPL",
            asset_class="stock",
            currency="USD",
        )
        quote = NormalizedQuote(
            quote_uid="pending",
            provider="schwab",
            connection_uid="local-schwab-primary",
            instrument_key=request.instrument_key,
            provider_instrument_id=request.provider_instrument_id,
            symbol="AAPL",
            asset_class=request.asset_class,
            currency=request.currency,
            bid=Decimal("199.90"),
            ask=Decimal("200.10"),
            last=Decimal("200.00"),
            provider_quote_at=datetime(2026, 8, 28, 14, 30, tzinfo=UTC),
            received_at=self.received_at,
            market_session="regular",
            data_mode="real_time",
            entitlement_status="entitled",
            asof=self.asof,
            raw_path=(
                "data/raw/schwab/2026-08-28/quote-captures/"
                "schwab-quote-run-0001/quote-response.json"
            ),
            raw_sha256=self.raw_sha256,
            adapter_version="schwab-quote-json-v1",
        )
        quote = replace(quote, quote_uid=build_quote_uid(quote))
        self.capture = QuoteCaptureEnvelope(
            quote_run_uid="schwab-quote-run-0001",
            provider="schwab",
            connection_uid="local-schwab-primary",
            asof=self.asof,
            started_at=self.started_at,
            received_at=self.received_at,
            evaluated_at=self.evaluated_at,
            requests=(request,),
            source=self.source,
            adapter_version=quote.adapter_version,
            quotes=(quote,),
        )
        scope_sha256 = sha256(
            request_scope_json(self.capture).encode("utf-8")
        ).hexdigest()
        self.store.commit(
            source=self.source,
            raw_response_bytes=self.raw_body,
            manifest=PrivateRawCaptureManifest(
                schema=PRIVATE_CAPTURE_MANIFEST_SCHEMA,
                provider=self.capture.provider,
                quote_run_uid=self.capture.quote_run_uid,
                connection_uid=self.capture.connection_uid,
                approval_id="PNL-02-T13-APPROVAL",
                acknowledgement_uid="schwab-acknowledgement-0001",
                asof=self.asof,
                request_scope_sha256=scope_sha256,
                started_at=self.started_at,
                received_at=self.received_at,
                completed_at=self.evaluated_at,
                raw_sha256=self.raw_sha256,
                raw_byte_count=len(self.raw_body),
                capture_envelope_sha256=sha256(
                    quote_capture_artifact_bytes(self.capture)
                ).hexdigest(),
                final_status="captured_private_uningested",
            ),
            capture=self.capture,
        )

    def _db(self) -> Path:
        db_path = self.root / "journal.duckdb"
        apply_schema_migrations(db_path, migrations_dir=MIGRATIONS_DIR)
        return db_path

    def _persist(self, db_path: Path):
        return persist_durable_quote_capture(
            db_path=db_path,
            private_capture_store=LocalPrivateRawCaptureStore(
                private_root=self.private_root
            ),
            source=self.source,
            policy=self.policy,
            expected_provider="schwab",
            expected_connection_uid="local-schwab-primary",
            expected_quote_run_uid="schwab-quote-run-0001",
            expected_asof=self.asof,
        )

    def test_restart_recovery_persists_reads_back_and_replays_exactly(self) -> None:
        db_path = self._db()

        first = self._persist(db_path)
        replay = self._persist(db_path)

        self.assertFalse(first.was_replay)
        self.assertTrue(replay.was_replay)
        self.assertEqual(first.persisted_quote_count, 1)
        self.assertEqual(first.read_back_quote_count, 1)
        self.assertEqual(first.final_status, "persisted_and_read_back")
        self.assertNotIn("private quote response", first.to_json())
        with duckdb.connect(str(db_path), read_only=True) as con:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM market_quote_ingestion_runs").fetchone()[0],
                1,
            )
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM normalized_market_quotes").fetchone()[0],
                1,
            )

    def test_tampered_envelope_fails_before_any_quote_row_is_written(self) -> None:
        db_path = self._db()
        envelope_path = (
            self.private_root
            / self.source.locator
        ).with_name(PRIVATE_CAPTURE_ENVELOPE_FILENAME)
        envelope_path.write_bytes(envelope_path.read_bytes() + b" ")

        with self.assertRaisesRegex(PrivateRawCaptureError, "digest changed"):
            self._persist(db_path)

        with duckdb.connect(str(db_path), read_only=True) as con:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM market_quote_ingestion_runs").fetchone()[0],
                0,
            )

    def test_approval_scope_mismatch_fails_before_database_write(self) -> None:
        db_path = self._db()
        with self.assertRaisesRegex(DurableQuoteIngestionError, "connection"):
            persist_durable_quote_capture(
                db_path=db_path,
                private_capture_store=self.store,
                source=self.source,
                policy=self.policy,
                expected_provider="schwab",
                expected_connection_uid="other-connection",
                expected_quote_run_uid=self.capture.quote_run_uid,
                expected_asof=self.asof,
            )
        with duckdb.connect(str(db_path), read_only=True) as con:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM market_quote_ingestion_runs").fetchone()[0],
                0,
            )

    def test_operator_never_auto_migrates_an_unprepared_database(self) -> None:
        db_path = self.root / "unprepared.duckdb"
        with duckdb.connect(str(db_path)) as con:
            con.execute("CREATE TABLE unrelated (value INTEGER)")

        with self.assertRaisesRegex(DurableQuoteIngestionError, "schema"):
            self._persist(db_path)

        with duckdb.connect(str(db_path), read_only=True) as con:
            self.assertEqual({row[0] for row in con.execute("SHOW TABLES").fetchall()}, {"unrelated"})

    def test_migration_checksum_drift_fails_before_quote_write(self) -> None:
        db_path = self._db()
        with duckdb.connect(str(db_path)) as con:
            con.execute(
                "UPDATE schema_migrations SET file_checksum = ? WHERE version = '0012'",
                ["0" * 64],
            )

        with self.assertRaisesRegex(DurableQuoteIngestionError, "checksum"):
            self._persist(db_path)

        with duckdb.connect(str(db_path), read_only=True) as con:
            self.assertEqual(
                con.execute("SELECT COUNT(*) FROM market_quote_ingestion_runs").fetchone()[0],
                0,
            )

    def test_cli_defaults_to_validation_only_and_requires_explicit_persist(self) -> None:
        common = [
            "--private-vault-root",
            str(self.private_root),
            "--source-locator",
            self.source.locator,
            "--raw-sha256",
            self.source.raw_sha256,
            "--provider",
            "schwab",
            "--connection-uid",
            self.capture.connection_uid,
            "--quote-run-uid",
            self.capture.quote_run_uid,
            "--asof",
            self.asof.isoformat(),
        ]
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(operator_main(common), 0)
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["final_status"], "validated_private_uningested")
        self.assertIsNone(summary["database_path"])

        db_path = self._db()
        output = StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                operator_main([*common, "--db", str(db_path), "--persist"]),
                0,
            )
        summary = json.loads(output.getvalue())
        self.assertEqual(summary["final_status"], "persisted_and_read_back")
        self.assertFalse(summary["was_replay"])


if __name__ == "__main__":
    unittest.main()
