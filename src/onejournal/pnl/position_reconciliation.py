"""Credential-free PNL-03 broker-position reconciliation boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
import re

from onejournal.instruments import InstrumentIdentity


class PositionReconciliationError(ValueError):
    """Raised when a reconciliation scope is malformed or ambiguous."""


def _utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise PositionReconciliationError(f"{field_name} must include a timezone")
    return value.astimezone(UTC)


def _finite(value: Decimal | None, field_name: str) -> None:
    if value is not None and not value.is_finite():
        raise PositionReconciliationError(f"{field_name} must be finite when supplied")


@dataclass(frozen=True)
class CanonicalPositionQuantity:
    source_broker: str
    connection_uid: str
    source_account_id: str
    identity: InstrumentIdentity
    quantity: Decimal
    asof: date
    evaluated_at: datetime
    calculation_version: str
    open_cost_basis: Decimal = Decimal("0")
    legacy_instrument_key: str | None = None

    def __post_init__(self) -> None:
        if not all((self.source_broker.strip(), self.connection_uid.strip(), self.source_account_id.strip())):
            raise PositionReconciliationError("broker, connection_uid, and account are required")
        _finite(self.quantity, "canonical quantity")
        if not self.open_cost_basis.is_finite() or self.open_cost_basis < 0:
            raise PositionReconciliationError("open_cost_basis must be finite and non-negative")
        if not self.calculation_version.strip():
            raise PositionReconciliationError("calculation_version is required")
        object.__setattr__(self, "evaluated_at", _utc(self.evaluated_at, "evaluated_at"))


@dataclass(frozen=True)
class BrokerPositionRecord:
    identity: InstrumentIdentity
    quantity: Decimal
    provider_position_id: str | None = None
    broker_average_cost: Decimal | None = None
    broker_market_value: Decimal | None = None
    broker_unrealized_pnl: Decimal | None = None
    broker_tax_lot_average_price: Decimal | None = None

    def __post_init__(self) -> None:
        _finite(self.quantity, "broker quantity")
        _finite(self.broker_average_cost, "broker_average_cost")
        _finite(self.broker_market_value, "broker_market_value")
        _finite(self.broker_unrealized_pnl, "broker_unrealized_pnl")
        _finite(
            self.broker_tax_lot_average_price,
            "broker_tax_lot_average_price",
        )


@dataclass(frozen=True)
class BrokerPositionSnapshot:
    """One account observation containing zero or more exact position rows."""

    snapshot_uid: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    asof: date
    retrieved_at: datetime
    raw_path: str
    raw_sha256: str
    account_complete: bool
    adapter_version: str
    positions: tuple[BrokerPositionRecord, ...]
    provider_observed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not all((self.snapshot_uid.strip(), self.source_broker.strip(), self.connection_uid.strip(), self.source_account_id.strip())):
            raise PositionReconciliationError("snapshot identity, broker, connection_uid, and account are required")
        if not self.raw_path.strip() or not re.fullmatch(r"[0-9a-f]{64}", self.raw_sha256):
            raise PositionReconciliationError("snapshot raw lineage and lowercase SHA-256 are required")
        if type(self.account_complete) is not bool or not self.adapter_version.strip():
            raise PositionReconciliationError("account_complete boolean and adapter_version are required")
        identities = [item.identity for item in self.positions]
        if len(set(identities)) != len(identities):
            raise PositionReconciliationError("snapshot contains duplicate canonical instrument identity")
        object.__setattr__(self, "retrieved_at", _utc(self.retrieved_at, "retrieved_at"))
        if self.provider_observed_at is not None:
            object.__setattr__(self, "provider_observed_at", _utc(self.provider_observed_at, "provider_observed_at"))


@dataclass(frozen=True)
class PositionReconciliationResult:
    identity: InstrumentIdentity
    status: str
    canonical_quantity: Decimal | None
    broker_quantity: Decimal | None
    reason: str | None


def reconcile_account_positions(
    canonical_positions: tuple[CanonicalPositionQuantity, ...],
    broker_snapshot: BrokerPositionSnapshot,
    *,
    evaluated_at: datetime,
    max_snapshot_age_seconds: int,
) -> tuple[PositionReconciliationResult, ...]:
    evaluated_at = _utc(evaluated_at, "evaluated_at")
    if max_snapshot_age_seconds < 0:
        raise PositionReconciliationError("max_snapshot_age_seconds must be non-negative")
    expected_scope = (broker_snapshot.source_broker, broker_snapshot.connection_uid, broker_snapshot.source_account_id, broker_snapshot.asof)
    for item in canonical_positions:
        if (item.source_broker, item.connection_uid, item.source_account_id, item.asof) != expected_scope:
            raise PositionReconciliationError("canonical and broker positions must share one exact account scope")
        if item.evaluated_at != evaluated_at:
            raise PositionReconciliationError("canonical positions must match the evaluation instant")
    if broker_snapshot.retrieved_at > evaluated_at:
        raise PositionReconciliationError("broker snapshot cannot be retrieved after evaluation")
    canonical_by_identity = {item.identity: item for item in canonical_positions}
    if len(canonical_by_identity) != len(canonical_positions):
        raise PositionReconciliationError("duplicate canonical identity in one reconciliation scope")
    broker_by_identity = {item.identity: item for item in broker_snapshot.positions}
    identities = sorted(set(canonical_by_identity) | set(broker_by_identity), key=lambda item: item.key)
    if not broker_snapshot.account_complete:
        return tuple(PositionReconciliationResult(
            identity, "reconciliation_pending",
            canonical_by_identity.get(identity).quantity if identity in canonical_by_identity else None,
            broker_by_identity.get(identity).quantity if identity in broker_by_identity else None,
            "complete broker account snapshot is required",
        ) for identity in identities)
    stale = (evaluated_at - broker_snapshot.retrieved_at).total_seconds() > max_snapshot_age_seconds
    results = []
    for identity in identities:
        canonical = canonical_by_identity.get(identity)
        broker = broker_by_identity.get(identity)
        if stale:
            results.append(PositionReconciliationResult(identity, "reconciliation_pending", canonical.quantity if canonical else None, broker.quantity if broker else None, "broker position snapshot exceeds the explicit age limit"))
        elif canonical is None:
            results.append(PositionReconciliationResult(identity, "reconciliation_pending", None, broker.quantity, "broker position has no canonical FIFO quantity"))
        elif broker is None:
            results.append(PositionReconciliationResult(identity, "reconciliation_pending", canonical.quantity, None, "canonical FIFO position has no broker snapshot"))
        elif canonical.quantity != broker.quantity:
            results.append(PositionReconciliationResult(identity, "reconciliation_pending", canonical.quantity, broker.quantity, "canonical and broker quantities differ"))
        else:
            results.append(PositionReconciliationResult(identity, "valid", canonical.quantity, broker.quantity, None))
    return tuple(results)
