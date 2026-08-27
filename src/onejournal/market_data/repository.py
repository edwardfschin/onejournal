"""Transactional DuckDB persistence for normalized market quote evidence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path

import duckdb

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.market_data.ingestion import (
    QuoteCaptureEnvelope,
    build_quote_capture_fingerprint,
    request_scope_json,
    validate_quote_capture,
)
from onejournal.market_data.quotes import (
    QuoteFreshnessPolicy,
    build_quote_uid,
    validate_normalized_quote,
)


@dataclass(frozen=True)
class QuoteIngestionRun:
    """Audit envelope for one provider/connection quote batch."""

    quote_run_uid: str
    provider: str
    connection_uid: str
    asof: date
    started_at: datetime
    completed_at: datetime
    requested_instrument_count: int
    adapter_version: str
    status: str = "ok"
    notes: str | None = None


def _utc_text(value: datetime, field_name: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _quote_fingerprint(quotes: tuple[NormalizedQuote, ...]) -> str:
    rows = []
    for quote in quotes:
        payload = asdict(quote)
        for key, value in tuple(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = format(value, "f")
            elif isinstance(value, datetime):
                payload[key] = _utc_text(value, key)
            elif isinstance(value, date):
                payload[key] = value.isoformat()
        rows.append(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()


def _validate_run(run: QuoteIngestionRun, quotes: tuple[NormalizedQuote, ...]) -> None:
    if not run.quote_run_uid.strip():
        raise ValueError("quote_run_uid is required")
    if not run.provider.strip() or not run.connection_uid.strip():
        raise ValueError("provider and connection_uid are required")
    if not run.adapter_version.strip():
        raise ValueError("adapter_version is required")
    if run.requested_instrument_count < 0:
        raise ValueError("requested_instrument_count must not be negative")
    if run.requested_instrument_count < len(quotes):
        raise ValueError("received quotes exceed requested instrument count")
    if run.status != "ok":
        raise ValueError("only fully validated status=ok quote batches may be persisted")
    _utc_text(run.completed_at, "completed_at")
    _utc_text(run.started_at, "started_at")
    if run.completed_at.astimezone(UTC) < run.started_at.astimezone(UTC):
        raise ValueError("completed_at must not precede started_at")

    seen: set[str] = set()
    for quote in quotes:
        validate_normalized_quote(quote)
        if quote.quote_uid != build_quote_uid(quote):
            raise ValueError(f"quote_uid does not match canonical identity: {quote.quote_uid}")
        if quote.quote_uid in seen:
            raise ValueError(f"duplicate quote_uid in batch: {quote.quote_uid}")
        seen.add(quote.quote_uid)
        if quote.provider != run.provider:
            raise ValueError(f"quote provider differs from run: {quote.quote_uid}")
        if quote.connection_uid != run.connection_uid:
            raise ValueError(f"quote connection differs from run: {quote.quote_uid}")
        if quote.asof != run.asof:
            raise ValueError(f"quote asof differs from run: {quote.quote_uid}")
        if quote.adapter_version != run.adapter_version:
            raise ValueError(f"quote adapter version differs from run: {quote.quote_uid}")


def _quote_insert_rows(
    quote_run_uid: str,
    quotes: tuple[NormalizedQuote, ...],
) -> list[list[object]]:
    return [
        [
            quote.quote_uid,
            quote_run_uid,
            quote.provider,
            quote.connection_uid,
            quote.instrument_key,
            quote.provider_instrument_id,
            quote.symbol,
            quote.asset_class,
            quote.currency,
            quote.bid,
            quote.ask,
            quote.last,
            _utc_text(quote.provider_quote_at, "provider_quote_at"),
            _utc_text(quote.received_at, "received_at"),
            quote.market_session,
            quote.data_mode,
            quote.entitlement_status,
            quote.asof,
            quote.raw_path,
            quote.raw_sha256,
            quote.adapter_version,
        ]
        for quote in quotes
    ]


def _insert_quotes(
    con: duckdb.DuckDBPyConnection,
    quote_run_uid: str,
    quotes: tuple[NormalizedQuote, ...],
) -> None:
    if not quotes:
        return
    con.executemany(
        """
        INSERT INTO normalized_market_quotes (
            quote_uid, quote_run_uid, provider, connection_uid,
            instrument_key, provider_instrument_id, symbol, asset_class,
            currency, bid, ask, last_price, provider_quote_at_utc,
            received_at_utc, market_session, data_mode,
            entitlement_status, asof_date, raw_path, raw_sha256,
            adapter_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        _quote_insert_rows(quote_run_uid, quotes),
    )


