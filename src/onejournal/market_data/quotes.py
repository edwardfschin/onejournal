"""Validation and freshness assessment for normalized quote evidence.

This module has no provider client, credential, network, database, UI, or order
capability. It converts already-normalized quote evidence into an explicit
freshness result. PNL-03 must approve and implement mark-price selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from pathlib import PurePosixPath
import re
from typing import Literal

from onejournal.brokers.normalized import NormalizedQuote


REAL_TIME_DATA_MODES = {"real_time"}
CLOSED_DATA_MODES = {"official_close", "frozen"}
SUPPORTED_DATA_MODES = REAL_TIME_DATA_MODES | CLOSED_DATA_MODES | {
    "delayed",
    "unknown",
}
SUPPORTED_SESSIONS = {"pre_market", "regular", "after_hours", "closed", "unknown"}
SUPPORTED_ENTITLEMENTS = {"entitled", "delayed", "denied", "unknown"}


class QuoteContractError(ValueError):
    """Raised when quote evidence violates the normalized contract."""


@dataclass(frozen=True)
class QuoteFreshnessPolicy:
    """Configurable thresholds for assessing quote evidence."""

    regular_session_seconds: int = 60
    extended_session_seconds: int = 120
    future_tolerance_seconds: int = 5
    delayed_quotes_are_current: bool = False
    unknown_entitlement_is_valid: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "regular_session_seconds",
            "extended_session_seconds",
            "future_tolerance_seconds",
        ):
            if getattr(self, field_name) < 0:
                raise QuoteContractError(f"{field_name} must not be negative")


@dataclass(frozen=True)
class FreshnessAssessment:
    """Computed quote state at one explicit evaluation instant."""

    status: Literal[
        "live_fresh",
        "live_stale",
        "delayed",
        "market_closed_last",
        "unavailable",
    ]
    valuation_allowed: bool
    age_seconds: Decimal | None
    evaluated_at: datetime
    reason: str


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise QuoteContractError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _clean_required(value: str, field_name: str) -> str:
    cleaned = str(value).strip()
    if not cleaned:
        raise QuoteContractError(f"{field_name} is required")
    return cleaned


def _price(value: Decimal | None, field_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise QuoteContractError(f"{field_name} must be decimal-safe") from exc
    if not parsed.is_finite() or parsed < 0:
        raise QuoteContractError(f"{field_name} must be finite and non-negative")
    return parsed


def validate_normalized_quote(quote: NormalizedQuote) -> None:
    """Fail closed on malformed, private, or ambiguous quote evidence."""

    for field_name in (
        "quote_uid",
        "provider",
        "connection_uid",
        "instrument_key",
        "provider_instrument_id",
        "symbol",
        "asset_class",
        "currency",
        "raw_path",
        "raw_sha256",
        "adapter_version",
    ):
        _clean_required(getattr(quote, field_name), field_name)

    if quote.provider != quote.provider.lower() or not re.fullmatch(
        r"[a-z][a-z0-9_]*", quote.provider
    ):
        raise QuoteContractError(
            "provider must be a lowercase machine identifier"
        )
    if len(quote.connection_uid) > 128 or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.:-]*", quote.connection_uid
    ):
        raise QuoteContractError(
            "connection_uid must be an opaque machine identifier without spaces or paths"
        )

    _utc(quote.provider_quote_at, "provider_quote_at")
    _utc(quote.received_at, "received_at")
    bid = _price(quote.bid, "bid")
    ask = _price(quote.ask, "ask")
    last = _price(quote.last, "last")
    if bid is None and ask is None and last is None:
        raise QuoteContractError("at least one of bid, ask, or last is required")
    if bid is not None and ask is not None and bid > ask:
        raise QuoteContractError("crossed quote rejected: bid exceeds ask")

    if quote.market_session not in SUPPORTED_SESSIONS:
        raise QuoteContractError(f"unsupported market_session: {quote.market_session}")
    if quote.data_mode not in SUPPORTED_DATA_MODES:
        raise QuoteContractError(f"unsupported data_mode: {quote.data_mode}")
    if quote.entitlement_status not in SUPPORTED_ENTITLEMENTS:
        raise QuoteContractError(
            f"unsupported entitlement_status: {quote.entitlement_status}"
        )

    raw_path = PurePosixPath(quote.raw_path.replace("\\", "/"))
    expected_prefix = PurePosixPath("data") / "raw" / quote.provider.lower()
    if (
        raw_path.is_absolute()
        or ".." in raw_path.parts
        or raw_path.parts[:3] != expected_prefix.parts
    ):
        raise QuoteContractError(
            f"raw_path must be repository-relative under {expected_prefix}"
        )
    digest = quote.raw_sha256.lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise QuoteContractError("raw_sha256 must be a 64-character SHA-256 digest")


def build_quote_uid(quote: NormalizedQuote) -> str:
    """Return an identity hash covering source, timestamp, and quote values."""

    validate_normalized_quote(quote)
    payload = {
        "provider": quote.provider.lower(),
        "connection_uid": quote.connection_uid,
        "instrument_key": quote.instrument_key,
        "provider_instrument_id": quote.provider_instrument_id,
        "bid": None if quote.bid is None else format(quote.bid, "f"),
        "ask": None if quote.ask is None else format(quote.ask, "f"),
        "last": None if quote.last is None else format(quote.last, "f"),
        "provider_quote_at": _utc(
            quote.provider_quote_at, "provider_quote_at"
        ).isoformat(),
        "data_mode": quote.data_mode,
        "raw_sha256": quote.raw_sha256.lower(),
    }
    return "quote:" + sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def assess_quote_freshness(
    quote: NormalizedQuote,
    *,
    evaluated_at: datetime,
    policy: QuoteFreshnessPolicy | None = None,
    expected_market_open: bool | None = None,
) -> FreshnessAssessment:
    """Classify quote freshness without guessing an exchange calendar.

    ``expected_market_open`` must come from an approved calendar/session
    service when supplied. ``None`` means only provider-declared session and
    data mode are available.
    """

    validate_normalized_quote(quote)
    policy = policy or QuoteFreshnessPolicy()
    now_utc = _utc(evaluated_at, "evaluated_at")
    quote_utc = _utc(quote.provider_quote_at, "provider_quote_at")
    age = Decimal(str((now_utc - quote_utc).total_seconds()))

    if age < -Decimal(policy.future_tolerance_seconds):
        return FreshnessAssessment(
            "unavailable", False, age, now_utc, "provider quote timestamp is in the future"
        )
    age = max(age, Decimal("0"))

    if quote.entitlement_status == "denied":
        return FreshnessAssessment(
            "unavailable", False, age, now_utc, "provider entitlement denied"
        )
    if (
        quote.entitlement_status == "unknown"
        and not policy.unknown_entitlement_is_valid
    ):
        return FreshnessAssessment(
            "unavailable", False, age, now_utc, "provider entitlement is unknown"
        )
    if quote.data_mode == "unknown":
        return FreshnessAssessment(
            "unavailable", False, age, now_utc, "provider data mode is unknown"
        )
    if quote.market_session == "unknown":
        return FreshnessAssessment(
            "unavailable", False, age, now_utc, "provider market session is unknown"
        )
    if quote.data_mode == "delayed" or quote.entitlement_status == "delayed":
        return FreshnessAssessment(
            "delayed",
            policy.delayed_quotes_are_current,
            age,
            now_utc,
            "provider reports delayed market data",
        )

    provider_says_closed = quote.market_session == "closed"
    if quote.data_mode in CLOSED_DATA_MODES:
        if expected_market_open is True:
            return FreshnessAssessment(
                "live_stale", False, age, now_utc, "closed/frozen quote while market is expected open"
            )
        if provider_says_closed or expected_market_open is False:
            return FreshnessAssessment(
                "market_closed_last",
                True,
                age,
                now_utc,
                "provider-declared closed-session mark; not a live quote",
            )
        return FreshnessAssessment(
            "unavailable", False, age, now_utc, "closed/frozen quote lacks closed-session evidence"
        )

    if expected_market_open is False or provider_says_closed:
        return FreshnessAssessment(
            "market_closed_last",
            True,
            age,
            now_utc,
            "latest real-time quote retained after provider-declared market close",
        )

    threshold = (
        policy.regular_session_seconds
        if quote.market_session == "regular"
        else policy.extended_session_seconds
    )
    if age <= Decimal(threshold):
        return FreshnessAssessment(
            "live_fresh", True, age, now_utc, "real-time quote is within freshness threshold"
        )
    return FreshnessAssessment(
        "live_stale", False, age, now_utc, "real-time quote exceeds freshness threshold"
    )
