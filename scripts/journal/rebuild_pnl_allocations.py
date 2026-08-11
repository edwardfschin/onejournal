#!/usr/bin/env python3
"""Build versioned P&L allocations from fills and approved lifecycle instructions.

Dry-run is the default. ``--apply`` appends a calculation run and any new
approved instruction rows in one DuckDB transaction. The operator never reads
raw broker files, calls broker APIs, or changes normalized evidence.
"""

from __future__ import annotations

import argparse
import json
from csv import DictReader
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4

import duckdb

from onejournal.brokers.normalized import NormalizedFill
from onejournal.pnl import (
    FIFO_CALCULATION_VERSION,
    OPTION_LIFECYCLE_CALCULATION_VERSION,
    ApprovedOptionLifecycleEvent,
    PnLCalculationResult,
    build_fill_input_fingerprint,
    build_instrument_key,
    build_lifecycle_input_fingerprint,
    calculate_fifo_pnl_with_lifecycle_events,
)


DEFAULT_DB = Path("data/journal/onejournal.duckdb")


@dataclass(frozen=True)
class ApprovedInstructionRecord:
    event: ApprovedOptionLifecycleEvent
    reviewed_at: datetime
    review_source: str
    instruction_path: str


@dataclass(frozen=True)
class PnLRunSummary:
    calculation_run_id: str | None
    asof: date
    fill_count: int
    approved_event_count: int
    group_count: int
    closed_allocation_count: int
    lifecycle_allocation_count: int
    applied: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build OneJournal FIFO P&L from normalized fills and explicitly "
            "approved option lifecycle instructions."
        )
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB path.")
    parser.add_argument("--asof", required=True, help="YYYY-MM-DD market date.")
    parser.add_argument(
        "--instructions",
        required=True,
        help="Reviewed option lifecycle instruction CSV path.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Append approved instructions and a versioned calculation run.",
    )
    return parser.parse_args()


def _text(row: dict[str, str | None], field: str) -> str:
    value = row.get(field)
    return "" if value is None else str(value).strip()


def _decimal(
    value: str,
    *,
    field: str,
    row_index: int,
    optional: bool = False,
) -> Decimal | None:
    if not value:
        if optional:
            return None
        raise ValueError(f"instruction row {row_index}: {field} is required")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(
            f"instruction row {row_index}: {field} must be decimal"
        ) from exc
    if not parsed.is_finite():
        raise ValueError(
            f"instruction row {row_index}: {field} must be finite"
        )
    return parsed


