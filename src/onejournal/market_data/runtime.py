"""Guarded local runtime for durable private quote-capture ingestion."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from hashlib import sha256
import json
from pathlib import Path

import duckdb

from onejournal.journal.migrations import DEFAULT_MIGRATIONS_DIR
from onejournal.market_data.ingestion import (
    QuoteCaptureEnvelope,
    QuoteEvidenceSource,
    build_quote_capture_fingerprint,
    request_scope_json,
)
from onejournal.market_data.quotes import QuoteFreshnessPolicy
from onejournal.market_data.repository import (
    load_quote_capture_run,
    persist_quote_capture_result,
)
from onejournal.provider_connectors.private_capture import (
    LoadedPrivateQuoteCapture,
    LocalPrivateRawCaptureStore,
)


DURABLE_QUOTE_INGESTION_AUDIT_SCHEMA = "onejournal.market-data.quote-ingestion-audit.v1"
REQUIRED_QUOTE_SCHEMA_VERSION = 12


class DurableQuoteIngestionError(RuntimeError):
    """Raised when a private capture cannot safely enter journal state."""


@dataclass(frozen=True)
class DurableQuoteIngestionAudit:
    """Secret-free local audit for validation, first persistence, or replay."""

    schema: str
    quote_run_uid: str
    provider: str
    connection_uid: str
    asof: date
    approval_id: str
    acknowledgement_uid: str
    capture_contract_version: str
    capture_fingerprint: str
    source_storage_kind: str
    source_locator: str
    source_raw_sha256: str
    requested_instrument_count: int
    normalized_quote_count: int
    persisted_quote_count: int
    read_back_quote_count: int
    database_path: str | None
    database_schema_version: int | None
    was_replay: bool | None
    final_status: str

    def to_json(self) -> str:
        payload = asdict(self)
        payload["asof"] = self.asof.isoformat()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _require_expected_capture(
    loaded: LoadedPrivateQuoteCapture,
    *,
    source: QuoteEvidenceSource,
    expected_provider: str,
    expected_connection_uid: str,
    expected_quote_run_uid: str,
    expected_asof: date,
) -> QuoteCaptureEnvelope:
    capture = loaded.capture
    if capture.source != source:
        raise DurableQuoteIngestionError("loaded private source differs from approval scope")
    if capture.provider != expected_provider:
        raise DurableQuoteIngestionError("capture provider differs from approval scope")
    if capture.connection_uid != expected_connection_uid:
        raise DurableQuoteIngestionError("capture connection differs from approval scope")
    if capture.quote_run_uid != expected_quote_run_uid:
        raise DurableQuoteIngestionError("capture run identity differs from approval scope")
    if capture.asof != expected_asof:
        raise DurableQuoteIngestionError("capture market date differs from approval scope")
    scope_sha256 = sha256(request_scope_json(capture).encode("utf-8")).hexdigest()
    if scope_sha256 != loaded.manifest.request_scope_sha256:
        raise DurableQuoteIngestionError("capture request scope differs from private manifest")
    if not loaded.manifest.approval_id or not loaded.manifest.acknowledgement_uid:
        raise DurableQuoteIngestionError("capture approval lineage is missing")
    return capture


def validate_durable_quote_capture(
    *,
    private_capture_store: LocalPrivateRawCaptureStore,
    source: QuoteEvidenceSource,
    policy: QuoteFreshnessPolicy,
    expected_provider: str,
    expected_connection_uid: str,
    expected_quote_run_uid: str,
    expected_asof: date,
) -> tuple[LoadedPrivateQuoteCapture, DurableQuoteIngestionAudit]:
    """Revalidate restart-safe private evidence without opening a database."""

    loaded = private_capture_store.load_capture(source=source, policy=policy)
    capture = _require_expected_capture(
        loaded,
        source=source,
        expected_provider=expected_provider,
        expected_connection_uid=expected_connection_uid,
        expected_quote_run_uid=expected_quote_run_uid,
        expected_asof=expected_asof,
    )
    return loaded, DurableQuoteIngestionAudit(
        schema=DURABLE_QUOTE_INGESTION_AUDIT_SCHEMA,
        quote_run_uid=capture.quote_run_uid,
        provider=capture.provider,
        connection_uid=capture.connection_uid,
        asof=capture.asof,
        approval_id=loaded.manifest.approval_id,
        acknowledgement_uid=loaded.manifest.acknowledgement_uid,
        capture_contract_version=capture.contract_version,
        capture_fingerprint=build_quote_capture_fingerprint(capture),
        source_storage_kind=capture.source.storage_kind,
        source_locator=capture.source.locator,
        source_raw_sha256=capture.source.raw_sha256,
        requested_instrument_count=len(capture.requests),
        normalized_quote_count=len(capture.quotes),
        persisted_quote_count=0,
        read_back_quote_count=0,
        database_path=None,
        database_schema_version=None,
        was_replay=None,
        final_status="validated_private_uningested",
    )


def require_quote_ingestion_schema(
    db_path: Path,
    *,
    migrations_dir: Path = DEFAULT_MIGRATIONS_DIR,
) -> int:
    """Fail closed unless an existing database has applied migrations 0011/0012."""

    if not db_path.is_absolute():
        raise DurableQuoteIngestionError("journal database path must be absolute")
    if db_path.is_symlink() or not db_path.is_file():
        raise DurableQuoteIngestionError("journal database must be an existing regular file")
    try:
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
            required_tables = {
                "schema_migrations",
                "market_quote_ingestion_runs",
                "normalized_market_quotes",
            }
            if not required_tables.issubset(tables):
                raise DurableQuoteIngestionError("journal quote schema is not installed")
            applied_rows = {
                str(row[0]): str(row[1])
                for row in con.execute(
                    """
                    SELECT version, file_checksum
                    FROM schema_migrations
                    WHERE status = 'applied'
                    """
                ).fetchall()
            }
            if not {"0011", "0012"}.issubset(applied_rows):
                raise DurableQuoteIngestionError(
                    "journal database requires applied migrations 0011 and 0012"
                )
            non_applied = con.execute(
                "SELECT COUNT(*) FROM schema_migrations WHERE status <> 'applied'"
            ).fetchone()[0]
            if non_applied:
                raise DurableQuoteIngestionError(
                    "journal migration ledger contains a non-applied migration"
                )
            current_version = max(int(version) for version in applied_rows)
            if current_version != REQUIRED_QUOTE_SCHEMA_VERSION:
                raise DurableQuoteIngestionError(
                    "journal schema version is not the reviewed quote-ingestion version"
                )
            for version, filename in (
                ("0011", "0011_add_normalized_market_quotes.sql"),
                ("0012", "0012_add_quote_capture_envelope.sql"),
            ):
                migration_path = migrations_dir / filename
                if not migration_path.is_file():
                    raise DurableQuoteIngestionError(
                        f"reviewed migration {version} is unavailable"
                    )
                expected_checksum = sha256(migration_path.read_bytes()).hexdigest()
                if applied_rows[version] != expected_checksum:
                    raise DurableQuoteIngestionError(
                        f"journal migration {version} checksum does not match repository"
                    )
            columns = {
                row[1]
                for row in con.execute(
                    "PRAGMA table_info(market_quote_ingestion_runs)"
                ).fetchall()
            }
            required_columns = {
                "ingestion_contract_version",
                "received_at_utc",
                "request_scope_json",
                "source_storage_kind",
                "source_locator",
                "source_raw_sha256",
            }
            if not required_columns.issubset(columns):
                raise DurableQuoteIngestionError("journal quote schema is incomplete")
            return current_version
        finally:
            con.close()
    except duckdb.Error as exc:
        raise DurableQuoteIngestionError("journal database schema check failed") from exc


def persist_durable_quote_capture(
    *,
    db_path: Path,
    private_capture_store: LocalPrivateRawCaptureStore,
    source: QuoteEvidenceSource,
    policy: QuoteFreshnessPolicy,
    expected_provider: str,
    expected_connection_uid: str,
    expected_quote_run_uid: str,
    expected_asof: date,
) -> DurableQuoteIngestionAudit:
    """Validate, atomically persist, and exactly read back one private capture."""

    loaded, validation_audit = validate_durable_quote_capture(
        private_capture_store=private_capture_store,
        source=source,
        policy=policy,
        expected_provider=expected_provider,
        expected_connection_uid=expected_connection_uid,
        expected_quote_run_uid=expected_quote_run_uid,
        expected_asof=expected_asof,
    )
    schema_version = require_quote_ingestion_schema(db_path)
    try:
        persisted = persist_quote_capture_result(
            db_path,
            loaded.capture,
            policy=policy,
        )
        read_back = load_quote_capture_run(
            db_path,
            quote_run_uid=loaded.capture.quote_run_uid,
            provider=loaded.capture.provider,
            connection_uid=loaded.capture.connection_uid,
            asof=loaded.capture.asof,
            policy=policy,
        )
    except (duckdb.Error, ValueError) as exc:
        raise DurableQuoteIngestionError(
            "quote persistence or exact read-back failed; identical replay is the recovery path"
        ) from exc
    if read_back.input_fingerprint != validation_audit.capture_fingerprint:
        raise DurableQuoteIngestionError("persisted quote capture differs from private source")
    if (
        read_back.quote_run_uid != loaded.capture.quote_run_uid
        or read_back.provider != loaded.capture.provider
        or read_back.connection_uid != loaded.capture.connection_uid
        or read_back.asof != loaded.capture.asof
        or read_back.started_at != loaded.capture.started_at
        or read_back.received_at != loaded.capture.received_at
        or read_back.evaluated_at != loaded.capture.evaluated_at
        or read_back.requests != loaded.capture.requests
        or read_back.source != loaded.capture.source
        or read_back.adapter_version != loaded.capture.adapter_version
        or read_back.contract_version != loaded.capture.contract_version
        or read_back.quotes != loaded.capture.quotes
    ):
        raise DurableQuoteIngestionError("persisted quote fields differ from private source")
    return DurableQuoteIngestionAudit(
        **{
            **asdict(validation_audit),
            "persisted_quote_count": persisted.persisted_quote_count,
            "read_back_quote_count": len(read_back.quotes),
            "database_path": str(db_path),
            "database_schema_version": schema_version,
            "was_replay": persisted.was_replay,
            "final_status": "persisted_and_read_back",
        }
    )
