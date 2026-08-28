"""Canonical private serialization for durable quote-capture recovery.

The artifact contains only the already normalized, provider-independent capture
envelope. Exact provider response bytes remain a separate immutable private file.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Mapping

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.market_data.ingestion import (
    QuoteCaptureEnvelope,
    QuoteEvidenceSource,
    QuoteInstrumentRequest,
)


QUOTE_CAPTURE_ARTIFACT_SCHEMA = "onejournal.market-data.quote-capture-artifact.v1"
MAX_QUOTE_CAPTURE_ARTIFACT_BYTES = 2 * 1024 * 1024


class QuoteCaptureArtifactError(ValueError):
    """Raised when a durable private capture artifact is not canonical."""


def _utc_text(value: datetime, field: str) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise QuoteCaptureArtifactError(f"{field} must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise QuoteCaptureArtifactError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise QuoteCaptureArtifactError(f"{field} is not a valid timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise QuoteCaptureArtifactError(f"{field} must include a timezone")
    return parsed.astimezone(UTC)


def _mapping(value: object, field: str, keys: set[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise QuoteCaptureArtifactError(f"{field} fields do not match the contract")
    return value


def _string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise QuoteCaptureArtifactError(f"{field} must be a string")
    return value


def _date(value: object, field: str) -> date:
    try:
        return date.fromisoformat(_string(value, field))
    except ValueError as exc:
        raise QuoteCaptureArtifactError(f"{field} is not a valid date") from exc


def _decimal(value: object, field: str) -> Decimal | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise QuoteCaptureArtifactError(f"{field} must be a decimal string or null")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise QuoteCaptureArtifactError(f"{field} is not a valid decimal") from exc
    if not parsed.is_finite():
        raise QuoteCaptureArtifactError(f"{field} must be finite")
    return parsed


def quote_capture_artifact_bytes(capture: QuoteCaptureEnvelope) -> bytes:
    """Return deterministic JSON bytes for one provider-neutral capture."""

    quotes: list[dict[str, object]] = []
    for quote in capture.quotes:
        row = asdict(quote)
        for field in ("bid", "ask", "last"):
            value = row[field]
            row[field] = None if value is None else format(value, "f")
        row["provider_quote_at"] = _utc_text(
            quote.provider_quote_at, "quote.provider_quote_at"
        )
        row["received_at"] = _utc_text(quote.received_at, "quote.received_at")
        row["asof"] = quote.asof.isoformat()
        quotes.append(row)
    payload = {
        "schema": QUOTE_CAPTURE_ARTIFACT_SCHEMA,
        "capture_contract_version": capture.contract_version,
        "quote_run_uid": capture.quote_run_uid,
        "provider": capture.provider,
        "connection_uid": capture.connection_uid,
        "asof": capture.asof.isoformat(),
        "started_at": _utc_text(capture.started_at, "started_at"),
        "received_at": _utc_text(capture.received_at, "received_at"),
        "evaluated_at": _utc_text(capture.evaluated_at, "evaluated_at"),
        "requests": [asdict(request) for request in capture.requests],
        "source": asdict(capture.source),
        "adapter_version": capture.adapter_version,
        "quotes": quotes,
    }
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(body) > MAX_QUOTE_CAPTURE_ARTIFACT_BYTES:
        raise QuoteCaptureArtifactError("quote capture artifact exceeds the size limit")
    return body


def load_quote_capture_artifact_bytes(body: bytes) -> QuoteCaptureEnvelope:
    """Reconstruct one capture from strict deterministic private JSON."""

    if not isinstance(body, bytes) or not body:
        raise QuoteCaptureArtifactError("quote capture artifact must be non-empty bytes")
    if len(body) > MAX_QUOTE_CAPTURE_ARTIFACT_BYTES:
        raise QuoteCaptureArtifactError("quote capture artifact exceeds the size limit")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QuoteCaptureArtifactError("quote capture artifact is not valid JSON") from exc
    payload = _mapping(
        payload,
        "artifact",
        {
            "schema",
            "capture_contract_version",
            "quote_run_uid",
            "provider",
            "connection_uid",
            "asof",
            "started_at",
            "received_at",
            "evaluated_at",
            "requests",
            "source",
            "adapter_version",
            "quotes",
        },
    )
    if payload["schema"] != QUOTE_CAPTURE_ARTIFACT_SCHEMA:
        raise QuoteCaptureArtifactError("unsupported quote capture artifact schema")
    raw_requests = payload["requests"]
    raw_quotes = payload["quotes"]
    if not isinstance(raw_requests, list) or not isinstance(raw_quotes, list):
        raise QuoteCaptureArtifactError("artifact requests and quotes must be arrays")

    requests = tuple(
        QuoteInstrumentRequest(
            **_mapping(
                item,
                f"requests[{index}]",
                {"instrument_key", "provider_instrument_id", "asset_class", "currency"},
            )
        )
        for index, item in enumerate(raw_requests)
    )
    source_row = _mapping(
        payload["source"],
        "source",
        {"storage_kind", "locator", "raw_sha256"},
    )
    source = QuoteEvidenceSource(
        storage_kind=_string(source_row["storage_kind"], "source.storage_kind"),  # type: ignore[arg-type]
        locator=_string(source_row["locator"], "source.locator"),
        raw_sha256=_string(source_row["raw_sha256"], "source.raw_sha256"),
    )

    quote_fields = {
        "quote_uid",
        "provider",
        "connection_uid",
        "instrument_key",
        "provider_instrument_id",
        "symbol",
        "asset_class",
        "currency",
        "bid",
        "ask",
        "last",
        "provider_quote_at",
        "received_at",
        "market_session",
        "data_mode",
        "entitlement_status",
        "asof",
        "raw_path",
        "raw_sha256",
        "adapter_version",
    }
    quotes: list[NormalizedQuote] = []
    for index, item in enumerate(raw_quotes):
        row = _mapping(item, f"quotes[{index}]", quote_fields)
        quotes.append(
            NormalizedQuote(
                quote_uid=_string(row["quote_uid"], "quote.quote_uid"),
                provider=_string(row["provider"], "quote.provider"),
                connection_uid=_string(row["connection_uid"], "quote.connection_uid"),
                instrument_key=_string(row["instrument_key"], "quote.instrument_key"),
                provider_instrument_id=_string(
                    row["provider_instrument_id"], "quote.provider_instrument_id"
                ),
                symbol=_string(row["symbol"], "quote.symbol"),
                asset_class=_string(row["asset_class"], "quote.asset_class"),
                currency=_string(row["currency"], "quote.currency"),
                bid=_decimal(row["bid"], "quote.bid"),
                ask=_decimal(row["ask"], "quote.ask"),
                last=_decimal(row["last"], "quote.last"),
                provider_quote_at=_parse_utc(
                    row["provider_quote_at"], "quote.provider_quote_at"
                ),
                received_at=_parse_utc(row["received_at"], "quote.received_at"),
                market_session=_string(row["market_session"], "quote.market_session"),
                data_mode=_string(row["data_mode"], "quote.data_mode"),
                entitlement_status=_string(
                    row["entitlement_status"], "quote.entitlement_status"
                ),
                asof=_date(row["asof"], "quote.asof"),
                raw_path=_string(row["raw_path"], "quote.raw_path"),
                raw_sha256=_string(row["raw_sha256"], "quote.raw_sha256"),
                adapter_version=_string(row["adapter_version"], "quote.adapter_version"),
            )
        )

    return QuoteCaptureEnvelope(
        contract_version=_string(
            payload["capture_contract_version"], "capture_contract_version"
        ),
        quote_run_uid=_string(payload["quote_run_uid"], "quote_run_uid"),
        provider=_string(payload["provider"], "provider"),
        connection_uid=_string(payload["connection_uid"], "connection_uid"),
        asof=_date(payload["asof"], "asof"),
        started_at=_parse_utc(payload["started_at"], "started_at"),
        received_at=_parse_utc(payload["received_at"], "received_at"),
        evaluated_at=_parse_utc(payload["evaluated_at"], "evaluated_at"),
        requests=requests,
        source=source,
        adapter_version=_string(payload["adapter_version"], "adapter_version"),
        quotes=tuple(quotes),
    )