def _utc_datetime(value: str, *, field: str, row_index: int | None = None) -> datetime:
    prefix = f"instruction row {row_index}: " if row_index is not None else ""
    if not value:
        raise ValueError(f"{prefix}{field} is required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"{prefix}{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{prefix}{field} must include a timezone offset")
    return parsed.astimezone(UTC)


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("cannot serialize timezone-less datetime as UTC evidence")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _string_array(value: str, *, field: str, row_index: int) -> tuple[str, ...]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"instruction row {row_index}: {field} must be a JSON array"
        ) from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError(
            f"instruction row {row_index}: {field} must be a non-empty JSON array"
        )
    values = tuple(str(item).strip() for item in parsed)
    if any(not item for item in values) or len(set(values)) != len(values):
        raise ValueError(
            f"instruction row {row_index}: {field} values must be non-empty and unique"
        )
    return values


def load_approved_instructions(path: Path) -> list[ApprovedInstructionRecord]:
    if not path.exists():
        raise ValueError(f"approved lifecycle instruction file missing: {path}")

    required = {
        "event_uid",
        "event_type",
        "source_broker",
        "source_account_id",
        "currency",
        "effective_at",
        "option_instrument_key",
        "predecessor_direction",
        "contracts",
        "predecessor_open_fill_uids_json",
        "event_commission",
        "event_fees",
        "evidence_status",
        "source_event_leg_uids_json",
        "successor_action",
        "successor_position_effect",
        "successor_symbol",
        "successor_quantity",
        "strike_cash_amount",
        "reviewed_at",
        "review_source",
    }
    records: list[ApprovedInstructionRecord] = []
    seen_event_uids: set[str] = set()
    with path.open(newline="", encoding="utf-8") as fh:
        reader = DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"approved lifecycle instruction file has no header: {path}")
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(
                f"approved lifecycle instruction file missing required columns {missing}"
            )

        for row_index, row in enumerate(reader, start=2):
            event_uid = _text(row, "event_uid")
            if not event_uid:
                raise ValueError(f"instruction row {row_index}: event_uid is required")
            if event_uid in seen_event_uids:
                raise ValueError(f"duplicate instruction event_uid: {event_uid}")
            seen_event_uids.add(event_uid)

            source_broker = _text(row, "source_broker")
            source_account_id = _text(row, "source_account_id")
            currency = _text(row, "currency").upper()
            instrument_key = _text(row, "option_instrument_key")
            review_source = _text(row, "review_source")
            if not source_broker or not source_account_id or not currency:
                raise ValueError(
                    f"instruction row {row_index}: broker, account, and currency are required"
                )
            if not instrument_key:
                raise ValueError(
                    f"instruction row {row_index}: option_instrument_key is required"
                )
            if not review_source:
                raise ValueError(
                    f"instruction row {row_index}: review_source is required"
                )

            successor_quantity = _decimal(
                _text(row, "successor_quantity"),
                field="successor_quantity",
                row_index=row_index,
                optional=True,
            )
            strike_cash_amount = _decimal(
                _text(row, "strike_cash_amount"),
                field="strike_cash_amount",
                row_index=row_index,
                optional=True,
            )
            event = ApprovedOptionLifecycleEvent(
                event_uid=event_uid,
                event_type=_text(row, "event_type").upper(),
                source_broker=source_broker,
                source_account_id=source_account_id,
                currency=currency,
                effective_at=_utc_datetime(
                    _text(row, "effective_at"),
                    field="effective_at",
                    row_index=row_index,
                ),
                option_scope_key=(
                    source_broker,
                    source_account_id,
                    instrument_key,
                    currency,
                ),
                predecessor_direction=_text(row, "predecessor_direction").upper(),
                contracts=_decimal(
                    _text(row, "contracts"),
                    field="contracts",
                    row_index=row_index,
                ),
                predecessor_open_fill_uids=_string_array(
                    _text(row, "predecessor_open_fill_uids_json"),
                    field="predecessor_open_fill_uids_json",
                    row_index=row_index,
                ),
                event_commission=_decimal(
                    _text(row, "event_commission"),
                    field="event_commission",
                    row_index=row_index,
                ),
                event_fees=_decimal(
                    _text(row, "event_fees"),
                    field="event_fees",
                    row_index=row_index,
                ),
                evidence_status=_text(row, "evidence_status").lower(),
                source_event_leg_uids=_string_array(
                    _text(row, "source_event_leg_uids_json"),
                    field="source_event_leg_uids_json",
                    row_index=row_index,
                ),
                successor_action=_text(row, "successor_action").upper() or None,
                successor_position_effect=(
                    _text(row, "successor_position_effect").upper() or None
                ),
                successor_symbol=_text(row, "successor_symbol").upper() or None,
                successor_quantity=successor_quantity,
                strike_cash_amount=strike_cash_amount,
            )
            records.append(
                ApprovedInstructionRecord(
                    event=event,
                    reviewed_at=_utc_datetime(
                        _text(row, "reviewed_at"),
                        field="reviewed_at",
                        row_index=row_index,
                    ),
                    review_source=review_source,
                    instruction_path=str(path),
                )
            )
    return records


