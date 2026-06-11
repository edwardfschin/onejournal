"""Manual CSV fill parser for OneJournal.

Purpose
-------
Read a manually supplied fills CSV and convert rows into OneJournal
broker-normalized fill records.

This module is read-only:
- no broker API calls
- no data writes
- no order placement
- no order cancellation
- no automation

Expected CSV shape is documented in:
docs/examples/manual_csv/fills_template.csv
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from onejournal.brokers.normalized import NormalizedFill


REQUIRED_FILL_COLUMNS = {
    "asof",
    "source_broker",
    "source_account_id",
    "source_fill_id",
    "filled_at",
    "asset_class",
    "symbol",
    "side",
    "quantity",
    "fill_price",
    "commission",
    "fees",
    "currency",
}


def parse_manual_fills_csv(path: str | Path) -> list[NormalizedFill]:
    """Parse a manual fills CSV file into NormalizedFill records."""

    csv_path = Path(path)

    if not csv_path.exists():
        raise FileNotFoundError(f"Manual fills CSV not found: {csv_path}")

    records: list[NormalizedFill] = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        if reader.fieldnames is None:
            raise ValueError(f"Manual fills CSV has no header row: {csv_path}")

        missing = sorted(REQUIRED_FILL_COLUMNS - set(reader.fieldnames))
        if missing:
            raise ValueError(
                f"Manual fills CSV missing required column(s): {missing}"
            )

        for row_num, row in enumerate(reader, start=2):
            records.append(_row_to_normalized_fill(row, csv_path, row_num))

    return records


def _row_to_normalized_fill(
    row: dict[str, str],
    csv_path: Path,
    row_num: int,
) -> NormalizedFill:
    """Convert one CSV row into a NormalizedFill."""

    asof_value = _parse_date(row["asof"], "asof", row_num)
    filled_at = _parse_datetime(row["filled_at"], "filled_at", row_num)

    source_broker = _clean(row["source_broker"]) or "manual_csv"
    source_account_id = _require(row, "source_account_id", row_num)
    source_fill_id = _require(row, "source_fill_id", row_num)

    source_order_id = _clean(row.get("source_order_id"))
    symbol = _require(row, "symbol", row_num)

    return NormalizedFill(
        fill_uid=f"{source_broker}:{source_account_id}:{source_fill_id}",
        source_broker=source_broker,
        source_account_id=source_account_id,
        source_fill_id=source_fill_id,
        source_order_id=source_order_id,
        episode_group_id=_clean(row.get("episode_group_id")),
        asof=asof_value,
        filled_at=filled_at,
        asset_class=_require(row, "asset_class", row_num),
        symbol=symbol,
        side=_require(row, "side", row_num).upper(),
        quantity=_parse_decimal(row["quantity"], "quantity", row_num),
        fill_price=_parse_decimal(row["fill_price"], "fill_price", row_num),
        commission=_parse_decimal(row["commission"], "commission", row_num),
        fees=_parse_decimal(row["fees"], "fees", row_num),
        currency=_require(row, "currency", row_num).upper(),
        fetched_at=datetime.now().astimezone(),
        raw_path=str(csv_path),
        option_symbol=_clean(row.get("option_symbol")),
        underlying_symbol=_clean(row.get("underlying_symbol")),
        option_type=_clean(row.get("option_type")),
        expiry=_parse_optional_date(row.get("expiry"), "expiry", row_num),
        strike=_parse_optional_decimal(row.get("strike"), "strike", row_num),
        multiplier=_parse_optional_decimal(row.get("multiplier"), "multiplier", row_num),
        open_close=_clean(row.get("open_close")),
        execution_venue=_clean(row.get("execution_venue")),
        liquidity_flag=_clean(row.get("liquidity_flag")),
    )


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _require(row: dict[str, str], field: str, row_num: int) -> str:
    value = _clean(row.get(field))
    if value is None:
        raise ValueError(f"Row {row_num}: missing required value for {field}")
    return value


def _parse_date(value: str, field: str, row_num: int) -> date:
    try:
        return date.fromisoformat(_require({field: value}, field, row_num))
    except ValueError as exc:
        raise ValueError(
            f"Row {row_num}: invalid date for {field}: {value}"
        ) from exc


def _parse_optional_date(value: str | None, field: str, row_num: int) -> date | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return date.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"Row {row_num}: invalid date for {field}: {value}"
        ) from exc


def _parse_datetime(value: str, field: str, row_num: int) -> datetime:
    cleaned = _require({field: value}, field, row_num)
    try:
        return datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(
            f"Row {row_num}: invalid datetime for {field}: {value}"
        ) from exc


def _parse_decimal(value: str, field: str, row_num: int) -> Decimal:
    cleaned = _require({field: value}, field, row_num)
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(
            f"Row {row_num}: invalid decimal for {field}: {value}"
        ) from exc


def _parse_optional_decimal(
    value: str | None,
    field: str,
    row_num: int,
) -> Decimal | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(
            f"Row {row_num}: invalid decimal for {field}: {value}"
        ) from exc
