"""Credential-free Schwab market-hours to provider-authority resolver.

This module accepts only already parsed, checksum-bound schedule evidence.  It
has no network, credential, persistence, account, or order capability.  Schwab
product scope and IANA timezone mappings are explicit and offset-validated;
the schedule response remains the authority for every phase boundary.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import PurePosixPath
import re
from typing import Literal
from zoneinfo import ZoneInfo

from onejournal.brokers.normalized import NormalizedQuote
from onejournal.market_data.quotes import validate_normalized_quote
from onejournal.market_data.sessions import (
    ProviderMarketSessionAuthority,
    build_provider_session_authority_uid,
)

from .market_hours_json import (
    SchwabMarketHoursProduct,
    SchwabMarketHoursResponse,
)


RESOLVER_VERSION = "schwab-market-hours-resolver-v1"
_DIGEST_RE = re.compile(r"[0-9a-f]{64}")


class SchwabMarketHoursResolverError(ValueError):
    """Raised when schedule evidence cannot produce exact authority."""


@dataclass(frozen=True)
class SchwabMarketHoursScope:
    """Approved deterministic mapping for one Schwab product schedule."""

    provider_market: Literal["equity", "option"]
    product_code: Literal["EQ", "EQO", "IND"]
    asset_class: Literal["stock", "option"]
    schedule_scope_id: str
    venue_timezone: str
    mic: str | None = None


SCHWAB_EQUITY_SCOPE = SchwabMarketHoursScope(
    provider_market="equity",
    product_code="EQ",
    asset_class="stock",
    schedule_scope_id="schwab:market-hours:equity:EQ",
    venue_timezone="America/New_York",
)
SCHWAB_EQUITY_OPTION_SCOPE = SchwabMarketHoursScope(
    provider_market="option",
    product_code="EQO",
    asset_class="option",
    schedule_scope_id="schwab:market-hours:option:EQO",
    venue_timezone="America/New_York",
)
SCHWAB_INDEX_OPTION_SCOPE = SchwabMarketHoursScope(
    provider_market="option",
    product_code="IND",
    asset_class="option",
    schedule_scope_id="schwab:market-hours:option:IND",
    venue_timezone="America/New_York",
)
_SUPPORTED_SCOPES = {
    (scope.provider_market, scope.product_code): scope
    for scope in (
        SCHWAB_EQUITY_SCOPE,
        SCHWAB_EQUITY_OPTION_SCOPE,
        SCHWAB_INDEX_OPTION_SCOPE,
    )
}


@dataclass(frozen=True)
class SchwabScheduleEvidence:
    """One parsed response and its immutable member lineage."""

    response: SchwabMarketHoursResponse
    raw_path: str
    raw_sha256: str
    retrieved_at: datetime
    valid_until: datetime


@dataclass(frozen=True)
class SchwabCombinedScheduleEvidence:
    """Schedule set whose manifest binds every response used by the resolver."""

    normal_reference_date: date
    schedules: tuple[SchwabScheduleEvidence, ...]
    manifest_raw_path: str
    manifest_raw_sha256: str
    manifest_member_sha256s: tuple[str, ...]
    provider_source_version: str | None = None


@dataclass(frozen=True)
class _ResolvedPhase:
    market_session: Literal["pre_market", "regular", "after_hours", "closed"]
    trading_day_kind: Literal["regular", "early_close", "closed_unspecified"]
    started_at: datetime
    ended_at: datetime


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SchwabMarketHoursResolverError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _digest(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not _DIGEST_RE.fullmatch(value):
        raise SchwabMarketHoursResolverError(
            f"{field_name} must be a lowercase SHA-256 digest"
        )
    return value


def _raw_path(value: str, field_name: str) -> str:
    if not isinstance(value, str):
        raise SchwabMarketHoursResolverError(
            f"{field_name} must be a Schwab raw-evidence path"
        )
    path = PurePosixPath(value.replace("\\", "/"))
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.parts[:3] != ("data", "raw", "schwab")
    ):
        raise SchwabMarketHoursResolverError(
            f"{field_name} must be repository-relative under data/raw/schwab"
        )
    return path.as_posix()


def _wall_time(value: datetime) -> time:
    return value.timetz().replace(tzinfo=None)


def _phase_signature(product: SchwabMarketHoursProduct) -> tuple[tuple[str, time, time], ...]:
    return tuple(
        (
            phase.market_session,
            _wall_time(phase.started_at),
            _wall_time(phase.ended_at),
        )
        for phase in product.phases
    )


def _validate_scope(scope: SchwabMarketHoursScope) -> ZoneInfo:
    approved = _SUPPORTED_SCOPES.get((scope.provider_market, scope.product_code))
    if approved != scope:
        raise SchwabMarketHoursResolverError(
            "Schwab market-hours scope is not an approved exact mapping"
        )
    return ZoneInfo(scope.venue_timezone)


def _validate_offsets(
    product: SchwabMarketHoursProduct,
    *,
    scope: SchwabMarketHoursScope,
    venue_zone: ZoneInfo,
) -> None:
    if product.provider_market != scope.provider_market:
        raise SchwabMarketHoursResolverError("Schwab schedule market does not match scope")
    if not product.is_closed_sentinel and product.product_code != scope.product_code:
        raise SchwabMarketHoursResolverError("Schwab schedule product does not match scope")
    for phase in product.phases:
        for field_name, value in (
            ("started_at", phase.started_at),
            ("ended_at", phase.ended_at),
        ):
            localized = value.astimezone(venue_zone)
            if (
                localized.utcoffset() != value.utcoffset()
                or localized.replace(tzinfo=None) != value.replace(tzinfo=None)
            ):
                raise SchwabMarketHoursResolverError(
                    f"Schwab {scope.product_code} {field_name} offset conflicts "
                    "with the approved IANA timezone"
                )


def _is_shortened_session(
    target: SchwabMarketHoursProduct,
    normal: SchwabMarketHoursProduct,
) -> bool:
    target_by_session = {phase.market_session: phase for phase in target.phases}
    normal_by_session = {phase.market_session: phase for phase in normal.phases}
    if set(target_by_session) != set(normal_by_session):
        return False
    target_regular = target_by_session.get("regular")
    normal_regular = normal_by_session.get("regular")
    if target_regular is None or normal_regular is None:
        return False
    if _wall_time(target_regular.started_at) != _wall_time(normal_regular.started_at):
        return False
    if _wall_time(target_regular.ended_at) >= _wall_time(normal_regular.ended_at):
        return False

    for market_session in set(target_by_session) - {"regular", "after_hours"}:
        target_phase = target_by_session[market_session]
        normal_phase = normal_by_session[market_session]
        if (
            _wall_time(target_phase.started_at) != _wall_time(normal_phase.started_at)
            or _wall_time(target_phase.ended_at) != _wall_time(normal_phase.ended_at)
        ):
            return False

    if "after_hours" in target_by_session:
        target_after = target_by_session["after_hours"]
        normal_after = normal_by_session["after_hours"]
        if (
            _wall_time(target_after.started_at)
            != _wall_time(target_regular.ended_at)
            or _wall_time(normal_after.started_at)
            != _wall_time(normal_regular.ended_at)
            or _wall_time(target_after.ended_at)
            >= _wall_time(normal_after.ended_at)
        ):
            return False
    return True


def _trading_day_kind(
    product: SchwabMarketHoursProduct,
    *,
    normal: SchwabMarketHoursProduct,
) -> Literal["regular", "early_close", "closed_unspecified"]:
    if product.is_closed_sentinel:
        return "closed_unspecified"
    if normal.is_closed_sentinel:
        raise SchwabMarketHoursResolverError(
            "normal reference schedule cannot be a closed sentinel"
        )
    if _phase_signature(product) == _phase_signature(normal):
        return "regular"
    if _is_shortened_session(product, normal):
        return "early_close"
    raise SchwabMarketHoursResolverError(
        "open Schwab schedule differs from the normal reference in an unsupported way"
    )


def _day_boundary(market_date: date, venue_zone: ZoneInfo) -> tuple[datetime, datetime]:
    started_at = datetime.combine(market_date, time.min, tzinfo=venue_zone)
    ended_at = datetime.combine(market_date + timedelta(days=1), time.min, tzinfo=venue_zone)
    return started_at, ended_at


def _phase_at(
    product: SchwabMarketHoursProduct,
    *,
    instant: datetime,
    day_kind: Literal["regular", "early_close", "closed_unspecified"],
    venue_zone: ZoneInfo,
) -> _ResolvedPhase:
    instant_utc = _utc(instant, "session instant")
    if instant_utc.astimezone(venue_zone).date() != product.market_date:
        raise SchwabMarketHoursResolverError(
            "session instant does not match the Schwab schedule date"
        )
    day_started_at, day_ended_at = _day_boundary(product.market_date, venue_zone)
    if product.is_closed_sentinel:
        return _ResolvedPhase(
            market_session="closed",
            trading_day_kind="closed_unspecified",
            started_at=day_started_at,
            ended_at=day_ended_at,
        )

    ordered = sorted(product.phases, key=lambda phase: phase.started_at)
    for phase in ordered:
        if _utc(phase.started_at, "phase.started_at") <= instant_utc < _utc(
            phase.ended_at, "phase.ended_at"
        ):
            return _ResolvedPhase(
                market_session=phase.market_session,
                trading_day_kind=day_kind,
                started_at=phase.started_at,
                ended_at=phase.ended_at,
            )

    lower = day_started_at
    upper = day_ended_at
    for phase in ordered:
        if _utc(phase.ended_at, "phase.ended_at") <= instant_utc:
            lower = phase.ended_at
        elif instant_utc < _utc(phase.started_at, "phase.started_at"):
            upper = phase.started_at
            break
    return _ResolvedPhase(
        market_session="closed",
        trading_day_kind=day_kind,
        started_at=lower,
        ended_at=upper,
    )


class SchwabMarketHoursResolver:
    """Resolve exact same-connection authority from immutable schedule evidence."""

    def __init__(
        self,
        *,
        connection_uid: str,
        scope: SchwabMarketHoursScope,
        evidence: SchwabCombinedScheduleEvidence,
    ) -> None:
        if not isinstance(connection_uid, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", connection_uid
        ):
            raise SchwabMarketHoursResolverError(
                "connection_uid must be an opaque machine identifier"
            )
        venue_zone = _validate_scope(scope)
        manifest_path = _raw_path(evidence.manifest_raw_path, "manifest_raw_path")
        manifest_digest = _digest(
            evidence.manifest_raw_sha256,
            "manifest_raw_sha256",
        )
        member_digests = tuple(
            _digest(value, "manifest_member_sha256s")
            for value in evidence.manifest_member_sha256s
        )
        if not member_digests or len(set(member_digests)) != len(member_digests):
            raise SchwabMarketHoursResolverError(
                "manifest member digests must be non-empty and unique"
            )
        if not evidence.schedules:
            raise SchwabMarketHoursResolverError("at least one schedule is required")

        schedules_by_date: dict[date, SchwabScheduleEvidence] = {}
        for schedule in evidence.schedules:
            _raw_path(schedule.raw_path, "schedule.raw_path")
            digest = _digest(schedule.raw_sha256, "schedule.raw_sha256")
            if digest not in member_digests:
                raise SchwabMarketHoursResolverError(
                    "schedule digest is not bound by the combined manifest"
                )
            if schedule.response.market_date in schedules_by_date:
                raise SchwabMarketHoursResolverError("duplicate schedule market date")
            retrieved_at = _utc(schedule.retrieved_at, "schedule.retrieved_at")
            valid_until = _utc(schedule.valid_until, "schedule.valid_until")
            if valid_until <= retrieved_at:
                raise SchwabMarketHoursResolverError(
                    "schedule validity must follow retrieval"
                )
            product = schedule.response.product(
                provider_market=scope.provider_market,
                product_code=scope.product_code,
            )
            _validate_offsets(product, scope=scope, venue_zone=venue_zone)
            schedules_by_date[schedule.response.market_date] = schedule

        if evidence.normal_reference_date not in schedules_by_date:
            raise SchwabMarketHoursResolverError(
                "normal reference date is absent from schedule evidence"
            )
        normal = schedules_by_date[evidence.normal_reference_date].response.product(
            provider_market=scope.provider_market,
            product_code=scope.product_code,
        )
        if normal.is_closed_sentinel:
            raise SchwabMarketHoursResolverError(
                "normal reference date must contain an open product schedule"
            )
        self._connection_uid = connection_uid
        self._scope = scope
        self._evidence = evidence
        self._schedules_by_date = schedules_by_date
        self._normal = normal
        self._venue_zone = venue_zone
        self._manifest_path = manifest_path
        self._manifest_digest = manifest_digest

    def _evidence_for(self, market_date: date) -> SchwabScheduleEvidence:
        try:
            return self._schedules_by_date[market_date]
        except KeyError as exc:
            raise SchwabMarketHoursResolverError(
                "no exact Schwab schedule exists for the requested market date"
            ) from exc

    def resolve(
        self,
        *,
        quote: NormalizedQuote,
        evaluated_at: datetime,
    ) -> ProviderMarketSessionAuthority:
        validate_normalized_quote(quote)
        if quote.provider != "schwab":
            raise SchwabMarketHoursResolverError("resolver accepts only Schwab quotes")
        if quote.connection_uid != self._connection_uid:
            raise SchwabMarketHoursResolverError(
                "quote connection does not match schedule evidence owner"
            )
        if quote.asset_class != self._scope.asset_class:
            raise SchwabMarketHoursResolverError(
                "quote asset class does not match Schwab schedule scope"
            )
        evaluated_utc = _utc(evaluated_at, "evaluated_at")
        quote_market_date = quote.provider_quote_at.astimezone(self._venue_zone).date()
        evaluation_market_date = evaluated_utc.astimezone(self._venue_zone).date()
        if quote_market_date != quote.asof:
            raise SchwabMarketHoursResolverError(
                "quote asof does not match the approved Schwab scope timezone"
            )

        quote_evidence = self._evidence_for(quote_market_date)
        evaluation_evidence = self._evidence_for(evaluation_market_date)
        normal_evidence = self._evidence_for(self._evidence.normal_reference_date)
        used_evidence = {quote_evidence, evaluation_evidence, normal_evidence}
        retrieved_at = max(
            _utc(item.retrieved_at, "schedule.retrieved_at") for item in used_evidence
        )
        valid_until = min(
            _utc(item.valid_until, "schedule.valid_until") for item in used_evidence
        )
        if not retrieved_at <= evaluated_utc < valid_until:
            raise SchwabMarketHoursResolverError(
                "Schwab schedule evidence is not valid at the evaluation instant"
            )

        quote_product = quote_evidence.response.product(
            provider_market=self._scope.provider_market,
            product_code=self._scope.product_code,
        )
        evaluation_product = evaluation_evidence.response.product(
            provider_market=self._scope.provider_market,
            product_code=self._scope.product_code,
        )
        quote_kind = _trading_day_kind(quote_product, normal=self._normal)
        evaluation_kind = _trading_day_kind(
            evaluation_product,
            normal=self._normal,
        )
        quote_phase = _phase_at(
            quote_product,
            instant=quote.provider_quote_at,
            day_kind=quote_kind,
            venue_zone=self._venue_zone,
        )
        evaluation_phase = _phase_at(
            evaluation_product,
            instant=evaluated_utc,
            day_kind=evaluation_kind,
            venue_zone=self._venue_zone,
        )

        authority = ProviderMarketSessionAuthority(
            authority_uid="pending",
            provider="schwab",
            connection_uid=quote.connection_uid,
            quote_uid=quote.quote_uid,
            instrument_key=quote.instrument_key,
            provider_instrument_id=quote.provider_instrument_id,
            schedule_scope_id=self._scope.schedule_scope_id,
            mic=self._scope.mic,
            venue_timezone=self._scope.venue_timezone,
            provider_quote_at=quote.provider_quote_at,
            evaluated_at=evaluated_utc,
            quote_market_date=quote_market_date,
            evaluation_market_date=evaluation_market_date,
            quote_market_session=quote_phase.market_session,
            evaluation_market_session=evaluation_phase.market_session,
            quote_trading_day_kind=quote_phase.trading_day_kind,
            evaluation_trading_day_kind=evaluation_phase.trading_day_kind,
            quote_phase_started_at=quote_phase.started_at,
            quote_phase_ends_at=quote_phase.ended_at,
            evaluation_phase_started_at=evaluation_phase.started_at,
            evaluation_phase_ends_at=evaluation_phase.ended_at,
            retrieved_at=retrieved_at,
            resolved_at=evaluated_utc,
            valid_until=valid_until,
            source_response_type="combined",
            provider_source_version=self._evidence.provider_source_version,
            raw_path=self._manifest_path,
            raw_sha256=self._manifest_digest,
            adapter_version=RESOLVER_VERSION,
        )
        return replace(
            authority,
            authority_uid=build_provider_session_authority_uid(authority),
        )
