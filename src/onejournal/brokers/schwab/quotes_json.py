"""Fail-closed normalization for Schwab market-data quote JSON.

This module never performs network, credential, database, or order operations.
It accepts an already-captured response and an explicit OneJournal instrument
mapping. The mapping is deliberately supplied by the caller; provider symbols,
asset classes, currencies, and market sessions are not inferred.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re
from typing import Any, Mapping

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.market_data.quotes import build_quote_uid, validate_normalized_quote


ADAPTER_VERSION = "schwab-quote-json-v1"

_INSTRUMENT_KEY_RE = re.compile(r"[^\x00-\x1f\x7f]{1,512}")
_PROVIDER_SYMBOL_RE = re.compile(r"[^\x00-\x1f\x7f,]{1,64}")

_ASSET_CLASS_BY_PROVIDER_TYPE = {
    "EQUITY": "stock",
    "OPTION": "option",
}
_MARKET_SESSION_BY_PROVIDER_VALUE = {
    "REGULAR": "regular",
    "PRE_MARKET": "pre_market",
    "PREMARKET": "pre_market",
    "AFTER_HOURS": "after_hours",
    "POST_MARKET": "after_hours",
    "POSTMARKET": "after_hours",
    "CLOSED": "closed",
    "UNKNOWN": "unknown",
}


class SchwabQuoteAdapterError(ValueError):
    """Raised when a Schwab quote payload cannot be normalized safely."""


@dataclass(frozen=True)
class SchwabQuoteRequest:
    """Explicit provider-to-OneJournal identity mapping for one quote."""

    provider_symbol: str
    instrument_key: str
    asset_class: str
    currency: str

    def __post_init__(self) -> None:
        provider_symbol = self.provider_symbol.strip()
        instrument_key = self.instrument_key.strip()
        asset_class = self.asset_class.strip().lower()
        currency = self.currency.strip().upper()
        if not provider_symbol:
            raise SchwabQuoteAdapterError("provider_symbol is required")
        if not _PROVIDER_SYMBOL_RE.fullmatch(provider_symbol):
            raise SchwabQuoteAdapterError(
                "provider_symbol must be 1-64 characters without commas or controls"
            )
        if not instrument_key:
            raise SchwabQuoteAdapterError("instrument_key is required")
        if not _INSTRUMENT_KEY_RE.fullmatch(instrument_key):
            raise SchwabQuoteAdapterError(
                "instrument_key must be 1-512 characters without control characters"
            )
        if asset_class not in {"stock", "option"}:
            raise SchwabQuoteAdapterError(
                "asset_class must be an explicitly mapped stock or option"
            )
        if not instrument_key.startswith(asset_class + "|"):
            raise SchwabQuoteAdapterError(
                f"instrument_key must use the {asset_class}| prefix"
            )
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise SchwabQuoteAdapterError(
                "currency must be an explicit three-letter alphabetic code"
            )
        object.__setattr__(self, "provider_symbol", provider_symbol)
        object.__setattr__(self, "instrument_key", instrument_key)
        object.__setattr__(self, "asset_class", asset_class)
        object.__setattr__(self, "currency", currency)


def load_quotes_json(path: Path) -> dict[str, Any]:
    """Load exact-decimal Schwab quote JSON from an already captured file."""

    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_float=Decimal,
        parse_constant=lambda value: (_ for _ in ()).throw(
            SchwabQuoteAdapterError(f"invalid non-finite JSON number: {value}")
        ),
    )
    if not isinstance(payload, dict):
        raise SchwabQuoteAdapterError("Schwab quotes JSON must be a top-level object")
    return payload


def _symbol_key(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SchwabQuoteAdapterError(f"{field_name} must be a non-empty string")
    return value.strip().upper()


def _decimal_or_none(value: Any, field_name: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (bool, float)):
        raise SchwabQuoteAdapterError(
            f"{field_name} must use exact JSON decimal or integer input"
        )
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SchwabQuoteAdapterError(f"{field_name} is not decimal-safe") from exc
    if not parsed.is_finite() or parsed < 0:
        raise SchwabQuoteAdapterError(
            f"{field_name} must be finite and non-negative"
        )
    return parsed


def _epoch_millis(value: Any, field_name: str) -> datetime:
    if isinstance(value, bool):
        raise SchwabQuoteAdapterError(f"{field_name} must be integer epoch milliseconds")
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise SchwabQuoteAdapterError(
            f"{field_name} must be integer epoch milliseconds"
        ) from exc
    if not parsed.is_finite() or parsed < 0 or parsed != parsed.to_integral_value():
        raise SchwabQuoteAdapterError(
            f"{field_name} must be non-negative integer epoch milliseconds"
        )
    return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=int(parsed))


def _market_session(item: Mapping[str, Any], quote: Mapping[str, Any]) -> str:
    raw_value = quote.get("marketSession", item.get("marketSession"))
    if raw_value is None:
        return "unknown"
    if not isinstance(raw_value, str):
        raise SchwabQuoteAdapterError("marketSession must be a string when present")
    mapped = _MARKET_SESSION_BY_PROVIDER_VALUE.get(raw_value.strip().upper())
    if mapped is None:
        raise SchwabQuoteAdapterError(
            f"unsupported provider marketSession: {raw_value!r}"
        )
    return mapped


def _payload_by_symbol(payload: Mapping[str, Any]) -> dict[str, tuple[str, Any]]:
    indexed: dict[str, tuple[str, Any]] = {}
    for raw_key, item in payload.items():
        symbol_key = _symbol_key(raw_key, "top-level quote key")
        if symbol_key in indexed:
            raise SchwabQuoteAdapterError(
                f"duplicate case-insensitive provider symbol: {symbol_key}"
            )
        indexed[symbol_key] = (str(raw_key), item)
    return indexed


def normalized_quotes_from_payload(
    payload: Mapping[str, Any],
    *,
    requests: tuple[SchwabQuoteRequest, ...],
    connection_uid: str,
    asof: date,
    received_at: datetime,
    raw_path: str,
    raw_sha256: str,
) -> tuple[NormalizedQuote, ...]:
    """Normalize an exact, explicitly bounded Schwab quote response.

    The response must contain exactly the requested provider symbols. A missing
    or unexpected symbol rejects the batch so a broader response cannot silently
    enter evidence. Absence of a provider-declared market session is preserved
    as ``unknown`` and therefore fails the downstream freshness gate.
    """

    if not isinstance(payload, Mapping):
        raise SchwabQuoteAdapterError("Schwab quotes payload must be an object")
    if not requests:
        raise SchwabQuoteAdapterError("at least one explicit quote request is required")
    if received_at.tzinfo is None or received_at.utcoffset() is None:
        raise SchwabQuoteAdapterError("received_at must include a timezone")

    request_by_symbol: dict[str, SchwabQuoteRequest] = {}
    instrument_keys: set[str] = set()
    for request in requests:
        symbol_key = _symbol_key(request.provider_symbol, "provider_symbol")
        if symbol_key in request_by_symbol:
            raise SchwabQuoteAdapterError(f"duplicate requested symbol: {symbol_key}")
        if request.instrument_key in instrument_keys:
            raise SchwabQuoteAdapterError(
                f"duplicate requested instrument_key: {request.instrument_key}"
            )
        request_by_symbol[symbol_key] = request
        instrument_keys.add(request.instrument_key)

    payload_by_symbol = _payload_by_symbol(payload)
    requested_symbols = set(request_by_symbol)
    returned_symbols = set(payload_by_symbol)
    if returned_symbols != requested_symbols:
        missing = sorted(requested_symbols - returned_symbols)
        unexpected = sorted(returned_symbols - requested_symbols)
        raise SchwabQuoteAdapterError(
            f"quote response scope mismatch; missing={missing}, unexpected={unexpected}"
        )

    normalized: list[NormalizedQuote] = []
    for symbol_key in sorted(request_by_symbol):
        request = request_by_symbol[symbol_key]
        _raw_key, item = payload_by_symbol[symbol_key]
        if not isinstance(item, Mapping):
            raise SchwabQuoteAdapterError(f"quote item for {symbol_key} must be an object")

        provider_symbol = _symbol_key(item.get("symbol"), f"{symbol_key}.symbol")
        if provider_symbol != symbol_key:
            raise SchwabQuoteAdapterError(
                f"provider symbol mismatch for {symbol_key}: {provider_symbol}"
            )

        provider_asset_type = _symbol_key(
            item.get("assetMainType"), f"{symbol_key}.assetMainType"
        )
        asset_class = _ASSET_CLASS_BY_PROVIDER_TYPE.get(provider_asset_type)
        if asset_class is None:
            raise SchwabQuoteAdapterError(
                f"unsupported Schwab assetMainType: {provider_asset_type}"
            )
        if asset_class != request.asset_class:
            raise SchwabQuoteAdapterError(
                f"asset-class mapping mismatch for {symbol_key}: "
                f"provider={asset_class}, requested={request.asset_class}"
            )

        realtime = item.get("realtime")
        if not isinstance(realtime, bool):
            raise SchwabQuoteAdapterError(
                f"{symbol_key}.realtime must be an explicit boolean"
            )
        data_mode = "real_time" if realtime else "delayed"
        entitlement_status = "entitled" if realtime else "delayed"

        quote = item.get("quote")
        if not isinstance(quote, Mapping):
            raise SchwabQuoteAdapterError(f"{symbol_key}.quote must be an object")
        security_status = quote.get("securityStatus")
        if security_status is not None and (
            not isinstance(security_status, str)
            or security_status.strip().upper() != "NORMAL"
        ):
            raise SchwabQuoteAdapterError(
                f"{symbol_key}.securityStatus is not NORMAL"
            )

        candidate = NormalizedQuote(
            quote_uid="pending",
            provider="schwab",
            connection_uid=connection_uid,
            instrument_key=request.instrument_key,
            provider_instrument_id=request.provider_symbol,
            symbol=provider_symbol,
            asset_class=asset_class,
            currency=request.currency,
            bid=_decimal_or_none(quote.get("bidPrice"), f"{symbol_key}.bidPrice"),
            ask=_decimal_or_none(quote.get("askPrice"), f"{symbol_key}.askPrice"),
            last=_decimal_or_none(quote.get("lastPrice"), f"{symbol_key}.lastPrice"),
            provider_quote_at=_epoch_millis(
                quote.get("quoteTime"), f"{symbol_key}.quoteTime"
            ),
            received_at=received_at.astimezone(UTC),
            market_session=_market_session(item, quote),
            data_mode=data_mode,
            entitlement_status=entitlement_status,
            asof=asof,
            raw_path=raw_path,
            raw_sha256=raw_sha256,
            adapter_version=ADAPTER_VERSION,
        )
        candidate = replace(candidate, quote_uid=build_quote_uid(candidate))
        validate_normalized_quote(candidate)
        normalized.append(candidate)

    return tuple(normalized)
