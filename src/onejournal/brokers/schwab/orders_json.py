from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


NORMALIZED_FILL_COLUMNS = [
    "asof",
    "source_broker",
    "source_account_id",
    "source_fill_id",
    "source_order_id",
    "filled_at",
    "asset_class",
    "symbol",
    "side",
    "quantity",
    "fill_price",
    "commission",
    "fees",
    "currency",
    "option_symbol",
    "underlying_symbol",
    "option_type",
    "expiry",
    "strike",
    "multiplier",
    "open_close",
    "execution_venue",
    "liquidity_flag",
    "episode_group_id",
]


@dataclass(frozen=True)
class SchwabOrdersJsonStats:
    top_level_orders: int = 0
    flattened_orders: int = 0
    fill_activities: int = 0
    fill_rows: int = 0
    skipped_non_fill_activities: int = 0
    skipped_unmatched_legs: int = 0


_OPTION_SYMBOL_RE = re.compile(
    r"^(?P<root>.+?)(?P<yymmdd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$"
)


def load_orders_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(
        path.read_text(encoding="utf-8"),
        parse_float=Decimal,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Invalid non-finite JSON number: {value}")
        ),
    )
    if not isinstance(payload, list):
        raise ValueError("Schwab orders JSON must be a top-level list")
    orders: list[dict[str, Any]] = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Schwab orders JSON item {idx} is not an object")
        orders.append(item)
    return orders