def _load_fills(con: duckdb.DuckDBPyConnection, *, asof: date) -> list[NormalizedFill]:
    rows = con.execute(
        """
        SELECT fill_uid, source_broker, source_account_id, source_fill_id,
               source_order_id, episode_group_id, asof_date, filled_at_utc,
               asset_class, symbol, side, quantity, fill_price, commission,
               fees, currency, fetched_at_utc, raw_path, option_symbol,
               underlying_symbol, option_type, expiry, strike, multiplier,
               open_close, execution_venue, liquidity_flag
        FROM normalized_fills
        WHERE asof_date <= ?
        ORDER BY filled_at_utc, fill_uid
        """,
        (asof,),
    ).fetchall()
    fills: list[NormalizedFill] = []
    for row in rows:
        (
            fill_uid,
            source_broker,
            source_account_id,
            source_fill_id,
            source_order_id,
            episode_group_id,
            asof_date,
            filled_at_utc,
            asset_class,
            symbol,
            side,
            quantity,
            fill_price,
            commission,
            fees,
            currency,
            fetched_at_utc,
            raw_path,
            option_symbol,
            underlying_symbol,
            option_type,
            expiry,
            strike,
            multiplier,
            open_close,
            execution_venue,
            liquidity_flag,
        ) = row
        if not filled_at_utc or not fetched_at_utc:
            raise ValueError(
                f"fill {fill_uid} lacks canonical UTC evidence; legacy timestamp backfill is required"
            )
        fills.append(
            NormalizedFill(
                fill_uid=fill_uid,
                source_broker=source_broker,
                source_account_id=source_account_id,
                source_fill_id=source_fill_id,
                source_order_id=source_order_id,
                episode_group_id=episode_group_id,
                asof=asof_date,
                filled_at=_utc_datetime(filled_at_utc, field="filled_at_utc"),
                asset_class=asset_class,
                symbol=symbol,
                side=side,
                quantity=quantity,
                fill_price=fill_price,
                commission=commission,
                fees=fees,
                currency=currency,
                fetched_at=_utc_datetime(fetched_at_utc, field="fetched_at_utc"),
                raw_path=raw_path,
                option_symbol=option_symbol,
                underlying_symbol=underlying_symbol,
                option_type=option_type,
                expiry=expiry,
                strike=strike,
                multiplier=multiplier,
                open_close=open_close,
                execution_venue=execution_venue,
                liquidity_flag=liquidity_flag,
            )
        )
    return fills


def _load_existing_instructions(
    con: duckdb.DuckDBPyConnection,
) -> list[ApprovedInstructionRecord]:
    rows = con.execute(
        """
        SELECT event_uid, event_type, source_broker, source_account_id, currency,
               effective_at_utc, option_instrument_key, predecessor_direction,
               contracts, event_commission, event_fees, evidence_status,
               successor_action, successor_position_effect, successor_symbol,
               successor_quantity, strike_cash_amount, reviewed_at_utc,
               review_source, instruction_path
        FROM approved_option_lifecycle_events
        ORDER BY effective_at_utc, event_uid
        """
    ).fetchall()
    records: list[ApprovedInstructionRecord] = []
    for row in rows:
        event_uid = row[0]
        predecessors = tuple(
            item[0]
            for item in con.execute(
                """
                SELECT open_fill_uid
                FROM approved_option_lifecycle_predecessors
                WHERE event_uid = ?
                ORDER BY predecessor_index
                """,
                (event_uid,),
            ).fetchall()
        )
        source_legs = tuple(
            item[0]
            for item in con.execute(
                """
                SELECT event_leg_uid
                FROM approved_option_lifecycle_source_legs
                WHERE event_uid = ?
                ORDER BY event_leg_uid
                """,
                (event_uid,),
            ).fetchall()
        )
        event = ApprovedOptionLifecycleEvent(
            event_uid=event_uid,
            event_type=row[1],
            source_broker=row[2],
            source_account_id=row[3],
            currency=row[4],
            effective_at=_utc_datetime(row[5], field="effective_at_utc"),
            option_scope_key=(row[2], row[3], row[6], row[4]),
            predecessor_direction=row[7],
            contracts=row[8],
            predecessor_open_fill_uids=predecessors,
            event_commission=row[9],
            event_fees=row[10],
            evidence_status=row[11],
            source_event_leg_uids=source_legs,
            successor_action=row[12],
            successor_position_effect=row[13],
            successor_symbol=row[14],
            successor_quantity=row[15],
            strike_cash_amount=row[16],
        )
        records.append(
            ApprovedInstructionRecord(
                event=event,
                reviewed_at=_utc_datetime(row[17], field="reviewed_at_utc"),
                review_source=row[18],
                instruction_path=row[19],
            )
        )
    return records


def _instruction_signature(record: ApprovedInstructionRecord) -> tuple:
    event = record.event
    return (
        event.event_uid,
        event.event_type,
        event.source_broker,
        event.source_account_id,
        event.currency,
        event.effective_at,
        event.option_scope_key,
        event.predecessor_direction,
        event.contracts,
        event.predecessor_open_fill_uids,
        event.event_commission,
        event.event_fees,
        event.evidence_status,
        tuple(sorted(event.source_event_leg_uids)),
        event.successor_action,
        event.successor_position_effect,
        event.successor_symbol,
        event.successor_quantity,
        event.strike_cash_amount,
        _utc_text(record.reviewed_at),
        record.review_source,
    )


