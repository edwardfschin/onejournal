"""Private API serialization for persisted broker-current valuations.

The contract is intentionally not registered on the unauthenticated app.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from onejournal.api.contracts import DECIMAL_STRING
from onejournal.journal.broker_current_position_valuation_repository import (
    BrokerCurrentPositionValuationReadBack,
)


BROKER_CURRENT_PRIVATE_API_CONTRACT_VERSION = (
    "onejournal.api.broker-current-position-valuation.v1"
)
BROKER_CURRENT_FINANCIAL_RELEASE_AUTHORIZATION_VERSION = (
    "onejournal.broker-current-financial-release-authorization.v1"
)
_SHA256 = r"^[0-9a-f]{64}$"


class BrokerCurrentApiContractError(ValueError):
    """Raised when persisted state cannot be released safely."""


class BrokerCurrentApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrokerCurrentFinancialReleaseAuthorization(BrokerCurrentApiModel):
    contract_version: Literal[
        "onejournal.broker-current-financial-release-authorization.v1"
    ] = BROKER_CURRENT_FINANCIAL_RELEASE_AUTHORIZATION_VERSION
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


class BrokerCurrentResponseMetadata(BrokerCurrentApiModel):
    contract_version: Literal[
        "onejournal.api.broker-current-position-valuation.v1"
    ] = BROKER_CURRENT_PRIVATE_API_CONTRACT_VERSION
    view_type: Literal["broker_reconciled_current_position"] = (
        "broker_reconciled_current_position"
    )
    source_contract_version: str
    basis_method: str
    valuation_run_uid: str
    result_fingerprint: str = Field(pattern=_SHA256)
    snapshot_uid: str
    source_broker: str
    asof: date
    retrieved_at: datetime
    evaluated_at: datetime
    max_snapshot_age_seconds: int = Field(ge=0)
    snapshot_age_seconds: str
    currency_quantum_by_currency: dict[str, str]
    release_status: Literal["withheld", "owner_accepted"]
    owner_acceptance_uid: str | None = None

    @field_validator("retrieved_at", "evaluated_at")
    @classmethod
    def require_utc_instant(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("timestamps must be UTC instants")
        return value

    @field_validator("snapshot_age_seconds")
    @classmethod
    def validate_snapshot_age(cls, value: str) -> str:
        if DECIMAL_STRING.fullmatch(value) is None:
            raise ValueError("snapshot age must be a decimal string")
        return value

    @field_validator("currency_quantum_by_currency")
    @classmethod
    def validate_currency_quanta(cls, value: dict[str, str]) -> dict[str, str]:
        if not value or any(
            not currency
            or DECIMAL_STRING.fullmatch(quantum) is None
            or Decimal(quantum) <= 0
            for currency, quantum in value.items()
        ):
            raise ValueError("currency quantum mapping is invalid")
        return value


class BrokerCurrentCoverageCounts(BrokerCurrentApiModel):
    position_count: int = Field(ge=1)
    cost_basis_available_count: int = Field(ge=0)
    market_value_available_count: int = Field(ge=0)
    unrealized_pnl_available_count: int = Field(ge=0)


class BrokerCurrentPosition(BrokerCurrentApiModel):
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
    quantity: str | None = None
    tax_lot_average_price: str | None = None
    open_cost_basis: str | None = None
    broker_market_value: str | None = None
    broker_reported_unrealized_pnl: str | None = None
    unrealized_pnl: str | None = None
    unrealized_reconciliation_difference: str | None = None
    cost_basis_status: Literal["available", "unavailable"]
    market_value_status: Literal["available", "unavailable"]
    unrealized_pnl_status: Literal["available", "unavailable"]
    position_status: Literal["available", "partial", "unavailable"]
    reason_codes: tuple[str, ...]

    @field_validator(
        "strike",
        "multiplier",
        "quantity",
        "tax_lot_average_price",
        "open_cost_basis",
        "broker_market_value",
        "broker_reported_unrealized_pnl",
        "unrealized_pnl",
        "unrealized_reconciliation_difference",
    )
    @classmethod
    def validate_decimal_strings(cls, value: str | None) -> str | None:
        if value is not None and DECIMAL_STRING.fullmatch(value) is None:
            raise ValueError("financial values must be decimal strings")
        return value


class BrokerCurrentPortfolioTotal(BrokerCurrentApiModel):
    currency: str
    portfolio_cost_basis: str | None = None
    portfolio_market_value: str | None = None
    portfolio_unrealized_pnl: str | None = None

    @field_validator(
        "portfolio_cost_basis",
        "portfolio_market_value",
        "portfolio_unrealized_pnl",
    )
    @classmethod
    def validate_decimal_strings(cls, value: str | None) -> str | None:
        if value is not None and DECIMAL_STRING.fullmatch(value) is None:
            raise ValueError("portfolio totals must be decimal strings")
        return value


class BrokerCurrentPositionValuationResponse(BrokerCurrentApiModel):
    metadata: BrokerCurrentResponseMetadata
    counts: BrokerCurrentCoverageCounts
    positions: tuple[BrokerCurrentPosition, ...]
    portfolio_totals: tuple[BrokerCurrentPortfolioTotal, ...]
    complete_portfolio_cost_basis_available: bool
    complete_portfolio_market_value_available: bool
    complete_portfolio_unrealized_pnl_available: bool
    final_status: Literal["complete", "partial"]


def _utc_instant(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BrokerCurrentApiContractError(
            "persisted timestamp is invalid"
        ) from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise BrokerCurrentApiContractError(
            "persisted timestamp is not a UTC instant"
        )
    return parsed


def _decimal_text(value: Decimal | None, *, release: bool) -> str | None:
    return format(value, "f") if release and value is not None else None


def build_broker_current_position_valuation_response(
    read_back: BrokerCurrentPositionValuationReadBack,
    *,
    authorization: BrokerCurrentFinancialReleaseAuthorization | None = None,
) -> BrokerCurrentPositionValuationResponse:
    """Serialize exact read-back, withholding values until owner acceptance."""

    if read_back.financial_acceptance:
        raise BrokerCurrentApiContractError(
            "calculation rows must not impersonate owner financial acceptance"
        )
    release = authorization is not None
    if authorization is not None and (
        authorization.valuation_run_uid != read_back.valuation_run_uid
    ):
        raise BrokerCurrentApiContractError(
            "owner acceptance does not match the requested valuation run"
        )
    if authorization is not None and (
        authorization.result_fingerprint != read_back.result_fingerprint
    ):
        raise BrokerCurrentApiContractError(
            "owner acceptance does not match the persisted valuation fingerprint"
        )
    retrieved_at = _utc_instant(read_back.retrieved_at_utc)
    evaluated_at = _utc_instant(read_back.evaluated_at_utc)
    if authorization is not None and authorization.accepted_at < evaluated_at:
        raise BrokerCurrentApiContractError(
            "owner acceptance predates the persisted valuation result"
        )

    positions: list[BrokerCurrentPosition] = []
    for row in read_back.positions:
        try:
            reason_codes = tuple(json.loads(row["reason_codes_json"]))
        except (TypeError, ValueError) as exc:
            raise BrokerCurrentApiContractError(
                "persisted reason codes are invalid"
            ) from exc
        if not all(isinstance(item, str) for item in reason_codes):
            raise BrokerCurrentApiContractError(
                "persisted reason codes are invalid"
            )
        positions.append(
            BrokerCurrentPosition(
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
                quantity=_decimal_text(row["quantity"], release=release),
                tax_lot_average_price=_decimal_text(
                    row["tax_lot_average_price"], release=release
                ),
                open_cost_basis=_decimal_text(
                    row["open_cost_basis"], release=release
                ),
                broker_market_value=_decimal_text(
                    row["broker_market_value"], release=release
                ),
                broker_reported_unrealized_pnl=_decimal_text(
                    row["broker_reported_unrealized_pnl"], release=release
                ),
                unrealized_pnl=_decimal_text(
                    row["unrealized_pnl"], release=release
                ),
                unrealized_reconciliation_difference=_decimal_text(
                    row["unrealized_reconciliation_difference"], release=release
                ),
                cost_basis_status=row["cost_basis_status"],
                market_value_status=row["market_value_status"],
                unrealized_pnl_status=row["unrealized_pnl_status"],
                position_status=row["position_status"],
                reason_codes=reason_codes,
            )
        )
    totals = tuple(
        BrokerCurrentPortfolioTotal(
            currency=row["currency"],
            portfolio_cost_basis=_decimal_text(
                row["portfolio_cost_basis"], release=release
            ),
            portfolio_market_value=_decimal_text(
                row["portfolio_market_value"], release=release
            ),
            portfolio_unrealized_pnl=_decimal_text(
                row["portfolio_unrealized_pnl"], release=release
            ),
        )
        for row in read_back.portfolio_totals
    )
    return BrokerCurrentPositionValuationResponse(
        metadata=BrokerCurrentResponseMetadata(
            source_contract_version=read_back.contract_version,
            basis_method=read_back.basis_method,
            valuation_run_uid=read_back.valuation_run_uid,
            result_fingerprint=read_back.result_fingerprint,
            snapshot_uid=read_back.snapshot_uid,
            source_broker=read_back.source_broker,
            asof=read_back.asof,
            retrieved_at=retrieved_at,
            evaluated_at=evaluated_at,
            max_snapshot_age_seconds=read_back.max_snapshot_age_seconds,
            snapshot_age_seconds=format(read_back.snapshot_age_seconds, "f"),
            currency_quantum_by_currency={
                key: format(value, "f")
                for key, value in sorted(
                    read_back.currency_quantum_by_currency.items()
                )
            },
            release_status="owner_accepted" if release else "withheld",
            owner_acceptance_uid=(
                authorization.owner_acceptance_uid if authorization else None
            ),
        ),
        counts=BrokerCurrentCoverageCounts(
            position_count=read_back.position_count,
            cost_basis_available_count=read_back.cost_basis_available_count,
            market_value_available_count=read_back.market_value_available_count,
            unrealized_pnl_available_count=(
                read_back.unrealized_pnl_available_count
            ),
        ),
        positions=tuple(positions),
        portfolio_totals=totals,
        complete_portfolio_cost_basis_available=(
            read_back.complete_portfolio_cost_basis_available
        ),
        complete_portfolio_market_value_available=(
            read_back.complete_portfolio_market_value_available
        ),
        complete_portfolio_unrealized_pnl_available=(
            read_back.complete_portfolio_unrealized_pnl_available
        ),
        final_status=read_back.final_status,
    )