def persist_quote_batch(
    db_path: Path,
    run: QuoteIngestionRun,
    quotes: tuple[NormalizedQuote, ...],
) -> int:
    """Persist one validated batch atomically and idempotently.

    The caller must apply migration 0011 first. Existing run identities are
    accepted only when their stored input fingerprint matches exactly.
    """

    _validate_run(run, quotes)
    fingerprint = _quote_fingerprint(quotes)
    con = duckdb.connect(str(db_path))
    try:
        con.execute("BEGIN TRANSACTION")
        existing = con.execute(
            "SELECT input_fingerprint FROM market_quote_ingestion_runs WHERE quote_run_uid = ?",
            [run.quote_run_uid],
        ).fetchone()
        if existing is not None:
            if existing[0] != fingerprint:
                raise ValueError(
                    f"quote run identity conflict for {run.quote_run_uid}: input changed"
                )
            persisted = con.execute(
                "SELECT COUNT(*) FROM normalized_market_quotes WHERE quote_run_uid = ?",
                [run.quote_run_uid],
            ).fetchone()[0]
            if persisted != len(quotes):
                raise ValueError(
                    f"quote run {run.quote_run_uid} is incomplete: expected {len(quotes)}, found {persisted}"
                )
            con.execute("COMMIT")
            return int(persisted)

        con.execute(
            """
            INSERT INTO market_quote_ingestion_runs (
                quote_run_uid, provider, connection_uid, asof_date,
                started_at_utc, completed_at_utc, requested_instrument_count,
                received_quote_count, accepted_quote_count, rejected_quote_count,
                input_fingerprint, adapter_version, status, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                run.quote_run_uid,
                run.provider,
                run.connection_uid,
                run.asof,
                _utc_text(run.started_at, "started_at"),
                _utc_text(run.completed_at, "completed_at"),
                run.requested_instrument_count,
                len(quotes),
                len(quotes),
                0,
                fingerprint,
                run.adapter_version,
                run.status,
                run.notes,
            ],
        )
        _insert_quotes(con, run.quote_run_uid, quotes)
        con.execute("COMMIT")
        return len(quotes)
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def persist_quote_capture(
    db_path: Path,
    capture: QuoteCaptureEnvelope,
    *,
    policy: QuoteFreshnessPolicy,
) -> int:
    """Persist one complete provider-neutral capture atomically and idempotently.

    Migration 0012 must be applied first. Failed or partial connector results do
    not cross this boundary; callers retain them as audit failures outside the
    accepted normalized-quote tables.
    """

    validate_quote_capture(capture, policy=policy)
    fingerprint = build_quote_capture_fingerprint(capture)
    scope_json = request_scope_json(capture)
    quotes = capture.quotes
    con = duckdb.connect(str(db_path))
    try:
        con.execute("BEGIN TRANSACTION")
        existing = con.execute(
            """
            SELECT input_fingerprint, ingestion_contract_version
            FROM market_quote_ingestion_runs
            WHERE quote_run_uid = ?
            """,
            [capture.quote_run_uid],
        ).fetchone()
        if existing is not None:
            if existing != (fingerprint, capture.contract_version):
                raise ValueError(
                    f"quote capture identity conflict for {capture.quote_run_uid}: envelope changed"
                )
            stored_quote_uids = {
                row[0]
                for row in con.execute(
                    "SELECT quote_uid FROM normalized_market_quotes WHERE quote_run_uid = ?",
                    [capture.quote_run_uid],
                ).fetchall()
            }
            expected_quote_uids = {quote.quote_uid for quote in quotes}
            if stored_quote_uids != expected_quote_uids:
                raise ValueError(
                    f"quote capture {capture.quote_run_uid} has incomplete normalized rows"
                )
            con.execute("COMMIT")
            return len(stored_quote_uids)

        duplicate = con.execute(
            """
            SELECT quote_uid, quote_run_uid
            FROM normalized_market_quotes
            WHERE quote_uid IN (SELECT UNNEST(?))
            """,
            [[quote.quote_uid for quote in quotes]],
        ).fetchall()
        if duplicate:
            quote_uid, existing_run_uid = duplicate[0]
            raise ValueError(
                f"quote identity {quote_uid} already belongs to run {existing_run_uid}"
            )

        con.execute(
            """
            INSERT INTO market_quote_ingestion_runs (
                quote_run_uid, provider, connection_uid, asof_date,
                started_at_utc, completed_at_utc, requested_instrument_count,
                received_quote_count, accepted_quote_count, rejected_quote_count,
                input_fingerprint, adapter_version, status, notes,
                ingestion_contract_version, received_at_utc, request_scope_json,
                source_storage_kind, source_locator, source_raw_sha256
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                capture.quote_run_uid,
                capture.provider,
                capture.connection_uid,
                capture.asof,
                _utc_text(capture.started_at, "started_at"),
                _utc_text(capture.evaluated_at, "evaluated_at"),
                len(capture.requests),
                len(quotes),
                len(quotes),
                0,
                fingerprint,
                capture.adapter_version,
                "ok",
                None,
                capture.contract_version,
                _utc_text(capture.received_at, "received_at"),
                scope_json,
                capture.source.storage_kind,
                capture.source.locator,
                capture.source.raw_sha256,
            ],
        )
        _insert_quotes(con, capture.quote_run_uid, quotes)
        con.execute("COMMIT")
        return len(quotes)
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def _parse_utc_text(value: str, field_name: str) -> datetime:
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid stored {field_name}: {value}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"stored {field_name} must include a timezone")
    return parsed.astimezone(UTC)


