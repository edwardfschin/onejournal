#!/usr/bin/env python3
"""Import current OneJournal CSV-derived journal data into DuckDB.

Safe local importer.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
import json
from csv import DictReader
from decimal import Decimal
from datetime import UTC, date, datetime
from pathlib import Path

import duckdb

from onejournal.brokers.manual_csv.fills import parse_manual_fills_csv
from onejournal.brokers.normalized import NormalizedFill
from onejournal.journal.episodes import build_episode_previews_from_fills
from onejournal.journal.identity import (
    build_fill_identity_signature,
    conflicting_fill_identity_report,
    dedupe_identical_fills,
)
from onejournal.journal.reviews import load_manual_reviews

DEFAULT_DB = Path("data/journal/onejournal.duckdb")
DEFAULT_FILLS = Path("docs/examples/manual_csv/fills_template.csv")
DEFAULT_REVIEWS = Path("data/journal/reviews/manual_reviews.csv")
DEFAULT_LIFECYCLE_EVENTS = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import OneJournal journal data into DuckDB.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    parser.add_argument("--asof", required=False, help="Optional as-of date in YYYY-MM-DD format. When provided, imported fills must match this date.")
    parser.add_argument("--file", dest="fills_alias", required=False, help="ODFS alias for --fills.")
    parser.add_argument("--fills", default=str(DEFAULT_FILLS), help="Manual fills CSV path.")
    parser.add_argument("--reviews", default=str(DEFAULT_REVIEWS), help="Manual reviews CSV path.")
    parser.add_argument(
        "--lifecycle-events",
        dest="lifecycle_events",
        default=DEFAULT_LIFECYCLE_EVENTS,
        help="Optional lifecycle events CSV path emitted by the Schwab transactions converter.",
    )
    parser.add_argument("--replace", action="store_true", help="Replace existing imported journal rows.")
    args = parser.parse_args()
    if args.fills_alias:
        args.fills = args.fills_alias
    return args


def _parse_event_at(value: str) -> datetime:
    if not value:
        raise ValueError("lifecycle event row has empty event_at")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        event_at = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid lifecycle event_at value: {value}") from exc
    if event_at.tzinfo is None:
        return event_at
    return event_at.astimezone(UTC).replace(tzinfo=None)


def _side_sign(side: str) -> Decimal:
    normalized = side.strip().upper()
    if normalized in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
        return Decimal(1)
    if normalized in {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}:
        return Decimal(-1)
    raise ValueError(f"unexpected side {side}; expected BUY/SELL family")


def _position_key(fill) -> tuple:
    return (
        fill.source_broker,
        fill.source_account_id,
        fill.asset_class,
        fill.symbol,
        fill.option_symbol or "",
        fill.underlying_symbol or "",
        fill.option_type or "",
        fill.expiry or date.min,
        fill.strike,
        fill.multiplier,
        fill.asof,
    )


def _position_uid_for(key: tuple) -> str:
    return "|".join(
        str(part) if part is not None else ""
        for part in key
    )


LIFECYCLE_EVENT_COLUMNS = (
    "event_uid",
    "source_broker",
    "source_account_id",
    "source_activity_id",
    "source_order_id",
    "source_position_id",
    "event_class",
    "event_type",
    "asof_date",
    "event_at",
    "event_name",
    "raw_path",
    "import_run_id",
)


def _load_lifecycle_events(
    lifecycle_events_path: Path | None,
    *,
    import_run_id: str,
    fills_asof: date | None,
) -> list[tuple]:
    if lifecycle_events_path is None:
        return []

    if not lifecycle_events_path.exists():
        raise ValueError(f"lifecycle-events file missing: {lifecycle_events_path}")

    events: list[tuple] = []
    with lifecycle_events_path.open(newline="", encoding="utf-8") as fh:
        reader = DictReader(fh)
        if reader.fieldnames is None:
            raise ValueError(f"lifecycle-events file has no header: {lifecycle_events_path}")

        headers = set(reader.fieldnames)
        missing = [
            name
            for name in (
                "event_uid",
                "source_broker",
                "source_account_id",
                "source_activity_id",
                "source_order_id",
                "source_position_id",
                "event_class",
                "event_type",
                "event_name",
                "event_at",
            )
            if name not in headers
        ]
        if "asof" not in headers and "asof_date" not in headers:
            missing.append("asof_date")
        if missing:
            raise ValueError(
                f"lifecycle-events file missing required columns {missing} in {lifecycle_events_path}"
            )

        for row_index, row in enumerate(reader, start=2):
            event_uid = str(row.get("event_uid", "")).strip()
            source_broker = str(row.get("source_broker", "")).strip()
            source_account_id = str(row.get("source_account_id", "")).strip()
            asof_value = str(row.get("asof_date", "")).strip() or str(row.get("asof", "")).strip()
            event_at_value = str(row.get("event_at", "")).strip()
            event_class = str(row.get("event_class", "")).strip()
            event_type = str(row.get("event_type", "")).strip()
            event_name = str(row.get("event_name", "")).strip()

            source_activity_id = str(row.get("source_activity_id", "")).strip()
            source_order_id = str(row.get("source_order_id", "")).strip()
            source_position_id = str(row.get("source_position_id", "")).strip()

            if not event_uid or not source_broker or not event_class or not event_type:
                raise ValueError(
                    f"invalid lifecycle-events row {row_index}: required fields missing "
                    f"(event_uid/source_broker/event_class/event_type)"
                )
            if not asof_value:
                raise ValueError(f"invalid lifecycle-events row {row_index}: missing asof")
            if fills_asof and asof_value != str(fills_asof):
                raise ValueError(
                    f"lifecycle-events asof mismatch at row {row_index}: row_asof={asof_value} import_asof={fills_asof}"
                )
            try:
                asof_date = date.fromisoformat(asof_value)
            except ValueError as exc:
                raise ValueError(f"invalid lifecycle-events row {row_index}: asof must be YYYY-MM-DD") from exc

            events.append(
                (
                    event_uid,
                    source_broker,
                    source_account_id,
                    source_activity_id,
                    source_order_id,
                    source_position_id,
                    event_class,
                    event_type,
                    asof_date,
                    _parse_event_at(event_at_value),
                    event_name,
                    str(lifecycle_events_path),
                    import_run_id,
                )
            )
    return events


def _fill_record_signature(fill: NormalizedFill | dict[str, object]) -> tuple:
    if not isinstance(fill, dict):
        fill = fill.__dict__
    if isinstance(fill, dict):
        record = {
            "fill_uid": fill["fill_uid"],
            "source_broker": fill["source_broker"],
            "source_account_id": fill["source_account_id"],
            "source_fill_id": fill["source_fill_id"],
            "source_order_id": fill["source_order_id"],
            "episode_group_id": fill["episode_group_id"],
            "asof": fill["asof_date"],
            "filled_at": fill["filled_at"],
            "asset_class": fill["asset_class"],
            "symbol": fill["symbol"],
            "side": fill["side"],
            "quantity": fill["quantity"],
            "fill_price": fill["fill_price"],
            "commission": fill["commission"],
            "fees": fill["fees"],
            "currency": fill["currency"],
            "fetched_at": fill["fetched_at"],
            "raw_path": fill["raw_path"],
            "option_symbol": fill["option_symbol"],
            "underlying_symbol": fill["underlying_symbol"],
            "option_type": fill["option_type"],
            "expiry": fill["expiry"],
            "strike": fill["strike"],
            "multiplier": fill["multiplier"],
            "open_close": fill["open_close"],
            "execution_venue": fill["execution_venue"],
            "liquidity_flag": fill["liquidity_flag"],
        }
    return build_fill_identity_signature(NormalizedFill(**record))


def _normalize_fills_by_uid(fills: list[NormalizedFill]) -> dict[str, tuple[tuple, NormalizedFill]]:
    by_uid: dict[str, tuple[tuple, NormalizedFill]] = {}
    for fill in fills:
        by_uid[fill.fill_uid] = (build_fill_identity_signature(fill), fill)
    return by_uid


def _load_existing_fill_signatures(
    con: duckdb.DuckDBPyConnection,
) -> dict[str, tuple]:
    rows = con.execute(
        """
        SELECT
            fill_uid, source_broker, source_account_id, source_fill_id,
            source_order_id, episode_group_id, asof_date, filled_at, asset_class, symbol,
            side, quantity, fill_price, commission, fees, currency, fetched_at,
            raw_path, option_symbol, underlying_symbol, option_type, expiry, strike,
            multiplier, open_close, execution_venue, liquidity_flag
        FROM normalized_fills
        """
    ).fetchall()
    signatures_by_uid: dict[str, tuple] = {}
    for row in rows:
        (
            fill_uid,
            source_broker,
            source_account_id,
            source_fill_id,
            source_order_id,
            episode_group_id,
            asof_date,
            filled_at,
            asset_class,
            symbol,
            side,
            quantity,
            fill_price,
            commission,
            fees,
            currency,
            fetched_at,
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
        signatures_by_uid[fill_uid] = _fill_record_signature(
            {
                "fill_uid": fill_uid,
                "source_broker": source_broker,
                "source_account_id": source_account_id,
                "source_fill_id": source_fill_id,
                "source_order_id": source_order_id,
                "episode_group_id": episode_group_id,
                "asof_date": asof_date,
                "filled_at": filled_at,
                "asset_class": asset_class,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "fill_price": fill_price,
                "commission": commission,
                "fees": fees,
                "currency": currency,
                "fetched_at": fetched_at,
                "raw_path": raw_path,
                "option_symbol": option_symbol,
                "underlying_symbol": underlying_symbol,
                "option_type": option_type,
                "expiry": expiry,
                "strike": strike,
                "multiplier": multiplier,
                "open_close": open_close,
                "execution_venue": execution_venue,
                "liquidity_flag": liquidity_flag,
            }
        )
    return signatures_by_uid


def _snapshot_replaced_fill_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    replacement_run_id: str,
    replacement_fills_by_uid: dict[str, tuple[tuple, NormalizedFill]],
) -> None:
    existing = con.execute(
        """
        SELECT fill_uid, source_broker, source_account_id, source_fill_id, source_order_id,
               episode_group_id, asof_date, filled_at, asset_class, symbol, side,
               quantity, fill_price, commission, fees, currency, fetched_at, raw_path,
               option_symbol, underlying_symbol, option_type, expiry, strike, multiplier,
               open_close, execution_venue, liquidity_flag, import_run_id
        FROM normalized_fills
        """
    ).fetchall()

    for row in existing:
        (
            fill_uid,
            source_broker,
            source_account_id,
            source_fill_id,
            source_order_id,
            episode_group_id,
            asof_date,
            filled_at,
            asset_class,
            symbol,
            side,
            quantity,
            fill_price,
            commission,
            fees,
            currency,
            fetched_at,
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
            prior_import_run_id,
        ) = row

        prior_signature = _fill_record_signature(
            {
                "fill_uid": fill_uid,
                "source_broker": source_broker,
                "source_account_id": source_account_id,
                "source_fill_id": source_fill_id,
                "source_order_id": source_order_id,
                "episode_group_id": episode_group_id,
                "asof_date": asof_date,
                "filled_at": filled_at,
                "asset_class": asset_class,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "fill_price": fill_price,
                "commission": commission,
                "fees": fees,
                "currency": currency,
                "fetched_at": fetched_at,
                "raw_path": raw_path,
                "option_symbol": option_symbol,
                "underlying_symbol": underlying_symbol,
                "option_type": option_type,
                "expiry": expiry,
                "strike": strike,
                "multiplier": multiplier,
                "open_close": open_close,
                "execution_venue": execution_venue,
                "liquidity_flag": liquidity_flag,
            }
        )
        next_signature, next_fill = replacement_fills_by_uid.get(fill_uid, (None, None))
        if next_signature is None:
            event_type = "evicted_from_reimport"
            next_signature_value = None
            next_payload = None
        elif next_signature == prior_signature:
            continue
        else:
            event_type = "correction_rewrite"
            next_signature_value = "|".join(next_signature)
            next_payload = json.dumps(next_fill.__dict__, default=str)

        con.execute(
            """
            INSERT INTO normalized_fill_revisions (
                fill_uid, source_broker, source_account_id, source_fill_id,
                prior_import_run_id, next_import_run_id, event_type,
                prior_signature, next_signature, prior_payload_json, next_payload_json,
                archived_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fill_uid,
                source_broker,
                source_account_id,
                source_fill_id,
                prior_import_run_id,
                replacement_run_id,
                event_type,
                "|".join(prior_signature),
                next_signature_value,
                json.dumps(
                    {
                        "fill_uid": fill_uid,
                        "source_broker": source_broker,
                        "source_account_id": source_account_id,
                        "source_fill_id": source_fill_id,
                        "source_order_id": source_order_id,
                        "episode_group_id": episode_group_id,
                        "asof_date": str(asof_date),
                        "filled_at": str(filled_at),
                        "asset_class": asset_class,
                        "symbol": symbol,
                        "side": side,
                        "quantity": str(quantity),
                        "fill_price": str(fill_price),
                        "commission": str(commission),
                        "fees": str(fees),
                        "currency": currency,
                        "raw_path": raw_path,
                        "option_symbol": option_symbol,
                        "underlying_symbol": underlying_symbol,
                        "option_type": option_type,
                        "expiry": str(expiry) if expiry is not None else None,
                        "strike": str(strike) if strike is not None else None,
                        "multiplier": str(multiplier) if multiplier is not None else None,
                        "open_close": open_close,
                        "execution_venue": execution_venue,
                        "liquidity_flag": liquidity_flag,
                    },
                    default=str,
                ),
                next_payload,
                datetime.now().astimezone().replace(tzinfo=None),
            ),
        )


