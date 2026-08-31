"""Compose cumulative FIFO, broker reconciliation, and PNL-02 marks."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from zoneinfo import ZoneInfo

from onejournal.brokers.normalized import NormalizedFill, NormalizedQuote
from onejournal.instruments import InstrumentIdentity
from onejournal.market_data import FreshnessAssessment
from onejournal.pnl.calculations import (
    ApprovedOptionLifecycleEvent,
    build_fill_input_fingerprint,
    build_instrument_key,
    build_lifecycle_input_fingerprint,
    calculate_fifo_pnl_with_lifecycle_events,
)
from onejournal.pnl.position_reconciliation import (
    BrokerPositionSnapshot,
    CanonicalPositionQuantity,
    reconcile_account_positions,
)
from onejournal.pnl.valuation_marks import ValuationMarkAssessment, select_valuation_mark


@dataclass(frozen=True)
class CanonicalPositionValuation:
    identity: InstrumentIdentity
    legacy_instrument_key: str | None
    direction: str | None
    quantity: Decimal | None
    broker_quantity: Decimal | None
    open_cost_basis: Decimal | None
    reconciliation_status: str
    reconciliation_reason: str | None
    mark: ValuationMarkAssessment | None
    market_value: Decimal | None
    unrealized_pnl: Decimal | None
    status: str
    reason: str | None


@dataclass(frozen=True)
class PositionValuationRun:
    valuation_run_uid: str
    snapshot_uid: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    asof: date
    evaluated_at: datetime
    calculation_version: str
    fill_fingerprint: str
    lifecycle_fingerprint: str
    max_snapshot_age_seconds: int
    positions: tuple[CanonicalPositionValuation, ...]


def _identity_map(
    fills: tuple[NormalizedFill, ...],
    lifecycle_events: tuple[ApprovedOptionLifecycleEvent, ...],
) -> dict[str, InstrumentIdentity]:
    mapping: dict[str, InstrumentIdentity] = {}
    for fill in fills:
        identity = InstrumentIdentity.from_fill(fill)
        legacy = build_instrument_key(fill)
        prior = mapping.get(legacy)
        if prior is not None and prior != identity:
            raise ValueError(f"legacy instrument key maps to conflicting canonical identities: {legacy}")
        mapping[legacy] = identity
    for event in lifecycle_events:
        if event.successor_symbol and event.successor_quantity:
            identity = InstrumentIdentity(
                asset_class="equity",
                market_scope="US",
                currency=event.currency,
                symbol=event.successor_symbol,
            )
            mapping[f"stock|{event.successor_symbol.strip().upper()}"] = identity
    return mapping


def build_position_valuation_run(
    *,
    fills: tuple[NormalizedFill, ...],
    lifecycle_events: tuple[ApprovedOptionLifecycleEvent, ...],
    broker_snapshot: BrokerPositionSnapshot,
    quotes: dict[InstrumentIdentity, tuple[NormalizedQuote, FreshnessAssessment]],
    source_broker: str,
    connection_uid: str,
    source_account_id: str,
    asof: date,
    evaluated_at: datetime,
    max_snapshot_age_seconds: int,
) -> PositionValuationRun:
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must include a timezone")
    evaluated_at = evaluated_at.astimezone(UTC)
    if evaluated_at.astimezone(ZoneInfo("America/New_York")).date() != asof:
        raise ValueError("asof must equal evaluated_at's America/New_York market date")
    for fill in fills:
        if fill.filled_at.tzinfo is None or fill.filled_at.utcoffset() is None:
            raise ValueError(f"fill {fill.fill_uid} lacks a timezone-aware filled_at")
    for event in lifecycle_events:
        if event.effective_at.tzinfo is None or event.effective_at.utcoffset() is None:
            raise ValueError(f"lifecycle event {event.event_uid} lacks a timezone-aware effective_at")
    scoped_fills = tuple(
        fill for fill in fills
        if fill.source_broker == source_broker
        and fill.source_account_id == source_account_id
        and fill.asof <= asof
        and fill.filled_at.astimezone(UTC) <= evaluated_at
    )
    scoped_events = tuple(
        event for event in lifecycle_events
        if event.source_broker == source_broker
        and event.source_account_id == source_account_id
        and event.effective_at.astimezone(UTC) <= evaluated_at
    )
    unmarked = calculate_fifo_pnl_with_lifecycle_events(scoped_fills, scoped_events)
    identities = _identity_map(scoped_fills, scoped_events)
    canonical = []
    group_by_identity = {}
    for scope, group in unmarked.groups.items():
        if group.open_quantity == 0:
            continue
        legacy = scope[2]
        identity = identities.get(legacy)
        if identity is None:
            raise ValueError(f"open FIFO group lacks canonical identity: {legacy}")
        direction = "LONG" if group.open_quantity > 0 else "SHORT"
        item = CanonicalPositionQuantity(
            source_broker, connection_uid, source_account_id, identity,
            group.open_quantity, asof, evaluated_at, unmarked.calculation_version,
            group.open_cost_basis, legacy,
        )
        canonical.append(item)
        if identity in group_by_identity:
            raise ValueError("multiple legacy FIFO keys map to one canonical instrument identity")
        group_by_identity[identity] = (group, direction, legacy)
    reconciliations = {
        item.identity: item
        for item in reconcile_account_positions(
            tuple(canonical), broker_snapshot, evaluated_at=evaluated_at,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
        )
    }
    selected_marks: dict[InstrumentIdentity, ValuationMarkAssessment] = {}
    legacy_marks: dict[str, Decimal] = {}
    for item in canonical:
        reconciliation = reconciliations[item.identity]
        if reconciliation.status != "valid" or item.identity not in quotes:
            continue
        quote, freshness = quotes[item.identity]
        direction = "LONG" if item.quantity > 0 else "SHORT"
        mark = select_valuation_mark(
            identity=item.identity,
            direction=direction,
            quote=quote,
            freshness=freshness,
            expected_provider=source_broker,
            expected_connection_uid=connection_uid,
            expected_evaluated_at=evaluated_at,
        )
        selected_marks[item.identity] = mark
        if mark.status == "valid":
            legacy_marks[item.legacy_instrument_key] = mark.price
    marked = calculate_fifo_pnl_with_lifecycle_events(
        scoped_fills, scoped_events, marks=legacy_marks
    )
    results = []
    for item in canonical:
        reconciliation = reconciliations[item.identity]
        group, direction, legacy = group_by_identity[item.identity]
        mark = selected_marks.get(item.identity)
        marked_group = marked.groups[(source_broker, source_account_id, legacy, item.identity.currency)]
        if reconciliation.status != "valid":
            status, reason = "reconciliation_pending", reconciliation.reason
        elif mark is None:
            status, reason = "unavailable", "no quote assessment for canonical instrument"
        elif mark.status != "valid":
            status, reason = "unavailable", mark.reason
        else:
            status, reason = "valid", None
        multiplier = item.identity.multiplier if item.identity.asset_class == "option" else Decimal("1")
        market_value = item.quantity * mark.price * multiplier if status == "valid" else None
        unrealized = marked_group.unrealized_pnl if status == "valid" else None
        results.append(CanonicalPositionValuation(
            identity=item.identity, legacy_instrument_key=legacy, direction=direction,
            quantity=item.quantity, broker_quantity=reconciliation.broker_quantity,
            open_cost_basis=group.open_cost_basis,
            reconciliation_status=reconciliation.status,
            reconciliation_reason=reconciliation.reason, mark=mark,
            market_value=market_value, unrealized_pnl=unrealized,
            status=status, reason=reason,
        ))
    canonical_identities = {item.identity for item in canonical}
    for identity, reconciliation in reconciliations.items():
        if identity in canonical_identities:
            continue
        results.append(CanonicalPositionValuation(
            identity=identity, legacy_instrument_key=None, direction=None,
            quantity=None, broker_quantity=reconciliation.broker_quantity,
            open_cost_basis=None, reconciliation_status=reconciliation.status,
            reconciliation_reason=reconciliation.reason, mark=None,
            market_value=None, unrealized_pnl=None,
            status="reconciliation_pending", reason=reconciliation.reason,
        ))
    ordered_results = tuple(sorted(results, key=lambda item: item.identity.key))
    snapshot_uid = broker_snapshot.snapshot_uid
    fill_fingerprint = build_fill_input_fingerprint(scoped_fills)
    lifecycle_fingerprint = build_lifecycle_input_fingerprint(scoped_events)
    identity_payload = {
        "source_broker": source_broker,
        "connection_uid": connection_uid,
        "source_account_id": source_account_id,
        "asof": asof.isoformat(),
        "evaluated_at": evaluated_at.isoformat(),
        "calculation_version": unmarked.calculation_version,
        "fill_fingerprint": fill_fingerprint,
        "lifecycle_fingerprint": lifecycle_fingerprint,
        "snapshot_uid": snapshot_uid,
        "max_snapshot_age_seconds": max_snapshot_age_seconds,
        "positions": [
            {
                "identity": item.identity.key,
                "quantity": str(item.quantity) if item.quantity is not None else None,
                "broker_quantity": str(item.broker_quantity) if item.broker_quantity is not None else None,
                "status": item.status,
                "quote_uid": item.mark.quote_uid if item.mark else None,
                "mark_price": str(item.mark.price) if item.mark and item.mark.price is not None else None,
            }
            for item in ordered_results
        ],
    }
    digest = sha256(json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return PositionValuationRun(
        valuation_run_uid=f"position-valuation:{digest}",
        snapshot_uid=snapshot_uid,
        source_broker=source_broker,
        connection_uid=connection_uid,
        source_account_id=source_account_id,
        asof=asof,
        evaluated_at=evaluated_at,
        calculation_version=unmarked.calculation_version,
        fill_fingerprint=fill_fingerprint,
        lifecycle_fingerprint=lifecycle_fingerprint,
        max_snapshot_age_seconds=max_snapshot_age_seconds,
        positions=ordered_results,
    )
