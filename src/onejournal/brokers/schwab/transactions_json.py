from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import ROUND_DOWN, Decimal, InvalidOperation
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

LIFECYCLE_EVENT_COLUMNS = [
    "event_uid",
    "source_broker",
    "source_account_id",
    "source_activity_id",
    "source_order_id",
    "source_position_id",
    "event_class",
    "event_type",
    "asof",
    "event_at",
    "event_name",
]

LIFECYCLE_EVENT_LEG_COLUMNS = [
    "event_leg_uid",
    "event_uid",
    "leg_index",
    "leg_kind",
    "asset_class",
    "symbol",
    "option_symbol",
    "underlying_symbol",
    "option_type",
    "expiry",
    "strike",
    "multiplier",
    "signed_quantity",
    "price",
    "cash_amount",
    "position_effect",
    "fee_type",
    "currency",
    "deliverable_json",
    "evidence_status",
    "evidence_notes",
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
_CURRENCY_SYMBOL_RE = re.compile(r"^(?:CURRENCY_)?(?P<code>[A-Z]{3})$")

_LIFECYCLE_DESCRIPTION_HINTS = {
    "ASSIGNMENT": re.compile(r"\bassignment\b", re.IGNORECASE),
    "EXERCISE": re.compile(r"\bexercise\b", re.IGNORECASE),
    "EXPIRATION": re.compile(r"\bexpiration\b", re.IGNORECASE),
}


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
    currency_consensus_code: str = ""
    currency_consensus_evidence_items: int = 0
    currency_consensus_resolved_records: int = 0


@dataclass(frozen=True)
class SchwabTransactionCurrencyConsensus:
    """Unique explicit provider currency evidence for one verified scope."""

    currency_code: str
    evidence_item_count: int

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Z]{3}", self.currency_code):
            raise ValueError("Schwab currency consensus code is invalid")
        if type(self.evidence_item_count) is not int or self.evidence_item_count < 1:
            raise ValueError("Schwab currency consensus evidence count is invalid")


def validate_asof(value: str | None) -> str | None:
    if not value:
        return None
    datetime.strptime(value, "%Y-%m-%d")
    return value


def load_transactions_json_bytes(body: bytes) -> list[dict[str, Any]]:
    """Parse exact Schwab transaction response bytes without filesystem access."""

    if not isinstance(body, bytes) or not body:
        raise ValueError("Schwab transactions JSON bytes are invalid")
    payload = json.loads(
        body.decode("utf-8"),
        parse_float=Decimal,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"Invalid non-finite JSON number: {value}")
        ),
    )
    if not isinstance(payload, list):
        raise ValueError("Schwab transactions JSON must be a top-level list")
    out = []
    for idx, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"Schwab transactions JSON item {idx} is not an object")
        out.append(item)
    return out


def load_transactions_json(path: Path) -> list[dict[str, Any]]:
    return load_transactions_json_bytes(path.read_bytes())


def _date_part(value: str) -> str:
    return value[:10] if value else ""


def _parse_occ_like_symbol(symbol: str) -> dict[str, str]:
    compact = (symbol or "").replace(" ", "").upper()
    m = _OPTION_SYMBOL_RE.match(compact)
    if not m:
        return {}
    yymmdd = m.group("yymmdd")
    strike = Decimal(m.group("strike")) / Decimal("1000")
    strike_text = format(strike, "f")
    if "." in strike_text:
        strike_text = strike_text.rstrip("0").rstrip(".")
    return {
        "root": m.group("root").strip().upper(),
        "expiry": f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}",
        "option_type": "CALL" if m.group("cp") == "C" else "PUT",
        "strike": strike_text,
    }


def _asset_class(asset_type: str) -> str:
    value = (asset_type or "").strip().upper()
    if value == "OPTION":
        return "option"
    if value in {"EQUITY", "STOCK"}:
        return "stock"
    return value.lower()


def _side_from_amount(amount: Decimal) -> str:
    # Schwab transaction transferItems sample: positive amount = buy/debit leg, negative amount = sell/credit leg.
    return "buy" if amount > 0 else "sell"


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


