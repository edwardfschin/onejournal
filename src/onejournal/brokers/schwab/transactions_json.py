from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


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

_UNSUPPORTED_ACTIVITY_TYPES = {
    "ASSIGNMENT",
    "EXERCISE",
    "EXPIRATION",
    "CORPORATE_ACTION",
    "DIVIDEND",
    "INTEREST",
    "ROLL",
    "ROLLOVER",
    "TRANSFER",
}

_LIFECYCLE_ACTIVITY_ALIASES = {
    "OPTION_EXERCISE": "EXERCISE",
}

_OPTION_SYMBOL_RE = re.compile(r"^(?P<root>.+?)(?P<yymmdd>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


@dataclass(frozen=True)
class SchwabTransactionsJsonStats:
    transactions: int = 0
    trade_valid: int = 0
    security_items: int = 0
    currency_items: int = 0
    fill_rows: int = 0
    unsupported_items: int = 0
    unsupported_activity_counts: dict[str, int] = field(default_factory=dict)
    unsupported_asset_counts: dict[str, int] = field(default_factory=dict)
    unsupported_record_counts: dict[str, int] = field(default_factory=dict)


def validate_asof(value: str | None) -> str | None:
    if not value:
        return None
    datetime.strptime(value, "%Y-%m-%d")
    return value


def load_transactions_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Schwab transactions JSON must be a top-level list")
    out = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Schwab transactions JSON item {idx} is not an object")
        out.append(item)
    return out


def _date_part(value: str) -> str:
    return value[:10] if value else ""


def _parse_occ_like_symbol(symbol: str) -> dict[str, str]:
    compact = (symbol or "").replace(" ", "").upper()
    m = _OPTION_SYMBOL_RE.match(compact)
    if not m:
        return {}
    yymmdd = m.group("yymmdd")
    strike = int(m.group("strike")) / 1000
    return {
        "root": m.group("root").strip().upper(),
        "expiry": f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}",
        "option_type": "CALL" if m.group("cp") == "C" else "PUT",
        "strike": f"{strike:.3f}".rstrip("0").rstrip("."),
    }


def _asset_class(asset_type: str) -> str:
    value = (asset_type or "").strip().upper()
    if value == "OPTION":
        return "option"
    if value in {"EQUITY", "STOCK"}:
        return "stock"
    return value.lower()


def _side_from_amount(amount: float) -> str:
    # Schwab transaction transferItems sample: positive amount = buy/debit leg, negative amount = sell/credit leg.
    return "buy" if amount > 0 else "sell"


def _open_close(position_effect: str) -> str:
    value = (position_effect or "").strip().upper()
    if value == "OPENING":
        return "open"
    if value == "CLOSING":
        return "close"
    return ""


def _unsupported_activity_key(txn: dict[str, Any]) -> str | None:
    activity_type = str(txn.get("activityType", "")).strip().upper()
    sub_type = str(txn.get("subType", "")).strip().upper()
    if activity_type in _UNSUPPORTED_ACTIVITY_TYPES:
        return f"activityType:{activity_type}"
    canonical_activity_type = _LIFECYCLE_ACTIVITY_ALIASES.get(activity_type)
    if canonical_activity_type is not None:
        return f"activityType:{canonical_activity_type}"
    if sub_type in _UNSUPPORTED_ACTIVITY_TYPES:
        return f"subType:{sub_type}"
    canonical_subtype = _LIFECYCLE_ACTIVITY_ALIASES.get(sub_type)
    if canonical_subtype is not None:
        return f"subType:{canonical_subtype}"
    if activity_type:
        return None
    return None


def extract_lifecycle_events_from_transactions(
    transactions: list[dict[str, Any]],
    *,
    asof: str | None = None,
) -> list[dict[str, str]]:
    """Return lifecycle-only activity rows for future event-ledger wiring.

    This keeps non-fill broker events visible without interpreting them as fills.
    """

    events: list[dict[str, str]] = []

    for txn_index, txn in enumerate(transactions):
        if str(txn.get("type", "")).upper().strip() != "TRADE":
            continue
        if str(txn.get("status", "")).upper().strip() != "VALID":
            continue

        activity_type = str(txn.get("activityType", "")).strip()
        sub_type = str(txn.get("subType", "")).strip()
        if not activity_type and not sub_type:
            continue

        reason = _unsupported_activity_key(txn)
        if reason is None:
            continue

        filled_at = str(txn.get("tradeDate") or txn.get("time") or "").strip()
        row_asof = _date_part(filled_at)
        if asof and row_asof != asof:
            continue

        activity_id = str(txn.get("activityId", "")).strip()
        event_uid = (
            f"schwab_txn:{activity_id}:event:{str(txn.get('type', '')).strip()}"
            if activity_id
            else f"schwab_txn:{row_asof or 'na'}:event:{str(txn.get('type', '')).strip()}:row:{txn_index}"
        )

        events.append(
            {
                "event_uid": event_uid,
                "source_broker": "schwab",
                "source_account_id": str(txn.get("accountNumber", "")).strip(),
                "source_activity_id": activity_id,
                "source_order_id": str(txn.get("orderId", "")).strip(),
                "source_position_id": str(txn.get("positionId", "")).strip(),
                "event_class": "TRANSACTION_LIFECYCLE",
                "event_type": reason,
                "asof": row_asof,
                "event_at": filled_at,
                "event_name": reason,
            }
        )

    return events