def flatten_orders(orders: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    flat: list[dict[str, Any]] = []
    for order in orders:
        children = order.get("childOrderStrategies")
        if isinstance(children, list) and children:
            for child in flatten_orders([c for c in children if isinstance(c, dict)]):
                inherited = dict(child)
                inherited.setdefault("parentOrderId", order.get("orderId"))
                inherited.setdefault("parentOrderStrategyType", order.get("orderStrategyType"))
                flat.append(inherited)
        else:
            flat.append(order)
    return flat


def _date_part(value: str) -> str:
    if not value:
        return ""
    return value[:10]


def _parse_expiry_from_option_symbol(symbol: str) -> str:
    parsed = _parse_occ_like_symbol(symbol)
    return parsed.get("expiry", "")


def _parse_strike_from_option_symbol(symbol: str) -> str:
    parsed = _parse_occ_like_symbol(symbol)
    return parsed.get("strike", "")


def _parse_occ_like_symbol(symbol: str) -> dict[str, str]:
    compact = (symbol or "").replace(" ", "").upper()
    m = _OPTION_SYMBOL_RE.match(compact)
    if not m:
        return {}
    yymmdd = m.group("yymmdd")
    year = int("20" + yymmdd[:2])
    month = int(yymmdd[2:4])
    day = int(yymmdd[4:6])
    strike_raw = Decimal(m.group("strike"))
    strike = strike_raw / Decimal("1000")
    strike_text = format(strike, "f")
    if "." in strike_text:
        strike_text = strike_text.rstrip("0").rstrip(".")
    return {
        "root": m.group("root").strip().upper(),
        "expiry": f"{year:04d}-{month:02d}-{day:02d}",
        "option_type": "CALL" if m.group("cp") == "C" else "PUT",
        "strike": strike_text,
    }


def _instruction_to_side(instruction: str) -> str:
    value = (instruction or "").strip().upper()
    if value.startswith("BUY"):
        return "buy"
    if value.startswith("SELL"):
        return "sell"
    raise ValueError(f"Unsupported Schwab instruction: {instruction!r}")


def _position_effect_to_open_close(position_effect: str, instruction: str) -> str:
    value = (position_effect or "").strip().upper()
    if value == "OPENING":
        return "open"
    if value == "CLOSING":
        return "close"
    instr = (instruction or "").strip().upper()
    if instr.endswith("_OPEN"):
        return "open"
    if instr.endswith("_CLOSE"):
        return "close"
    return ""


def _asset_class(asset_type: str) -> str:
    value = (asset_type or "").strip().upper()
    if value == "OPTION":
        return "option"
    if value in {"EQUITY", "STOCK"}:
        return "stock"
    return value.lower()


def _decimal_value(
    value: Any,
    *,
    field_name: str,
    allow_zero: bool = True,
) -> Decimal:
    if value in (None, ""):
        raise ValueError(f"Missing Schwab financial field: {field_name}")
    if isinstance(value, (bool, float)):
        raise ValueError(
            f"Schwab financial field {field_name} must be an exact decimal value, not {type(value).__name__}"
        )
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid Schwab financial field {field_name}: {value!r}") from exc
    if not parsed.is_finite():
        raise ValueError(f"Invalid non-finite Schwab financial field {field_name}: {value!r}")
    if not allow_zero and parsed == 0:
        raise ValueError(f"Schwab financial field {field_name} must not be zero")
    return parsed


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def _multiplier_from_instrument(instrument: dict[str, Any]) -> str:
    deliverables = instrument.get("optionDeliverables")
    if isinstance(deliverables, list) and deliverables:
        first = deliverables[0]
        if isinstance(first, dict):
            units = first.get("deliverableUnits")
            if units not in (None, ""):
                value = _decimal_value(
                    units, field_name="option deliverable units", allow_zero=False
                )
                if value < 0:
                    raise ValueError("Schwab option deliverable units must be positive")
                return _decimal_text(value)
    raise ValueError("Missing broker-confirmed Schwab option multiplier")


def _leg_map(order: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    legs = order.get("orderLegCollection") or []
    if not isinstance(legs, list):
        return result
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        leg_id = leg.get("legId")
        if leg_id is None:
            continue
        try:
            result[int(leg_id)] = leg
        except Exception:
            continue
    return result


def _iter_fill_activities(order: dict[str, Any]) -> Iterable[dict[str, Any]]:
    activities = order.get("orderActivityCollection") or []
    if not isinstance(activities, list):
        return
    for activity in activities:
        if not isinstance(activity, dict):
            continue
        if str(activity.get("executionType", "")).upper() == "FILL":
            yield activity


def normalized_rows_from_orders(
    orders: list[dict[str, Any]],
    *,
    asof: str | None = None,
) -> tuple[list[dict[str, str]], SchwabOrdersJsonStats]:
    flat = flatten_orders(orders)
    rows: list[dict[str, str]] = []
    fill_activities = 0
    skipped_non_fill = 0
    skipped_unmatched = 0

    for order in flat:
        leg_by_id = _leg_map(order)
        activities = order.get("orderActivityCollection") or []
        if isinstance(activities, list):
            skipped_non_fill += sum(
                1
                for a in activities
                if isinstance(a, dict) and str(a.get("executionType", "")).upper() != "FILL"
            )

        for activity in _iter_fill_activities(order):
            fill_activities += 1
            activity_id = str(activity.get("activityId", "")).strip()
            execution_legs = activity.get("executionLegs") or []
            if not isinstance(execution_legs, list):
                continue
            for execution_leg in execution_legs:
                if not isinstance(execution_leg, dict):
                    continue
                try:
                    leg_id = int(execution_leg.get("legId"))
                except Exception:
                    skipped_unmatched += 1
                    continue
                order_leg = leg_by_id.get(leg_id)
                if not order_leg:
                    skipped_unmatched += 1
                    continue

                filled_at = str(execution_leg.get("time") or activity.get("time") or order.get("closeTime") or "").strip()
                row_asof = _date_part(filled_at)
                if asof and row_asof != asof:
                    continue

                instrument = order_leg.get("instrument") or {}
                if not isinstance(instrument, dict):
                    instrument = {}

                raw_asset = str(instrument.get("assetType", "")).strip()
                asset_class = _asset_class(raw_asset)
                instruction = str(order_leg.get("instruction", "")).strip()
                side = _instruction_to_side(instruction)
                open_close = _position_effect_to_open_close(str(order_leg.get("positionEffect", "")).strip(), instruction)

                option_symbol = ""
                underlying_symbol = ""
                option_type = ""
                expiry = ""
                strike = ""
                multiplier = ""

                raw_symbol = str(instrument.get("symbol", "")).strip()
                parsed = _parse_occ_like_symbol(raw_symbol)

                if asset_class == "option":
                    option_symbol = raw_symbol
                    underlying_symbol = str(instrument.get("underlyingSymbol") or parsed.get("root", "")).strip().upper()
                    option_type = str(instrument.get("putCall") or parsed.get("option_type", "")).strip().upper()
                    expiry_raw = str(instrument.get("expirationDate") or "").strip()
                    expiry = _date_part(expiry_raw) or parsed.get("expiry", "")
                    strike_raw = instrument.get("strikePrice")
                    if strike_raw not in (None, ""):
                        strike_value = _decimal_value(
                            strike_raw, field_name="option strike"
                        )
                        if strike_value < 0:
                            raise ValueError("Schwab option strike must not be negative")
                        strike = _decimal_text(strike_value)
                    else:
                        strike = parsed.get("strike", "")
                    if not strike:
                        raise ValueError("Missing Schwab option strike evidence")
                    multiplier = _multiplier_from_instrument(instrument)
                    symbol = underlying_symbol
                else:
                    symbol = raw_symbol.strip().upper()

                quantity = _decimal_value(
                    execution_leg.get("quantity"),
                    field_name="execution quantity",
                    allow_zero=False,
                )
                if quantity < 0:
                    raise ValueError("Schwab execution quantity must be positive")
                fill_price = _decimal_value(
                    execution_leg.get("price"), field_name="execution price"
                )
                if fill_price < 0:
                    raise ValueError("Schwab execution price must not be negative")

                order_id = str(order.get("orderId", "")).strip()
                source_fill_id = f"schwab_order:{order_id}:activity:{activity_id}:leg:{leg_id}"

                row = {
                    "asof": row_asof,
                    "source_broker": "schwab",
                    "source_account_id": str(order.get("accountNumber", "")).strip(),
                    "source_fill_id": source_fill_id,
                    "source_order_id": order_id,
                    "filled_at": filled_at,
                    "asset_class": asset_class,
                    "symbol": symbol,
                    "side": side,
                    "quantity": _decimal_text(quantity),
                    "fill_price": _decimal_text(fill_price),
                    "commission": "0",
                    "fees": "0",
                    "currency": "USD",
                    "option_symbol": option_symbol,
                    "underlying_symbol": underlying_symbol,
                    "option_type": option_type,
                    "expiry": expiry,
                    "strike": strike,
                    "multiplier": multiplier if asset_class == "option" else "",
                    "open_close": open_close,
                    "execution_venue": str(order.get("destinationLinkName", "")).strip(),
                    "liquidity_flag": "",
                    "episode_group_id": "",
                }
                rows.append(row)

    stats = SchwabOrdersJsonStats(
        top_level_orders=len(orders),
        flattened_orders=len(flat),
        fill_activities=fill_activities,
        fill_rows=len(rows),
        skipped_non_fill_activities=skipped_non_fill,
        skipped_unmatched_legs=skipped_unmatched,
    )
    return rows, stats


def convert_orders_json_to_normalized_csv(input_path: Path, output_path: Path, *, asof: str | None = None) -> SchwabOrdersJsonStats:
    orders = load_orders_json(input_path)
    rows, stats = normalized_rows_from_orders(orders, asof=asof)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=NORMALIZED_FILL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return stats


def validate_asof(value: str | None) -> str | None:
    if not value:
        return None
    datetime.strptime(value, "%Y-%m-%d")
    return value
