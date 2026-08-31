"""Private, credential-free account and identity binding for PNL-03H.

This module parses canonical bytes supplied by an owner-only operator.  It has
no filesystem, provider, credential, database, or process capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
import re

from onejournal.brokers.schwab.positions_json import SchwabPositionMapping
from onejournal.instruments import InstrumentIdentity, InstrumentIdentityError


SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA = "onejournal.schwab-position-private-binding.v1"
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}")
_ACCOUNT_HASH = re.compile(r"[A-Za-z0-9._~-]{1,512}")
_SAFE_ACCOUNT_NUMBER = re.compile(r"[^\x00-\x1f\x7f]{1,256}")
_ROOT_FIELDS = {
    "schema",
    "connection_uid",
    "source_account_id",
    "provider_account_hash",
    "provider_account_number",
    "mappings",
}
_MAPPING_FIELDS = {"provider_symbol", "identity"}


class SchwabPositionPrivateBindingError(ValueError):
    """Raised when owner-only position binding bytes are invalid or unsafe."""


@dataclass(frozen=True)
class SchwabPositionPrivateBinding:
    """Private account binding plus exact provider-to-canonical mappings."""

    schema: str
    connection_uid: str
    source_account_id: str
    provider_account_hash: str
    provider_account_number: str
    mappings: tuple[SchwabPositionMapping, ...]


def _fields(row: object, expected: set[str], field: str) -> dict[str, object]:
    if not isinstance(row, dict) or set(row) != expected:
        raise SchwabPositionPrivateBindingError(f"{field} fields do not match the contract")
    return row


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise SchwabPositionPrivateBindingError(f"{field} is invalid")
    return value


def _account_hash(value: object) -> str:
    if not isinstance(value, str) or not _ACCOUNT_HASH.fullmatch(value):
        raise SchwabPositionPrivateBindingError("provider_account_hash is invalid")
    return value


def _account_number(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_ACCOUNT_NUMBER.fullmatch(value.strip()):
        raise SchwabPositionPrivateBindingError("provider_account_number is invalid")
    return value.strip()


def _decimal(value: object, field: str) -> Decimal:
    if not isinstance(value, str):
        raise SchwabPositionPrivateBindingError(f"{field} must be an exact decimal string")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise SchwabPositionPrivateBindingError(f"{field} is invalid") from exc
    if not parsed.is_finite():
        raise SchwabPositionPrivateBindingError(f"{field} is invalid")
    return parsed


def _identity_document(identity: InstrumentIdentity) -> dict[str, str]:
    if identity.asset_class == "equity":
        return {
            "asset_class": "equity",
            "market_scope": identity.market_scope,
            "currency": identity.currency,
            "symbol": identity.symbol or "",
        }
    return {
        "asset_class": "option",
        "market_scope": identity.market_scope,
        "currency": identity.currency,
        "underlying_symbol": identity.underlying_symbol or "",
        "expiry": identity.expiry.isoformat() if identity.expiry else "",
        "option_right": identity.option_right or "",
        "strike": format(identity.strike, "f") if identity.strike else "",
        "multiplier": format(identity.multiplier, "f") if identity.multiplier else "",
    }


def _identity(value: object, field: str) -> InstrumentIdentity:
    if not isinstance(value, dict):
        raise SchwabPositionPrivateBindingError(f"{field} must be an object")
    asset_class = value.get("asset_class")
    if asset_class == "equity":
        row = _fields(
            value,
            {"asset_class", "market_scope", "currency", "symbol"},
            field,
        )
        try:
            return InstrumentIdentity(
                asset_class="equity",
                market_scope=str(row["market_scope"]),
                currency=str(row["currency"]),
                symbol=str(row["symbol"]),
            )
        except InstrumentIdentityError as exc:
            raise SchwabPositionPrivateBindingError(f"{field} is invalid") from exc
    if asset_class == "option":
        row = _fields(
            value,
            {
                "asset_class",
                "market_scope",
                "currency",
                "underlying_symbol",
                "expiry",
                "option_right",
                "strike",
                "multiplier",
            },
            field,
        )
        try:
            expiry = date.fromisoformat(str(row["expiry"]))
            return InstrumentIdentity(
                asset_class="option",
                market_scope=str(row["market_scope"]),
                currency=str(row["currency"]),
                underlying_symbol=str(row["underlying_symbol"]),
                expiry=expiry,
                option_right=str(row["option_right"]),
                strike=_decimal(row["strike"], f"{field}.strike"),
                multiplier=_decimal(row["multiplier"], f"{field}.multiplier"),
            )
        except (InstrumentIdentityError, ValueError) as exc:
            raise SchwabPositionPrivateBindingError(f"{field} is invalid") from exc
    raise SchwabPositionPrivateBindingError(f"{field}.asset_class is unsupported")


def _document(binding: SchwabPositionPrivateBinding) -> dict[str, object]:
    return {
        "schema": binding.schema,
        "connection_uid": binding.connection_uid,
        "source_account_id": binding.source_account_id,
        "provider_account_hash": binding.provider_account_hash,
        "provider_account_number": binding.provider_account_number,
        "mappings": [
            {
                "provider_symbol": mapping.provider_symbol,
                "identity": _identity_document(mapping.identity),
            }
            for mapping in binding.mappings
        ],
    }


def schwab_position_private_binding_bytes(binding: SchwabPositionPrivateBinding) -> bytes:
    """Serialize canonical private binding bytes for owner-only storage."""

    document = _document(binding)
    parsed = load_schwab_position_private_binding_bytes(
        (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )
    )
    if parsed != binding:
        raise SchwabPositionPrivateBindingError("binding object is not canonical")
    return (
        json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")


def load_schwab_position_private_binding_bytes(
    body: bytes,
) -> SchwabPositionPrivateBinding:
    """Load exact canonical owner-only binding bytes without filesystem access."""

    if not isinstance(body, bytes) or not body:
        raise SchwabPositionPrivateBindingError("private binding bytes are invalid")
    try:
        document = json.loads(
            body.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SchwabPositionPrivateBindingError("private binding is not finite JSON") from exc
    row = _fields(document, _ROOT_FIELDS, "private binding")
    if row["schema"] != SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA:
        raise SchwabPositionPrivateBindingError("private binding schema is unsupported")
    mappings_value = row["mappings"]
    if not isinstance(mappings_value, list):
        raise SchwabPositionPrivateBindingError("mappings must be an array")
    mappings: list[SchwabPositionMapping] = []
    provider_symbols: set[str] = set()
    identity_keys: set[str] = set()
    for index, mapping_value in enumerate(mappings_value):
        mapping_row = _fields(mapping_value, _MAPPING_FIELDS, f"mappings[{index}]")
        try:
            mapping = SchwabPositionMapping(
                provider_symbol=mapping_row["provider_symbol"],
                identity=_identity(mapping_row["identity"], f"mappings[{index}].identity"),
            )
        except (TypeError, ValueError) as exc:
            raise SchwabPositionPrivateBindingError(
                f"mappings[{index}] is invalid"
            ) from exc
        if mapping.provider_symbol in provider_symbols or mapping.identity.key in identity_keys:
            raise SchwabPositionPrivateBindingError("mappings must be unique")
        provider_symbols.add(mapping.provider_symbol)
        identity_keys.add(mapping.identity.key)
        mappings.append(mapping)
    binding = SchwabPositionPrivateBinding(
        schema=SCHWAB_POSITION_PRIVATE_BINDING_SCHEMA,
        connection_uid=_safe_id(row["connection_uid"], "connection_uid"),
        source_account_id=_safe_id(row["source_account_id"], "source_account_id"),
        provider_account_hash=_account_hash(row["provider_account_hash"]),
        provider_account_number=_account_number(row["provider_account_number"]),
        mappings=tuple(mappings),
    )
    canonical = (
        json.dumps(_document(binding), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if body != canonical:
        raise SchwabPositionPrivateBindingError("private binding bytes are not canonical")
    return binding


def schwab_position_private_binding_sha256(body: bytes) -> str:
    """Return the safe digest after canonical binding validation."""

    load_schwab_position_private_binding_bytes(body)
    return sha256(body).hexdigest()
