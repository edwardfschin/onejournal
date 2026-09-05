"""Provider-neutral validation for immutable quote-capture envelopes.

Provider connectors may acquire evidence, and provider adapters may normalize
it, but neither concern belongs in this module. This boundary accepts only an
already captured, checksum-bound batch and proves that its identity, timing,
request scope, and normalized records are internally consistent before a
repository writer may persist it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from typing import Literal
from zoneinfo import ZoneInfo

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.market_data.quotes import (
    QuoteFreshnessPolicy,
    build_quote_uid,
    validate_normalized_quote,
)


CAPTURE_CONTRACT_VERSION = "onejournal.market-data.quote-capture.v1"
INITIAL_MARKET_TIMEZONE = ZoneInfo("America/New_York")
_MACHINE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_PROVIDER_RE = re.compile(r"[a-z][a-z0-9_]*")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class QuoteCaptureContractError(ValueError):
    """Raised when a quote capture cannot safely cross the ingestion boundary."""


@dataclass(frozen=True)
class QuoteInstrumentRequest:
    """Explicit provider-to-OneJournal identity requested from a connector."""

    instrument_key: str
    provider_instrument_id: str
    asset_class: str
    currency: str


@dataclass(frozen=True)
class QuoteEvidenceSource:
    """Checksum-bound locator relative to an approved local evidence root."""

    storage_kind: Literal["odfs_raw", "external_private_vault"]
    locator: str
    raw_sha256: str


@dataclass(frozen=True)
class QuoteCaptureEnvelope:
    """Complete accepted quote batch produced before durable ingestion."""

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
    quotes: tuple[NormalizedQuote, ...]
    contract_version: str = CAPTURE_CONTRACT_VERSION


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise QuoteCaptureContractError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _required(value: str, field_name: str) -> str:
    if not isinstance(value, str) or value != value.strip() or not value:
        raise QuoteCaptureContractError(f"{field_name} must be a non-empty trimmed string")
    return value


def _validate_source(source: QuoteEvidenceSource, provider: str) -> None:
    if source.storage_kind not in {"odfs_raw", "external_private_vault"}:
        raise QuoteCaptureContractError(f"unsupported source storage_kind: {source.storage_kind}")
    locator_text = _required(source.locator, "source.locator").replace("\\", "/")
    locator = PurePosixPath(locator_text)
    if locator.is_absolute() or ".." in locator.parts or locator_text in {".", ""}:
        raise QuoteCaptureContractError("source.locator must be a safe relative path")
    if source.storage_kind == "odfs_raw":
        expected = ("data", "raw", provider)
        if locator.parts[:3] != expected:
            raise QuoteCaptureContractError(
                f"odfs_raw source.locator must be below data/raw/{provider}"
            )
    if not isinstance(source.raw_sha256, str) or not _DIGEST_RE.fullmatch(
        source.raw_sha256
    ):
        raise QuoteCaptureContractError("source.raw_sha256 must be a lowercase SHA-256 digest")


def _validate_request(request: QuoteInstrumentRequest) -> None:
    _required(request.instrument_key, "request.instrument_key")
    _required(request.provider_instrument_id, "request.provider_instrument_id")
    asset_class = _required(request.asset_class, "request.asset_class")
    if asset_class not in {"stock", "option"}:
        raise QuoteCaptureContractError("request.asset_class must be stock or option")
    permitted_prefixes = (
        ("stock|", "instrument.v1|equity|")
        if asset_class == "stock"
        else ("option|", "instrument.v1|option|")
    )
    if not request.instrument_key.startswith(permitted_prefixes):
        raise QuoteCaptureContractError(
            "request.instrument_key must use the matching legacy or canonical "
            f"{asset_class} identity prefix"
        )
    if not re.fullmatch(r"[A-Z]{3}", request.currency):
        raise QuoteCaptureContractError("request.currency must be an uppercase ISO code")


def validate_quote_capture(
    capture: QuoteCaptureEnvelope,
    *,
    policy: QuoteFreshnessPolicy,
) -> None:
    """Validate a complete batch without calling a provider or writing state."""

    if capture.contract_version != CAPTURE_CONTRACT_VERSION:
        raise QuoteCaptureContractError("unsupported quote-capture contract_version")
    if not _MACHINE_ID_RE.fullmatch(capture.quote_run_uid):
        raise QuoteCaptureContractError("quote_run_uid must be an opaque machine identifier")
    if not _PROVIDER_RE.fullmatch(capture.provider):
        raise QuoteCaptureContractError("provider must be a lowercase machine identifier")
    if not _MACHINE_ID_RE.fullmatch(capture.connection_uid):
        raise QuoteCaptureContractError("connection_uid must be an opaque machine identifier")
    _required(capture.adapter_version, "adapter_version")
    _validate_source(capture.source, capture.provider)

    started_at = _utc(capture.started_at, "started_at")
    received_at = _utc(capture.received_at, "received_at")
    evaluated_at = _utc(capture.evaluated_at, "evaluated_at")
    if not started_at <= received_at <= evaluated_at:
        raise QuoteCaptureContractError(
            "capture times must satisfy started_at <= received_at <= evaluated_at"
        )

    if not capture.requests:
        raise QuoteCaptureContractError("at least one explicit instrument request is required")
    request_by_key: dict[str, QuoteInstrumentRequest] = {}
    provider_ids: set[str] = set()
    for request in capture.requests:
        _validate_request(request)
        if request.instrument_key in request_by_key:
            raise QuoteCaptureContractError(
                f"duplicate requested instrument_key: {request.instrument_key}"
            )
        if request.provider_instrument_id in provider_ids:
            raise QuoteCaptureContractError(
                f"duplicate requested provider_instrument_id: {request.provider_instrument_id}"
            )
        request_by_key[request.instrument_key] = request
        provider_ids.add(request.provider_instrument_id)

    quote_by_key: dict[str, NormalizedQuote] = {}
    for quote in capture.quotes:
        validate_normalized_quote(quote)
        if quote.quote_uid != build_quote_uid(quote):
            raise QuoteCaptureContractError(
                f"quote_uid does not match canonical identity: {quote.quote_uid}"
            )
        if quote.instrument_key in quote_by_key:
            raise QuoteCaptureContractError(
                f"duplicate normalized instrument_key: {quote.instrument_key}"
            )
        quote_by_key[quote.instrument_key] = quote

        if quote.provider != capture.provider:
            raise QuoteCaptureContractError("quote provider differs from capture")
        if quote.connection_uid != capture.connection_uid:
            raise QuoteCaptureContractError("quote connection differs from capture")
        if quote.asof != capture.asof:
            raise QuoteCaptureContractError("quote asof differs from capture")
        if quote.adapter_version != capture.adapter_version:
            raise QuoteCaptureContractError("quote adapter version differs from capture")
        if quote.raw_sha256 != capture.source.raw_sha256:
            raise QuoteCaptureContractError("quote raw digest differs from capture source")
        if _utc(quote.received_at, "quote.received_at") != received_at:
            raise QuoteCaptureContractError("quote received_at differs from capture")

        quote_at = _utc(quote.provider_quote_at, "quote.provider_quote_at")
        if (
            quote_at > received_at
            and (quote_at - received_at).total_seconds() > policy.future_tolerance_seconds
        ):
            raise QuoteCaptureContractError(
                "provider quote time exceeds received_at future tolerance"
            )
        if quote_at.astimezone(INITIAL_MARKET_TIMEZONE).date() != capture.asof:
            raise QuoteCaptureContractError(
                "quote provider time does not match the America/New_York market date"
            )

    if set(quote_by_key) != set(request_by_key):
        missing = sorted(set(request_by_key) - set(quote_by_key))
        unexpected = sorted(set(quote_by_key) - set(request_by_key))
        raise QuoteCaptureContractError(
            f"quote capture scope mismatch; missing={missing}, unexpected={unexpected}"
        )
    for instrument_key, request in request_by_key.items():
        quote = quote_by_key[instrument_key]
        if (
            quote.provider_instrument_id != request.provider_instrument_id
            or quote.asset_class != request.asset_class
            or quote.currency != request.currency
        ):
            raise QuoteCaptureContractError(
                f"normalized identity differs from request: {instrument_key}"
            )


def _json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _utc(value, "fingerprint timestamp").isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    return value


def request_scope_json(capture: QuoteCaptureEnvelope) -> str:
    """Return stable request-scope JSON for private DuckDB audit storage."""

    rows = sorted(
        (asdict(request) for request in capture.requests),
        key=lambda row: (row["instrument_key"], row["provider_instrument_id"]),
    )
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def build_quote_capture_fingerprint(capture: QuoteCaptureEnvelope) -> str:
    """Fingerprint the full capture envelope and every normalized quote field."""

    payload = {
        "contract_version": capture.contract_version,
        "quote_run_uid": capture.quote_run_uid,
        "provider": capture.provider,
        "connection_uid": capture.connection_uid,
        "asof": capture.asof.isoformat(),
        "started_at": _utc(capture.started_at, "started_at").isoformat(),
        "received_at": _utc(capture.received_at, "received_at").isoformat(),
        "evaluated_at": _utc(capture.evaluated_at, "evaluated_at").isoformat(),
        "requests": json.loads(request_scope_json(capture)),
        "source": asdict(capture.source),
        "adapter_version": capture.adapter_version,
        "quotes": [],
    }
    for quote in capture.quotes:
        row = {key: _json_value(value) for key, value in asdict(quote).items()}
        payload["quotes"].append(row)
    payload["quotes"] = sorted(
        payload["quotes"], key=lambda row: (row["instrument_key"], row["quote_uid"])
    )
    digest = sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return f"{CAPTURE_CONTRACT_VERSION}:{digest}"
