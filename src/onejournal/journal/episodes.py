"""Simple trade episode preview builder.

Purpose
-------
Convert broker-normalized fills into simple trade episode previews.

This is intentionally small. It is not the final trade lifecycle engine.

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

from onejournal.brokers.normalized import NormalizedFill


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
    """Build simple trade episode previews from normalized fills.

    Grouping rule v1:
    - source_account_id
    - asset_class
    - symbol

    This is deliberately simple. Later, we can improve grouping for rolls,
    multi-leg options, partial exits, assignments, and adjustments.
    """

    grouped: dict[tuple[str, str, str, str], list[NormalizedFill]] = {}

    for fill in fills:
        episode_key = fill.episode_group_id or fill.symbol
        key = (
            fill.source_broker,
            fill.source_account_id,
            fill.asset_class,
            episode_key,
        )
        grouped.setdefault(key, []).append(fill)

    previews: list[TradeEpisodePreview] = []

    for (
        source_broker,
        source_account_id,
        asset_class,
        symbol,
    ), group in sorted(grouped.items()):
        sorted_group = sorted(group, key=lambda f: f.filled_at)
        opened_at = sorted_group[0].filled_at

        net_quantity = sum(
            (_signed_quantity(fill) for fill in sorted_group),
            Decimal("0"),
        )
        gross_cashflow = sum(
            (_cashflow(fill) for fill in sorted_group),
            Decimal("0"),
        )
        total_commission = sum(
            (fill.commission for fill in sorted_group),
            Decimal("0"),
        )
        total_fees = sum(
            (fill.fees for fill in sorted_group),
            Decimal("0"),
        )

        status = _episode_status(sorted_group, net_quantity)

        strategy_type, strategy_label = _classify_strategy(sorted_group)

        previews.append(
            TradeEpisodePreview(
                episode_uid=(
                    f"{source_broker}:{source_account_id}:"
                    f"{asset_class}:{symbol}"
                ),
                source_account_id=source_account_id,
                primary_symbol=symbol,
                asset_class=asset_class,
                opened_at=opened_at,
                status=status,
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

    return previews


def _leg_short_label(fill: NormalizedFill) -> str:
    side = fill.side.upper()
    qty = format(fill.quantity, "f")
    symbol = fill.option_symbol or fill.symbol
    return f"{side} {qty} {symbol}"


def _leg_summary(fills: list[NormalizedFill]) -> str:
    return " / ".join(_leg_short_label(fill) for fill in fills)


def _cashflow_label(value: Decimal) -> str:
    direction = "credit" if value > 0 else "debit" if value < 0 else "even"
    return f"${abs(value):,.2f} {direction}"


def _leg_to_payload(fill: NormalizedFill) -> dict[str, Any]:
    cashflow = _cashflow(fill)
    return {
        "side": fill.side.upper(),
        "symbol": fill.symbol,
        "option_symbol": fill.option_symbol,
        "underlying_symbol": fill.underlying_symbol,
        "option_type": fill.option_type,
        "expiry": fill.expiry.isoformat() if fill.expiry else None,
        "strike": format(fill.strike, "f") if fill.strike is not None else None,
        "quantity": format(fill.quantity, "f"),
        "fill_price": format(fill.fill_price, "f"),
        "cashflow": format(cashflow, "f"),
        "commission": format(fill.commission, "f"),
        "fees": format(fill.fees, "f"),
    }

def _episode_status(fills: list[NormalizedFill], net_quantity: Decimal) -> str:
    """Classify simple preview status.

    Single-leg trades can use net quantity.
    Multi-leg opening spreads may net to zero but are still open.
    """

    open_close_values = {(fill.open_close or "").upper() for fill in fills}
    if "OPEN" in open_close_values:
        return "open"
    if net_quantity == 0:
        return "closed"
    return "open"


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
        sides = {fill.side.upper() for fill in option_fills}
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
    side = first.side.upper()
    option_type = (first.option_type or "").upper()
    open_close = (first.open_close or "").upper()

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

    side = fill.side.upper()

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

    side = fill.side.upper()
    multiplier = fill.multiplier if fill.multiplier is not None else Decimal("1")
    notional = fill.quantity * fill.fill_price * multiplier

    if side in {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}:
        return notional

    if side in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
        return -notional

    raise ValueError(f"Unsupported fill side for cashflow: {fill.side}")
