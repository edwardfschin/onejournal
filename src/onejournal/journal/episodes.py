"""Trade episode preview builders for read-only dashboard and DB import surfaces.

Purpose
-------
Build deterministic trade-episode previews from broker-normalized fills.

This implementation uses lifecycle matching to determine deterministic group and
close behavior while keeping the public preview format stable.

Read-only:
- no broker API calls
- no database writes
- no output files
- no order placement
- no order cancellation
- no automation
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any
from collections import defaultdict

from onejournal.brokers.normalized import NormalizedFill
from onejournal.journal.lifecycle import (
    LifecycleContractError,
    build_lifecycle_fill_events,
)
from onejournal.pnl.calculations import build_instrument_key


@dataclass(frozen=True)
class TradeEpisodePreview:
    """Minimal trade story preview built from normalized fills."""

    episode_uid: str
    source_account_id: str
    primary_symbol: str
    asset_class: str
    opened_at: datetime
    status: str
    fill_count: int
    net_quantity: Decimal
    gross_cashflow: Decimal
    total_commission: Decimal
    total_fees: Decimal
    source_broker: str
    strategy_type: str
    strategy_label: str
    leg_count: int
    leg_summary: str
    cashflow_label: str
    legs: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_episode_previews_from_fills(
    fills: list[NormalizedFill],
) -> list[TradeEpisodePreview]:
    """Build deterministic trade episode previews from normalized fills."""
    if not fills:
        return []

    try:
        lifecycle_result = build_lifecycle_fill_events(fills)
    except LifecycleContractError as exc:
        raise ValueError(str(exc))

    fill_lookup = {fill.fill_uid: fill for fill in fills}
    if len(fill_lookup) != len(fills):
        raise ValueError("Duplicate fill_uid values were supplied to episode builder")

    grouped_events: dict[tuple[str, str, str, str, str], list] = defaultdict(list)
    for event in lifecycle_result.events:
        grouped_events[_episode_bucket_key(fill_lookup[event.fill_uid])].append(event)

    previews: list[TradeEpisodePreview] = []
    for grouped_key in sorted(grouped_events):
        previews.extend(
            _build_previews_from_lifecycle_bucket(
                grouped_key,
                grouped_events[grouped_key],
                fill_lookup,
            )
        )

    return previews


def _build_previews_from_lifecycle_bucket(
    grouped_key: tuple[str, str, str, str, str],
    events: list,
    fill_lookup: dict[str, NormalizedFill],
) -> list[TradeEpisodePreview]:
    source_broker, source_account_id, asset_class, currency, episode_key = grouped_key
    previews: list[TradeEpisodePreview] = []
    episode_fills: list[NormalizedFill] = []
    open_long = Decimal("0")
    open_short = Decimal("0")
    episode_index = 1

    def flush_episode() -> None:
        nonlocal episode_fills, open_long, open_short, episode_index
        if not episode_fills:
            return

        sorted_group = sorted(episode_fills, key=lambda f: f.filled_at)
        opened_at = sorted_group[0].filled_at

        net_quantity = sum(
            (_signed_quantity(fill) for fill in sorted_group),
            Decimal("0"),
        )
        gross_cashflow = sum((_cashflow(fill) for fill in sorted_group), Decimal("0"))
        total_commission = sum((fill.commission for fill in sorted_group), Decimal("0"))
        total_fees = sum((fill.fees for fill in sorted_group), Decimal("0"))

        open_status = _episode_status(
            sorted_group,
            net_quantity,
            "open" if (open_long or open_short) else "closed",
        )
        strategy_type, strategy_label = _classify_strategy(sorted_group)
        primary_symbol = _primary_symbol_for_episode(sorted_group, episode_key)

        previews.append(
            TradeEpisodePreview(
                episode_uid=_episode_uid_from_parts(
                    source_broker,
                    source_account_id,
                    asset_class,
                    episode_key,
                    episode_index,
                    currency,
                ),
                source_account_id=source_account_id,
                primary_symbol=primary_symbol,
                asset_class=asset_class,
                opened_at=opened_at,
                status=open_status,
                fill_count=len(sorted_group),
                net_quantity=net_quantity,
                gross_cashflow=gross_cashflow,
                total_commission=total_commission,
                total_fees=total_fees,
                source_broker=source_broker,
                strategy_type=strategy_type,
                strategy_label=strategy_label,
                leg_count=len(sorted_group),
                leg_summary=_leg_summary(sorted_group),
                cashflow_label=_cashflow_label(gross_cashflow),
                legs=[_leg_to_payload(fill) for fill in sorted_group],
            )
        )

        episode_index += 1
        episode_fills = []
        open_long = Decimal("0")
        open_short = Decimal("0")

    for event in events:
        fill = fill_lookup[event.fill_uid]
        if event.action == "OPEN":
            if event.direction == "LONG":
                open_long += event.fill_quantity
            else:
                open_short += event.fill_quantity
            episode_fills.append(fill)
            continue

        if event.direction == "LONG":
            open_long -= event.matched_open_quantity
            if open_long < 0:
                raise ValueError(f"Lifecycle open state underflow in bucket {grouped_key}")
        else:
            open_short -= event.matched_open_quantity
            if open_short < 0:
                raise ValueError(f"Lifecycle open state underflow in bucket {grouped_key}")

        episode_fills.append(fill)
        if open_long == 0 and open_short == 0:
            flush_episode()

    if episode_fills:
        flush_episode()

    return previews


def _episode_bucket_key(fill: NormalizedFill) -> tuple[str, str, str, str, str]:
    episode_key = (fill.episode_group_id or "").strip() or build_instrument_key(fill)
    return (
        fill.source_broker,
        fill.source_account_id,
        fill.asset_class,
        (fill.currency or "").strip().upper(),
        episode_key,
    )


def _episode_uid_from_parts(
    source_broker: str,
    source_account_id: str,
    asset_class: str,
    episode_key: str,
    episode_index: int,
    _currency: str,
) -> str:
    base_uid = f"{source_broker}:{source_account_id}:{asset_class}:{episode_key}"
    if episode_index == 1:
        return base_uid
    return f"{base_uid}:{episode_index}"


def _primary_symbol_for_episode(fills: list[NormalizedFill], fallback: str) -> str:
    """Return tradable underlying symbol for a trade episode.

    The episode grouping key may be an operator-friendly episode_group_id such as
    AAPL_SELL_PUT_001 or SPY_PUT_VERTICAL_001. That key must remain in
    episode_uid, but it must not be used as the dashboard symbol.

    For option episodes, prefer underlying_symbol.
    For stock episodes, prefer symbol.
    """

    option_underlyings = sorted(
        {
            (fill.underlying_symbol or "").strip().upper()
            for fill in fills
            if fill.asset_class.lower() == "option" and (fill.underlying_symbol or "").strip()
        }
    )
    if len(option_underlyings) == 1:
        return option_underlyings[0]

    stock_symbols = sorted(
        {
            (fill.symbol or "").strip().upper()
            for fill in fills
            if fill.asset_class.lower() == "stock" and (fill.symbol or "").strip()
        }
    )
    if len(stock_symbols) == 1:
        return stock_symbols[0]

    any_underlying = next(
        ((fill.underlying_symbol or "").strip().upper() for fill in fills if (fill.underlying_symbol or "").strip()),
        "",
    )
    if any_underlying:
        return any_underlying

    any_symbol = next(
        ((fill.symbol or "").strip().upper() for fill in fills if (fill.symbol or "").strip()),
        "",
    )
    return any_symbol or fallback


def _leg_short_label(fill: NormalizedFill) -> str:
    side = (fill.side or "").strip().upper()
    qty = format(fill.quantity, "f")
    symbol = (fill.option_symbol or fill.symbol or "").strip()
    return f"{side} {qty} {symbol}"


def _leg_summary(fills: list[NormalizedFill]) -> str:
    return " / ".join(_leg_short_label(fill) for fill in fills)


def _cashflow_label(value: Decimal) -> str:
    direction = "credit" if value > 0 else "debit" if value < 0 else "even"
    return f"${abs(value):,.2f} {direction}"


def _leg_to_payload(fill: NormalizedFill) -> dict[str, Any]:
    cashflow = _cashflow(fill)
    return {
        "side": (fill.side or "").strip().upper(),
        "symbol": (fill.symbol or "").strip(),
        "option_symbol": (fill.option_symbol or "").strip(),
        "underlying_symbol": (fill.underlying_symbol or "").strip(),
        "option_type": (fill.option_type or "").strip().upper(),
        "expiry": fill.expiry.isoformat() if fill.expiry else None,
        "strike": format(fill.strike, "f") if fill.strike is not None else None,
        "quantity": format(fill.quantity, "f"),
        "fill_price": format(fill.fill_price, "f"),
        "cashflow": format(cashflow, "f"),
        "commission": format(fill.commission, "f"),
        "fees": format(fill.fees, "f"),
    }


def _episode_status(
    fills: list[NormalizedFill],
    net_quantity: Decimal,
    fallback_status: str,
) -> str:
    """Classify simple preview status.

    Single-leg trades can use net quantity.
    Multi-leg opening spreads may net to zero but are still open.
    """

    open_close_values = {(fill.open_close or "").strip().upper() for fill in fills}
    if "OPEN" in open_close_values:
        return "open"
    if net_quantity == 0:
        return "closed"
    return fallback_status


def _classify_strategy(fills: list[NormalizedFill]) -> tuple[str, str]:
    """Classify a simple strategy from grouped fills.

    v1 supports single-leg option/equity trades and simple 2-leg verticals.
    Up to 4-leg trades are grouped safely and labelled as Multi-Leg Option
    until a more specific classifier is added.
    """

    if not fills:
        return "unknown", "Unknown"

    option_fills = [fill for fill in fills if fill.asset_class.lower() == "option"]

    if len(option_fills) == 2:
        underlyings = {(fill.underlying_symbol or "").upper() for fill in option_fills}
        expiries = {fill.expiry for fill in option_fills}
        option_types = {(fill.option_type or "").upper() for fill in option_fills}
        sides = {(fill.side or "").strip().upper() for fill in option_fills}
        has_buy = bool(sides & {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"})
        has_sell = bool(sides & {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"})
        if len(underlyings) == 1 and len(expiries) == 1 and len(option_types) == 1 and has_buy and has_sell:
            option_type = next(iter(option_types))
            net_cashflow = sum((_cashflow(fill) for fill in option_fills), Decimal("0"))
            credit_or_debit = "credit" if net_cashflow > 0 else "debit"
            if option_type == "PUT":
                if credit_or_debit == "credit":
                    return "put_credit_vertical", "Put Credit Vertical"
                return "put_debit_vertical", "Put Debit Vertical"
            if option_type == "CALL":
                if credit_or_debit == "credit":
                    return "call_credit_vertical", "Call Credit Vertical"
                return "call_debit_vertical", "Call Debit Vertical"

    if 2 < len(option_fills) <= 4:
        return "multi_leg_option", "Multi-Leg Option"

    first = fills[0]
    asset_class = first.asset_class.lower()
    side = (first.side or "").strip().upper()
    option_type = (first.option_type or "").upper()
    open_close = (first.open_close or "").strip().upper()

    if asset_class == "option" and open_close in {"", "OPEN"}:
        if side in {"SELL", "SELL_TO_OPEN"} and option_type == "PUT":
            return "sell_put", "Sell Put"
        if side in {"BUY", "BUY_TO_OPEN"} and option_type == "CALL":
            return "buy_call", "Buy Call"
        if side in {"SELL", "SELL_TO_OPEN"} and option_type == "CALL":
            return "sell_call", "Sell Call"
        if side in {"BUY", "BUY_TO_OPEN"} and option_type == "PUT":
            return "buy_put", "Buy Put"

    if asset_class in {"stock", "equity"}:
        if side in {"BUY", "BUY_TO_OPEN"}:
            return "stock_long", "Stock Long"
        if side in {"SELL", "SELL_TO_OPEN"}:
            return "stock_short", "Stock Short"

    return "unknown", "Unknown"

def _signed_quantity(fill: NormalizedFill) -> Decimal:
    """Return signed quantity using simple BUY/SELL side convention."""

    side = (fill.side or "").strip().upper()

    if side in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
        return fill.quantity

    if side in {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}:
        return -fill.quantity

    raise ValueError(f"Unsupported fill side for quantity signing: {fill.side}")


def _cashflow(fill: NormalizedFill) -> Decimal:
    """Return simple cashflow before commission/fees.

    SELL = cash inflow.
    BUY = cash outflow.

    For options, multiplier is applied when available.
    """

    side = (fill.side or "").strip().upper()
    multiplier = fill.multiplier if fill.multiplier is not None else Decimal("1")
    notional = fill.quantity * fill.fill_price * multiplier

    if side in {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}:
        return notional

    if side in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
        return -notional

    raise ValueError(f"Unsupported fill side for cashflow: {fill.side}")