def _derive_normalized_accounts(fills, import_run_id: str, imported_at: datetime) -> list[tuple]:
    account_rows: dict[str, tuple] = {}
    for fill in fills:
        account_uid = f"{fill.source_broker}:{fill.source_account_id}"
        if account_uid in account_rows:
            continue
        account_rows[account_uid] = (
            account_uid,
            fill.source_broker,
            fill.source_account_id,
            fill.source_account_id,
            fill.source_broker,
            fill.currency,
            fill.asof,
            imported_at,
            fill.raw_path,
            None,
            None,
            None,
            None,
            None,
            None,
            None,
            import_run_id,
        )
    return [
        (
            account_uid,
            source_broker,
            source_account_id,
            account_label,
            account_type,
            currency,
            asof_date,
            fetched_at,
            raw_path,
            buying_power,
            cash_balance,
            net_liquidation_value,
            maintenance_requirement,
            initial_requirement,
            day_trade_buying_power,
            status,
            import_run_ref,
        )
        for (
            account_uid,
            source_broker,
            source_account_id,
            account_label,
            account_type,
            currency,
            asof_date,
            fetched_at,
            raw_path,
            buying_power,
            cash_balance,
            net_liquidation_value,
            maintenance_requirement,
            initial_requirement,
            day_trade_buying_power,
            status,
            import_run_ref,
        ) in account_rows.values()
    ]