def load_latest_quotes(
    db_path: Path,
    *,
    provider: str,
    connection_uid: str,
    instrument_keys: tuple[str, ...],
    asof: date,
) -> tuple[NormalizedQuote, ...]:
    """Read the latest normalized quote per requested instrument and date.

    Selection never falls back to another provider, connection, or market
    date. Missing instruments remain missing so the downstream freshness and
    valuation boundary can fail closed.
    """

    provider = provider.strip()
    connection_uid = connection_uid.strip()
    if not provider or not connection_uid:
        raise ValueError("provider and connection_uid are required")
    if not instrument_keys:
        return ()
    if any(not key.strip() for key in instrument_keys):
        raise ValueError("instrument_keys must not contain blank values")
    if len(set(instrument_keys)) != len(instrument_keys):
        raise ValueError("instrument_keys must be unique")

    placeholders = ", ".join("?" for _ in instrument_keys)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        rows = con.execute(
            f"""
            WITH ranked AS (
                SELECT
                    quote_uid, provider, connection_uid, instrument_key,
                    provider_instrument_id, symbol, asset_class, currency,
                    bid, ask, last_price, provider_quote_at_utc,
                    received_at_utc, market_session, data_mode,
                    entitlement_status, asof_date, raw_path, raw_sha256,
                    adapter_version,
                    ROW_NUMBER() OVER (
                        PARTITION BY instrument_key
                        ORDER BY provider_quote_at_utc DESC,
                                 received_at_utc DESC,
                                 quote_uid DESC
                    ) AS rn
                FROM normalized_market_quotes
                WHERE provider = ?
                  AND connection_uid = ?
                  AND asof_date = ?
                  AND instrument_key IN ({placeholders})
            )
            SELECT
                quote_uid, provider, connection_uid, instrument_key,
                provider_instrument_id, symbol, asset_class, currency,
                bid, ask, last_price, provider_quote_at_utc,
                received_at_utc, market_session, data_mode,
                entitlement_status, asof_date, raw_path, raw_sha256,
                adapter_version
            FROM ranked
            WHERE rn = 1
            ORDER BY instrument_key
            """,
            [provider, connection_uid, asof, *instrument_keys],
        ).fetchall()
    finally:
        con.close()

    quotes = tuple(
        NormalizedQuote(
            quote_uid=row[0],
            provider=row[1],
            connection_uid=row[2],
            instrument_key=row[3],
            provider_instrument_id=row[4],
            symbol=row[5],
            asset_class=row[6],
            currency=row[7],
            bid=row[8],
            ask=row[9],
            last=row[10],
            provider_quote_at=_parse_utc_text(row[11], "provider_quote_at_utc"),
            received_at=_parse_utc_text(row[12], "received_at_utc"),
            market_session=row[13],
            data_mode=row[14],
            entitlement_status=row[15],
            asof=row[16],
            raw_path=row[17],
            raw_sha256=row[18],
            adapter_version=row[19],
        )
        for row in rows
    )
    for quote in quotes:
        validate_normalized_quote(quote)
    return quotes
