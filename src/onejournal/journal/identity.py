"""Identity helpers for normalized event replay and dedupe checks.

These helpers support CON-05 and provide stable, deterministic behavior for
replayed normalized fill evidence.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from onejournal.brokers.normalized import NormalizedFill


IdentityKey = tuple[str, str, str]


def build_fill_identity_key(fill: NormalizedFill) -> IdentityKey:
    """Build the stable natural key used by normalized fill replay logic."""

    return (fill.source_broker, fill.source_account_id, fill.source_fill_id)


def build_fill_identity_signature(fill: NormalizedFill) -> tuple[Any, ...]:
    """Build a deterministic signature from normalized fill economics.

    Two fills with the same identity key but different signatures represent a
    true correction/revision rather than idempotent duplicate re-delivery.
    """

    payload = asdict(fill)
    # `fill_uid` is derived and intentionally excluded from signature checks.
    payload.pop("fill_uid", None)
    payload.pop("raw_path", None)
    payload.pop("fetched_at", None)

    # Normalize dictionary key order and nested types so equivalent values
    # produce stable signatures.
    return tuple(
        _normalize_signature_value(payload[field])
        for field in sorted(payload)
    )


def _normalize_signature_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.12g}"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "normalize"):
        # Decimal-like types normalize numeric scale to avoid false drift from
        # textual formatting differences.
        try:
            return str(value.normalize())
        except Exception:
            return str(value)
    return str(value)


def dedupe_identical_fills(
    fills: list[NormalizedFill],
    *,
    allow_conflicts: bool = False,
) -> list[NormalizedFill]:
    """Deduplicate redelivered fills by identity key.

    Returns the input fills list with identical-by-key-and-signature duplicates
    collapsed to one copy while rejecting conflicting payload changes.
    """

    signature_by_key: dict[IdentityKey, tuple[Any, ...]] = {}
    deduped: list[NormalizedFill] = []
    for fill in fills:
        key = build_fill_identity_key(fill)
        signature = build_fill_identity_signature(fill)
        previous_signature = signature_by_key.get(key)
        if previous_signature is None:
            signature_by_key[key] = signature
            deduped.append(fill)
            continue

        if previous_signature == signature:
            continue

        if allow_conflicts:
            signature_by_key[key] = signature
            deduped.append(fill)
            continue

        raise ValueError(
            f"conflicting normalized fill payload for identity key {key}: "
            f"signature changed across replayed records"
        )

    return deduped


def conflicting_fill_identity_report(fills: list[NormalizedFill]) -> list[str]:
    """Return descriptive conflict messages for conflicting identity payloads."""

    seen: dict[IdentityKey, tuple[Any, ...]] = {}
    conflicts: list[str] = []
    for fill in fills:
        key = build_fill_identity_key(fill)
        signature = build_fill_identity_signature(fill)
        previous_signature = seen.get(key)
        if previous_signature is None:
            seen[key] = signature
            continue
        if previous_signature != signature:
            conflicts.append(f"{key}: changed payload across identity key")
    return sorted(set(conflicts))
