"""Provider-neutral, point-in-time market-session authority contracts.

The original ``v1`` contract is retained unchanged as historical groundwork.
The provider-native ``v2`` contract binds schedule evidence to the same quote,
provider, connection, and instrument.  This module validates values only; it
has no credential, network, persistence, or provider-selection capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from onejournal.brokers.normalized import NormalizedQuote


SESSION_AUTHORITY_CONTRACT_VERSION = "onejournal.market-session-authority.v1"
PROVIDER_SESSION_AUTHORITY_CONTRACT_VERSION = (
    "onejournal.provider-market-session-authority.v2"
)
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
SUPPORTED_PROVIDER_TRADING_DAY_KINDS = SUPPORTED_TRADING_DAY_KINDS | {
    "closed_unspecified",
}
SUPPORTED_PROVIDER_RESPONSE_TYPES = {
    "quote",
    "market_hours",
    "trading_schedule",
    "instrument",
    "combined",
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


@dataclass(frozen=True)
class ProviderMarketSessionAuthority:
    """Same-provider schedule evidence for one quote freshness assessment.

    Quote-time and evaluation-time phases are separate because a valid quote
    may be retained across a phase boundary. ``mic`` is optional and may be
    populated only when the provider supplies it or an approved mapping proves
    it; ``schedule_scope_id`` remains the provider-native authority key.
    """

    authority_uid: str
    provider: str
    connection_uid: str
    quote_uid: str
    instrument_key: str
    provider_instrument_id: str
    schedule_scope_id: str
    mic: str | None
    venue_timezone: str
    provider_quote_at: datetime
    evaluated_at: datetime
    quote_market_date: date
    evaluation_market_date: date
    quote_market_session: Literal[
        "pre_market", "regular", "after_hours", "closed"
    ]
    evaluation_market_session: Literal[
        "pre_market", "regular", "after_hours", "closed"
    ]
    quote_trading_day_kind: Literal[
        "regular",
        "early_close",
        "holiday",
        "unscheduled_closure",
        "closed_unspecified",
    ]
    evaluation_trading_day_kind: Literal[
        "regular",
        "early_close",
        "holiday",
        "unscheduled_closure",
        "closed_unspecified",
    ]
    quote_phase_started_at: datetime
    quote_phase_ends_at: datetime
    evaluation_phase_started_at: datetime
    evaluation_phase_ends_at: datetime
    retrieved_at: datetime
    resolved_at: datetime
    valid_until: datetime
    source_response_type: Literal[
        "quote", "market_hours", "trading_schedule", "instrument", "combined"
    ]
    provider_source_version: str | None
    raw_path: str
    raw_sha256: str
    adapter_version: str
    contract_version: str = PROVIDER_SESSION_AUTHORITY_CONTRACT_VERSION


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


def _provider(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise SessionAuthorityError("provider must be a lowercase machine identifier")
    return value


def _connection_uid(value: str) -> str:
    return _machine_id(value, "connection_uid")


def _bounded_text(value: str, field_name: str, *, max_length: int = 255) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > max_length
        or any(ord(character) < 32 for character in value)
    ):
        raise SessionAuthorityError(f"{field_name} must be non-empty bounded text")
    return value


def _schedule_scope_id(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:|/-]{0,255}", value
    ):
        raise SessionAuthorityError(
            "schedule_scope_id must be an explicit provider-native identifier"
        )
    return value


def _provider_raw_source(authority: ProviderMarketSessionAuthority) -> None:
    raw_path = PurePosixPath(authority.raw_path.replace("\\", "/"))
    expected_prefix = PurePosixPath("data") / "raw" / authority.provider
    if (
        raw_path.is_absolute()
        or ".." in raw_path.parts
        or raw_path.parts[:3] != expected_prefix.parts
    ):
        raise SessionAuthorityError(
            f"raw_path must be repository-relative under {expected_prefix}"
        )
    digest = authority.raw_sha256.lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise SessionAuthorityError("raw_sha256 must be a 64-character SHA-256 digest")


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


def _provider_authority_payload(
    authority: ProviderMarketSessionAuthority,
) -> dict[str, str | None]:
    return {
        "contract_version": authority.contract_version,
        "provider": authority.provider,
        "connection_uid": authority.connection_uid,
        "quote_uid": authority.quote_uid,
        "instrument_key": authority.instrument_key,
        "provider_instrument_id": authority.provider_instrument_id,
        "schedule_scope_id": authority.schedule_scope_id,
        "mic": authority.mic,
        "venue_timezone": authority.venue_timezone,
        "provider_quote_at": _utc(
            authority.provider_quote_at, "provider_quote_at"
        ).isoformat(),
        "evaluated_at": _utc(authority.evaluated_at, "evaluated_at").isoformat(),
        "quote_market_date": authority.quote_market_date.isoformat(),
        "evaluation_market_date": authority.evaluation_market_date.isoformat(),
        "quote_market_session": authority.quote_market_session,
        "evaluation_market_session": authority.evaluation_market_session,
        "quote_trading_day_kind": authority.quote_trading_day_kind,
        "evaluation_trading_day_kind": authority.evaluation_trading_day_kind,
        "quote_phase_started_at": _utc(
            authority.quote_phase_started_at, "quote_phase_started_at"
        ).isoformat(),
        "quote_phase_ends_at": _utc(
            authority.quote_phase_ends_at, "quote_phase_ends_at"
        ).isoformat(),
        "evaluation_phase_started_at": _utc(
            authority.evaluation_phase_started_at, "evaluation_phase_started_at"
        ).isoformat(),
        "evaluation_phase_ends_at": _utc(
            authority.evaluation_phase_ends_at, "evaluation_phase_ends_at"
        ).isoformat(),
        "retrieved_at": _utc(authority.retrieved_at, "retrieved_at").isoformat(),
        "resolved_at": _utc(authority.resolved_at, "resolved_at").isoformat(),
        "valid_until": _utc(authority.valid_until, "valid_until").isoformat(),
        "source_response_type": authority.source_response_type,
        "provider_source_version": authority.provider_source_version,
        "raw_path": authority.raw_path,
        "raw_sha256": authority.raw_sha256.lower(),
        "adapter_version": authority.adapter_version,
    }


def build_provider_session_authority_uid(
    authority: ProviderMarketSessionAuthority,
) -> str:
    """Build the deterministic identity for validated provider-native authority."""

    validate_provider_session_authority(authority, verify_uid=False)
    encoded = json.dumps(
        _provider_authority_payload(authority),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "provider-session-authority:" + sha256(encoded).hexdigest()


def validate_provider_session_authority(
    authority: ProviderMarketSessionAuthority,
    *,
    verify_uid: bool = True,
) -> None:
    """Validate provider-native identity, temporal scope, source, and lineage."""

    if authority.contract_version != PROVIDER_SESSION_AUTHORITY_CONTRACT_VERSION:
        raise SessionAuthorityError(
            "unsupported provider session-authority contract version"
        )
    _provider(authority.provider)
    _connection_uid(authority.connection_uid)
    _bounded_text(authority.quote_uid, "quote_uid")
    _instrument_key(authority.instrument_key)
    _bounded_text(authority.provider_instrument_id, "provider_instrument_id")
    _schedule_scope_id(authority.schedule_scope_id)
    if authority.mic is not None and not re.fullmatch(r"[A-Z0-9]{4}", authority.mic):
        raise SessionAuthorityError("mic must be absent or an explicit four-character MIC")
    try:
        venue_zone = ZoneInfo(authority.venue_timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise SessionAuthorityError(
            "venue_timezone must be a valid IANA timezone"
        ) from exc

    for field_name in ("quote_market_session", "evaluation_market_session"):
        if getattr(authority, field_name) not in SUPPORTED_AUTHORITY_SESSIONS:
            raise SessionAuthorityError(f"unsupported {field_name}")
    for field_name in ("quote_trading_day_kind", "evaluation_trading_day_kind"):
        if getattr(authority, field_name) not in SUPPORTED_PROVIDER_TRADING_DAY_KINDS:
            raise SessionAuthorityError(f"unsupported {field_name}")
    for prefix in ("quote", "evaluation"):
        if (
            getattr(authority, f"{prefix}_trading_day_kind")
            in {"holiday", "unscheduled_closure", "closed_unspecified"}
            and getattr(authority, f"{prefix}_market_session") != "closed"
        ):
            raise SessionAuthorityError(
                f"{prefix} closed-day kind must report a closed session"
            )

    if authority.source_response_type not in SUPPORTED_PROVIDER_RESPONSE_TYPES:
        raise SessionAuthorityError("unsupported source_response_type")
    if authority.provider_source_version is not None:
        _bounded_text(
            authority.provider_source_version,
            "provider_source_version",
            max_length=128,
        )
    _machine_id(authority.adapter_version, "adapter_version")
    _provider_raw_source(authority)

    provider_quote_at = _utc(authority.provider_quote_at, "provider_quote_at")
    evaluated_at = _utc(authority.evaluated_at, "evaluated_at")
    quote_phase_started_at = _utc(
        authority.quote_phase_started_at, "quote_phase_started_at"
    )
    quote_phase_ends_at = _utc(authority.quote_phase_ends_at, "quote_phase_ends_at")
    evaluation_phase_started_at = _utc(
        authority.evaluation_phase_started_at, "evaluation_phase_started_at"
    )
    evaluation_phase_ends_at = _utc(
        authority.evaluation_phase_ends_at, "evaluation_phase_ends_at"
    )
    retrieved_at = _utc(authority.retrieved_at, "retrieved_at")
    resolved_at = _utc(authority.resolved_at, "resolved_at")
    valid_until = _utc(authority.valid_until, "valid_until")

    if not quote_phase_started_at <= provider_quote_at < quote_phase_ends_at:
        raise SessionAuthorityError(
            "provider_quote_at must be inside the quote half-open phase window"
        )
    if not evaluation_phase_started_at <= evaluated_at < evaluation_phase_ends_at:
        raise SessionAuthorityError(
            "evaluated_at must be inside the evaluation half-open phase window"
        )
    if provider_quote_at > evaluated_at:
        raise SessionAuthorityError("provider_quote_at must not follow evaluated_at")
    if not retrieved_at <= resolved_at <= evaluated_at:
        raise SessionAuthorityError(
            "authority times must satisfy retrieved_at <= resolved_at <= evaluated_at"
        )
    if valid_until <= evaluated_at or valid_until <= resolved_at:
        raise SessionAuthorityError(
            "provider session authority is expired or has no validity window"
        )
    if provider_quote_at.astimezone(venue_zone).date() != authority.quote_market_date:
        raise SessionAuthorityError(
            "quote_market_date must match provider_quote_at in venue_timezone"
        )
    if evaluated_at.astimezone(venue_zone).date() != authority.evaluation_market_date:
        raise SessionAuthorityError(
            "evaluation_market_date must match evaluated_at in venue_timezone"
        )

    if verify_uid:
        expected_uid = build_provider_session_authority_uid(authority)
        if authority.authority_uid != expected_uid:
            raise SessionAuthorityError(
                "authority_uid does not match provider session-authority content"
            )


def validate_provider_session_authority_binding(
    authority: ProviderMarketSessionAuthority,
    *,
    quote: NormalizedQuote,
    evaluated_at: datetime,
) -> None:
    """Bind provider-native authority to the exact normalized quote assessment."""

    validate_provider_session_authority(authority)
    expected = {
        "provider": quote.provider,
        "connection_uid": quote.connection_uid,
        "quote_uid": quote.quote_uid,
        "instrument_key": quote.instrument_key,
        "provider_instrument_id": quote.provider_instrument_id,
    }
    for field_name, expected_value in expected.items():
        if getattr(authority, field_name) != expected_value:
            raise SessionAuthorityError(
                f"provider session authority {field_name} does not match quote"
            )
    if authority.quote_market_date != quote.asof:
        raise SessionAuthorityError(
            "provider session authority quote_market_date does not match quote asof"
        )
    if _utc(authority.provider_quote_at, "authority.provider_quote_at") != _utc(
        quote.provider_quote_at, "quote.provider_quote_at"
    ):
        raise SessionAuthorityError(
            "provider session authority provider_quote_at does not match quote"
        )
    if _utc(authority.evaluated_at, "authority.evaluated_at") != _utc(
        evaluated_at, "evaluated_at"
    ):
        raise SessionAuthorityError(
            "provider session authority evaluated_at does not match assessment"
        )
