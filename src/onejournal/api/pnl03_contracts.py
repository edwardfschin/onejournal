"""Versioned private response contract for persisted bounded PNL-03 results.

This module defines serialization only. It is intentionally not registered on
the unauthenticated FastAPI application.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from onejournal.api.contracts import DECIMAL_STRING
from onejournal.journal.bounded_pnl03_valuation_repository import (
    BoundedPnl03ValuationReadBack,
)


PNL03_PRIVATE_API_CONTRACT_VERSION = "onejournal.api.pnl03-position-valuation.v1"
PNL03_FINANCIAL_RELEASE_AUTHORIZATION_VERSION = (
    "onejournal.pnl03-financial-release-authorization.v1"
)
_SHA256 = r"^[0-9a-f]{64}$"


class Pnl03ApiContractError(ValueError):
    """Raised when persisted state cannot be released under the private contract."""


class Pnl03ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Pnl03FinancialReleaseAuthorization(Pnl03ApiModel):
    contract_version: Literal[
        "onejournal.pnl03-financial-release-authorization.v1"
    ] = PNL03_FINANCIAL_RELEASE_AUTHORIZATION_VERSION
    owner_acceptance_uid: str = Field(min_length=1, max_length=256)
    valuation_run_uid: str = Field(min_length=1, max_length=256)
    result_fingerprint: str = Field(pattern=_SHA256)
    accepted_at: datetime
    decision: Literal["accepted"] = "accepted"

    @field_validator("accepted_at")
    @classmethod
    def require_utc_instant(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("accepted_at must be a UTC instant")
        return value


class Pnl03ResponseMetadata(Pnl03ApiModel):
    contract_version: Literal[
        "onejournal.api.pnl03-position-valuation.v1"
    ] = PNL03_PRIVATE_API_CONTRACT_VERSION
    source_contract_version: str
    route_version: str
    valuation_run_uid: str
    reconciliation_run_uid: str
    binding_sha256: str
    snapshot_uid: str
    assembly_sha256: str
    quote_evidence_sha256: str
    quote_scope_sha256: str
    asof: date
    evaluated_at: datetime
    calculation_version: str
    fill_fingerprint: str
    release_status: Literal["withheld", "owner_accepted"]
    owner_acceptance_uid: str | None = None

    @field_validator("evaluated_at")
    @classmethod
    def require_utc_instant(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("evaluated_at must be a UTC instant")
        return value


class Pnl03CoverageCounts(Pnl03ApiModel):
    complete_position_count: int = Field(ge=1)
    eligible_count: int = Field(ge=1)
    valid_mark_count: int = Field(ge=0)
    mark_unavailable_count: int = Field(ge=0)
    unavailable_count: int = Field(ge=0)


class Pnl03Position(Pnl03ApiModel):
    instrument_key: str
    asset_class: Literal["equity", "option"]
    market_scope: str
    currency: str
    symbol: str | None = None
    underlying_symbol: str | None = None
    expiry: date | None = None
    option_right: Literal["CALL", "PUT"] | None = None
    strike: str | None = None
    multiplier: str | None = None
    coverage_status: str
    reconciliation_status: str
    position_status: Literal["valued", "mark_unavailable", "unavailable"]
    reason_codes: tuple[str, ...]
    broker_quantity: str | None = None
    canonical_quantity: str | None = None
    open_cost_basis: str | None = None
    quote_uid: str | None = None
    freshness_status: str | None = None
    freshness_age_seconds: str | None = None
    quote_market_session: str | None = None
    evaluation_market_session: str | None = None
    session_authority_uid: str | None = None
    mark_policy_version: str | None = None
    selected_price_field: Literal["bid", "ask", "last"] | None = None
    mark_price: str | None = None
    market_value: str | None = None
    unrealized_pnl: str | None = None

    @field_validator(
        "strike",
        "multiplier",
        "broker_quantity",
        "canonical_quantity",
        "open_cost_basis",
        "freshness_age_seconds",
        "mark_price",
        "market_value",
        "unrealized_pnl",
    )
    @classmethod
    def validate_decimal_strings(cls, value: str | None) -> str | None:
        if value is not None and DECIMAL_STRING.fullmatch(value) is None:
            raise ValueError("financial values must be decimal strings")
        return value


class Pnl03EligibleSubtotal(Pnl03ApiModel):
    currency: str
    eligible_cost_basis: str | None = None
    eligible_market_value: str | None = None
    eligible_unrealized_pnl: str | None = None
    subtotal_status: Literal["eligible_subtotal", "unavailable"]

    @field_validator(
        "eligible_cost_basis",
        "eligible_market_value",
        "eligible_unrealized_pnl",
    )
    @classmethod
    def validate_decimal_strings(cls, value: str | None) -> str | None:
        if value is not None and DECIMAL_STRING.fullmatch(value) is None:
            raise ValueError("subtotal values must be decimal strings")
        return value


class Pnl03PositionValuationResponse(Pnl03ApiModel):
    metadata: Pnl03ResponseMetadata
    counts: Pnl03CoverageCounts
    positions: tuple[Pnl03Position, ...]
    eligible_subtotals: tuple[Pnl03EligibleSubtotal, ...]
    portfolio_market_value_by_currency: None = None
    portfolio_unrealized_pnl_by_currency: None = None
    complete_portfolio_totals_available: Literal[False] = False
    final_status: Literal["eligible_valued", "mark_unavailable"]


def _decimal_text(value: Decimal | None, *, release: bool) -> str | None:
    return format(value, "f") if release and value is not None else None


def _utc_instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise Pnl03ApiContractError("persisted evaluated_at is not a UTC instant")
    return parsed


def build_pnl03_position_valuation_response(
    read_back: BoundedPnl03ValuationReadBack,
    *,
    authorization: Pnl03FinancialReleaseAuthorization | None = None,
) -> Pnl03PositionValuationResponse:
    """Serialize one exact read-back, withholding values until owner acceptance."""

    if read_back.complete_portfolio_totals_available:
        raise Pnl03ApiContractError("persisted result incorrectly claims portfolio totals")
    if read_back.financial_acceptance:
        raise Pnl03ApiContractError(
            "calculation rows must not impersonate owner financial acceptance"
        )
    release = authorization is not None
    if authorization is not None and authorization.valuation_run_uid != read_back.valuation_run_uid:
        raise Pnl03ApiContractError(
            "owner acceptance does not match the requested valuation run"
        )
    if authorization is not None and authorization.result_fingerprint != read_back.result_fingerprint:
        raise Pnl03ApiContractError(
            "owner acceptance does not match the persisted valuation fingerprint"
        )
    evaluated_at = _utc_instant(read_back.evaluated_at_utc)
    if authorization is not None and authorization.accepted_at < evaluated_at:
        raise Pnl03ApiContractError(
            "owner acceptance predates the persisted valuation result"
        )

    positions: list[Pnl03Position] = []
    for row in read_back.positions:
        try:
            reason_codes = tuple(json.loads(row["reason_codes_json"]))
        except (TypeError, ValueError) as exc:
            raise Pnl03ApiContractError("persisted reason codes are invalid") from exc
        if not all(isinstance(item, str) for item in reason_codes):
            raise Pnl03ApiContractError("persisted reason codes are invalid")
        positions.append(
            Pnl03Position(
                instrument_key=row["instrument_key"],
                asset_class=row["asset_class"],
                market_scope=row["market_scope"],
                currency=row["currency"],
                symbol=row["symbol"],
                underlying_symbol=row["underlying_symbol"],
                expiry=row["expiry"],
                option_right=row["option_right"],
                strike=_decimal_text(row["strike"], release=True),
                multiplier=_decimal_text(row["multiplier"], release=True),
                coverage_status=row["coverage_status"],
                reconciliation_status=row["reconciliation_status"],
                position_status=row["position_status"],
                reason_codes=reason_codes,
                broker_quantity=_decimal_text(row["broker_quantity"], release=release),
                canonical_quantity=_decimal_text(
                    row["canonical_quantity"], release=release
                ),
                open_cost_basis=_decimal_text(row["open_cost_basis"], release=release),
                quote_uid=row["quote_uid"] if release else None,
                freshness_status=row["freshness_status"] if release else None,
                freshness_age_seconds=_decimal_text(
                    row["freshness_age_seconds"], release=release
                ),
                quote_market_session=row["quote_market_session"] if release else None,
                evaluation_market_session=(
                    row["evaluation_market_session"] if release else None
                ),
                session_authority_uid=row["session_authority_uid"] if release else None,
                mark_policy_version=row["mark_policy_version"] if release else None,
                selected_price_field=row["selected_price_field"] if release else None,
                mark_price=_decimal_text(row["mark_price"], release=release),
                market_value=_decimal_text(row["market_value"], release=release),
                unrealized_pnl=_decimal_text(row["unrealized_pnl"], release=release),
            )
        )
    subtotals = tuple(
        Pnl03EligibleSubtotal(
            currency=row["currency"],
            eligible_cost_basis=_decimal_text(
                row["eligible_cost_basis"], release=release
            ),
            eligible_market_value=_decimal_text(
                row["eligible_market_value"], release=release
            ),
            eligible_unrealized_pnl=_decimal_text(
                row["eligible_unrealized_pnl"], release=release
            ),
            subtotal_status=row["subtotal_status"],
        )
        for row in read_back.subtotals
    )
    return Pnl03PositionValuationResponse(
        metadata=Pnl03ResponseMetadata(
            source_contract_version=read_back.contract_version,
            route_version=read_back.route_version,
            valuation_run_uid=read_back.valuation_run_uid,
            reconciliation_run_uid=read_back.reconciliation_run_uid,
            binding_sha256=read_back.binding_sha256,
            snapshot_uid=read_back.snapshot_uid,
            assembly_sha256=read_back.assembly_sha256,
            quote_evidence_sha256=read_back.quote_evidence_sha256,
            quote_scope_sha256=read_back.quote_scope_sha256,
            asof=read_back.asof,
            evaluated_at=evaluated_at,
            calculation_version=read_back.calculation_version,
            fill_fingerprint=read_back.fill_fingerprint,
            release_status="owner_accepted" if release else "withheld",
            owner_acceptance_uid=(
                authorization.owner_acceptance_uid if authorization else None
            ),
        ),
        counts=Pnl03CoverageCounts(
            complete_position_count=read_back.complete_position_count,
            eligible_count=read_back.eligible_count,
            valid_mark_count=read_back.valid_mark_count,
            mark_unavailable_count=read_back.mark_unavailable_count,
            unavailable_count=read_back.unavailable_count,
        ),
        positions=tuple(positions),
        eligible_subtotals=subtotals,
        final_status=read_back.final_status,
    )
