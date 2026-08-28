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
    QuoteEvidenceSource,
    QuoteInstrumentRequest,
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


@dataclass(frozen=True)
class QuotePersistenceResult:
    """Atomic write outcome, including whether the capture was an exact replay."""

    persisted_quote_count: int
    was_replay: bool


@dataclass(frozen=True)
class QuoteCaptureReadBack:
    """Exact-run database evidence after persistence.

    Decimal values are compared semantically by callers because DuckDB's fixed
    scale adds trailing zeroes on read-back without changing financial value.
    """

    quote_run_uid: str
    provider: str
    connection_uid: str
    asof: date
    started_at: datetime
    received_at: datetime
    evaluated_at: datetime
    requests: tuple[QuoteInstrumentRequest, ...]
    source: QuoteEvidenceSource
    adapter_version: str
    contract_version: str
    input_fingerprint: str
    quotes: tuple[NormalizedQuote, ...]


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


def persist_quote_capture_result(
    db_path: Path,
    capture: QuoteCaptureEnvelope,
    *,
    policy: QuoteFreshnessPolicy,
) -> QuotePersistenceResult:
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
            return QuotePersistenceResult(
                persisted_quote_count=len(stored_quote_uids),
                was_replay=True,
            )

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
        return QuotePersistenceResult(
            persisted_quote_count=len(quotes),
            was_replay=False,
        )
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
    """Compatibility wrapper returning only the accepted normalized-row count."""

    return persist_quote_capture_result(
        db_path,
        capture,
        policy=policy,
    ).persisted_quote_count


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


def _quote_from_row(row: tuple[object, ...]) -> NormalizedQuote:
    return NormalizedQuote(
        quote_uid=str(row[0]),
        provider=str(row[1]),
        connection_uid=str(row[2]),
        instrument_key=str(row[3]),
        provider_instrument_id=str(row[4]),
        symbol=str(row[5]),
        asset_class=str(row[6]),
        currency=str(row[7]),
        bid=row[8],  # type: ignore[arg-type]
        ask=row[9],  # type: ignore[arg-type]
        last=row[10],  # type: ignore[arg-type]
        provider_quote_at=_parse_utc_text(str(row[11]), "provider_quote_at_utc"),
        received_at=_parse_utc_text(str(row[12]), "received_at_utc"),
        market_session=str(row[13]),
        data_mode=str(row[14]),
        entitlement_status=str(row[15]),
        asof=row[16],  # type: ignore[arg-type]
        raw_path=str(row[17]),
        raw_sha256=str(row[18]),
        adapter_version=str(row[19]),
    )