def _merge_instructions(
    existing: list[ApprovedInstructionRecord],
    incoming: list[ApprovedInstructionRecord],
) -> tuple[list[ApprovedInstructionRecord], list[ApprovedInstructionRecord]]:
    merged = {record.event.event_uid: record for record in existing}
    new_records: list[ApprovedInstructionRecord] = []
    for record in incoming:
        prior = merged.get(record.event.event_uid)
        if prior is not None:
            if _instruction_signature(prior) != _instruction_signature(record):
                raise ValueError(
                    f"approved lifecycle instruction conflict for event {record.event.event_uid}; corrections require a linked corrective event"
                )
            continue
        merged[record.event.event_uid] = record
        new_records.append(record)
    ordered = sorted(
        merged.values(), key=lambda record: (record.event.effective_at, record.event.event_uid)
    )
    return ordered, new_records


def _validate_instruction_evidence(
    con: duckdb.DuckDBPyConnection,
    records: list[ApprovedInstructionRecord],
    fills: list[NormalizedFill],
    *,
    asof: date,
) -> None:
    fill_scopes = {
        fill.fill_uid: (
            fill.source_broker,
            fill.source_account_id,
            build_instrument_key(fill),
            fill.currency,
        )
        for fill in fills
    }
    for record in records:
        event = record.event
        header = con.execute(
            """
            SELECT source_broker, source_account_id, event_type, event_at_utc,
                   asof_date
            FROM normalized_lifecycle_events
            WHERE event_uid = ?
            """,
            (event.event_uid,),
        ).fetchone()
        if header is None:
            raise ValueError(
                f"approved lifecycle event has no normalized event header: {event.event_uid}"
            )
        if header[0] != event.source_broker or header[1] != event.source_account_id:
            raise ValueError(
                f"approved lifecycle event broker/account mismatch: {event.event_uid}"
            )
        if not header[3]:
            raise ValueError(
                f"approved lifecycle event lacks canonical UTC evidence: {event.event_uid}"
            )
        if _utc_datetime(header[3], field="event_at_utc") != event.effective_at:
            raise ValueError(
                f"approved lifecycle event effective_at mismatch: {event.event_uid}"
            )
        if header[4] > asof:
            raise ValueError(
                f"approved lifecycle event is later than --asof: {event.event_uid}"
            )
        raw_event_name = str(header[2]).split(":")[-1].upper()
        if raw_event_name != event.event_type:
            raise ValueError(
                f"approved lifecycle event type mismatch: {event.event_uid}"
            )

        expected_scope = event.option_scope_key
        for fill_uid in event.predecessor_open_fill_uids:
            scope = fill_scopes.get(fill_uid)
            if scope is None:
                raise ValueError(
                    f"approved lifecycle predecessor fill is missing: {fill_uid}"
                )
            if scope != expected_scope:
                raise ValueError(
                    f"approved lifecycle predecessor scope mismatch: {fill_uid}"
                )
        for leg_uid in event.source_event_leg_uids:
            leg = con.execute(
                """
                SELECT event_uid
                FROM normalized_lifecycle_event_legs
                WHERE event_leg_uid = ?
                """,
                (leg_uid,),
            ).fetchone()
            if leg is None or leg[0] != event.event_uid:
                raise ValueError(
                    f"approved lifecycle source leg is missing or linked to another event: {leg_uid}"
                )