def _derive_normalized_orders(fills, import_run_id: str, imported_at: datetime) -> list[tuple]:
    grouped: dict[str, dict[str, object]] = {}

    for fill in fills:
        if fill.source_order_id is None:
            continue
        order_uid = f"{fill.source_broker}:{fill.source_account_id}:{fill.source_order_id}"
        state = grouped.get(order_uid)
        if state is None:
            grouped[order_uid] = {
                "order_uid": order_uid,
                "source_broker": fill.source_broker,
                "source_account_id": fill.source_account_id,
                "source_order_id": fill.source_order_id,
                "asof_date": fill.asof,
                "order_status": "IMPORTED_FILL",
                "order_type": "FILL_STREAM",
                "time_in_force": "DAY",
                "asset_class": fill.asset_class,
                "symbol": fill.symbol,
                "side": fill.side,
                "quantity": fill.quantity * _side_sign(fill.side),
                "created_at": fill.filled_at,
                "fetched_at": imported_at,
                "raw_path": fill.raw_path,
                "limit_price": fill.fill_price,
                "stop_price": None,
                "filled_quantity": fill.quantity,
                "remaining_quantity": None,
                "average_fill_price": fill.fill_price,
                "cancelled_at": None,
                "replaced_by_order_id": None,
                "parent_order_id": None,
                "broker_strategy_type": None,
                "notes": "derived from fill import",
                "import_run_id": import_run_id,
            }
            continue

        state["quantity"] = state["quantity"] + (fill.quantity * _side_sign(fill.side))
        state["filled_quantity"] = state["filled_quantity"] + fill.quantity
        if fill.filled_at < state["created_at"]:
            state["created_at"] = fill.filled_at

    return [
        (
            payload["order_uid"],
            payload["source_broker"],
            payload["source_account_id"],
            payload["source_order_id"],
            payload["asof_date"],
            payload["order_status"],
            payload["order_type"],
            payload["time_in_force"],
            payload["asset_class"],
            payload["symbol"],
            payload["side"],
            payload["quantity"],
            payload["created_at"],
            payload["fetched_at"],
            payload["raw_path"],
            payload["limit_price"],
            payload["stop_price"],
            payload["filled_quantity"],
            payload["remaining_quantity"],
            payload["average_fill_price"],
            payload["cancelled_at"],
            payload["replaced_by_order_id"],
            payload["parent_order_id"],
            payload["broker_strategy_type"],
            payload["notes"],
            payload["import_run_id"],
        )
        for payload in grouped.values()
    ]


