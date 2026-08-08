"""Deterministic FIFO P&L calculations for confirmed fills.

This module implements a conservative calculator for closed and open lot P&L.

Scope and caveats:
- Uses confirmed fills only.
- Uses FIFO allocation by open lot order.
- Treats close actions only when there is a matching open lot; unsupported
  lifecycle events are intentionally rejected (fail-closed).
- Works with simple net-closed positions and partial closes.

The implementation intentionally avoids UI formatting and broker API concerns so
the same logic can later be reused by canonical job and reporting layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Iterable

from onejournal.brokers.normalized import NormalizedFill


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
class PnLCalculationResult:
    """Result of FIFO P&L calculation across all groups."""

    groups: dict[tuple[str, str, str, str], PnLGroupResult]
    total_realized_pnl_by_currency: dict[str, Decimal]
    total_unrealized_pnl_by_currency: dict[str, Decimal | None]
    unmatched_close_fill_uids: tuple[str, ...] = ()


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
        strike = f"{fill.strike}" if fill.strike is not None else ""
        multiplier = f"{fill.multiplier}" if fill.multiplier is not None else "1"
        return (
            f"option|{(fill.underlying_symbol or '').upper()}|"
            f"{(fill.option_symbol or '').upper()}|"
            f"{(fill.option_type or '').upper()}|{expiry}|{strike}|{multiplier}"
        )
    return f"stock|{fill.symbol.strip().upper()}"


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
    unmatched_close_fill_uids: list[str] = []

    for scope_key, group_fills in groups.items():
        _source_broker, _source_account_id, instrument_key, currency = scope_key
        classified_fills = []
        for fill in group_fills:
            action, close_quantity, direction = _classify_fill(fill)
            sort_action = 0 if action == "OPEN" else 1
            classified_fills.append((fill.filled_at, sort_action, fill.fill_uid, fill, action, close_quantity, direction))

        ordered = sorted(classified_fills, key=lambda item: (item[0], item[1], item[2]))
        state = _MatchedLot(instrument_key=instrument_key, open_lots=[])

        for _filled_at, _sort_action, _fill_uid, fill, action, close_quantity, direction in ordered:
            if action == "OPEN":
                state.open_lots.append(_create_open_lot(fill))
                continue
            _match_close_fill(
                state,
                close_fill=fill,
                close_quantity=close_quantity,
                direction=direction,
                allow_unmatched_close=allow_unmatched_close,
                unmatched_close_fill_uids=unmatched_close_fill_uids,
            )

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
        groups=results,
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
    close_fill: NormalizedFill,
    close_quantity: Decimal,
    direction: str,
    *,
    allow_unmatched_close: bool,
    unmatched_close_fill_uids: list[str],
) -> None:
    close_remain = close_quantity
    close_costs = close_fill.commission + close_fill.fees
    close_unit_cost = close_costs / close_quantity if close_quantity else Decimal("0")

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

        realized = _calc_matched_realized(open_lot, close_fill, match_qty)
        realized -= _allocate_match_costs(
            open_lot.open_commission, open_lot.opened_quantity, match_qty
        )
        realized -= _allocate_match_costs(
            open_lot.open_fees, open_lot.opened_quantity, match_qty
        )
        realized -= close_unit_cost * match_qty
        state.realized_pnl += realized

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