def load_quote_capture_run(
    db_path: Path,
    *,
    quote_run_uid: str,
    provider: str,
    connection_uid: str,
    asof: date,
    policy: QuoteFreshnessPolicy,
) -> QuoteCaptureReadBack:
    """Reconstruct and validate one exact persisted capture without fallback."""

    for value, field in (
        (quote_run_uid, "quote_run_uid"),
        (provider, "provider"),
        (connection_uid, "connection_uid"),
    ):
        if not isinstance(value, str) or not value.strip() or value != value.strip():
            raise ValueError(f"{field} must be a non-empty trimmed string")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        run = con.execute(
            """
            SELECT quote_run_uid, provider, connection_uid, asof_date,
                   started_at_utc, received_at_utc, completed_at_utc,
                   requested_instrument_count, received_quote_count,
                   accepted_quote_count, rejected_quote_count,
                   input_fingerprint, adapter_version, status,
                   ingestion_contract_version, request_scope_json,
                   source_storage_kind, source_locator, source_raw_sha256
            FROM market_quote_ingestion_runs
            WHERE quote_run_uid = ? AND provider = ? AND connection_uid = ?
              AND asof_date = ?
            """,
            [quote_run_uid, provider, connection_uid, asof],
        ).fetchone()
        if run is None:
            raise ValueError("exact scoped quote capture run was not found")
        quote_rows = con.execute(
            """
            SELECT quote_uid, provider, connection_uid, instrument_key,
                   provider_instrument_id, symbol, asset_class, currency,
                   bid, ask, last_price, provider_quote_at_utc,
                   received_at_utc, market_session, data_mode,
                   entitlement_status, asof_date, raw_path, raw_sha256,
                   adapter_version
            FROM normalized_market_quotes
            WHERE quote_run_uid = ?
            ORDER BY instrument_key, quote_uid
            """,
            [quote_run_uid],
        ).fetchall()
    finally:
        con.close()

    if run[13] != "ok" or run[14] is None:
        raise ValueError("stored quote capture run is not an accepted envelope")
    if any(run[index] is None for index in (5, 15, 16, 17, 18)):
        raise ValueError("stored quote capture run is missing required lineage")
    try:
        request_rows = json.loads(str(run[15]))
    except json.JSONDecodeError as exc:
        raise ValueError("stored quote capture request scope is invalid JSON") from exc
    if not isinstance(request_rows, list):
        raise ValueError("stored quote capture request scope must be an array")
    required_request_fields = {
        "instrument_key",
        "provider_instrument_id",
        "asset_class",
        "currency",
    }
    requests = []
    for row in request_rows:
        if not isinstance(row, dict) or set(row) != required_request_fields:
            raise ValueError("stored quote capture request scope fields are invalid")
        requests.append(
            QuoteInstrumentRequest(
                instrument_key=str(row["instrument_key"]),
                provider_instrument_id=str(row["provider_instrument_id"]),
                asset_class=str(row["asset_class"]),
                currency=str(row["currency"]),
            )
        )
    quotes = tuple(_quote_from_row(row) for row in quote_rows)
    expected_count = len(quotes)
    if (
        run[7] != len(requests)
        or run[8] != expected_count
        or run[9] != expected_count
        or run[10] != 0
    ):
        raise ValueError("stored quote capture audit counts are inconsistent")
    read_back = QuoteCaptureReadBack(
        quote_run_uid=str(run[0]),
        provider=str(run[1]),
        connection_uid=str(run[2]),
        asof=run[3],
        started_at=_parse_utc_text(str(run[4]), "started_at_utc"),
        received_at=_parse_utc_text(str(run[5]), "received_at_utc"),
        evaluated_at=_parse_utc_text(str(run[6]), "completed_at_utc"),
        requests=tuple(requests),
        source=QuoteEvidenceSource(
            storage_kind=str(run[16]),  # type: ignore[arg-type]
            locator=str(run[17]),
            raw_sha256=str(run[18]),
        ),
        adapter_version=str(run[12]),
        quotes=quotes,
        contract_version=str(run[14]),
        input_fingerprint=str(run[11]),
    )
    for quote in read_back.quotes:
        validate_normalized_quote(quote)
        if (
            quote.provider != read_back.provider
            or quote.connection_uid != read_back.connection_uid
            or quote.asof != read_back.asof
            or quote.adapter_version != read_back.adapter_version
            or quote.raw_sha256 != read_back.source.raw_sha256
            or quote.received_at != read_back.received_at
        ):
            raise ValueError("stored normalized quote differs from its ingestion run")
    request_keys = {request.instrument_key for request in read_back.requests}
    quote_keys = {quote.instrument_key for quote in read_back.quotes}
    if (
        len(request_keys) != len(read_back.requests)
        or len(quote_keys) != len(read_back.quotes)
    ):
        raise ValueError("stored quote capture contains duplicate instrument scope")
    if request_keys != quote_keys:
        raise ValueError("stored quote capture scope is incomplete")
    for request in read_back.requests:
        quote = next(
            item for item in read_back.quotes if item.instrument_key == request.instrument_key
        )
        if (
            quote.provider_instrument_id != request.provider_instrument_id
            or quote.asset_class != request.asset_class
            or quote.currency != request.currency
        ):
            raise ValueError("stored normalized quote identity differs from request scope")
    return read_back


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

    quotes = tuple(_quote_from_row(row) for row in rows)
    for quote in quotes:
        validate_normalized_quote(quote)
    return quotes