def _derive_normalized_positions(fills, import_run_id: str, imported_at: datetime) -> list[tuple]:
    grouped: dict[tuple, dict[str, object]] = {}
    for fill in fills:
        key = _position_key(fill)
        state = grouped.get(key)
        if state is None:
            grouped[key] = {
                "position_uid": _position_uid_for(key),
                "source_broker": fill.source_broker,
                "source_account_id": fill.source_account_id,
                "asof_date": fill.asof,
                "asset_class": fill.asset_class,
                "symbol": fill.symbol,
                "quantity": Decimal(0),
                "weighted_abs_cost": Decimal(0),
                "abs_quantity": Decimal(0),
                "market_price": fill.fill_price,
                "currency": fill.currency,
                "fetched_at": imported_at,
                "raw_path": fill.raw_path,
                "unrealized_pnl": None,
                "realized_pnl": None,
                "delta": None,
                "beta_weighted_delta": None,
                "option_symbol": fill.option_symbol,
                "underlying_symbol": fill.underlying_symbol,
                "option_type": fill.option_type,
                "expiry": fill.expiry,
                "strike": fill.strike,
                "multiplier": fill.multiplier,
                "import_run_id": import_run_id,
            }
            state = grouped[key]

        signed_qty = fill.quantity * _side_sign(fill.side)
        state["quantity"] = state["quantity"] + signed_qty
        state["weighted_abs_cost"] += abs(fill.quantity) * fill.fill_price
        state["abs_quantity"] += abs(fill.quantity)
        state["market_price"] = fill.fill_price

    rows: list[tuple] = []
    for state in grouped.values():
        avg_cost = state["weighted_abs_cost"] / state["abs_quantity"] if state["abs_quantity"] else Decimal(0)
        market_value = state["quantity"] * state["market_price"]
        rows.append(
            (
                state["position_uid"],
                state["source_broker"],
                state["source_account_id"],
                state["asof_date"],
                state["asset_class"],
                state["symbol"],
                state["quantity"],
                avg_cost,
                state["market_price"],
                market_value,
                state["currency"],
                state["fetched_at"],
                state["raw_path"],
                state["unrealized_pnl"],
                state["realized_pnl"],
                state["delta"],
                state["beta_weighted_delta"],
                state["option_symbol"],
                state["underlying_symbol"],
                state["option_type"],
                state["expiry"],
                state["strike"],
                state["multiplier"],
                state["import_run_id"],
            )
        )
    return rows


