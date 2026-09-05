"""Broker-reconciled current-position valuation without fabricated lot history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, ROUND_HALF_EVEN
from hashlib import sha256
import json
from typing import Literal, Mapping

from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.position_reconciliation import BrokerPositionSnapshot


BROKER_CURRENT_POSITION_VALUATION_CONTRACT_VERSION = (
    "onejournal.broker-current-position-valuation.v1"
)
BROKER_POSITION_BASIS_METHOD = "broker-tax-lot-average.v1"


class BrokerCurrentPositionValuationError(ValueError):
    """Raised when the complete broker-position valuation scope is invalid."""


@dataclass(frozen=True)
class BrokerCurrentPositionValuation:
    """Per-metric availability for one member of a complete broker snapshot."""

    identity: InstrumentIdentity
    quantity: Decimal
    tax_lot_average_price: Decimal | None
    open_cost_basis: Decimal | None
    broker_market_value: Decimal | None
    broker_reported_unrealized_pnl: Decimal | None
    unrealized_pnl: Decimal | None
    unrealized_reconciliation_difference: Decimal | None
    cost_basis_status: Literal["available", "unavailable"]
    market_value_status: Literal["available", "unavailable"]
    unrealized_pnl_status: Literal["available", "unavailable"]
    status: Literal["available", "partial", "unavailable"]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class BrokerCurrentPositionValuationRun:
    """Deterministic current-position result sourced from one broker snapshot."""

    contract_version: str
    basis_method: str
    run_uid: str
    snapshot_uid: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    asof: date
    retrieved_at: datetime
    evaluated_at: datetime
    max_snapshot_age_seconds: int
    snapshot_age_seconds: Decimal
    currency_quantum_by_currency: Mapping[str, Decimal]
    position_count: int
    cost_basis_available_count: int
    market_value_available_count: int
    unrealized_pnl_available_count: int
    positions: tuple[BrokerCurrentPositionValuation, ...]
    portfolio_cost_basis_by_currency: Mapping[str, Decimal] | None
    portfolio_market_value_by_currency: Mapping[str, Decimal] | None
    portfolio_unrealized_pnl_by_currency: Mapping[str, Decimal] | None
    complete_portfolio_cost_basis_available: bool
    complete_portfolio_market_value_available: bool
    complete_portfolio_unrealized_pnl_available: bool
    financial_acceptance: Literal[False]
    final_status: Literal["complete", "partial"]

    def privacy_safe_audit(self) -> dict[str, object]:
        """Return lineage, counts, and availability without financial values."""

        return {
            "schema": "onejournal.broker-current-position-valuation-audit.v1",
            "contract_version": self.contract_version,
            "basis_method": self.basis_method,
            "run_uid": self.run_uid,
            "snapshot_uid": self.snapshot_uid,
            "source_broker": self.source_broker,
            "asof": self.asof.isoformat(),
            "retrieved_at": self.retrieved_at.isoformat(),
            "evaluated_at": self.evaluated_at.isoformat(),
            "max_snapshot_age_seconds": self.max_snapshot_age_seconds,
            "snapshot_age_seconds": format(self.snapshot_age_seconds, "f"),
            "currency_quantum_by_currency": {
                key: format(value, "f")
                for key, value in sorted(
                    self.currency_quantum_by_currency.items()
                )
            },
            "position_count": self.position_count,
            "cost_basis_available_count": self.cost_basis_available_count,
            "market_value_available_count": self.market_value_available_count,
            "unrealized_pnl_available_count": self.unrealized_pnl_available_count,
            "complete_portfolio_cost_basis_available": (
                self.complete_portfolio_cost_basis_available
            ),
            "complete_portfolio_market_value_available": (
                self.complete_portfolio_market_value_available
            ),
            "complete_portfolio_unrealized_pnl_available": (
                self.complete_portfolio_unrealized_pnl_available
            ),
            "private_financial_values_emitted": False,
            "raw_instrument_identifiers_emitted": False,
            "financial_acceptance": False,
            "final_status": self.final_status,
        }


def _digest(document: object) -> str:
    return sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BrokerCurrentPositionValuationError(
            f"{field_name} must include a timezone"
        )
    return value.astimezone(UTC)


def _metric_status(
    *, cost_basis: bool, market_value: bool, unrealized_pnl: bool
) -> Literal["available", "partial", "unavailable"]:
    available_count = sum((cost_basis, market_value, unrealized_pnl))
    if available_count == 3:
        return "available"
    if available_count:
        return "partial"
    return "unavailable"


def build_broker_current_position_valuation(
    *,
    broker_snapshot: BrokerPositionSnapshot,
    evaluated_at: datetime,
    max_snapshot_age_seconds: int,
    currency_quantum_by_currency: Mapping[str, Decimal],
) -> BrokerCurrentPositionValuationRun:
    """Validate complete broker-reported current basis, value, and open P&L."""

    evaluated = _utc(evaluated_at, "evaluated_at")
    if (
        type(max_snapshot_age_seconds) is not int
        or max_snapshot_age_seconds < 0
    ):
        raise BrokerCurrentPositionValuationError(
            "max_snapshot_age_seconds must be a non-negative integer"
        )
    if not broker_snapshot.account_complete:
        raise BrokerCurrentPositionValuationError(
            "a complete broker account snapshot is required"
        )
    if not broker_snapshot.positions:
        raise BrokerCurrentPositionValuationError(
            "an empty broker position scope cannot produce portfolio totals"
        )
    if broker_snapshot.retrieved_at > evaluated:
        raise BrokerCurrentPositionValuationError(
            "broker snapshot cannot be retrieved after evaluation"
        )
    snapshot_age = Decimal(
        str((evaluated - broker_snapshot.retrieved_at).total_seconds())
    )
    if snapshot_age > Decimal(max_snapshot_age_seconds):
        raise BrokerCurrentPositionValuationError(
            "broker position snapshot exceeds the explicit age limit"
        )

    currencies = {item.identity.currency for item in broker_snapshot.positions}
    if set(currency_quantum_by_currency) != currencies:
        raise BrokerCurrentPositionValuationError(
            "currency quantum scope must exactly match the position currencies"
        )
    for currency, quantum in currency_quantum_by_currency.items():
        if (
            not isinstance(currency, str)
            or not currency.strip()
            or not isinstance(quantum, Decimal)
            or not quantum.is_finite()
            or quantum <= 0
        ):
            raise BrokerCurrentPositionValuationError(
                "currency quanta must be positive finite Decimal values"
            )

    results: list[BrokerCurrentPositionValuation] = []
    cost_basis_totals: dict[str, Decimal] = {}
    market_value_totals: dict[str, Decimal] = {}
    unrealized_totals: dict[str, Decimal] = {}
    cost_basis_available_count = 0
    market_value_available_count = 0
    unrealized_pnl_available_count = 0

    for item in sorted(broker_snapshot.positions, key=lambda row: row.identity.key):
        if item.quantity == 0:
            raise BrokerCurrentPositionValuationError(
                "broker current-position rows must have non-zero quantity"
            )
        multiplier = (
            item.identity.multiplier
            if item.identity.asset_class == "option"
            else Decimal("1")
        )
        if multiplier is None or not multiplier.is_finite() or multiplier <= 0:
            raise BrokerCurrentPositionValuationError(
                "every position requires a positive finite multiplier"
            )
        currency = item.identity.currency
        quantum = currency_quantum_by_currency[currency]
        reasons: list[str] = []

        average_price = item.broker_tax_lot_average_price
        if average_price is None:
            open_cost_basis = None
            cost_basis_available = False
            reasons.append("broker_tax_lot_average_price_missing")
        elif not average_price.is_finite() or average_price <= 0:
            open_cost_basis = None
            cost_basis_available = False
            reasons.append("broker_tax_lot_average_price_non_positive")
        else:
            open_cost_basis = item.quantity * average_price * multiplier
            cost_basis_available = True
            cost_basis_available_count += 1
            cost_basis_totals[currency] = (
                cost_basis_totals.get(currency, Decimal("0")) + open_cost_basis
            )

        market_value = item.broker_market_value
        market_value_available = market_value is not None
        if market_value_available and (
            (item.quantity > 0 and market_value < 0)
            or (item.quantity < 0 and market_value > 0)
        ):
            market_value_available = False
            reasons.append("broker_market_value_direction_mismatch")
        elif not market_value_available:
            reasons.append("broker_market_value_missing")
        if market_value_available:
            assert market_value is not None
            market_value_available_count += 1
            market_value_totals[currency] = (
                market_value_totals.get(currency, Decimal("0")) + market_value
            )

        broker_unrealized = item.broker_unrealized_pnl
        unrealized_pnl: Decimal | None = None
        difference: Decimal | None = None
        unrealized_available = False
        if not cost_basis_available or not market_value_available:
            reasons.append("unrealized_inputs_unavailable")
        elif broker_unrealized is None:
            reasons.append("broker_unrealized_pnl_missing")
        else:
            assert open_cost_basis is not None and market_value is not None
            calculated = market_value - open_cost_basis
            difference = broker_unrealized - calculated
            if broker_unrealized.quantize(
                quantum, rounding=ROUND_HALF_EVEN
            ) != calculated.quantize(quantum, rounding=ROUND_HALF_EVEN):
                reasons.append("broker_unrealized_pnl_mismatch")
            else:
                unrealized_available = True
                unrealized_pnl = calculated
                unrealized_pnl_available_count += 1
                unrealized_totals[currency] = (
                    unrealized_totals.get(currency, Decimal("0"))
                    + unrealized_pnl
                )

        results.append(
            BrokerCurrentPositionValuation(
                identity=item.identity,
                quantity=item.quantity,
                tax_lot_average_price=average_price,
                open_cost_basis=open_cost_basis,
                broker_market_value=(market_value if market_value_available else None),
                broker_reported_unrealized_pnl=broker_unrealized,
                unrealized_pnl=unrealized_pnl,
                unrealized_reconciliation_difference=difference,
                cost_basis_status=(
                    "available" if cost_basis_available else "unavailable"
                ),
                market_value_status=(
                    "available" if market_value_available else "unavailable"
                ),
                unrealized_pnl_status=(
                    "available" if unrealized_available else "unavailable"
                ),
                status=_metric_status(
                    cost_basis=cost_basis_available,
                    market_value=market_value_available,
                    unrealized_pnl=unrealized_available,
                ),
                reason_codes=tuple(reasons),
            )
        )

    position_count = len(results)
    complete_cost_basis = cost_basis_available_count == position_count
    complete_market_value = market_value_available_count == position_count
    complete_unrealized = unrealized_pnl_available_count == position_count
    ordered_results = tuple(results)
    run_document = {
        "contract_version": BROKER_CURRENT_POSITION_VALUATION_CONTRACT_VERSION,
        "basis_method": BROKER_POSITION_BASIS_METHOD,
        "snapshot_uid": broker_snapshot.snapshot_uid,
        "raw_sha256": broker_snapshot.raw_sha256,
        "evaluated_at": evaluated.isoformat(),
        "max_snapshot_age_seconds": max_snapshot_age_seconds,
        "currency_quantum_by_currency": {
            key: format(value, "f")
            for key, value in sorted(currency_quantum_by_currency.items())
        },
        "positions": [
            {
                "identity": item.identity.key,
                "quantity": format(item.quantity, "f"),
                "tax_lot_average_price": (
                    format(item.tax_lot_average_price, "f")
                    if item.tax_lot_average_price is not None
                    else None
                ),
                "open_cost_basis": (
                    format(item.open_cost_basis, "f")
                    if item.open_cost_basis is not None
                    else None
                ),
                "broker_market_value": (
                    format(item.broker_market_value, "f")
                    if item.broker_market_value is not None
                    else None
                ),
                "broker_reported_unrealized_pnl": (
                    format(item.broker_reported_unrealized_pnl, "f")
                    if item.broker_reported_unrealized_pnl is not None
                    else None
                ),
                "unrealized_pnl": (
                    format(item.unrealized_pnl, "f")
                    if item.unrealized_pnl is not None
                    else None
                ),
                "reason_codes": list(item.reason_codes),
            }
            for item in ordered_results
        ],
    }
    complete = complete_cost_basis and complete_market_value and complete_unrealized
    return BrokerCurrentPositionValuationRun(
        contract_version=BROKER_CURRENT_POSITION_VALUATION_CONTRACT_VERSION,
        basis_method=BROKER_POSITION_BASIS_METHOD,
        run_uid="broker-current-position-valuation:" + _digest(run_document),
        snapshot_uid=broker_snapshot.snapshot_uid,
        source_broker=broker_snapshot.source_broker,
        connection_uid=broker_snapshot.connection_uid,
        source_account_id=broker_snapshot.source_account_id,
        asof=broker_snapshot.asof,
        retrieved_at=broker_snapshot.retrieved_at,
        evaluated_at=evaluated,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        snapshot_age_seconds=snapshot_age,
        currency_quantum_by_currency=dict(
            sorted(currency_quantum_by_currency.items())
        ),
        position_count=position_count,
        cost_basis_available_count=cost_basis_available_count,
        market_value_available_count=market_value_available_count,
        unrealized_pnl_available_count=unrealized_pnl_available_count,
        positions=ordered_results,
        portfolio_cost_basis_by_currency=(
            dict(sorted(cost_basis_totals.items())) if complete_cost_basis else None
        ),
        portfolio_market_value_by_currency=(
            dict(sorted(market_value_totals.items())) if complete_market_value else None
        ),
        portfolio_unrealized_pnl_by_currency=(
            dict(sorted(unrealized_totals.items())) if complete_unrealized else None
        ),
        complete_portfolio_cost_basis_available=complete_cost_basis,
        complete_portfolio_market_value_available=complete_market_value,
        complete_portfolio_unrealized_pnl_available=complete_unrealized,
        financial_acceptance=False,
        final_status="complete" if complete else "partial",
    )