def _description_lifecycle_hint(txn: dict[str, Any]) -> str | None:
    """Return an explicitly unconfirmed lifecycle hint from broker text.

    Schwab transaction history observed by OneJournal can omit structured
    activityType/subType fields for assignment and expiration records. ADR-0005
    prohibits treating description text as canonical lifecycle evidence, but it
    permits a review suggestion when it is labelled unconfirmed.
    """

    description = str(txn.get("description", "")).strip()
    if not description:
        return None
    for event_name, pattern in _LIFECYCLE_DESCRIPTION_HINTS.items():
        if pattern.search(description):
            return f"description_hint:{event_name}"
    return None


def _lifecycle_event_reason(txn: dict[str, Any]) -> tuple[str, bool] | None:
    """Return lifecycle reason and whether structured broker fields confirm it."""

    record_type = str(txn.get("type", "")).strip().upper()
    structured_reason = _unsupported_activity_key(txn)
    if structured_reason is not None:
        if record_type != "TRADE":
            return None
        return structured_reason, True

    description_hint = _description_lifecycle_hint(txn)
    if description_hint is None:
        return None

    if description_hint == "description_hint:EXPIRATION":
        if record_type != "RECEIVE_AND_DELIVER":
            return None
    elif record_type != "TRADE":
        return None
    return description_hint, False


def _lifecycle_event_identity(
    txn: dict[str, Any],
    *,
    txn_index: int,
) -> tuple[str, str, str]:
    event_at = str(txn.get("tradeDate") or txn.get("time") or "").strip()
    row_asof = _date_part(event_at)
    activity_id = str(txn.get("activityId", "")).strip()
    record_type = str(txn.get("type", "")).strip()
    event_uid = (
        f"schwab_txn:{activity_id}:event:{record_type}"
        if activity_id
        else f"schwab_txn:{row_asof or 'na'}:event:{record_type}:row:{txn_index}"
    )
    return event_uid, event_at, row_asof


def _decimal_evidence(value: Any, *, field_name: str) -> tuple[str, str | None]:
    if value in (None, ""):
        return "", None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        return "", f"invalid_{field_name}:{value}"
    if not parsed.is_finite():
        return "", f"invalid_{field_name}:{value}"
    return format(parsed, "f"), None