def _multiplier(instrument: dict[str, Any]) -> str:
    raw = instrument.get("optionPremiumMultiplier")
    if raw not in (None, ""):
        return str(int(float(raw))) if float(raw).is_integer() else str(raw)
    deliverables = instrument.get("optionDeliverables")
    if isinstance(deliverables, list) and deliverables:
        first = deliverables[0]
        if isinstance(first, dict):
            units = first.get("deliverableUnits")
            if units not in (None, ""):
                return str(int(float(units))) if float(units).is_integer() else str(units)
    return "100"


def _fee_totals(items: list[dict[str, Any]]) -> tuple[float, float, int]:
    commission = 0.0
    fees = 0.0
    currency_count = 0
    for item in items:
        instrument = item.get("instrument") or {}
        if not isinstance(instrument, dict):
            continue
        if str(instrument.get("assetType", "")).upper() != "CURRENCY":
            continue
        currency_count += 1
        fee_type = str(item.get("feeType", "")).upper()
        cost = abs(float(item.get("cost") or 0))
        amount = abs(float(item.get("amount") or 0))
        value = max(cost, amount)
        if fee_type == "COMMISSION":
            commission += value
        else:
            fees += value
    return commission, fees, currency_count


def normalized_rows_from_transactions(transactions: list[dict[str, Any]], *, asof: str | None = None) -> tuple[list[dict[str, str]], SchwabTransactionsJsonStats]:
    rows: list[dict[str, str]] = []
    trade_valid = 0
    security_items = 0
    currency_items = 0
    unsupported = 0

    unsupported_activity_counts: dict[str, int] = {}
    unsupported_asset_counts: dict[str, int] = {}
    unsupported_record_counts: dict[str, int] = {}

    for txn in transactions:
        record_type = str(txn.get("type", "")).upper().strip() or "EMPTY"
        record_status = str(txn.get("status", "")).upper().strip() or "EMPTY"
        if record_type != "TRADE":
            unsupported += 1
            key = f"record_type:{record_type}"
            unsupported_record_counts[key] = unsupported_record_counts.get(key, 0) + 1
            continue
        if record_status != "VALID":
            unsupported += 1
            key = f"record_status:{record_status}"
            unsupported_record_counts[key] = unsupported_record_counts.get(key, 0) + 1
            continue
        reason = _unsupported_activity_key(txn)
        if reason is not None:
            unsupported += 1
            unsupported_activity_counts[reason] = unsupported_activity_counts.get(reason, 0) + 1
            continue
        trade_valid += 1
        filled_at = str(txn.get("tradeDate") or txn.get("time") or "").strip()
        row_asof = _date_part(filled_at)
        if asof and row_asof != asof:
            continue

        items = txn.get("transferItems") or []
        if not isinstance(items, list):
            unsupported += 1
            unsupported_record_counts["record_items:non_list"] = unsupported_record_counts.get("record_items:non_list", 0) + 1
            continue
        if not items:
            unsupported += 1
            unsupported_record_counts["record_items:empty"] = unsupported_record_counts.get("record_items:empty", 0) + 1
            continue
        commission_total, fees_total, currency_count = _fee_totals([i for i in items if isinstance(i, dict)])
        currency_items += currency_count
        security = []
        for idx, item in enumerate(items):
            if not isinstance(item, dict):
                unsupported += 1
                unsupported_record_counts["record_items:non_object"] = unsupported_record_counts.get("record_items:non_object", 0) + 1
                continue
            instrument = item.get("instrument")
            if instrument is None:
                unsupported += 1
                unsupported_record_counts["record_items:missing_instrument"] = unsupported_record_counts.get("record_items:missing_instrument", 0) + 1
                continue
            if not isinstance(instrument, dict):
                unsupported += 1
                unsupported_record_counts["record_items:missing_instrument"] = unsupported_record_counts.get("record_items:missing_instrument", 0) + 1
                continue
            if not instrument:
                unsupported += 1
                unsupported_record_counts["record_items:missing_instrument"] = unsupported_record_counts.get("record_items:missing_instrument", 0) + 1
                continue
            asset_type = str(instrument.get("assetType", "")).upper()
            if asset_type == "CURRENCY":
                continue
            if asset_type not in {"OPTION", "EQUITY", "STOCK"}:
                unsupported_asset_counts[asset_type] = unsupported_asset_counts.get(asset_type, 0) + 1
                unsupported += 1
                continue
            security.append((idx, item, instrument))
        if not security:
            unsupported += 1
            unsupported_record_counts["record_security:unsupported_or_missing"] = unsupported_record_counts.get("record_security:unsupported_or_missing", 0) + 1
            continue

        per_leg_commission = commission_total / len(security) if security else 0.0
        per_leg_fees = fees_total / len(security) if security else 0.0

        for idx, item, instrument in security:
            security_items += 1
            asset_class = _asset_class(str(instrument.get("assetType", "")))
            raw_symbol = str(instrument.get("symbol", "")).strip()
            parsed = _parse_occ_like_symbol(raw_symbol)
            amount = float(item.get("amount") or 0)
            qty = abs(amount)
            price = item.get("price")
            multiplier = ""
            option_symbol = ""
            underlying = ""
            option_type = ""
            expiry = ""
            strike = ""

            if asset_class == "option":
                option_symbol = raw_symbol
                underlying = str(instrument.get("underlyingSymbol") or parsed.get("root", "")).strip().upper()
                option_type = str(instrument.get("putCall") or parsed.get("option_type", "")).strip().upper()
                expiry = _date_part(str(instrument.get("expirationDate") or "")) or parsed.get("expiry", "")
                strike_raw = instrument.get("strikePrice")
                strike = str(strike_raw) if strike_raw not in (None, "") else parsed.get("strike", "")
                multiplier = _multiplier(instrument)
                symbol = underlying
            else:
                symbol = raw_symbol.upper()

            if price in (None, ""):
                mult = float(multiplier or 1)
                cost = abs(float(item.get("cost") or 0))
                price = cost / (qty * mult) if qty and mult else ""

            activity_id = str(txn.get("activityId", "")).strip()
            order_id = str(txn.get("orderId", "")).strip()
            position_id = str(txn.get("positionId", "")).strip()
            source_fill_id = f"schwab_txn:{activity_id}:order:{order_id}:position:{position_id}:item:{idx}"

            rows.append({
                "asof": row_asof,
                "source_broker": "schwab",
                "source_account_id": str(txn.get("accountNumber", "")).strip(),
                "source_fill_id": source_fill_id,
                "source_order_id": order_id,
                "filled_at": filled_at,
                "asset_class": asset_class,
                "symbol": symbol,
                "side": _side_from_amount(amount),
                "quantity": str(qty),
                "fill_price": str(price),
                "commission": f"{per_leg_commission:.2f}",
                "fees": f"{per_leg_fees:.2f}",
                "currency": "USD",
                "option_symbol": option_symbol,
                "underlying_symbol": underlying,
                "option_type": option_type,
                "expiry": expiry,
                "strike": strike,
                "multiplier": multiplier if asset_class == "option" else "",
                "open_close": _open_close(str(item.get("positionEffect", ""))),
                "execution_venue": "",
                "liquidity_flag": "",
                "episode_group_id": "",
            })

    return rows, SchwabTransactionsJsonStats(
    transactions=len(transactions),
    trade_valid=trade_valid,
    security_items=security_items,
    currency_items=currency_items,
    fill_rows=len(rows),
    unsupported_items=unsupported,
    unsupported_activity_counts=unsupported_activity_counts,
    unsupported_asset_counts=unsupported_asset_counts,
    unsupported_record_counts=unsupported_record_counts,
    )


def convert_transactions_json_to_normalized_csv(input_path: Path, output_path: Path, *, asof: str | None = None) -> SchwabTransactionsJsonStats:
    transactions = load_transactions_json(input_path)
    return convert_transactions_json_to_normalized_csv_from_rows(transactions, output_path, asof=asof)


def convert_transactions_json_to_normalized_csv_from_rows(
    transactions: list[dict[str, Any]],
    output_path: Path,
    *,
    asof: str | None = None,
) -> SchwabTransactionsJsonStats:
    rows, stats = normalized_rows_from_transactions(transactions, asof=asof)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=NORMALIZED_FILL_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return stats
