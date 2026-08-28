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
from pathlib import Path
import re
from typing import Literal

import yaml

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.market_data.sessions import (
    ProviderMarketSessionAuthority,
    SessionAuthorityError,
    validate_provider_session_authority_binding,
)


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
class MarketDataPolicy:
    """Validated repository policy used by quote-ingestion callers."""

    contract_version: int
    provider_selection: str
    provider_sequence: tuple[str, ...]
    allow_cross_provider_fallback: bool
    freshness: QuoteFreshnessPolicy


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
    quote_market_session: Literal[
        "pre_market", "regular", "after_hours", "closed", "unknown"
    ]
    evaluation_market_session: Literal[
        "pre_market", "regular", "after_hours", "closed", "unknown"
    ]
    quote_session_source: Literal[
        "provider", "authority", "provider_and_authority", "unavailable"
    ]
    evaluation_session_source: Literal["provider", "authority", "unavailable"]
    session_authority_uid: str | None


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
    """Return a versioned identity hash covering the complete quote evidence."""

    validate_normalized_quote(quote)
    payload = {
        "identity_version": "onejournal.normalized-quote.v2",
        "provider": quote.provider.lower(),
        "connection_uid": quote.connection_uid,
        "instrument_key": quote.instrument_key,
        "provider_instrument_id": quote.provider_instrument_id,
        "symbol": quote.symbol,
        "asset_class": quote.asset_class,
        "currency": quote.currency,
        "bid": None if quote.bid is None else format(quote.bid, "f"),
        "ask": None if quote.ask is None else format(quote.ask, "f"),
        "last": None if quote.last is None else format(quote.last, "f"),
        "provider_quote_at": _utc(
            quote.provider_quote_at, "provider_quote_at"
        ).isoformat(),
        "received_at": _utc(quote.received_at, "received_at").isoformat(),
        "market_session": quote.market_session,
        "data_mode": quote.data_mode,
        "entitlement_status": quote.entitlement_status,
        "asof": quote.asof.isoformat(),
        "raw_path": quote.raw_path,
        "raw_sha256": quote.raw_sha256.lower(),
        "adapter_version": quote.adapter_version,
    }
    return "quote:" + sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def load_market_data_policy(path: Path) -> MarketDataPolicy:
    """Load and fail closed on an incomplete or ambiguous market-data policy."""

    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise QuoteContractError(f"unable to load market-data policy: {path}") from exc
    if not isinstance(document, dict) or set(document) != {"marketdata"}:
        raise QuoteContractError("market-data policy must contain only a marketdata object")
    config = document["marketdata"]
    if not isinstance(config, dict):
        raise QuoteContractError("marketdata must be an object")

    version = config.get("contract_version")
    if type(version) is not int or version != 1:
        raise QuoteContractError("marketdata.contract_version must be the supported integer 1")
    if config.get("mode") != "read_only":
        raise QuoteContractError("marketdata.mode must remain read_only")
    if config.get("provider_selection") != "account_broker":
        raise QuoteContractError("marketdata.provider_selection must be account_broker")
    if config.get("allow_cross_provider_fallback") is not False:
        raise QuoteContractError("cross-provider fallback must remain disabled")

    sequence = config.get("provider_sequence")
    if (
        not isinstance(sequence, list)
        or not sequence
        or any(
            not isinstance(provider, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]*", provider)
            for provider in sequence
        )
        or len(set(sequence)) != len(sequence)
    ):
        raise QuoteContractError("provider_sequence must contain unique lowercase providers")
    providers = config.get("providers")
    if not isinstance(providers, dict) or any(provider not in providers for provider in sequence):
        raise QuoteContractError("provider_sequence entries must exist in providers")

    freshness = config.get("freshness")
    expected_freshness_fields = {
        "regular_session_seconds",
        "extended_session_seconds",
        "future_tolerance_seconds",
        "delayed_quotes_are_current",
        "unknown_entitlement_is_valid",
    }
    if not isinstance(freshness, dict) or set(freshness) != expected_freshness_fields:
        raise QuoteContractError("marketdata.freshness fields do not match contract version 1")
    for field_name in (
        "regular_session_seconds",
        "extended_session_seconds",
        "future_tolerance_seconds",
    ):
        if type(freshness[field_name]) is not int:
            raise QuoteContractError(f"marketdata.freshness.{field_name} must be an integer")
    for field_name in ("delayed_quotes_are_current", "unknown_entitlement_is_valid"):
        if type(freshness[field_name]) is not bool:
            raise QuoteContractError(f"marketdata.freshness.{field_name} must be a boolean")

    return MarketDataPolicy(
        contract_version=version,
        provider_selection=config["provider_selection"],
        provider_sequence=tuple(sequence),
        allow_cross_provider_fallback=config["allow_cross_provider_fallback"],
        freshness=QuoteFreshnessPolicy(**freshness),
    )


