"""Deterministic FIFO P&L calculations for confirmed fills.

This module implements a conservative calculator for closed and open lot P&L.

Scope and caveats:
- Uses confirmed fills only.
- Uses FIFO allocation by open lot order.
- Preserves each closed-lot allocation with source-fill and cost lineage.
- Treats close actions only when there is a matching open lot; unsupported
  lifecycle events are intentionally rejected (fail-closed).
- Works with simple net-closed positions and partial closes.

The implementation intentionally avoids UI formatting and broker API concerns so
the same logic can later be reused by canonical job and reporting layers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from typing import Iterable, Literal

from onejournal.brokers.normalized import NormalizedFill


FIFO_CALCULATION_VERSION = "onejournal-fifo-v1"
OPTION_LIFECYCLE_CALCULATION_VERSION = "onejournal-option-lifecycle-v1"


class LotAllocationError(ValueError):
    """Raised when a close action cannot be matched to an open lot."""


@dataclass(frozen=True)
class PnLGroupResult:
    """P&L state for one instrument in one account/currency group."""

    instrument_key: str
    currency: str
    open_quantity: Decimal
    open_cost_basis: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal | None


@dataclass(frozen=True)
class ClosedLotAllocation:
    """One auditable FIFO match between an opening and closing fill."""

    scope_key: tuple[str, str, str, str]
    open_fill_uid: str
    close_fill_uid: str
    direction: str
    quantity: Decimal
    multiplier: Decimal
    open_price: Decimal
    close_price: Decimal
    gross_realized_pnl: Decimal
    allocated_open_commission: Decimal
    allocated_open_fees: Decimal
    allocated_close_commission: Decimal
    allocated_close_fees: Decimal
    realized_pnl: Decimal
    closed_at: datetime
    source_event_uid: str | None = None


@dataclass(frozen=True)
class ApprovedOptionLifecycleEvent:
    """Approved broker-independent instruction for one option lifecycle event.

    Raw broker evidence never creates this object directly. A resolver or
    operator must approve the predecessor fill links and successor economics
    first. This keeps description hints and structurally incomplete legs out of
    financial calculations.
    """

    event_uid: str
    event_type: Literal["ASSIGNMENT", "EXERCISE", "EXPIRATION"]
    source_broker: str
    source_account_id: str
    currency: str
    effective_at: datetime
    option_scope_key: tuple[str, str, str, str]
    predecessor_direction: Literal["LONG", "SHORT"]
    contracts: Decimal
    predecessor_open_fill_uids: tuple[str, ...]
    event_commission: Decimal
    event_fees: Decimal
    evidence_status: Literal["approved"]
    source_event_leg_uids: tuple[str, ...]
    successor_action: Literal["BUY", "SELL"] | None = None
    successor_position_effect: Literal["OPEN", "CLOSE"] | None = None
    successor_symbol: str | None = None
    successor_quantity: Decimal | None = None
    strike_cash_amount: Decimal | None = None


@dataclass(frozen=True)
class LifecycleLotAllocation:
    """One auditable option-lot allocation to an approved lifecycle event."""

    calculation_version: str
    event_uid: str
    event_type: str
    allocation_index: int
    option_scope_key: tuple[str, str, str, str]
    predecessor_open_fill_uid: str
    predecessor_direction: str
    contracts: Decimal
    multiplier: Decimal
    net_option_basis: Decimal
    allocated_open_commission: Decimal
    allocated_open_fees: Decimal
    allocated_event_commission: Decimal
    allocated_event_fees: Decimal
    realized_pnl: Decimal
    successor_fill_uid: str | None
    successor_action: str | None
    successor_position_effect: str | None
    successor_symbol: str | None
    successor_quantity: Decimal | None
    successor_effective_price: Decimal | None
    effective_at: datetime
    source_event_leg_uids: tuple[str, ...]


@dataclass(frozen=True)
class PnLCalculationResult:
    """Versioned FIFO totals plus their auditable closed-lot allocations."""

    calculation_version: str
    groups: dict[tuple[str, str, str, str], PnLGroupResult]
    closed_allocations: tuple[ClosedLotAllocation, ...]
    total_realized_pnl_by_currency: dict[str, Decimal]
    total_unrealized_pnl_by_currency: dict[str, Decimal | None]
    unmatched_close_fill_uids: tuple[str, ...] = ()
    lifecycle_allocations: tuple[LifecycleLotAllocation, ...] = ()


@dataclass
class _OpenLot:
    fill_uid: str
    direction: str
    opened_quantity: Decimal
    remaining_quantity: Decimal
    fill_price: Decimal
    multiplier: Decimal
    open_commission: Decimal
    open_fees: Decimal
    opened_at: datetime


@dataclass
class _MatchedLot:
    instrument_key: str
    open_lots: list[_OpenLot]
    closed_allocations: list[ClosedLotAllocation]
    realized_pnl: Decimal = Decimal("0")


def build_instrument_key(fill: NormalizedFill) -> str:
    """Return a stable instrument key for lot matching.

    For stock/equity, symbol is used directly.
    For options, the key includes underlying, symbol, side fields, expiry, strike,
    and multiplier to avoid collisions across contracts.
    """

    asset_class = fill.asset_class.strip().lower()
    if asset_class == "option":
        expiry = fill.expiry.isoformat() if fill.expiry is not None else ""
        strike = _canonical_decimal_text(fill.strike) if fill.strike is not None else ""
        multiplier = (
            _canonical_decimal_text(fill.multiplier)
            if fill.multiplier is not None
            else "1"
        )
        return (
            f"option|{(fill.underlying_symbol or '').upper()}|"
            f"{(fill.option_symbol or '').upper()}|"
            f"{(fill.option_type or '').upper()}|{expiry}|{strike}|{multiplier}"
        )
    return f"stock|{fill.symbol.strip().upper()}"


def _canonical_decimal_text(value: Decimal) -> str:
    """Serialize a decimal without storage-scale or exponent differences."""

    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"", "-0"} else text


def _fingerprint_value(value):
    if isinstance(value, Decimal):
        return _canonical_decimal_text(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("P&L fingerprint timestamps must include a timezone")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _fingerprint_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_fingerprint_value(item) for item in value]
    return value


def _records_fingerprint(records: Iterable[object]) -> str:
    normalized = [_fingerprint_value(asdict(record)) for record in records]
    serialized = [
        json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        for item in normalized
    ]
    payload = "\n".join(sorted(serialized)).encode("utf-8")
    return sha256(payload).hexdigest()


def build_fill_input_fingerprint(fills: Iterable[NormalizedFill]) -> str:
    """Hash the complete canonical fill input independently of record order."""

    return _records_fingerprint(fills)


def build_lifecycle_input_fingerprint(
    events: Iterable[ApprovedOptionLifecycleEvent],
) -> str:
    """Hash approved lifecycle instructions independently of record order."""

    return _records_fingerprint(events)


def calculate_fifo_pnl_from_fills(
    fills: Iterable[NormalizedFill],
    *,
    marks: dict[str, Decimal] | None = None,
    allow_unmatched_close: bool = False,
) -> PnLCalculationResult:
    """Calculate FIFO realized P&L and open-position summaries from fills.

    Args:
        fills: Confirmed fills to process.
        marks: Optional mapping from instrument key to fresh mark price.

    Returns:
        Aggregated P&L by instrument with total realized/unrealized by currency.
        Unmatched close fills are included in `unmatched_close_fill_uids` when
        allow_unmatched_close=True.

    Raises:
        LotAllocationError: when a close action cannot be allocated.
    """

    groups = _group_fills_by_scope(fills)
    results: dict[tuple[str, str, str, str], PnLGroupResult] = {}
    closed_allocations: list[ClosedLotAllocation] = []
    unmatched_close_fill_uids: list[str] = []

    for scope_key, group_fills in groups.items():
        _source_broker, _source_account_id, instrument_key, currency = scope_key
        classified_fills = []
        for fill in group_fills:
            _validate_fill_economics(fill)
            action, close_quantity, direction = _classify_fill(fill)
            sort_action = 0 if action == "OPEN" else 1
            classified_fills.append((fill.filled_at, sort_action, fill.fill_uid, fill, action, close_quantity, direction))

        ordered = sorted(classified_fills, key=lambda item: (item[0], item[1], item[2]))
        state = _MatchedLot(
            instrument_key=instrument_key,
            open_lots=[],
            closed_allocations=[],
        )

        for _filled_at, _sort_action, _fill_uid, fill, action, close_quantity, direction in ordered:
            if action == "OPEN":
                state.open_lots.append(_create_open_lot(fill))
                continue
            _match_close_fill(
                state,
                scope_key=scope_key,
                close_fill=fill,
                close_quantity=close_quantity,
                direction=direction,
                allow_unmatched_close=allow_unmatched_close,
                unmatched_close_fill_uids=unmatched_close_fill_uids,
            )

        closed_allocations.extend(state.closed_allocations)

        realized = state.realized_pnl
        direction = _current_direction(state.open_lots)
        open_quantity = _sum_open_quantity(state.open_lots)
        open_cost_basis = _sum_open_cost_basis(state.open_lots)

        mark = marks.get(instrument_key) if marks else None
        unrealized_pnl = None
        if mark is not None:
            if direction == "LONG":
                notional_open_qty = _open_notional_quantity(state.open_lots)
                unrealized_pnl = (mark - _weighted_open_price(state.open_lots)) * notional_open_qty
                unrealized_pnl -= _open_fees_opening_component(state.open_lots)
            elif direction == "SHORT":
                notional_open_qty = _open_notional_quantity(state.open_lots, absolute=True)
                unrealized_pnl = (_weighted_open_price(state.open_lots) - mark) * notional_open_qty
                unrealized_pnl -= _open_fees_opening_component(state.open_lots)
            else:
                unrealized_pnl = Decimal("0")

        results[scope_key] = PnLGroupResult(
            instrument_key=instrument_key,
            currency=currency,
            open_quantity=open_quantity,
            open_cost_basis=open_cost_basis,
            realized_pnl=realized,
            unrealized_pnl=unrealized_pnl,
        )

    totals_realized: dict[str, Decimal] = {}
    totals_unrealized: dict[str, Decimal | None] = {}

    for result in results.values():
        totals_realized[result.currency] = (
            totals_realized.get(result.currency, Decimal("0")) + result.realized_pnl
        )
        totals_unrealized[result.currency] = _add_optional(
            totals_unrealized.get(result.currency),
            result.unrealized_pnl,
        )

    return PnLCalculationResult(
        calculation_version=FIFO_CALCULATION_VERSION,
        groups=results,
        closed_allocations=tuple(closed_allocations),
        total_realized_pnl_by_currency=totals_realized,
        total_unrealized_pnl_by_currency=totals_unrealized,
        unmatched_close_fill_uids=tuple(unmatched_close_fill_uids),
    )


def calculate_fifo_pnl_with_lifecycle_events(
    fills: Iterable[NormalizedFill],
    lifecycle_events: Iterable[ApprovedOptionLifecycleEvent],
    *,
    marks: dict[str, Decimal] | None = None,
    allow_unmatched_close: bool = False,
) -> PnLCalculationResult:
    """Calculate FIFO P&L with explicitly approved option lifecycle events.

    Fills and lifecycle events are processed in effective-time order. Ordinary
    fills win a timestamp tie, then opens win a fill tie before closes. This
    lets a confirmed opening fill establish inventory before a same-instant
    lifecycle instruction while preserving deterministic replay.

    Unconfirmed broker rows, description hints, and raw evidence legs are not
    accepted by this boundary. Callers must resolve them into
    :class:`ApprovedOptionLifecycleEvent` first.
    """

    states: dict[tuple[str, str, str, str], _MatchedLot] = {}
    unmatched_close_fill_uids: list[str] = []
    lifecycle_allocations: list[LifecycleLotAllocation] = []
    timeline: list[tuple[datetime, int, int, str, str, object]] = []

    for fill in fills:
        _validate_fill_economics(fill)
        action, close_quantity, direction = _classify_fill(fill)
        sort_action = 0 if action == "OPEN" else 1
        timeline.append(
            (
                fill.filled_at,
                0,
                sort_action,
                fill.fill_uid,
                "FILL",
                (fill, action, close_quantity, direction),
            )
        )

    seen_event_uids: set[str] = set()
    for event in lifecycle_events:
        _validate_lifecycle_event(event)
        if event.event_uid in seen_event_uids:
            raise LotAllocationError(
                f"Duplicate approved lifecycle event UID: {event.event_uid}"
            )
        seen_event_uids.add(event.event_uid)
        timeline.append(
            (
                event.effective_at,
                1,
                0,
                event.event_uid,
                "LIFECYCLE",
                event,
            )
        )

    for _effective_at, _kind_order, _action_order, _uid, kind, payload in sorted(
        timeline, key=lambda item: (item[0], item[1], item[2], item[3])
    ):
        if kind == "FILL":
            fill, action, close_quantity, direction = payload
            scope_key = _scope_key_for_fill(fill)
            state = _state_for_scope(states, scope_key)
            _apply_classified_fill(
                state,
                scope_key=scope_key,
                fill=fill,
                action=action,
                close_quantity=close_quantity,
                direction=direction,
                allow_unmatched_close=allow_unmatched_close,
                unmatched_close_fill_uids=unmatched_close_fill_uids,
            )
            continue

        event = payload
        event_allocations = _apply_option_lifecycle_event(
            states,
            event,
            unmatched_close_fill_uids=unmatched_close_fill_uids,
        )
        lifecycle_allocations.extend(event_allocations)

    result = _summarize_states(
        states,
        marks=marks,
        unmatched_close_fill_uids=unmatched_close_fill_uids,
    )
    return PnLCalculationResult(
        calculation_version=result.calculation_version,
        groups=result.groups,
        closed_allocations=result.closed_allocations,
        total_realized_pnl_by_currency=result.total_realized_pnl_by_currency,
        total_unrealized_pnl_by_currency=result.total_unrealized_pnl_by_currency,
        unmatched_close_fill_uids=result.unmatched_close_fill_uids,
        lifecycle_allocations=tuple(lifecycle_allocations),
    )


def _scope_key_for_fill(fill: NormalizedFill) -> tuple[str, str, str, str]:
    return (
        fill.source_broker,
        fill.source_account_id,
        build_instrument_key(fill),
        fill.currency,
    )


def _state_for_scope(
    states: dict[tuple[str, str, str, str], _MatchedLot],
    scope_key: tuple[str, str, str, str],
) -> _MatchedLot:
    state = states.get(scope_key)
    if state is None:
        state = _MatchedLot(
            instrument_key=scope_key[2],
            open_lots=[],
            closed_allocations=[],
        )
        states[scope_key] = state
    return state


def _apply_classified_fill(
    state: _MatchedLot,
    *,
    scope_key: tuple[str, str, str, str],
    fill: NormalizedFill,
    action: str,
    close_quantity: Decimal,
    direction: str,
    allow_unmatched_close: bool,
    unmatched_close_fill_uids: list[str],
    source_event_uid: str | None = None,
) -> None:
    if action == "OPEN":
        state.open_lots.append(_create_open_lot(fill))
        return
    _match_close_fill(
        state,
        scope_key=scope_key,
        close_fill=fill,
        close_quantity=close_quantity,
        direction=direction,
        allow_unmatched_close=allow_unmatched_close,
        unmatched_close_fill_uids=unmatched_close_fill_uids,
        source_event_uid=source_event_uid,
    )


def _validate_lifecycle_event(event: ApprovedOptionLifecycleEvent) -> None:
    if not event.event_uid.strip():
        raise LotAllocationError("Lifecycle event UID is required")
    if event.evidence_status != "approved":
        raise LotAllocationError(
            f"Lifecycle event {event.event_uid} is not approved evidence"
        )
    if event.event_type not in {"ASSIGNMENT", "EXERCISE", "EXPIRATION"}:
        raise LotAllocationError(
            f"Unsupported lifecycle event type: {event.event_type}"
        )
    if event.contracts <= 0:
        raise LotAllocationError(
            f"Lifecycle event contracts must be positive: {event.event_uid}"
        )
    if event.event_commission < 0 or event.event_fees < 0:
        raise LotAllocationError(
            f"Lifecycle event costs must not be negative: {event.event_uid}"
        )
    if not event.predecessor_open_fill_uids:
        raise LotAllocationError(
            f"Lifecycle event predecessor fill links are required: {event.event_uid}"
        )
    if len(set(event.predecessor_open_fill_uids)) != len(
        event.predecessor_open_fill_uids
    ):
        raise LotAllocationError(
            f"Lifecycle event predecessor fill links must be unique: {event.event_uid}"
        )
    if not event.source_event_leg_uids:
        raise LotAllocationError(
            f"Lifecycle event source leg links are required: {event.event_uid}"
        )
    if len(set(event.source_event_leg_uids)) != len(event.source_event_leg_uids):
        raise LotAllocationError(
            f"Lifecycle event source leg links must be unique: {event.event_uid}"
        )
    if event.predecessor_direction not in {"LONG", "SHORT"}:
        raise LotAllocationError(
            f"Unsupported predecessor direction: {event.predecessor_direction}"
        )
    if event.event_type == "ASSIGNMENT" and event.predecessor_direction != "SHORT":
        raise LotAllocationError("Assignment must consume short option inventory")
    if event.event_type == "EXERCISE" and event.predecessor_direction != "LONG":
        raise LotAllocationError("Exercise must consume long option inventory")
    if event.option_scope_key[:2] != (
        event.source_broker,
        event.source_account_id,
    ) or event.option_scope_key[3] != event.currency:
        raise LotAllocationError(
            f"Lifecycle event scope disagrees with broker/account/currency: {event.event_uid}"
        )
    if not event.option_scope_key[2].startswith("option|"):
        raise LotAllocationError(
            f"Lifecycle event predecessor scope must identify an option: {event.event_uid}"
        )

    successor_values = (
        event.successor_action,
        event.successor_position_effect,
        event.successor_symbol,
        event.successor_quantity,
        event.strike_cash_amount,
    )
    if event.event_type == "EXPIRATION":
        if any(value is not None for value in successor_values):
            raise LotAllocationError(
                f"Expiration must not create a successor security: {event.event_uid}"
            )
        return

    if event.successor_action not in {"BUY", "SELL"}:
        raise LotAllocationError(
            f"Lifecycle successor action is required: {event.event_uid}"
        )
    if event.successor_position_effect not in {"OPEN", "CLOSE"}:
        raise LotAllocationError(
            f"Lifecycle successor position effect is required: {event.event_uid}"
        )
    if not (event.successor_symbol or "").strip():
        raise LotAllocationError(
            f"Lifecycle successor symbol is required: {event.event_uid}"
        )
    if event.successor_quantity is None or event.successor_quantity <= 0:
        raise LotAllocationError(
            f"Lifecycle successor quantity must be positive: {event.event_uid}"
        )
    if event.strike_cash_amount is None or event.strike_cash_amount < 0:
        raise LotAllocationError(
            f"Lifecycle strike cash amount must not be negative: {event.event_uid}"
        )


def _apply_option_lifecycle_event(
    states: dict[tuple[str, str, str, str], _MatchedLot],
    event: ApprovedOptionLifecycleEvent,
    *,
    unmatched_close_fill_uids: list[str],
) -> list[LifecycleLotAllocation]:
    option_state = states.get(event.option_scope_key)
    if option_state is None:
        raise LotAllocationError(
            f"No option inventory for lifecycle event {event.event_uid}"
        )

    remaining = event.contracts
    allocations: list[LifecycleLotAllocation] = []
    for expected_fill_uid in event.predecessor_open_fill_uids:
        if remaining <= 0:
            raise LotAllocationError(
                f"Lifecycle event {event.event_uid} has unused predecessor fill link {expected_fill_uid}"
            )
        open_lot = _find_next_matching_lot(
            option_state.open_lots, event.predecessor_direction
        )
        if open_lot is None:
            raise LotAllocationError(
                f"No matching option lot for lifecycle event {event.event_uid}"
            )
        if open_lot.fill_uid != expected_fill_uid:
            raise LotAllocationError(
                f"Lifecycle event {event.event_uid} violates FIFO predecessor order: "
                f"expected {open_lot.fill_uid}, received {expected_fill_uid}"
            )

        match_contracts = min(remaining, open_lot.remaining_quantity)
        open_commission = _allocate_match_costs(
            open_lot.open_commission,
            open_lot.opened_quantity,
            match_contracts,
        )
        open_fees = _allocate_match_costs(
            open_lot.open_fees,
            open_lot.opened_quantity,
            match_contracts,
        )
        event_commission = (
            event.event_commission / event.contracts
        ) * match_contracts
        event_fees = (event.event_fees / event.contracts) * match_contracts
        premium_amount = (
            open_lot.fill_price * open_lot.multiplier * match_contracts
        )
        if open_lot.direction == "LONG":
            net_option_basis = premium_amount + open_commission + open_fees
        else:
            net_option_basis = -(
                premium_amount - open_commission - open_fees
            )

        allocation_index = len(allocations)
        successor_fill_uid: str | None = None
        successor_quantity: Decimal | None = None
        successor_effective_price: Decimal | None = None
        realized_pnl = Decimal("0")

        if event.event_type == "EXPIRATION":
            realized_pnl = -net_option_basis - event_commission - event_fees
            option_state.realized_pnl += realized_pnl
        else:
            successor_quantity = (
                event.successor_quantity / event.contracts
            ) * match_contracts
            strike_cash = (
                event.strike_cash_amount / event.contracts
            ) * match_contracts
            if event.successor_action == "BUY":
                successor_effective_price = (
                    strike_cash + net_option_basis
                ) / successor_quantity
            else:
                successor_effective_price = (
                    strike_cash - net_option_basis
                ) / successor_quantity
            successor_fill_uid = (
                f"lifecycle:{event.event_uid}:successor:{allocation_index}"
            )
            successor_fill = _successor_fill_from_lifecycle(
                event,
                fill_uid=successor_fill_uid,
                quantity=successor_quantity,
                fill_price=successor_effective_price,
                commission=event_commission,
                fees=event_fees,
            )
            _validate_fill_economics(successor_fill)
            action, close_quantity, direction = _classify_fill(successor_fill)
            successor_scope = _scope_key_for_fill(successor_fill)
            successor_state = _state_for_scope(states, successor_scope)
            _apply_classified_fill(
                successor_state,
                scope_key=successor_scope,
                fill=successor_fill,
                action=action,
                close_quantity=close_quantity,
                direction=direction,
                allow_unmatched_close=False,
                unmatched_close_fill_uids=unmatched_close_fill_uids,
                source_event_uid=event.event_uid,
            )

        allocations.append(
            LifecycleLotAllocation(
                calculation_version=OPTION_LIFECYCLE_CALCULATION_VERSION,
                event_uid=event.event_uid,
                event_type=event.event_type,
                allocation_index=allocation_index,
                option_scope_key=event.option_scope_key,
                predecessor_open_fill_uid=open_lot.fill_uid,
                predecessor_direction=open_lot.direction,
                contracts=match_contracts,
                multiplier=open_lot.multiplier,
                net_option_basis=net_option_basis,
                allocated_open_commission=open_commission,
                allocated_open_fees=open_fees,
                allocated_event_commission=event_commission,
                allocated_event_fees=event_fees,
                realized_pnl=realized_pnl,
                successor_fill_uid=successor_fill_uid,
                successor_action=event.successor_action,
                successor_position_effect=event.successor_position_effect,
                successor_symbol=event.successor_symbol,
                successor_quantity=successor_quantity,
                successor_effective_price=successor_effective_price,
                effective_at=event.effective_at,
                source_event_leg_uids=event.source_event_leg_uids,
            )
        )

        open_lot.remaining_quantity -= match_contracts
        remaining -= match_contracts
        if open_lot.remaining_quantity <= 0:
            option_state.open_lots.remove(open_lot)

    if remaining > 0:
        raise LotAllocationError(
            f"Lifecycle event {event.event_uid} has {remaining} unmatched contract(s)"
        )
    return allocations


def _successor_fill_from_lifecycle(
    event: ApprovedOptionLifecycleEvent,
    *,
    fill_uid: str,
    quantity: Decimal,
    fill_price: Decimal,
    commission: Decimal,
    fees: Decimal,
) -> NormalizedFill:
    return NormalizedFill(
        fill_uid=fill_uid,
        source_broker=event.source_broker,
        source_account_id=event.source_account_id,
        source_fill_id=fill_uid,
        source_order_id=None,
        episode_group_id=None,
        asof=event.effective_at.date(),
        filled_at=event.effective_at,
        asset_class="stock",
        symbol=(event.successor_symbol or "").strip().upper(),
        side=event.successor_action or "",
        quantity=quantity,
        fill_price=fill_price,
        commission=commission,
        fees=fees,
        currency=event.currency,
        fetched_at=event.effective_at,
        raw_path=None,
        open_close=event.successor_position_effect,
    )


def _summarize_states(
    states: dict[tuple[str, str, str, str], _MatchedLot],
    *,
    marks: dict[str, Decimal] | None,
    unmatched_close_fill_uids: list[str],
) -> PnLCalculationResult:
    results: dict[tuple[str, str, str, str], PnLGroupResult] = {}
    closed_allocations: list[ClosedLotAllocation] = []

    for scope_key, state in states.items():
        _source_broker, _source_account_id, instrument_key, currency = scope_key
        closed_allocations.extend(state.closed_allocations)
        direction = _current_direction(state.open_lots)
        open_quantity = _sum_open_quantity(state.open_lots)
        open_cost_basis = _sum_open_cost_basis(state.open_lots)

        mark = marks.get(instrument_key) if marks else None
        unrealized_pnl = None
        if mark is not None:
            if direction == "LONG":
                notional_open_qty = _open_notional_quantity(state.open_lots)
                unrealized_pnl = (
                    mark - _weighted_open_price(state.open_lots)
                ) * notional_open_qty
                unrealized_pnl -= _open_fees_opening_component(state.open_lots)
            elif direction == "SHORT":
                notional_open_qty = _open_notional_quantity(
                    state.open_lots, absolute=True
                )
                unrealized_pnl = (
                    _weighted_open_price(state.open_lots) - mark
                ) * notional_open_qty
                unrealized_pnl -= _open_fees_opening_component(state.open_lots)
            else:
                unrealized_pnl = Decimal("0")

        results[scope_key] = PnLGroupResult(
            instrument_key=instrument_key,
            currency=currency,
            open_quantity=open_quantity,
            open_cost_basis=open_cost_basis,
            realized_pnl=state.realized_pnl,
            unrealized_pnl=unrealized_pnl,
        )

    totals_realized: dict[str, Decimal] = {}
    totals_unrealized: dict[str, Decimal | None] = {}
    for result in results.values():
        totals_realized[result.currency] = (
            totals_realized.get(result.currency, Decimal("0"))
            + result.realized_pnl
        )
        totals_unrealized[result.currency] = _add_optional(
            totals_unrealized.get(result.currency),
            result.unrealized_pnl,
        )

    return PnLCalculationResult(
        calculation_version=FIFO_CALCULATION_VERSION,
        groups=results,
        closed_allocations=tuple(closed_allocations),
        total_realized_pnl_by_currency=totals_realized,
        total_unrealized_pnl_by_currency=totals_unrealized,
        unmatched_close_fill_uids=tuple(unmatched_close_fill_uids),
    )


def _classify_fill(fill: NormalizedFill) -> tuple[str, Decimal, str]:
    """Classify fill as open or close and return fill size/direction.

    Returns:
        Tuple: (action, quantity_abs, direction)
          - action: OPEN or CLOSE
          - quantity_abs: positive Decimal
          - direction: LONG for long positions opened/closed, SHORT for short.
    """

    side = (fill.side or "").strip().upper()
    open_close = (fill.open_close or "").strip().upper()
    qty = _normalize_quantity(fill.quantity)

    if side == "BUY":
        if open_close in {"", "OPEN"}:
            return "OPEN", qty, "LONG"
        if open_close == "CLOSE":
            return "CLOSE", qty, "SHORT"
        raise LotAllocationError(f"Unsupported open_close value for side {fill.side}: {fill.open_close}")

    if side == "BUY_TO_OPEN":
        if open_close in {"", "OPEN"}:
            return "OPEN", qty, "LONG"
        raise LotAllocationError(f"Unsupported open_close value for side {fill.side}: {fill.open_close}")

    if side == "SELL_TO_CLOSE":
        return "CLOSE", qty, "LONG"

    if side == "BUY_TO_CLOSE":
        if open_close in {"", "CLOSE"}:
            return "CLOSE", qty, "SHORT"
        if open_close == "OPEN":
            raise LotAllocationError(f"Unsupported open_close value for side {fill.side}: {fill.open_close}")
        raise LotAllocationError(f"Unsupported open_close value for side {fill.side}: {fill.open_close}")

    if side in {"SELL", "SELL_TO_OPEN"}:
        if open_close in {"", "OPEN"}:
            return "OPEN", qty, "SHORT"
        if open_close == "CLOSE":
            return "CLOSE", qty, "LONG"
        raise LotAllocationError(f"Unsupported open_close value for side {fill.side}: {fill.open_close}")

    raise LotAllocationError(f"Unsupported fill side for FIFO P&L: {fill.side}")


def _normalize_quantity(quantity: Decimal) -> Decimal:
    if quantity <= 0:
        raise LotAllocationError(f"Fill quantity must be positive for FIFO matching: {quantity}")
    return quantity


def _validate_fill_economics(fill: NormalizedFill) -> None:
    if not fill.fill_uid.strip():
        raise LotAllocationError("Fill UID is required for P&L allocation lineage")
    if not fill.currency.strip():
        raise LotAllocationError(f"Fill currency is required for P&L: {fill.fill_uid}")
    if fill.fill_price < 0:
        raise LotAllocationError(
            f"Fill price must not be negative for P&L: {fill.fill_uid}={fill.fill_price}"
        )
    if fill.commission < 0 or fill.fees < 0:
        raise LotAllocationError(
            f"Commission and fees must not be negative for P&L: {fill.fill_uid}"
        )

    asset_class = fill.asset_class.strip().lower()
    if asset_class == "option" and fill.multiplier is None:
        raise LotAllocationError(
            f"Option multiplier is required for P&L: {fill.fill_uid}"
        )
    if fill.multiplier is not None and fill.multiplier <= 0:
        raise LotAllocationError(
            f"Multiplier must be positive for P&L: {fill.fill_uid}={fill.multiplier}"
        )


def _create_open_lot(fill: NormalizedFill) -> _OpenLot:
    return _OpenLot(
        fill_uid=fill.fill_uid,
        direction="LONG" if fill.side.upper() in {"BUY", "BUY_TO_OPEN"} else "SHORT",
        opened_quantity=fill.quantity,
        remaining_quantity=fill.quantity,
        fill_price=fill.fill_price,
        multiplier=fill.multiplier if fill.multiplier is not None else Decimal("1"),
        open_commission=_allocate_fill_fees(fill.commission, fill.quantity),
        open_fees=_allocate_fill_fees(fill.fees, fill.quantity),
        opened_at=fill.filled_at,
    )


def _allocate_fill_fees(value: Decimal, quantity: Decimal) -> Decimal:
    if quantity <= 0:
        raise LotAllocationError(f"Invalid quantity for fee allocation: {quantity}")
    return value


def _match_close_fill(
    state: _MatchedLot,
    scope_key: tuple[str, str, str, str],
    close_fill: NormalizedFill,
    close_quantity: Decimal,
    direction: str,
    *,
    allow_unmatched_close: bool,
    unmatched_close_fill_uids: list[str],
    source_event_uid: str | None = None,
) -> None:
    close_remain = close_quantity

    while close_remain > 0:
        open_lot = _find_next_matching_lot(state.open_lots, direction)
        if open_lot is None:
            if allow_unmatched_close:
                unmatched_close_fill_uids.append(close_fill.fill_uid)
                return
            raise LotAllocationError(
                f"No matching open lot for close fill {close_fill.fill_uid}"
            )
        match_qty = min(close_remain, open_lot.remaining_quantity)

        gross_realized = _calc_matched_realized(open_lot, close_fill, match_qty)
        allocated_open_commission = _allocate_match_costs(
            open_lot.open_commission, open_lot.opened_quantity, match_qty
        )
        allocated_open_fees = _allocate_match_costs(
            open_lot.open_fees, open_lot.opened_quantity, match_qty
        )
        allocated_close_commission = (close_fill.commission / close_quantity) * match_qty
        allocated_close_fees = (close_fill.fees / close_quantity) * match_qty
        realized = (
            gross_realized
            - allocated_open_commission
            - allocated_open_fees
            - allocated_close_commission
            - allocated_close_fees
        )
        state.realized_pnl += realized
        state.closed_allocations.append(
            ClosedLotAllocation(
                scope_key=scope_key,
                open_fill_uid=open_lot.fill_uid,
                close_fill_uid=close_fill.fill_uid,
                direction=open_lot.direction,
                quantity=match_qty,
                multiplier=open_lot.multiplier,
                open_price=open_lot.fill_price,
                close_price=close_fill.fill_price,
                gross_realized_pnl=gross_realized,
                allocated_open_commission=allocated_open_commission,
                allocated_open_fees=allocated_open_fees,
                allocated_close_commission=allocated_close_commission,
                allocated_close_fees=allocated_close_fees,
                realized_pnl=realized,
                closed_at=close_fill.filled_at,
                source_event_uid=source_event_uid,
            )
        )

        open_lot.remaining_quantity -= match_qty
        close_remain -= match_qty
        if open_lot.remaining_quantity <= 0:
            state.open_lots.remove(open_lot)


def _find_next_matching_lot(open_lots: list[_OpenLot], close_direction: str) -> _OpenLot | None:
    for lot in open_lots:
        if close_direction == "LONG" and lot.direction == "LONG":
            return lot
        if close_direction == "SHORT" and lot.direction == "SHORT":
            return lot
    return None


def _calc_matched_realized(open_lot: _OpenLot, close_fill: NormalizedFill, qty: Decimal) -> Decimal:
    multiplier = open_lot.multiplier
    open_multiplied = open_lot.fill_price * multiplier
    close_multiplied = close_fill.fill_price * multiplier

    if open_lot.direction == "LONG":
        return (close_multiplied - open_multiplied) * qty
    return (open_multiplied - close_multiplied) * qty


def _allocate_match_costs(total_cost: Decimal, total_quantity: Decimal, matched_quantity: Decimal) -> Decimal:
    if total_quantity <= 0:
        raise LotAllocationError(f"Open lot must have positive quantity: {total_quantity}")
    return total_cost * (matched_quantity / total_quantity)


def _sum_open_quantity(open_lots: list[_OpenLot]) -> Decimal:
    quantity = Decimal("0")
    for lot in open_lots:
        signed = lot.remaining_quantity
        if lot.direction == "SHORT":
            signed = -signed
        quantity += signed
    return quantity


def _current_direction(open_lots: list[_OpenLot]) -> str:
    if not open_lots:
        return "FLAT"
    first_dir = open_lots[0].direction
    if all(l.direction == first_dir for l in open_lots):
        return first_dir
    return "FLAT"


def _sum_open_cost_basis(open_lots: list[_OpenLot]) -> Decimal:
    cost = Decimal("0")
    for lot in open_lots:
        quantity = lot.remaining_quantity
        filled_cost = lot.fill_price * lot.multiplier * quantity
        fee_share = _allocate_match_costs(
            lot.open_commission + lot.open_fees,
            lot.opened_quantity,
            quantity,
        )
        cost += filled_cost + fee_share
    return cost


def _weighted_open_price(open_lots: list[_OpenLot]) -> Decimal:
    if not open_lots:
        return Decimal("0")
    total_qty = Decimal("0")
    weighted = Decimal("0")
    for lot in open_lots:
        qty = lot.remaining_quantity
        total_qty += qty
        weighted += lot.fill_price * qty
    return weighted / total_qty if total_qty else Decimal("0")


def _open_notional_quantity(open_lots: list[_OpenLot], *, absolute: bool = False) -> Decimal:
    if not open_lots:
        return Decimal("0")
    total = Decimal("0")
    for lot in open_lots:
        qty = lot.remaining_quantity * lot.multiplier
        total += abs(qty) if absolute else qty
    return total


def _open_fees_opening_component(open_lots: list[_OpenLot]) -> Decimal:
    if not open_lots:
        return Decimal("0")
    total = Decimal("0")
    for lot in open_lots:
        total += _allocate_match_costs(lot.open_commission + lot.open_fees, lot.opened_quantity, lot.remaining_quantity)
    return total


def _add_optional(a: Decimal | None, b: Decimal | None) -> Decimal | None:
    if b is None:
        return None
    if a is None:
        return b
    return a + b


def _group_fills_by_scope(fills: Iterable[NormalizedFill]) -> dict[tuple[str, str, str, str], list[NormalizedFill]]:
    grouped: dict[tuple[str, str, str, str], list[NormalizedFill]] = {}
    for fill in fills:
        key = (
            fill.source_broker,
            fill.source_account_id,
            build_instrument_key(fill),
            fill.currency,
        )
        grouped.setdefault(key, []).append(fill)

    return grouped
