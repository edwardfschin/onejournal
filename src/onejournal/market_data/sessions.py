"""Provider-neutral, point-in-time market-session authority contract.

This module does not select or call a calendar provider.  It validates a
session observation supplied by a separately approved resolver and binds that
observation to one instrument and one freshness-evaluation instant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


SESSION_AUTHORITY_CONTRACT_VERSION = "onejournal.market-session-authority.v1"
SUPPORTED_AUTHORITY_SESSIONS = {
    "pre_market",
    "regular",
    "after_hours",
    "closed",
}
SUPPORTED_TRADING_DAY_KINDS = {
    "regular",
    "early_close",
    "holiday",
    "unscheduled_closure",
}


class SessionAuthorityError(ValueError):
    """Raised when supplied session authority is ambiguous or mismatched."""


@dataclass(frozen=True)
class MarketSessionAuthority:
    """Authoritative session state for one instrument at one instant.

    ``phase_started_at`` and ``phase_ends_at`` use a half-open interval.  The
    source validity window is separate so a stale resolver result cannot be
    reused merely because its phase interval still contains the evaluation.
    """

    authority_uid: str
    instrument_key: str
    venue_id: str
    calendar_id: str
    venue_timezone: str
    market_date: date
    evaluated_at: datetime
    market_session: Literal["pre_market", "regular", "after_hours", "closed"]
    trading_day_kind: Literal[
        "regular", "early_close", "holiday", "unscheduled_closure"
    ]
    phase_started_at: datetime
    phase_ends_at: datetime
    resolved_at: datetime
    valid_until: datetime
    source: str
    source_version: str
    contract_version: str = SESSION_AUTHORITY_CONTRACT_VERSION


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SessionAuthorityError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _machine_id(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value
    ):
        raise SessionAuthorityError(
            f"{field_name} must be a non-empty machine identifier"
        )
    return value


def _instrument_key(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:|/-]{0,255}", value
    ):
        raise SessionAuthorityError(
            "instrument_key must be an explicit broker-independent identifier"
        )
    return value


def _authority_payload(authority: MarketSessionAuthority) -> dict[str, str]:
    return {
        "contract_version": authority.contract_version,
        "instrument_key": authority.instrument_key,
        "venue_id": authority.venue_id,
        "calendar_id": authority.calendar_id,
        "venue_timezone": authority.venue_timezone,
        "market_date": authority.market_date.isoformat(),
        "evaluated_at": _utc(authority.evaluated_at, "evaluated_at").isoformat(),
        "market_session": authority.market_session,
        "trading_day_kind": authority.trading_day_kind,
        "phase_started_at": _utc(
            authority.phase_started_at, "phase_started_at"
        ).isoformat(),
        "phase_ends_at": _utc(
            authority.phase_ends_at, "phase_ends_at"
        ).isoformat(),
        "resolved_at": _utc(authority.resolved_at, "resolved_at").isoformat(),
        "valid_until": _utc(authority.valid_until, "valid_until").isoformat(),
        "source": authority.source,
        "source_version": authority.source_version,
    }


def build_session_authority_uid(authority: MarketSessionAuthority) -> str:
    """Build the deterministic identity for a validated authority observation."""

    validate_market_session_authority(authority, verify_uid=False)
    encoded = json.dumps(
        _authority_payload(authority), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "session-authority:" + sha256(encoded).hexdigest()


def validate_market_session_authority(
    authority: MarketSessionAuthority,
    *,
    verify_uid: bool = True,
) -> None:
    """Validate structure, temporal scope, timezone, and deterministic identity."""

    if authority.contract_version != SESSION_AUTHORITY_CONTRACT_VERSION:
        raise SessionAuthorityError("unsupported session-authority contract version")
    _instrument_key(authority.instrument_key)
    if not re.fullmatch(r"[A-Z0-9]{4}", authority.venue_id):
        raise SessionAuthorityError("venue_id must be an explicit four-character MIC")
    _machine_id(authority.calendar_id, "calendar_id")
    _machine_id(authority.source, "source")
    _machine_id(authority.source_version, "source_version")
    try:
        venue_zone = ZoneInfo(authority.venue_timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise SessionAuthorityError(
            "venue_timezone must be a valid IANA timezone"
        ) from exc

    if authority.market_session not in SUPPORTED_AUTHORITY_SESSIONS:
        raise SessionAuthorityError("unsupported authoritative market_session")
    if authority.trading_day_kind not in SUPPORTED_TRADING_DAY_KINDS:
        raise SessionAuthorityError("unsupported trading_day_kind")
    if (
        authority.trading_day_kind in {"holiday", "unscheduled_closure"}
        and authority.market_session != "closed"
    ):
        raise SessionAuthorityError(
            "holiday and unscheduled-closure authority must report a closed session"
        )

    evaluated_at = _utc(authority.evaluated_at, "evaluated_at")
    phase_started_at = _utc(authority.phase_started_at, "phase_started_at")
    phase_ends_at = _utc(authority.phase_ends_at, "phase_ends_at")
    resolved_at = _utc(authority.resolved_at, "resolved_at")
    valid_until = _utc(authority.valid_until, "valid_until")
    if not phase_started_at <= evaluated_at < phase_ends_at:
        raise SessionAuthorityError(
            "evaluated_at must be inside the authoritative half-open phase window"
        )
    if resolved_at > evaluated_at:
        raise SessionAuthorityError("resolved_at must not follow evaluated_at")
    if valid_until <= evaluated_at or valid_until <= resolved_at:
        raise SessionAuthorityError(
            "session authority is expired or has no validity window"
        )
    if evaluated_at.astimezone(venue_zone).date() != authority.market_date:
        raise SessionAuthorityError(
            "market_date must match evaluated_at in venue_timezone"
        )

    if verify_uid:
        expected_uid = build_session_authority_uid(authority)
        if authority.authority_uid != expected_uid:
            raise SessionAuthorityError("authority_uid does not match authority content")


def validate_session_authority_binding(
    authority: MarketSessionAuthority,
    *,
    instrument_key: str,
    evaluated_at: datetime,
) -> None:
    """Bind an authority observation to the exact quote evaluation request."""

    validate_market_session_authority(authority)
    if authority.instrument_key != instrument_key:
        raise SessionAuthorityError(
            "session authority instrument_key does not match quote"
        )
    if _utc(authority.evaluated_at, "authority.evaluated_at") != _utc(
        evaluated_at, "evaluated_at"
    ):
        raise SessionAuthorityError(
            "session authority evaluated_at does not match freshness evaluation"
        )