def _json_evidence(value: Any) -> str:
    """Serialize retained evidence without losing exact Decimal tokens."""

    if value is None or isinstance(value, (bool, int, str)):
        return json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("deliverable evidence contains a non-finite decimal")
        return format(value, "f")
    if isinstance(value, float):
        return json.dumps(value, allow_nan=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_json_evidence(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(
            json.dumps(str(key), ensure_ascii=True)
            + ":"
            + _json_evidence(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        ) + "}"
    raise ValueError(
        f"deliverable evidence contains unsupported value type: {type(value).__name__}"
    )


def _lifecycle_leg_from_item(
    *,
    event_uid: str,
    item: Any,
    item_index: int,
    invalid_reason: str | None = None,
    unconfirmed_reason: str | None = None,
) -> dict[str, str]:
    row = {column: "" for column in LIFECYCLE_EVENT_LEG_COLUMNS}
    row.update(
        {
            "event_leg_uid": f"{event_uid}:item:{item_index}",
            "event_uid": event_uid,
            "leg_index": str(item_index),
            "evidence_status": "review_required",
        }
    )
    if invalid_reason:
        row["leg_kind"] = "unsupported"
        row["evidence_notes"] = invalid_reason
        return row
    if not isinstance(item, dict):
        row["leg_kind"] = "unsupported"
        row["evidence_notes"] = "transfer_item_not_object"
        return row

    instrument = item.get("instrument")
    if not isinstance(instrument, dict) or not instrument:
        row["leg_kind"] = "unsupported"
        row["evidence_notes"] = "missing_instrument"
        return row

    asset_type = str(instrument.get("assetType", "")).strip().upper()
    raw_symbol = str(instrument.get("symbol", "")).strip()
    parsed_symbol = _parse_occ_like_symbol(raw_symbol)
    notes: list[str] = []

    if asset_type == "CURRENCY":
        row["leg_kind"] = "cash"
        row["asset_class"] = "currency"
        row["currency"] = raw_symbol.upper()
        if not row["currency"]:
            notes.append("missing_currency")
    elif asset_type in {"OPTION", "EQUITY", "STOCK"}:
        row["leg_kind"] = "security"
        row["asset_class"] = _asset_class(asset_type)
        if asset_type == "OPTION":
            row["option_symbol"] = raw_symbol
            row["underlying_symbol"] = str(
                instrument.get("underlyingSymbol") or parsed_symbol.get("root", "")
            ).strip().upper()
            row["symbol"] = row["underlying_symbol"]
            row["option_type"] = str(
                instrument.get("putCall") or parsed_symbol.get("option_type", "")
            ).strip().upper()
            row["expiry"] = (
                _date_part(str(instrument.get("expirationDate") or ""))
                or parsed_symbol.get("expiry", "")
            )
            strike_value = instrument.get("strikePrice")
            if strike_value in (None, ""):
                strike_value = parsed_symbol.get("strike", "")
            row["strike"], strike_error = _decimal_evidence(
                strike_value, field_name="strike"
            )
            if strike_error:
                notes.append(strike_error)
            multiplier_value = instrument.get("optionPremiumMultiplier")
            row["multiplier"], multiplier_error = _decimal_evidence(
                multiplier_value, field_name="multiplier"
            )
            if multiplier_error:
                notes.append(multiplier_error)
            if not row["multiplier"]:
                notes.append("missing_option_multiplier")
            deliverables = instrument.get("optionDeliverables")
            if deliverables not in (None, ""):
                row["deliverable_json"] = _json_evidence(deliverables)
        else:
            row["symbol"] = raw_symbol.upper()
        if not row["symbol"]:
            notes.append("missing_symbol")
    else:
        row["leg_kind"] = "unsupported"
        row["asset_class"] = asset_type.lower()
        row["symbol"] = raw_symbol
        notes.append(f"unsupported_asset_type:{asset_type or 'EMPTY'}")

    row["signed_quantity"], quantity_error = _decimal_evidence(
        item.get("amount"), field_name="quantity"
    )
    row["price"], price_error = _decimal_evidence(item.get("price"), field_name="price")
    row["cash_amount"], cash_error = _decimal_evidence(
        item.get("cost"), field_name="cash_amount"
    )
    for error in (quantity_error, price_error, cash_error):
        if error:
            notes.append(error)

    row["position_effect"] = str(item.get("positionEffect", "")).strip().upper()
    row["fee_type"] = str(item.get("feeType", "")).strip().upper()

    if row["leg_kind"] == "security" and not row["signed_quantity"]:
        notes.append("missing_signed_quantity")
    if row["leg_kind"] == "cash" and not (row["cash_amount"] or row["signed_quantity"]):
        notes.append("missing_cash_evidence")

    if unconfirmed_reason:
        notes.append(unconfirmed_reason)
    row["evidence_notes"] = ";".join(dict.fromkeys(notes))
    row["evidence_status"] = "observed" if not notes else "review_required"
    return row


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
        if str(txn.get("status", "")).upper().strip() != "VALID":
            continue
        reason_result = _lifecycle_event_reason(txn)
        if reason_result is None:
            continue
        reason, _structured = reason_result

        event_uid, filled_at, row_asof = _lifecycle_event_identity(
            txn, txn_index=txn_index
        )
        if asof and row_asof != asof:
            continue

        activity_id = str(txn.get("activityId", "")).strip()

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


def extract_lifecycle_event_legs_from_transactions(
    transactions: list[dict[str, Any]],
    *,
    asof: str | None = None,
) -> list[dict[str, str]]:
    """Capture transfer-item evidence for recognized lifecycle events.

    Values are preserved as supplied by Schwab. This function does not infer
    lifecycle economics, fill prices, multipliers, or P&L.
    """

    legs: list[dict[str, str]] = []
    for txn_index, txn in enumerate(transactions):
        if str(txn.get("status", "")).upper().strip() != "VALID":
            continue
        reason_result = _lifecycle_event_reason(txn)
        if reason_result is None:
            continue
        _reason, structured = reason_result

        event_uid, _event_at, row_asof = _lifecycle_event_identity(
            txn, txn_index=txn_index
        )
        if asof and row_asof != asof:
            continue

        raw_items = txn.get("transferItems")
        if not isinstance(raw_items, list):
            item_evidence = [(raw_items, "transfer_items_not_list")]
        elif not raw_items:
            item_evidence = [(None, "transfer_items_empty")]
        else:
            item_evidence = [(item, None) for item in raw_items]
        for item_index, (item, invalid_reason) in enumerate(item_evidence):
            legs.append(
                _lifecycle_leg_from_item(
                    event_uid=event_uid,
                    item=item,
                    item_index=item_index,
                    invalid_reason=invalid_reason,
                    unconfirmed_reason=(
                        None if structured else "unconfirmed_description_hint"
                    ),
                )
            )
    return legs


def _multiplier(instrument: dict[str, Any]) -> str:
    raw = instrument.get("optionPremiumMultiplier")
    if raw not in (None, ""):
        value = _decimal_value(raw, field_name="option multiplier", allow_zero=False)
        if value < 0:
            raise ValueError("Schwab option multiplier must be positive")
        return _decimal_text(value)
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


def _currency_code(instrument: dict[str, Any]) -> str:
    symbol = str(instrument.get("symbol", "")).strip().upper()
    match = _CURRENCY_SYMBOL_RE.fullmatch(symbol)
    if match is None:
        raise ValueError(f"Invalid Schwab currency evidence: {symbol!r}")
    return match.group("code")


def schwab_transaction_currency_consensus(
    transactions: list[dict[str, Any]],
) -> SchwabTransactionCurrencyConsensus | None:
    """Return one conflict-free currency from eligible valid-trade legs.

    The caller owns account and window validation.  No consensus is returned
    when the response has no explicit currency or contains more than one code.
    """

    currency_codes: set[str] = set()
    evidence_item_count = 0
    for transaction in transactions:
        if (
            str(transaction.get("type", "")).strip().upper() != "TRADE"
            or str(transaction.get("status", "")).strip().upper() != "VALID"
            or _lifecycle_event_reason(transaction) is not None
        ):
            continue
        items = transaction.get("transferItems")
        if not isinstance(items, list):
            continue
        has_supported_security = any(
            isinstance(item, dict)
            and isinstance(item.get("instrument"), dict)
            and str(item["instrument"].get("assetType", "")).strip().upper()
            in {"OPTION", "EQUITY", "STOCK"}
            for item in items
        )
        if not has_supported_security:
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            instrument = item.get("instrument")
            if not isinstance(instrument, dict):
                continue
            if str(instrument.get("assetType", "")).strip().upper() != "CURRENCY":
                continue
            currency_codes.add(_currency_code(instrument))
            evidence_item_count += 1
    if len(currency_codes) != 1:
        return None
    return SchwabTransactionCurrencyConsensus(
        currency_code=next(iter(currency_codes)),
        evidence_item_count=evidence_item_count,
    )


def _fee_value(item: dict[str, Any], *, fee_type: str) -> Decimal:
    candidates: list[Decimal] = []
    for field_name in ("cost", "amount"):
        raw_value = item.get(field_name)
        if raw_value in (None, ""):
            continue
        value = abs(
            _decimal_value(raw_value, field_name=f"{fee_type} {field_name}")
        )
        if value != 0:
            candidates.append(value)
    if not candidates:
        return Decimal("0")
    if len(set(candidates)) != 1:
        raise ValueError(
            f"Ambiguous Schwab {fee_type} evidence: cost and amount disagree"
        )
    return candidates[0]


def _fee_totals(
    items: list[dict[str, Any]],
    *,
    currency_consensus: SchwabTransactionCurrencyConsensus | None = None,
) -> tuple[Decimal, Decimal, int, str, bool]:
    commission = Decimal("0")
    fees = Decimal("0")
    currency_count = 0
    currencies: set[str] = set()
    for item in items:
        instrument = item.get("instrument") or {}
        if not isinstance(instrument, dict):
            continue
        if str(instrument.get("assetType", "")).upper() != "CURRENCY":
            continue
        currency_count += 1
        currencies.add(_currency_code(instrument))
        fee_type = str(item.get("feeType", "")).strip().upper()
        if not fee_type:
            continue
        value = _fee_value(item, fee_type=fee_type)
        if fee_type == "COMMISSION":
            commission += value
        else:
            fees += value
    used_consensus = False
    if not currencies:
        if currency_consensus is None:
            raise ValueError("Missing Schwab transaction currency evidence")
        currencies.add(currency_consensus.currency_code)
        used_consensus = True
    if len(currencies) != 1:
        raise ValueError(
            f"Mixed Schwab transaction currencies are not supported: {sorted(currencies)}"
        )
    currency = next(iter(currencies))
    if (
        currency_consensus is not None
        and not used_consensus
        and currency != currency_consensus.currency_code
    ):
        raise ValueError("Schwab transaction currency conflicts with scope consensus")
    return commission, fees, currency_count, currency, used_consensus


def _allocate_total(total: Decimal, count: int) -> list[Decimal]:
    if count <= 0:
        raise ValueError("Financial allocation requires at least one security leg")
    if total < 0:
        raise ValueError("Financial allocation total must not be negative")
    quantum = Decimal(1).scaleb(min(total.as_tuple().exponent, -2))
    base = (total / count).quantize(quantum, rounding=ROUND_DOWN)
    residual = total - (base * count)
    residual_units = int((residual / quantum).to_integral_exact())
    allocations = [
        base + (quantum if index < residual_units else Decimal("0"))
        for index in range(count)
    ]
    if sum(allocations, Decimal("0")) != total:
        raise ValueError("Financial allocation residual did not reconcile")
    return allocations


def normalized_rows_from_transactions(
    transactions: list[dict[str, Any]],
    *,
    asof: str | None = None,
    currency_consensus: SchwabTransactionCurrencyConsensus | None = None,
) -> tuple[list[dict[str, str]], SchwabTransactionsJsonStats]:
    rows: list[dict[str, str]] = []
    trade_valid = 0
    security_items = 0
    currency_items = 0
    currency_consensus_resolved_records = 0
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
        reason_result = _lifecycle_event_reason(txn)
        if reason_result is not None:
            reason, _structured = reason_result
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

        (
            commission_total,
            fees_total,
            currency_count,
            currency,
            used_currency_consensus,
        ) = _fee_totals(
            [item for item in items if isinstance(item, dict)],
            currency_consensus=currency_consensus,
        )
        currency_items += currency_count
        if used_currency_consensus:
            currency_consensus_resolved_records += 1
        commission_allocations = _allocate_total(commission_total, len(security))
        fee_allocations = _allocate_total(fees_total, len(security))

        for allocation_index, (idx, item, instrument) in enumerate(security):
            security_items += 1
            asset_class = _asset_class(str(instrument.get("assetType", "")))
            raw_symbol = str(instrument.get("symbol", "")).strip()
            parsed = _parse_occ_like_symbol(raw_symbol)
            amount = _decimal_value(
                item.get("amount"), field_name="security quantity", allow_zero=False
            )
            qty = abs(amount)
            price_raw = item.get("price")
            cost_raw = item.get("cost")
            cost = (
                _decimal_value(cost_raw, field_name="security cash amount")
                if cost_raw not in (None, "")
                else None
            )
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
                multiplier = _multiplier(instrument)
                symbol = underlying
            else:
                symbol = raw_symbol.upper()

            if price_raw in (None, ""):
                if cost is None:
                    raise ValueError(
                        "Missing Schwab fill price and cash amount; price cannot be derived"
                    )
                mult = _decimal_value(
                    multiplier or "1", field_name="price derivation multiplier", allow_zero=False
                )
                price = abs(cost) / (qty * mult)
            else:
                price = _decimal_value(price_raw, field_name="fill price")
            if price < 0:
                raise ValueError("Schwab fill price must not be negative")

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
                "quantity": _decimal_text(qty),
                "fill_price": _decimal_text(price),
                "commission": _decimal_text(
                    commission_allocations[allocation_index]
                ),
                "fees": _decimal_text(fee_allocations[allocation_index]),
                "currency": currency,
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
        currency_consensus_code=(
            currency_consensus.currency_code if currency_consensus is not None else ""
        ),
        currency_consensus_evidence_items=(
            currency_consensus.evidence_item_count
            if currency_consensus is not None
            else 0
        ),
        currency_consensus_resolved_records=currency_consensus_resolved_records,
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
