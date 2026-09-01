"""Owner-private Schwab account binding without provider capability.

The canonical bytes bind an opaque OneJournal account identity to the Schwab
account hash and account number needed to validate already acquired provider
evidence.  This module has no filesystem, network, credential, database, or
process capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re


SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA = "onejournal.schwab-account-private-binding.v1"

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,127}")
_ACCOUNT_HASH = re.compile(r"[A-Za-z0-9._~-]{1,512}")
_SAFE_ACCOUNT_NUMBER = re.compile(r"[^\x00-\x1f\x7f]{1,256}")
_ROOT_FIELDS = {
    "schema",
    "connection_uid",
    "source_account_id",
    "provider_account_hash",
    "provider_account_number",
}


class SchwabAccountPrivateBindingError(ValueError):
    """Raised when owner-private account binding bytes are invalid."""


@dataclass(frozen=True)
class SchwabAccountPrivateBinding:
    schema: str
    connection_uid: str
    source_account_id: str
    provider_account_hash: str
    provider_account_number: str


def _safe_id(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise SchwabAccountPrivateBindingError(f"{field} is invalid")
    return value


def _account_hash(value: object) -> str:
    if not isinstance(value, str) or not _ACCOUNT_HASH.fullmatch(value):
        raise SchwabAccountPrivateBindingError("provider_account_hash is invalid")
    return value


def _account_number(value: object) -> str:
    if not isinstance(value, str) or not _SAFE_ACCOUNT_NUMBER.fullmatch(value.strip()):
        raise SchwabAccountPrivateBindingError("provider_account_number is invalid")
    return value.strip()


def _document(binding: SchwabAccountPrivateBinding) -> dict[str, str]:
    return {
        "schema": binding.schema,
        "connection_uid": binding.connection_uid,
        "source_account_id": binding.source_account_id,
        "provider_account_hash": binding.provider_account_hash,
        "provider_account_number": binding.provider_account_number,
    }


def load_schwab_account_private_binding_bytes(
    body: bytes,
) -> SchwabAccountPrivateBinding:
    """Load exact canonical owner-private binding bytes in memory."""

    if not isinstance(body, bytes) or not body:
        raise SchwabAccountPrivateBindingError("private account binding bytes are invalid")
    try:
        document = json.loads(
            body.decode("utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SchwabAccountPrivateBindingError(
            "private account binding is not finite JSON"
        ) from exc
    if not isinstance(document, dict) or set(document) != _ROOT_FIELDS:
        raise SchwabAccountPrivateBindingError(
            "private account binding fields do not match the contract"
        )
    if document["schema"] != SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA:
        raise SchwabAccountPrivateBindingError(
            "private account binding schema is unsupported"
        )
    binding = SchwabAccountPrivateBinding(
        schema=SCHWAB_ACCOUNT_PRIVATE_BINDING_SCHEMA,
        connection_uid=_safe_id(document["connection_uid"], "connection_uid"),
        source_account_id=_safe_id(document["source_account_id"], "source_account_id"),
        provider_account_hash=_account_hash(document["provider_account_hash"]),
        provider_account_number=_account_number(document["provider_account_number"]),
    )
    canonical = (
        json.dumps(_document(binding), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if body != canonical:
        raise SchwabAccountPrivateBindingError(
            "private account binding bytes are not canonical"
        )
    return binding


def schwab_account_private_binding_bytes(binding: SchwabAccountPrivateBinding) -> bytes:
    """Serialize canonical owner-private binding bytes."""

    body = (
        json.dumps(_document(binding), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if load_schwab_account_private_binding_bytes(body) != binding:
        raise SchwabAccountPrivateBindingError(
            "private account binding object is not canonical"
        )
    return body


def schwab_account_private_binding_sha256(body: bytes) -> str:
    load_schwab_account_private_binding_bytes(body)
    return sha256(body).hexdigest()
