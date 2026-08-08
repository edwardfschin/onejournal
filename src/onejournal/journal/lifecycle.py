"""Lifecycle contract scaffolding for deterministic fill-to-lifecycle transition planning.

This module is a first implementation for CON-04 (contracting lifecycle
semantics). It intentionally stays read-only and conservative:

- every normalized fill becomes one lifecycle record (no coalescing)
- close-side fills are matched against prior opens by FIFO-style scope state
- partial closes can be observed as partially matched with optional unmatched
  quantities represented explicitly
- unmatched closes fail closed by default
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Literal

from onejournal.brokers.normalized import NormalizedFill
from onejournal.pnl.calculations import build_instrument_key


LifecycleAction = Literal["OPEN", "CLOSE"]
LifecycleDirection = Literal["LONG", "SHORT"]
LifecycleStatus = Literal["open", "close_full", "close_partial"]


class LifecycleContractError(ValueError):
    """Raised when a fill cannot be represented in the current lifecycle contract."""


@dataclass(frozen=True)
class LifecycleFillEvent:
    """One immutable lifecycle-facing fill event.

    Keep this shape stable only after ADR-0005 is accepted.
    """

    fill_uid: str
    scope_key: tuple[str, str, str, str]
    action: LifecycleAction
    direction: LifecycleDirection
    fill_quantity: Decimal
    matched_open_quantity: Decimal
    unmatched_close_quantity: Decimal
    open_quantity_after: Decimal
    status: LifecycleStatus


@dataclass(frozen=True)
class LifecycleFillSequenceResult:
    """Lifecycle events with final per-scope open position summary."""

    events: tuple[LifecycleFillEvent, ...]
    scope_open_quantity: dict[tuple[str, str, str, str], tuple[Decimal, Decimal]]


def build_lifecycle_fill_events(
    fills: Iterable[NormalizedFill],
    *,
    allow_unmatched_close: bool = False,
) -> LifecycleFillSequenceResult:
    """Build lifecycle events from normalized fills with conservative matching.

    Matching behavior:
    - match closes against prior opens with same (scope, direction)
    - partial close leaves unmatched quantity when no enough open exists
    - unmatched close quantities fail closed by default
    """

    events: list[LifecycleFillEvent] = []
    open_by_scope: dict[tuple[str, str, str, str], tuple[Decimal, Decimal]] = {}
    # state tuple: (long_open, short_open)

    ordered = sorted(enumerate(fills), key=lambda item: (item[1].filled_at, item[0]))
    for _sequence_index, fill in ordered:
        action, close_qty, direction = _classify_fill(fill)
        scope = _scope_key(fill)
        long_open, short_open = open_by_scope.setdefault(scope, (Decimal("0"), Decimal("0")))

        if action == "OPEN":
            if direction == "LONG":
                long_open += close_qty
                open_after = long_open
            else:
                short_open += close_qty
                open_after = short_open

            matched = close_qty
            unmatched = Decimal("0")
            status: LifecycleStatus = "open"
        else:
            if direction == "LONG":
                can_match = long_open
                matched = min(close_qty, can_match)
                long_open -= matched
                unmatched = close_qty - matched
                open_after = long_open
            else:
                can_match = short_open
                matched = min(close_qty, can_match)
                short_open -= matched
                unmatched = close_qty - matched
                open_after = short_open

            if unmatched:
                if not allow_unmatched_close:
                    raise LifecycleContractError(
                        f"Unmatched close quantity for fill {fill.fill_uid}: {unmatched}"
                    )
                status = "close_partial"
            else:
                status = "close_full"

        open_by_scope[scope] = (long_open, short_open)

        events.append(
            LifecycleFillEvent(
                fill_uid=fill.fill_uid,
                scope_key=scope,
                action=action,
                direction=direction,
                fill_quantity=close_qty,
                matched_open_quantity=matched,
                unmatched_close_quantity=unmatched,
                open_quantity_after=open_after,
                status=status,
            )
        )

    return LifecycleFillSequenceResult(
        events=tuple(events),
        scope_open_quantity=open_by_scope,
    )


def _scope_key(fill: NormalizedFill) -> tuple[str, str, str, str]:
    if fill.episode_group_id:
        return (
            fill.source_broker,
            fill.source_account_id,
            f"episode:{fill.episode_group_id.strip()}",
            fill.currency,
        )
    return (
        fill.source_broker,
        fill.source_account_id,
        build_instrument_key(fill),
        fill.currency,
    )


def _classify_fill(fill: NormalizedFill) -> tuple[LifecycleAction, Decimal, LifecycleDirection]:
    """Classify a fill by action/direction with conservative validation."""

    side = fill.side.strip().upper()
    open_close = (fill.open_close or "").strip().upper()
    qty = _normalize_quantity(fill.quantity)

    if side in {"BUY", "BUY_TO_OPEN"}:
        if open_close in {"", "OPEN"}:
            return "OPEN", qty, "LONG"
        if open_close == "CLOSE":
            return "CLOSE", qty, "SHORT"
        raise LifecycleContractError(f"Unsupported open_close value for side {fill.side}: {fill.open_close}")

    if side == "SELL_TO_CLOSE":
        return "CLOSE", qty, "LONG"

    if side == "BUY_TO_CLOSE":
        return "CLOSE", qty, "SHORT"

    if side == "SELL_TO_OPEN":
        if open_close in {"", "OPEN"}:
            return "OPEN", qty, "SHORT"
        raise LifecycleContractError(f"Unsupported open_close value for side {fill.side}: {fill.open_close}")

    if side == "SELL":
        if open_close in {"", "OPEN"}:
            return "OPEN", qty, "LONG"
        if open_close == "CLOSE":
            return "CLOSE", qty, "LONG"
        raise LifecycleContractError(f"Unsupported open_close value for side {fill.side}: {fill.open_close}")

    raise LifecycleContractError(f"Unsupported fill side for lifecycle contract: {fill.side}")


def _normalize_quantity(quantity: Decimal) -> Decimal:
    if quantity <= 0:
        raise LifecycleContractError(f"Fill quantity must be positive for lifecycle matching: {quantity}")
    return quantity