def _persist_new_instructions(
    con: duckdb.DuckDBPyConnection,
    records: list[ApprovedInstructionRecord],
) -> None:
    for record in records:
        event = record.event
        con.execute(
            """
            INSERT INTO approved_option_lifecycle_events (
                event_uid, event_type, source_broker, source_account_id,
                currency, effective_at_utc, option_instrument_key,
                predecessor_direction, contracts, event_commission, event_fees,
                evidence_status, successor_action, successor_position_effect,
                successor_symbol, successor_quantity, strike_cash_amount,
                reviewed_at_utc, review_source, instruction_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_uid,
                event.event_type,
                event.source_broker,
                event.source_account_id,
                event.currency,
                _utc_text(event.effective_at),
                event.option_scope_key[2],
                event.predecessor_direction,
                event.contracts,
                event.event_commission,
                event.event_fees,
                event.evidence_status,
                event.successor_action,
                event.successor_position_effect,
                event.successor_symbol,
                event.successor_quantity,
                event.strike_cash_amount,
                _utc_text(record.reviewed_at),
                record.review_source,
                record.instruction_path,
            ),
        )
        con.executemany(
            """
            INSERT INTO approved_option_lifecycle_predecessors (
                event_uid, predecessor_index, open_fill_uid
            ) VALUES (?, ?, ?)
            """,
            [
                (event.event_uid, index, fill_uid)
                for index, fill_uid in enumerate(event.predecessor_open_fill_uids)
            ],
        )
        con.executemany(
            """
            INSERT INTO approved_option_lifecycle_source_legs (
                event_uid, event_leg_uid
            ) VALUES (?, ?)
            """,
            [(event.event_uid, leg_uid) for leg_uid in event.source_event_leg_uids],
        )


def _persist_result(
    con: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    asof: date,
    started_at: datetime,
    completed_at: datetime,
    fills: list[NormalizedFill],
    events: list[ApprovedOptionLifecycleEvent],
    result: PnLCalculationResult,
) -> None:
    con.execute(
        """
        INSERT INTO pnl_calculation_runs (
            calculation_run_id, calculation_version,
            lifecycle_calculation_version, asof_date, started_at_utc,
            completed_at_utc, input_fill_fingerprint,
            approved_event_fingerprint, fill_count, approved_event_count, group_count,
            closed_allocation_count, lifecycle_allocation_count, status, notes
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            result.calculation_version,
            OPTION_LIFECYCLE_CALCULATION_VERSION,
            asof,
            _utc_text(started_at),
            _utc_text(completed_at),
            build_fill_input_fingerprint(fills),
            build_lifecycle_input_fingerprint(events),
            len(fills),
            len(events),
            len(result.groups),
            len(result.closed_allocations),
            len(result.lifecycle_allocations),
            "ok",
            "approved option lifecycle FIFO calculation",
        ),
    )
    if result.groups:
        con.executemany(
            """
            INSERT INTO pnl_group_results (
                calculation_run_id, source_broker, source_account_id,
                instrument_key, currency, open_quantity, open_cost_basis,
                realized_pnl, unrealized_pnl
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (run_id, *scope_key, group.open_quantity, group.open_cost_basis,
                 group.realized_pnl, group.unrealized_pnl)
                for scope_key, group in result.groups.items()
            ],
        )
    if result.closed_allocations:
        con.executemany(
            """
            INSERT INTO pnl_closed_lot_allocations (
                calculation_run_id, allocation_index, source_broker,
                source_account_id, instrument_key, currency, open_fill_uid,
                close_fill_uid, source_event_uid, direction, quantity,
                multiplier, open_price, close_price, gross_realized_pnl,
                allocated_open_commission, allocated_open_fees,
                allocated_close_commission, allocated_close_fees, realized_pnl,
                closed_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    index,
                    *allocation.scope_key,
                    allocation.open_fill_uid,
                    allocation.close_fill_uid,
                    allocation.source_event_uid,
                    allocation.direction,
                    allocation.quantity,
                    allocation.multiplier,
                    allocation.open_price,
                    allocation.close_price,
                    allocation.gross_realized_pnl,
                    allocation.allocated_open_commission,
                    allocation.allocated_open_fees,
                    allocation.allocated_close_commission,
                    allocation.allocated_close_fees,
                    allocation.realized_pnl,
                    _utc_text(allocation.closed_at),
                )
                for index, allocation in enumerate(result.closed_allocations)
            ],
        )
    if result.lifecycle_allocations:
        con.executemany(
            """
            INSERT INTO pnl_lifecycle_allocations (
                calculation_run_id, event_uid, allocation_index,
                calculation_version, source_broker, source_account_id,
                option_instrument_key, currency, predecessor_open_fill_uid,
                predecessor_direction, contracts, multiplier, net_option_basis,
                allocated_open_commission, allocated_open_fees,
                allocated_event_commission, allocated_event_fees, realized_pnl,
                successor_fill_uid, successor_action,
                successor_position_effect, successor_symbol,
                successor_quantity, successor_effective_price,
                effective_at_utc, source_event_leg_uids_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    allocation.event_uid,
                    allocation.allocation_index,
                    allocation.calculation_version,
                    *allocation.option_scope_key,
                    allocation.predecessor_open_fill_uid,
                    allocation.predecessor_direction,
                    allocation.contracts,
                    allocation.multiplier,
                    allocation.net_option_basis,
                    allocation.allocated_open_commission,
                    allocation.allocated_open_fees,
                    allocation.allocated_event_commission,
                    allocation.allocated_event_fees,
                    allocation.realized_pnl,
                    allocation.successor_fill_uid,
                    allocation.successor_action,
                    allocation.successor_position_effect,
                    allocation.successor_symbol,
                    allocation.successor_quantity,
                    allocation.successor_effective_price,
                    _utc_text(allocation.effective_at),
                    json.dumps(allocation.source_event_leg_uids),
                )
                for allocation in result.lifecycle_allocations
            ],
        )


def build_pnl_allocations(
    db_path: Path,
    instruction_path: Path,
    *,
    asof: date,
    apply: bool,
) -> PnLRunSummary:
    if not db_path.exists():
        raise ValueError(f"journal database missing: {db_path}")
    incoming = load_approved_instructions(instruction_path)
    con = duckdb.connect(str(db_path), read_only=not apply)
    transaction_open = False
    try:
        tables = {row[0] for row in con.execute("SHOW TABLES").fetchall()}
        required_tables = {
            "normalized_fills",
            "normalized_lifecycle_events",
            "normalized_lifecycle_event_legs",
            "approved_option_lifecycle_events",
            "approved_option_lifecycle_predecessors",
            "approved_option_lifecycle_source_legs",
            "pnl_calculation_runs",
            "pnl_group_results",
            "pnl_closed_lot_allocations",
            "pnl_lifecycle_allocations",
        }
        missing = sorted(required_tables - tables)
        if missing:
            raise ValueError(
                f"journal database is missing required P&L migration tables: {missing}"
            )

        existing = _load_existing_instructions(con)
        merged, new_records = _merge_instructions(existing, incoming)
        fills = _load_fills(con, asof=asof)
        applicable_event_uids = {
            row[0]
            for row in con.execute(
                """
                SELECT event_uid
                FROM normalized_lifecycle_events
                WHERE asof_date <= ?
                """,
                (asof,),
            ).fetchall()
        }
        applicable = [
            record
            for record in merged
            if record.event.event_uid in applicable_event_uids
        ]
        _validate_instruction_evidence(con, applicable, fills, asof=asof)
        started_at = datetime.now(UTC)
        result = calculate_fifo_pnl_with_lifecycle_events(
            fills,
            [record.event for record in applicable],
        )
        completed_at = datetime.now(UTC)

        run_id: str | None = None
        if apply:
            run_id = (
                "pnl:"
                + started_at.strftime("%Y%m%dT%H%M%S%fZ")
                + ":"
                + uuid4().hex[:8]
            )
            con.execute("BEGIN TRANSACTION")
            transaction_open = True
            _persist_new_instructions(con, new_records)
            _persist_result(
                con,
                run_id=run_id,
                asof=asof,
                started_at=started_at,
                completed_at=completed_at,
                fills=fills,
                events=[record.event for record in applicable],
                result=result,
            )
            con.execute("COMMIT")
            transaction_open = False

        return PnLRunSummary(
            calculation_run_id=run_id,
            asof=asof,
            fill_count=len(fills),
            approved_event_count=len(applicable),
            group_count=len(result.groups),
            closed_allocation_count=len(result.closed_allocations),
            lifecycle_allocation_count=len(result.lifecycle_allocations),
            applied=apply,
        )
    except Exception:
        if transaction_open:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    summary = build_pnl_allocations(
        Path(args.db),
        Path(args.instructions),
        asof=date.fromisoformat(args.asof),
        apply=args.apply,
    )
    print("===== OneJournal approved lifecycle P&L =====")
    print(f"MODE                   : {'apply' if summary.applied else 'dry-run'}")
    print("BROKER API             : disabled")
    print("ORDER API              : disabled")
    print(f"ASOF                   : {summary.asof}")
    print(f"FILLS                  : {summary.fill_count}")
    print(f"APPROVED_EVENTS        : {summary.approved_event_count}")
    print(f"GROUPS                 : {summary.group_count}")
    print(f"CLOSED_ALLOCATIONS     : {summary.closed_allocation_count}")
    print(f"LIFECYCLE_ALLOCATIONS  : {summary.lifecycle_allocation_count}")
    print(f"CALCULATION_RUN_ID     : {summary.calculation_run_id or 'not written'}")
    print("STATUS                 : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
