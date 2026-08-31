"""Credential-free Schwab account-position intake for PNL-03.

The adapter accepts already captured response bytes and explicit OneJournal
identity mappings.  It has no provider, credential, persistence, or order
capability.  Provider symbols and option terms never become canonical identity
by inference.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import parse_qsl, unquote, urlsplit
from zoneinfo import ZoneInfo

from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.position_reconciliation import (
    BrokerPositionRecord,
    BrokerPositionSnapshot,
)


ADAPTER_VERSION = "schwab-position-json-v1"
SCHWAB_TRADER_HOST = "api.schwabapi.com"
_ACCOUNT_PATH_RE = re.compile(r"/trader/v1/accounts/([A-Za-z0-9._~-]{1,512})")
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_PROVIDER_SYMBOL_RE = re.compile(r"[^\x00-\x1f\x7f]{1,128}")
_SAFE_VALUE_RE = re.compile(r"[^\x00-\x1f\x7f]{1,256}")
_NEW_YORK = ZoneInfo("America/New_York")


class SchwabPositionAdapterError(ValueError):
    """Raised when position evidence is incomplete or ambiguous."""


@dataclass(frozen=True)
class SchwabPositionMapping:
    """Explicit provider symbol to canonical instrument identity mapping."""

    provider_symbol: str
    identity: InstrumentIdentity

    def __post_init__(self) -> None:
        symbol = _provider_symbol(self.provider_symbol, "provider_symbol")
        object.__setattr__(self, "provider_symbol", symbol)


@dataclass(frozen=True)
class SchwabPositionCaptureContext:
    """Verified request and source facts needed to assert account completeness."""

    request_url: str
    provider_account_hash_sha256: str
    provider_account_number: str
    connection_uid: str
    source_account_id: str
    asof: date
    retrieved_at: datetime
    raw_path: str
    raw_sha256: str
    method: str = "GET"
    status_code: int = 200
    content_type: str = "application/json"
    attempt_count: int = 1
    redirect_count: int = 0

    def __post_init__(self) -> None:
        if self.method != "GET":
            raise SchwabPositionAdapterError("position acquisition method must be GET")
        if self.status_code != 200:
            raise SchwabPositionAdapterError("position acquisition must have HTTP status 200")
        if self.content_type.split(";", 1)[0].strip().lower() != "application/json":
            raise SchwabPositionAdapterError("position acquisition must be application/json")
        if self.attempt_count != 1 or self.redirect_count != 0:
            raise SchwabPositionAdapterError(
                "position acquisition requires one attempt and zero redirects"
            )
        if not _DIGEST_RE.fullmatch(self.provider_account_hash_sha256):
            raise SchwabPositionAdapterError(
                "provider_account_hash_sha256 must be lowercase SHA-256"
            )
        if not _DIGEST_RE.fullmatch(self.raw_sha256):
            raise SchwabPositionAdapterError("raw_sha256 must be lowercase SHA-256")
        account_number = _safe_value(
            self.provider_account_number, "provider_account_number"
        )
        connection_uid = _safe_value(self.connection_uid, "connection_uid")
        source_account_id = _safe_value(self.source_account_id, "source_account_id")
        raw_path = _safe_value(self.raw_path, "raw_path")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise SchwabPositionAdapterError("retrieved_at must include a timezone")
        retrieved_at = self.retrieved_at.astimezone(UTC)
        if retrieved_at.astimezone(_NEW_YORK).date() != self.asof:
            raise SchwabPositionAdapterError(
                "asof must equal the New York market date at retrieval"
            )

        try:
            parsed = urlsplit(self.request_url)
            parsed_port = parsed.port
        except ValueError as exc:
            raise SchwabPositionAdapterError(
                "position request URL is outside the allowlist"
            ) from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != SCHWAB_TRADER_HOST
            or parsed_port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise SchwabPositionAdapterError("position request URL is outside the allowlist")
        path_match = _ACCOUNT_PATH_RE.fullmatch(parsed.path)
        if path_match is None:
            raise SchwabPositionAdapterError("position request path is outside the allowlist")
        account_hash = unquote(path_match.group(1))
        if sha256(account_hash.encode("utf-8")).hexdigest() != self.provider_account_hash_sha256:
            raise SchwabPositionAdapterError("position request account-hash binding failed")
        if parse_qsl(parsed.query, keep_blank_values=True) != [("fields", "positions")]:
            raise SchwabPositionAdapterError(
                "position request query must be exactly fields=positions"
            )

        object.__setattr__(self, "provider_account_number", account_number)
        object.__setattr__(self, "connection_uid", connection_uid)
        object.__setattr__(self, "source_account_id", source_account_id)
        object.__setattr__(self, "raw_path", raw_path)
        object.__setattr__(self, "retrieved_at", retrieved_at)


def _safe_value(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not _SAFE_VALUE_RE.fullmatch(value.strip()):
        raise SchwabPositionAdapterError(f"{field_name} is required and invalid")
    return value.strip()


def _provider_symbol(value: Any, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchwabPositionAdapterError(f"{field_name} must be a provider symbol")
    symbol = value.strip().upper()
    if not _PROVIDER_SYMBOL_RE.fullmatch(symbol):
        raise SchwabPositionAdapterError(f"{field_name} must be a provider symbol")
    return symbol


def _account_number(value: Any) -> str:
    if isinstance(value, bool):
        raise SchwabPositionAdapterError("securitiesAccount.accountNumber is invalid")
    if isinstance(value, str):
        return _safe_value(value, "securitiesAccount.accountNumber")
    if isinstance(value, (int, Decimal)):
        parsed = value if isinstance(value, Decimal) else Decimal(value)
        if parsed.is_finite() and parsed >= 0 and parsed == parsed.to_integral_value():
            return format(parsed, "f")
    raise SchwabPositionAdapterError("securitiesAccount.accountNumber is invalid")


def _decimal(
    value: Any,
    field_name: str,
    *,
    required: bool = False,
    non_negative: bool = False,
) -> Decimal | None:
    if value is None:
        if required:
            raise SchwabPositionAdapterError(f"{field_name} is required")
        return None
    if isinstance(value, (bool, float, str)):
        raise SchwabPositionAdapterError(
            f"{field_name} must use exact JSON decimal or integer input"
        )
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise SchwabPositionAdapterError(f"{field_name} is not decimal-safe") from exc
    if not parsed.is_finite() or (non_negative and parsed < 0):
        requirement = "finite and non-negative" if non_negative else "finite"
        raise SchwabPositionAdapterError(f"{field_name} must be {requirement}")
    return parsed


def load_positions_json(path: Path) -> dict[str, Any]:
    """Load an already captured Schwab account-position response."""

    return load_positions_json_bytes(path.read_bytes())


def load_positions_json_bytes(body: bytes) -> dict[str, Any]:
    """Load exact-decimal JSON from immutable response bytes."""

    if not isinstance(body, bytes) or not body:
        raise SchwabPositionAdapterError(
            "Schwab position response body must be non-empty bytes"
        )
    try:
        payload = json.loads(
            body.decode("utf-8"),
            parse_float=Decimal,
            parse_constant=lambda value: (_ for _ in ()).throw(
                SchwabPositionAdapterError(f"invalid non-finite JSON number: {value}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SchwabPositionAdapterError("Schwab positions JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise SchwabPositionAdapterError(
            "Schwab positions JSON must be a top-level object"
        )
    return payload


def _option_identity_matches(
    instrument: Mapping[str, Any], identity: InstrumentIdentity, field_name: str
) -> None:
    if _provider_symbol(instrument.get("underlyingSymbol"), f"{field_name}.underlyingSymbol") != identity.underlying_symbol:
        raise SchwabPositionAdapterError(f"{field_name} underlying mapping mismatch")
    right = _safe_value(instrument.get("putCall"), f"{field_name}.putCall").upper()
    if right != identity.option_right:
        raise SchwabPositionAdapterError(f"{field_name} option-right mapping mismatch")
    expiry_value = instrument.get("expirationDate")
    if not isinstance(expiry_value, str):
        raise SchwabPositionAdapterError(f"{field_name}.expirationDate is required")
    try:
        expiry = date.fromisoformat(expiry_value)
    except ValueError as exc:
        raise SchwabPositionAdapterError(
            f"{field_name}.expirationDate must be YYYY-MM-DD"
        ) from exc
    if expiry != identity.expiry:
        raise SchwabPositionAdapterError(f"{field_name} expiry mapping mismatch")
    strike = _decimal(
        instrument.get("strikePrice"), f"{field_name}.strikePrice", required=True,
        non_negative=True,
    )
    if strike != identity.strike:
        raise SchwabPositionAdapterError(f"{field_name} strike mapping mismatch")


def _position_record(
    item: Mapping[str, Any], mapping: SchwabPositionMapping, index: int
) -> BrokerPositionRecord:
    field = f"positions[{index}]"
    instrument = item.get("instrument")
    if not isinstance(instrument, Mapping):
        raise SchwabPositionAdapterError(f"{field}.instrument must be an object")
    provider_symbol = _provider_symbol(instrument.get("symbol"), f"{field}.instrument.symbol")
    if provider_symbol != mapping.provider_symbol:
        raise SchwabPositionAdapterError(f"{field} provider-symbol mapping mismatch")
    provider_asset_type = _safe_value(
        instrument.get("assetType"), f"{field}.instrument.assetType"
    ).upper()
    expected_asset_type = "EQUITY" if mapping.identity.asset_class == "equity" else "OPTION"
    if provider_asset_type != expected_asset_type:
        raise SchwabPositionAdapterError(f"{field} asset-class mapping mismatch")
    if mapping.identity.asset_class == "option":
        _option_identity_matches(instrument, mapping.identity, f"{field}.instrument")

    long_quantity = _decimal(
        item.get("longQuantity"), f"{field}.longQuantity", required=True,
        non_negative=True,
    )
    short_quantity = _decimal(
        item.get("shortQuantity"), f"{field}.shortQuantity", required=True,
        non_negative=True,
    )
    if long_quantity > 0 and short_quantity > 0:
        raise SchwabPositionAdapterError(
            f"{field} cannot net simultaneous long and short quantities"
        )
    quantity = long_quantity - short_quantity
    if quantity == 0:
        raise SchwabPositionAdapterError(f"{field} must be an open non-zero position")

    average_cost = _decimal(
        item.get("averagePrice"), f"{field}.averagePrice", non_negative=True
    )
    market_value = _decimal(item.get("marketValue"), f"{field}.marketValue")
    generic_open_pnl = _decimal(item.get("openProfitLoss"), f"{field}.openProfitLoss")
    long_open_pnl = _decimal(
        item.get("longOpenProfitLoss"), f"{field}.longOpenProfitLoss"
    )
    short_open_pnl = _decimal(
        item.get("shortOpenProfitLoss"), f"{field}.shortOpenProfitLoss"
    )
    if quantity > 0:
        open_pnl = long_open_pnl if long_open_pnl is not None else generic_open_pnl
        opposite_pnl = short_open_pnl
    else:
        open_pnl = short_open_pnl if short_open_pnl is not None else generic_open_pnl
        opposite_pnl = long_open_pnl
    direction_pnl = long_open_pnl if quantity > 0 else short_open_pnl
    if (
        direction_pnl is not None
        and generic_open_pnl is not None
        and direction_pnl != generic_open_pnl
    ):
        raise SchwabPositionAdapterError(
            f"{field} contains conflicting open profit/loss fields"
        )
    if opposite_pnl not in {None, Decimal("0")}:
        raise SchwabPositionAdapterError(
            f"{field} contains non-zero opposite-direction profit/loss"
        )

    return BrokerPositionRecord(
        identity=mapping.identity,
        quantity=quantity,
        broker_average_cost=average_cost,
        broker_market_value=market_value,
        broker_unrealized_pnl=open_pnl,
    )


def broker_position_snapshot_from_bytes(
    body: bytes,
    *,
    context: SchwabPositionCaptureContext,
    mappings: tuple[SchwabPositionMapping, ...],
) -> BrokerPositionSnapshot:
    """Validate one exact complete account response and normalize its positions."""

    observed_digest = sha256(body).hexdigest() if isinstance(body, bytes) else ""
    if observed_digest != context.raw_sha256:
        raise SchwabPositionAdapterError("position response checksum mismatch")
    payload = load_positions_json_bytes(body)
    securities_account = payload.get("securitiesAccount")
    if not isinstance(securities_account, Mapping):
        raise SchwabPositionAdapterError("securitiesAccount object is required")
    if _account_number(securities_account.get("accountNumber")) != context.provider_account_number:
        raise SchwabPositionAdapterError("position response account binding failed")
    if "positions" not in securities_account or not isinstance(
        securities_account.get("positions"), list
    ):
        raise SchwabPositionAdapterError(
            "securitiesAccount.positions must be an explicit complete list"
        )
    positions = securities_account["positions"]
    if any(not isinstance(item, Mapping) for item in positions):
        raise SchwabPositionAdapterError("every position must be an object")

    mapping_by_symbol: dict[str, SchwabPositionMapping] = {}
    identity_keys: set[str] = set()
    for mapping in mappings:
        if mapping.provider_symbol in mapping_by_symbol:
            raise SchwabPositionAdapterError("duplicate provider-symbol mapping")
        if mapping.identity.key in identity_keys:
            raise SchwabPositionAdapterError("duplicate canonical instrument mapping")
        mapping_by_symbol[mapping.provider_symbol] = mapping
        identity_keys.add(mapping.identity.key)

    indexed_positions: dict[str, tuple[int, Mapping[str, Any]]] = {}
    for index, item in enumerate(positions):
        instrument = item.get("instrument")
        if not isinstance(instrument, Mapping):
            raise SchwabPositionAdapterError(
                f"positions[{index}].instrument must be an object"
            )
        symbol = _provider_symbol(
            instrument.get("symbol"), f"positions[{index}].instrument.symbol"
        )
        if symbol in indexed_positions:
            raise SchwabPositionAdapterError("duplicate provider position symbol")
        indexed_positions[symbol] = (index, item)
    if set(indexed_positions) != set(mapping_by_symbol):
        missing = len(set(indexed_positions) - set(mapping_by_symbol))
        unexpected = len(set(mapping_by_symbol) - set(indexed_positions))
        raise SchwabPositionAdapterError(
            "position mapping scope mismatch; "
            f"unmapped_response_count={missing}, unused_mapping_count={unexpected}"
        )

    records = tuple(
        _position_record(indexed_positions[symbol][1], mapping_by_symbol[symbol], indexed_positions[symbol][0])
        for symbol in sorted(indexed_positions)
    )
    identity_document = {
        "adapter_version": ADAPTER_VERSION,
        "asof": context.asof.isoformat(),
        "connection_uid": context.connection_uid,
        "provider_account_hash_sha256": context.provider_account_hash_sha256,
        "raw_sha256": context.raw_sha256,
        "retrieved_at": context.retrieved_at.isoformat(),
        "source_account_id": context.source_account_id,
    }
    snapshot_uid = "broker-position-snapshot:" + sha256(
        json.dumps(identity_document, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return BrokerPositionSnapshot(
        snapshot_uid=snapshot_uid,
        source_broker="schwab",
        connection_uid=context.connection_uid,
        source_account_id=context.source_account_id,
        asof=context.asof,
        retrieved_at=context.retrieved_at,
        raw_path=context.raw_path,
        raw_sha256=context.raw_sha256,
        account_complete=True,
        adapter_version=ADAPTER_VERSION,
        positions=records,
        provider_observed_at=None,
    )