def _derive_normalized_transactions(fills, import_run_id: str, imported_at: datetime) -> list[tuple]:
    rows: list[tuple] = []
    for fill in fills:
        side = fill.side.strip().upper()
        gross = fill.quantity * fill.fill_price * (fill.multiplier or Decimal(1))
        fee_total = fill.fees + fill.commission
        if side in {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}:
            amount = -(gross + fee_total)
        elif side in {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}:
            amount = gross - fee_total
        else:
            raise ValueError(f"unexpected side for normalized transaction amount: {fill.side}")

        rows.append(
            (
                f"{fill.source_broker}:{fill.source_account_id}:{fill.source_fill_id}:txn",
                fill.source_broker,
                fill.source_account_id,
                fill.source_fill_id,
                fill.asof,
                fill.filled_at.replace(tzinfo=None),
                "FILL",
                amount,
                fill.currency,
                fill.filled_at.replace(tzinfo=None),
                fill.raw_path,
                fill.symbol,
                fill.asset_class,
                fill.quantity,
                fill.fill_price,
                fill.commission,
                fill.fees,
                f"derived from normalized fill {fill.fill_uid}",
                fill.source_order_id,
                fill.source_fill_id,
                import_run_id,
            )
        )
    return rows


def _insert_derived_normalized_rows(
    con: duckdb.DuckDBPyConnection,
    fills,
    *,
    import_run_id: str,
    imported_at: datetime,
) -> None:
    account_rows = _derive_normalized_accounts(fills, import_run_id, imported_at)
    order_rows = _derive_normalized_orders(fills, import_run_id, imported_at)
    position_rows = _derive_normalized_positions(fills, import_run_id, imported_at)
    transaction_rows = _derive_normalized_transactions(fills, import_run_id, imported_at)

    con.executemany(
        """
        INSERT OR REPLACE INTO normalized_accounts (
            account_uid, source_broker, source_account_id, account_label, account_type,
            currency, asof_date, fetched_at, raw_path, buying_power, cash_balance,
            net_liquidation_value, maintenance_requirement, initial_requirement,
            day_trade_buying_power, status, import_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        account_rows,
    )

    con.executemany(
        """
        INSERT OR REPLACE INTO normalized_orders (
            order_uid, source_broker, source_account_id, source_order_id,
            asof_date, order_status, order_type, time_in_force,
            asset_class, symbol, side, quantity, created_at, fetched_at,
            raw_path, limit_price, stop_price, filled_quantity, remaining_quantity,
            average_fill_price, cancelled_at, replaced_by_order_id, parent_order_id,
            broker_strategy_type, notes, import_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        order_rows,
    )

    con.executemany(
        """
        INSERT OR REPLACE INTO normalized_positions (
            position_uid, source_broker, source_account_id, asof_date,
            asset_class, symbol, quantity, average_cost, market_price,
            market_value, currency, fetched_at, raw_path, unrealized_pnl,
            realized_pnl, delta, beta_weighted_delta, option_symbol,
            underlying_symbol, option_type, expiry, strike, multiplier, import_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        position_rows,
    )

    con.executemany(
        """
        INSERT OR REPLACE INTO normalized_transactions (
            transaction_uid, source_broker, source_account_id, source_transaction_id,
            asof_date, transaction_at, transaction_type, amount, currency,
            fetched_at, raw_path, symbol, asset_class, quantity, price,
            commission, fees, description, linked_order_id, linked_fill_id, import_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        transaction_rows,
    )


def _insert_derived_lifecycle_events(
    con: duckdb.DuckDBPyConnection,
    lifecycle_events: list[tuple],
    *,
    import_run_id: str,
) -> None:
    if not lifecycle_events:
        return
    con.executemany(
        """
        INSERT OR REPLACE INTO normalized_lifecycle_events (
            event_uid, source_broker, source_account_id,
            source_activity_id, source_order_id, source_position_id,
            event_class, event_type, asof_date, event_at,
            event_name, raw_path, import_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                event_uid,
                source_broker,
                source_account_id,
                source_activity_id,
                source_order_id,
                source_position_id,
                event_class,
                event_type,
                asof_date,
                event_at,
                event_name,
                raw_path,
                import_run_id,
            )
            for (
                event_uid,
                source_broker,
                source_account_id,
                source_activity_id,
                source_order_id,
                source_position_id,
                event_class,
                event_type,
                asof_date,
                event_at,
                event_name,
                raw_path,
                _event_import_run_id,
            ) in lifecycle_events
        ],
    )


def import_to_db(
    db_path: Path,
    fills_path: Path,
    reviews_path: Path,
    replace: bool,
    lifecycle_events: Path | None = None,
    asof: date | None = None,
) -> dict[str, int]:
    import_run_id = "manual_csv:" + datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    imported_at = datetime.now().astimezone().replace(tzinfo=None)
    fills = parse_manual_fills_csv(fills_path)
    conflicts = conflicting_fill_identity_report(fills)
    if conflicts:
        if not replace:
            raise ValueError(
                "conflicting fill replays detected; run import with --replace to apply correction-safe re-import"
            )
    fills = dedupe_identical_fills(fills, allow_conflicts=True)
    fills_by_uid = _normalize_fills_by_uid(fills)

    con = duckdb.connect(str(db_path))
    try:
        if not replace:
            existing_signatures = _load_existing_fill_signatures(con)
            for fill_uid, (incoming_signature, _fill) in fills_by_uid.items():
                existing_signature = existing_signatures.get(fill_uid)
                if existing_signature is None:
                    continue
                if existing_signature != incoming_signature:
                    raise ValueError(
                        "conflicting fill replays detected; run import with --replace to apply correction-safe re-import"
                    )

        if asof is not None:
            mismatch_count = sum(1 for fill in fills if fill.asof != asof)
            if mismatch_count:
                raise ValueError(f"{mismatch_count} fill(s) have asof different from --asof {asof}")

        episodes = build_episode_previews_from_fills(fills)
        reviews = load_manual_reviews(reviews_path)
        lifecycle_rows = _load_lifecycle_events(
            lifecycle_events,
            import_run_id=import_run_id,
            fills_asof=asof if asof is not None else (fills[0].asof if fills else None),
        )

        if replace:
            con.execute(
                """
                INSERT OR REPLACE INTO import_runs (
                    import_run_id, source_type, source_path, asof_date, imported_at, row_count, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_run_id,
                    "manual_csv",
                    str(fills_path),
                    fills[0].asof if fills else None,
                    imported_at,
                    len(fills),
                    "ok",
                    "DB-1D correction-safe replace",
                ),
            )
        if replace:
            _snapshot_replaced_fill_rows(
                con,
                replacement_run_id=import_run_id,
                replacement_fills_by_uid=fills_by_uid,
            )
            for table_name in [
                "trade_episode_legs",
                "trade_episodes",
                "normalized_fills",
                "normalized_accounts",
                "normalized_orders",
                "normalized_positions",
                "normalized_transactions",
                "normalized_lifecycle_events",
            ]:
                con.execute(f"DELETE FROM {table_name}")

        con.executemany(
            """
            INSERT OR REPLACE INTO normalized_fills (
                fill_uid, source_broker, source_account_id, source_fill_id, source_order_id,
                episode_group_id, asof_date, filled_at, asset_class, symbol, side, quantity,
                fill_price, commission, fees, currency, fetched_at, raw_path, option_symbol,
                underlying_symbol, option_type, expiry, strike, multiplier, open_close,
                execution_venue, liquidity_flag, import_run_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    f.fill_uid,
                    f.source_broker,
                    f.source_account_id,
                    f.source_fill_id,
                    f.source_order_id,
                    f.episode_group_id,
                    f.asof,
                    f.filled_at.replace(tzinfo=None),
                    f.asset_class,
                    f.symbol,
                    f.side,
                    f.quantity,
                    f.fill_price,
                    f.commission,
                    f.fees,
                    f.currency,
                    f.fetched_at.replace(tzinfo=None),
                    f.raw_path,
                    f.option_symbol,
                    f.underlying_symbol,
                    f.option_type,
                    f.expiry,
                    f.strike,
                    f.multiplier,
                    f.open_close,
                    f.execution_venue,
                    f.liquidity_flag,
                    import_run_id,
                )
                for f in fills
            ],
        )

        con.executemany(
            """
            INSERT OR REPLACE INTO manual_reviews (
                episode_uid, review_status, setup_quality, entry_reason, notes, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (r.episode_uid, r.review_status, r.setup_quality, r.entry_reason, r.notes, imported_at)
                for r in reviews.values()
            ],
        )

        con.executemany(
            """
            INSERT OR REPLACE INTO trade_episodes (
                episode_uid, source_broker, source_account_id, primary_symbol, asset_class,
                strategy_type, strategy_label, opened_at, status, fill_count, leg_count,
                leg_summary, cashflow_label, net_quantity, gross_cashflow, commission, fees, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    e.episode_uid,
                    e.source_broker,
                    e.source_account_id,
                    e.primary_symbol,
                    e.asset_class,
                    e.strategy_type,
                    e.strategy_label,
                    e.opened_at.replace(tzinfo=None),
                    e.status,
                    e.fill_count,
                    e.leg_count,
                    e.leg_summary,
                    e.cashflow_label,
                    e.net_quantity,
                    e.gross_cashflow,
                    e.total_commission,
                    e.total_fees,
                    imported_at,
                )
                for e in episodes
            ],
        )

        leg_rows = []
        for e in episodes:
            for idx, leg in enumerate(e.legs, start=1):
                leg_rows.append((
                    e.episode_uid,
                    idx,
                    leg.get("asset_class"),
                    leg.get("symbol"),
                    leg.get("side"),
                    leg.get("quantity"),
                    leg.get("option_type"),
                    leg.get("expiry"),
                    leg.get("strike"),
                    json.dumps(leg, sort_keys=True),
                ))

        con.executemany(
            """
            INSERT OR REPLACE INTO trade_episode_legs (
                episode_uid, leg_index, asset_class, symbol, side, quantity, option_type, expiry, strike, raw_leg_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            leg_rows,
        )

        if not replace:
            con.execute(
                """
                INSERT OR REPLACE INTO import_runs (
                    import_run_id, source_type, source_path, asof_date, imported_at, row_count, status, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_run_id,
                    "manual_csv",
                    str(fills_path),
                    fills[0].asof if fills else None,
                    imported_at,
                    len(fills),
                    "ok",
                    "DB-1D initial CSV import",
                ),
            )

        _insert_derived_normalized_rows(con, fills, import_run_id=import_run_id, imported_at=imported_at)
        _insert_derived_lifecycle_events(con, lifecycle_rows, import_run_id=import_run_id)

        return {
            "import_runs": con.execute("SELECT COUNT(*) FROM import_runs").fetchone()[0],
            "normalized_fills": con.execute("SELECT COUNT(*) FROM normalized_fills").fetchone()[0],
            "normalized_accounts": con.execute("SELECT COUNT(*) FROM normalized_accounts").fetchone()[0],
            "normalized_orders": con.execute("SELECT COUNT(*) FROM normalized_orders").fetchone()[0],
            "normalized_positions": con.execute("SELECT COUNT(*) FROM normalized_positions").fetchone()[0],
            "normalized_transactions": con.execute("SELECT COUNT(*) FROM normalized_transactions").fetchone()[0],
            "normalized_lifecycle_events": con.execute(
                "SELECT COUNT(*) FROM normalized_lifecycle_events"
            ).fetchone()[0],
            "trade_episodes": con.execute("SELECT COUNT(*) FROM trade_episodes").fetchone()[0],
            "trade_episode_legs": con.execute("SELECT COUNT(*) FROM trade_episode_legs").fetchone()[0],
            "manual_reviews": con.execute("SELECT COUNT(*) FROM manual_reviews").fetchone()[0],
        }
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    asof = date.fromisoformat(args.asof) if args.asof else None
    counts = import_to_db(
        Path(args.db),
        Path(args.fills),
        Path(args.reviews),
        args.replace,
        lifecycle_events=(Path(args.lifecycle_events) if args.lifecycle_events else None),
        asof=asof,
    )
    print("===== OneJournal DB import =====")
    print(f"DB        : {args.db}")
    print(f"ASOF      : {args.asof or 'not enforced'}")
    print(f"FILLS     : {args.fills}")
    print(f"REVIEWS   : {args.reviews}")
    print(f"LIFECYCLE : {args.lifecycle_events or 'not provided'}")
    for key, value in counts.items():
        print(f"{key}: {value}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