def assess_quote_freshness(
    quote: NormalizedQuote,
    *,
    evaluated_at: datetime,
    policy: QuoteFreshnessPolicy | None = None,
    session_authority: ProviderMarketSessionAuthority | None = None,
) -> FreshnessAssessment:
    """Classify freshness from provider evidence and optional session authority.

    The provider-native authority is injected; this function has no clock-based
    session inference, resolver selection, network access, or persistence.
    """

    validate_normalized_quote(quote)
    policy = policy or QuoteFreshnessPolicy()
    now_utc = _utc(evaluated_at, "evaluated_at")
    quote_utc = _utc(quote.provider_quote_at, "provider_quote_at")
    received_utc = _utc(quote.received_at, "received_at")
    age = Decimal(str((now_utc - quote_utc).total_seconds()))

    authority_uid = None
    if session_authority is None:
        quote_session = quote.market_session
        evaluation_session = quote.market_session
        quote_session_source = (
            "unavailable" if quote.market_session == "unknown" else "provider"
        )
        evaluation_session_source = quote_session_source
        session_conflict = False
    else:
        if not isinstance(session_authority, ProviderMarketSessionAuthority):
            raise SessionAuthorityError(
                "legacy or unsupported session authority cannot qualify a quote"
            )
        validate_provider_session_authority_binding(
            session_authority,
            quote=quote,
            evaluated_at=now_utc,
        )
        authority_uid = session_authority.authority_uid
        evaluation_session = session_authority.evaluation_market_session
        evaluation_session_source = "authority"
        if quote.market_session == "unknown":
            quote_session = session_authority.quote_market_session
            quote_session_source = "authority"
            session_conflict = False
        elif (
            quote.market_session == session_authority.quote_market_session
        ):
            quote_session = quote.market_session
            quote_session_source = "provider_and_authority"
            session_conflict = False
        else:
            quote_session = quote.market_session
            quote_session_source = "unavailable"
            session_conflict = True

    def result(
        status: Literal[
            "live_fresh",
            "live_stale",
            "delayed",
            "market_closed_last",
            "unavailable",
        ],
        valuation_allowed: bool,
        result_age: Decimal | None,
        reason: str,
    ) -> FreshnessAssessment:
        return FreshnessAssessment(
            status=status,
            valuation_allowed=valuation_allowed,
            age_seconds=result_age,
            evaluated_at=now_utc,
            reason=reason,
            quote_market_session=quote_session,
            evaluation_market_session=evaluation_session,
            quote_session_source=quote_session_source,
            evaluation_session_source=evaluation_session_source,
            session_authority_uid=authority_uid,
        )

    if age < -Decimal(policy.future_tolerance_seconds):
        return result(
            "unavailable", False, age, "provider quote timestamp is in the future"
        )
    age = max(age, Decimal("0"))

    if received_utc > now_utc:
        return result(
            "unavailable", False, age, "quote was received after evaluation instant"
        )
    if (quote_utc - received_utc).total_seconds() > policy.future_tolerance_seconds:
        return result(
            "unavailable", False, age, "provider quote timestamp exceeds receipt time"
        )

    if session_conflict:
        return result(
            "unavailable",
            False,
            age,
            "provider and authoritative market sessions conflict",
        )

    if quote.entitlement_status == "denied":
        return result("unavailable", False, age, "provider entitlement denied")
    if (
        quote.entitlement_status == "unknown"
        and not policy.unknown_entitlement_is_valid
    ):
        return result("unavailable", False, age, "provider entitlement is unknown")
    if quote.data_mode == "unknown":
        return result("unavailable", False, age, "provider data mode is unknown")
    if quote_session == "unknown":
        return result("unavailable", False, age, "provider market session is unknown")
    if quote.data_mode == "delayed" or quote.entitlement_status == "delayed":
        return result(
            "delayed",
            policy.delayed_quotes_are_current,
            age,
            "provider reports delayed market data",
        )

    evaluation_session_closed = evaluation_session == "closed"
    if quote.data_mode in CLOSED_DATA_MODES:
        if not evaluation_session_closed:
            return result(
                "live_stale",
                False,
                age,
                "closed/frozen quote while evaluation session is open",
            )
        return result(
            "market_closed_last",
            True,
            age,
            "closed-session mark; not a live quote",
        )

    if evaluation_session_closed:
        return result(
            "market_closed_last",
            True,
            age,
            "latest real-time quote retained after effective market close",
        )

    threshold = (
        policy.regular_session_seconds
        if quote_session == "regular"
        else policy.extended_session_seconds
    )
    if age <= Decimal(threshold):
        return result(
            "live_fresh", True, age, "real-time quote is within freshness threshold"
        )
    return result(
        "live_stale", False, age, "real-time quote exceeds freshness threshold"
    )
