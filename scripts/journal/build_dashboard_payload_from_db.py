#!/usr/bin/env python3
"""Build OneJournal dashboard payload from DuckDB.

Read-only DB-to-dashboard publisher.

This script does not call broker APIs, does not place orders, and does not auto-trade.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime
from decimal import Decimal
from decimal import getcontext
from pathlib import Path
from typing import Any

import duckdb

from onejournal.brokers.normalized import NormalizedFill
from onejournal.pnl import PnLCalculationResult, calculate_fifo_pnl_from_fills, build_instrument_key
from onejournal.journal.pnl_repository import (
    load_approved_lifecycle_events,
    load_current_persisted_pnl_result,
)
from onejournal.journal.workflows import build_review_queues, flatten_review_queues

DASHBOARD_PAYLOAD_VERSION = "0.1.0-db"
DEFAULT_DB = Path("data/journal/onejournal.duckdb")
DEFAULT_OUTPUT = Path("output/dashboard/latest/dashboard_payload_from_db.json")
VALID_IMPORT_STATUSES = {"ok", "success", "completed"}
DATA_STATUSES = ("valid", "incomplete", "stale", "reconciliation_pending", "unavailable", "failed")
DATA_STATUS_ORDER = {status: rank for rank, status in enumerate(DATA_STATUSES)}
getcontext().prec = 28


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dashboard payload from OneJournal DuckDB.")
    parser.add_argument("--asof", required=True, help="Market date in YYYY-MM-DD format.")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="DuckDB database path.")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Dashboard payload JSON path.")
    parser.add_argument("--write", action="store_true", help="Write dashboard payload JSON.")
    return parser.parse_args()


def _decimal_to_string(value: Any) -> str:
    if value is None:
        return "0.00"
    return f"{Decimal(str(value)):.2f}"


def _iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    result = con.execute(sql, params or [])
    cols = [d[0] for d in result.description]
    return [dict(zip(cols, row)) for row in result.fetchall()]


def _optional_decimal_to_string(value: Any) -> str | None:
    if value is None:
        return None
    return f"{Decimal(str(value)):.2f}"


def _safe_divide(numerator: Decimal, denominator: Decimal | Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _safe_divide_optional(
    numerator: Decimal | None,
    denominator: Decimal | None,
) -> Decimal | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def _average(values: list[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, Decimal("0")) / Decimal(len(values))


def _sum_by_currency(
    items: list[tuple[str, Decimal | None]],
    *,
    skip_none: bool = False,
) -> tuple[dict[str, Decimal], dict[str, bool]]:
    totals: dict[str, Decimal] = {}
    availability: dict[str, bool] = {}
    for currency, value in items:
        if value is None:
            if not skip_none:
                availability.setdefault(currency, False)
            continue
        totals[currency] = totals.get(currency, Decimal("0")) + value
        availability[currency] = True
    return totals, availability


def _as_of_filter_params(asof: date) -> list[Any]:
    return [asof]


def _to_decimal(value: Any, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} must not be None for normalized fills")
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _build_fills_for_pnl(fills_rows: list[dict[str, Any]]) -> list[NormalizedFill]:
    def _timestamp(row: dict[str, Any], utc_field: str, legacy_field: str) -> datetime:
        utc_value = row.get(utc_field)
        if utc_value:
            text = str(utc_value)
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return datetime.fromisoformat(text)
        return row[legacy_field]

    return [
        NormalizedFill(
            fill_uid=row["fill_uid"],
            source_broker=row["source_broker"],
            source_account_id=row["source_account_id"],
            source_fill_id=row["source_fill_id"],
            source_order_id=row.get("source_order_id"),
            episode_group_id=row.get("episode_group_id"),
            asof=(
                row["asof_date"]
                if hasattr(row["asof_date"], "isoformat")
                else datetime.fromisoformat(str(row["asof_date"])).date()
            ),
            filled_at=_timestamp(row, "filled_at_utc", "filled_at"),
            asset_class=row["asset_class"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=_to_decimal(row["quantity"], "quantity"),
            fill_price=_to_decimal(row["fill_price"], "fill_price"),
            commission=_to_decimal(row["commission"], "commission"),
            fees=_to_decimal(row["fees"], "fees"),
            currency=(row["currency"] or "USD").upper(),
            fetched_at=_timestamp(row, "fetched_at_utc", "fetched_at"),
            raw_path=row.get("raw_path"),
            option_symbol=row.get("option_symbol"),
            underlying_symbol=row.get("underlying_symbol"),
            option_type=row.get("option_type"),
            expiry=row.get("expiry"),
            strike=_to_decimal(row["strike"], "strike") if row.get("strike") is not None else None,
            multiplier=_to_decimal(row["multiplier"], "multiplier") if row.get("multiplier") is not None else None,
            open_close=row.get("open_close"),
            execution_venue=row.get("execution_venue"),
            liquidity_flag=row.get("liquidity_flag"),
        )
        for row in fills_rows
    ]


def _build_currency_totals(values: dict[str, Decimal | None]) -> dict[str, str | None]:
    return {
        currency: _decimal_to_string(amount) if amount is not None else None
        for currency, amount in sorted(values.items())
    }


def _max_status(*statuses: str | None) -> str:
    valid = [status for status in statuses if status in DATA_STATUS_ORDER]
    if not valid:
        return "valid"
    return max(valid, key=DATA_STATUS_ORDER.get)


def _format_optional_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone().isoformat()
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _build_open_positions(
    con: duckdb.DuckDBPyConnection,
    asof: date,
) -> list[dict[str, Any]]:
    rows = _rows(
        con,
        """
        WITH ranked AS (
            SELECT
                position_uid, source_broker, source_account_id, asof_date, asset_class,
                symbol, quantity, average_cost, market_price, market_value, currency,
                unrealized_pnl, realized_pnl, option_symbol, underlying_symbol,
                option_type, expiry, strike, multiplier, raw_path, fetched_at,
                ROW_NUMBER() OVER (
                    PARTITION BY source_broker, source_account_id, asset_class, symbol,
                        COALESCE(option_symbol, ''),
                        COALESCE(underlying_symbol, ''),
                        COALESCE(option_type, ''),
                        COALESCE(expiry, DATE '0001-01-01'),
                        COALESCE(strike, 0),
                        COALESCE(multiplier, 1)
                    ORDER BY asof_date DESC, fetched_at DESC, position_uid DESC
                ) AS rn
            FROM normalized_positions
            WHERE asof_date <= ?
        )
        SELECT
            position_uid, source_broker, source_account_id, asof_date, asset_class,
            symbol, quantity, average_cost, market_price, market_value, currency,
            unrealized_pnl, realized_pnl, option_symbol, underlying_symbol, option_type,
            expiry, strike, multiplier, raw_path, fetched_at
        FROM ranked
        WHERE rn = 1
        ORDER BY source_broker, source_account_id, symbol, option_symbol NULLS LAST
        """,
        _as_of_filter_params(asof),
    )

    payload_positions: list[dict[str, Any]] = []
    for row in rows:
        quantity = row["quantity"] if row["quantity"] is not None else Decimal("0")
        if quantity == 0:
            continue
        direction = "FLAT"
        if quantity > 0:
            direction = "LONG"
        elif quantity < 0:
            direction = "SHORT"

        payload_positions.append({
            "position_uid": row["position_uid"],
            "source_broker": row["source_broker"],
            "source_account_id": row["source_account_id"],
            "asof": _iso(row["asof_date"]),
            "asset_class": row["asset_class"],
            "symbol": row["symbol"],
            "option_symbol": row.get("option_symbol"),
            "underlying_symbol": row.get("underlying_symbol"),
            "option_type": row.get("option_type"),
            "expiry": _format_optional_datetime(row["expiry"]),
            "strike": _optional_decimal_to_string(row.get("strike")),
            "multiplier": _optional_decimal_to_string(row.get("multiplier")),
            "quantity": _decimal_to_string(quantity),
            "direction": direction,
            "average_cost": _decimal_to_string(row.get("average_cost")),
            "market_price": _decimal_to_string(row.get("market_price")),
            "market_value": _decimal_to_string(row.get("market_value")),
            "cost_basis": _decimal_to_string(
                Decimal(str(quantity)) * Decimal(str(row["average_cost"] or 0))
            ),
            "realized_pnl": _optional_decimal_to_string(row.get("realized_pnl")),
            "unrealized_pnl": _optional_decimal_to_string(row.get("unrealized_pnl")),
            "currency": row["currency"] or "USD",
            "fetched_at": _format_optional_datetime(row["fetched_at"]),
            "raw_path": row.get("raw_path"),
        })

    return payload_positions


def _build_portfolio_snapshots(open_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str], dict[str, Decimal]] = {}
    for row in open_positions:
        key = (
            str(row["source_broker"]),
            str(row["source_account_id"]),
            str(row["currency"]),
        )
        state = by_key.setdefault(
            key,
            {
                "positions": Decimal("0"),
                "market_value": Decimal("0"),
                "cost_basis": Decimal("0"),
                "realized_pnl": Decimal("0"),
                "unrealized_pnl": Decimal("0"),
                "has_unavailable_unrealized": Decimal("0"),
                "asof": None,
                "fetched_at": None,
            },
        )

        state["positions"] += 1
        state["market_value"] += Decimal(str(row.get("market_value") or 0))
        state["cost_basis"] += Decimal(str(row.get("cost_basis") or 0))
        state["realized_pnl"] += Decimal(str(row.get("realized_pnl") or 0))
        if (
            state["asof"] is None
            or (row.get("asof") is not None and row["asof"] > state["asof"])
        ):
            state["asof"] = row.get("asof")
        if state["fetched_at"] is None or (row.get("fetched_at") is not None and row["fetched_at"] > state["fetched_at"]):
            state["fetched_at"] = row.get("fetched_at")
        if row.get("unrealized_pnl") is None:
            state["has_unavailable_unrealized"] = Decimal("1")
        else:
            state["unrealized_pnl"] += Decimal(str(row.get("unrealized_pnl") or 0))

    snapshots: list[dict[str, Any]] = []
    for (source_broker, source_account_id, currency), state in sorted(by_key.items()):
        snapshots.append(
            {
                "source_broker": source_broker,
                "source_account_id": source_account_id,
                "currency": currency,
                "position_count": int(state["positions"]),
                "market_value": _decimal_to_string(state["market_value"]),
                "cost_basis": _decimal_to_string(state["cost_basis"]),
                "realized_pnl": _decimal_to_string(state["realized_pnl"]),
                "asof": state["asof"],
                "fetched_at": _format_optional_datetime(state.get("fetched_at")),
                "unrealized_pnl": (
                    None
                    if state["has_unavailable_unrealized"] != 0
                    else _decimal_to_string(state["unrealized_pnl"])
                ),
            }
        )
    return snapshots


def _build_open_position_time_series(fills: list[NormalizedFill]) -> list[Decimal]:
    from onejournal.journal.lifecycle import build_lifecycle_fill_events

    if not fills:
        return []

    events = build_lifecycle_fill_events(fills, allow_unmatched_close=True).events
    fill_by_uid: dict[str, NormalizedFill] = {fill.fill_uid: fill for fill in fills}
    scope_open_qty: dict[tuple[tuple[str, str, str, str], str], Decimal] = {}
    scope_open_start: dict[tuple[tuple[str, str, str, str], str], datetime] = {}
    holding_days: list[Decimal] = []

    for event in events:
        fill = fill_by_uid.get(event.fill_uid)
        if fill is None:
            continue

        state_key = (event.scope_key, event.direction)
        open_qty = scope_open_qty.get(state_key, Decimal("0"))

        if event.action == "OPEN":
            if open_qty <= 0:
                scope_open_start[state_key] = fill.filled_at
            scope_open_qty[state_key] = open_qty + event.fill_quantity
            continue

        if event.matched_open_quantity <= 0:
            continue

        open_qty -= event.matched_open_quantity
        if open_qty <= 0:
            start_at = scope_open_start.get(state_key)
            if start_at is not None:
                holding_days.append(
                    Decimal((fill.filled_at - start_at).total_seconds()) / Decimal("86400")
                )
            scope_open_start.pop(state_key, None)
            scope_open_qty[state_key] = Decimal("0")
        else:
            scope_open_qty[state_key] = open_qty

    return holding_days


def _build_performance_breakdowns(
    fills: list[NormalizedFill],
    pnl_result: PnLCalculationResult,
    payload_episodes: list[dict[str, Any]],
) -> dict[str, Any]:
    def _build_agg() -> dict[str, Decimal | None]:
        return {
            "realized": Decimal("0"),
            "unrealized": Decimal("0"),
            "unrealized_available": True,
        }

    def _add_value(
        state: dict[str, Decimal | None],
        realized: Decimal,
        unrealized: Decimal | None,
    ) -> None:
        state["realized"] = state["realized"] + realized
        if unrealized is None:
            state["unrealized_available"] = False
        else:
            state["unrealized"] = (state["unrealized"] or Decimal("0")) + unrealized

    def _symbol_from_fill(fill: NormalizedFill) -> str:
        if fill.asset_class.lower() == "option" and fill.underlying_symbol:
            return str(fill.underlying_symbol).upper()
        return (fill.symbol or "").upper()

    fill_scope_index: dict[tuple[str, str, str, str], list[NormalizedFill]] = {}
    for fill in fills:
        scope = (
            fill.source_broker,
            fill.source_account_id,
            build_instrument_key(fill),
            fill.currency or "USD",
        )
        fill_scope_index.setdefault(scope, []).append(fill)

    strategy_by_key: dict[tuple[str, str, str, str], set[str]] = {}
    for row in payload_episodes:
        key = (
            row["source_broker"],
            row["source_account_id"],
            row["asset_class"],
            str(row["primary_symbol"]).upper(),
        )
        strategy_by_key.setdefault(key, set()).add(str(row.get("strategy_label") or "unassigned"))

    def _strategy_for_fill(fill: NormalizedFill) -> str:
        key = (fill.source_broker, fill.source_account_id, fill.asset_class, _symbol_from_fill(fill))
        candidates = strategy_by_key.get(key)
        if not candidates:
            return "unassigned"
        if len(candidates) == 1:
            return next(iter(candidates))
        return "mixed"

    by_account: dict[tuple[str, str, str], dict[str, Decimal | None]] = {}
    by_broker: dict[tuple[str, str], dict[str, Decimal | None]] = {}
    by_symbol: dict[tuple[str, str], dict[str, Decimal | None]] = {}
    by_asset_class: dict[tuple[str, str], dict[str, Decimal | None]] = {}
    by_strategy: dict[tuple[str, str], dict[str, Decimal | None]] = {}

    for scope, group in pnl_result.groups.items():
        fills_in_scope = fill_scope_index.get(scope)
        if not fills_in_scope:
            continue
        fill = fills_in_scope[0]
        broker, account, _instrument, currency = scope
        asset_class = fill.asset_class
        symbol = _symbol_from_fill(fill)
        strategy = _strategy_for_fill(fill)

        _add_value(by_account.setdefault((broker, account, currency), _build_agg()), group.realized_pnl, group.unrealized_pnl)
        _add_value(by_broker.setdefault((broker, currency), _build_agg()), group.realized_pnl, group.unrealized_pnl)
        _add_value(by_symbol.setdefault((currency, symbol), _build_agg()), group.realized_pnl, group.unrealized_pnl)
        _add_value(by_asset_class.setdefault((currency, asset_class), _build_agg()), group.realized_pnl, group.unrealized_pnl)
        _add_value(by_strategy.setdefault((strategy, currency), _build_agg()), group.realized_pnl, group.unrealized_pnl)

    def _as_rows(rows: dict[tuple[str, str], dict[str, Decimal | None]], extra: list[str]) -> list[dict[str, Any]]:
        formatted: list[dict[str, Any]] = []
        for key, values in sorted(rows.items(), key=lambda item: (str(item[0][0]), str(item[0][1]))):
            entry: dict[str, Any] = {
                **{name: value for name, value in zip(extra, key)},
                "realized_pnl": _decimal_to_string(values["realized"]),
                "unrealized_pnl": (
                    None
                    if values["unrealized_available"] is False
                    else _decimal_to_string(values["unrealized"])
                ),
            }
            formatted.append(entry)
        return formatted

    return {
        "by_account": _as_rows(by_account, ["source_broker", "source_account_id", "currency"]),
        "by_broker": _as_rows(by_broker, ["source_broker", "currency"]),
        "by_symbol": _as_rows(by_symbol, ["currency", "symbol"]),
        "by_asset_class": _as_rows(by_asset_class, ["currency", "asset_class"]),
        "by_strategy": _as_rows(by_strategy, ["strategy_label", "currency"]),
        "by_period": {
            "status": "unavailable",
            "reason": "PNL-07 time-based report breakdowns are blocked until reporting scope is finalized.",
        },
    }


def _build_performance_metrics(
    fills: list[NormalizedFill],
    pnl_result: PnLCalculationResult,
    open_positions: list[dict[str, Any]],
    breakdowns: dict[str, Any],
) -> dict[str, Any]:
    closed_groups = [
        group
        for group in pnl_result.groups.values()
        if group.open_quantity == 0 and group.realized_pnl is not None
    ]
    realized_wins = [group.realized_pnl for group in closed_groups if group.realized_pnl > 0]
    realized_losses = [group.realized_pnl for group in closed_groups if group.realized_pnl < 0]

    total_realized = pnl_result.total_realized_pnl_by_currency
    total_unrealized = pnl_result.total_unrealized_pnl_by_currency

    total_pnl_values: dict[str, Decimal | None] = {}
    for currency in set(total_realized.keys()) | set(total_unrealized.keys()):
        realized = total_realized.get(currency, Decimal("0"))
        unrealized = total_unrealized.get(currency)
        total_pnl_values[currency] = realized + unrealized if unrealized is not None else None

    gross_gain = sum((value for value in realized_wins), Decimal("0"))
    gross_loss_abs = sum((-value for value in realized_losses), Decimal("0"))
    avg_win = _average(realized_wins)
    avg_loss = _average([-value for value in realized_losses]) if realized_losses else None
    win_rate = (
        _safe_divide(Decimal(len(realized_wins)), Decimal(len(closed_groups)))
        if closed_groups
        else None
    )
    profit_factor = _safe_divide(gross_gain, gross_loss_abs)

    exposure_currency_totals, _ = _sum_by_currency(
        [
            (str(row["currency"]), _to_decimal(row["market_value"], "market_value"))
            for row in open_positions
        ],
        skip_none=True,
    )

    holding_days = _build_open_position_time_series(fills)
    avg_holding_days = _average(holding_days)

    has_unrealized_exposure = any(v is None for v in total_unrealized.values())

    return {
            "currency": {
                "total_realized_pnl_by_currency": _build_currency_totals(total_realized),
                "total_unrealized_pnl_by_currency": _build_currency_totals(total_unrealized),
                "total_pnl_by_currency": _build_currency_totals(total_pnl_values),
                "exposure_by_currency": _build_currency_totals(exposure_currency_totals),
            },
        "trade_counts": {
            "closed_trades": len(closed_groups),
            "total_scope_groups": len(pnl_result.groups),
        },
        "returns_by_currency": {
            "status": "unavailable",
            "reason": "Return denominator and benchmark policy has not been approved.",
            "values": {currency: None for currency in total_realized.keys()},
        },
        "win_rate": (
            _optional_decimal_to_string(_safe_divide(win_rate * Decimal("100"), Decimal("1")))
            if win_rate is not None
            else None
        ),
        "profit_factor": _optional_decimal_to_string(profit_factor),
        "average_win": _optional_decimal_to_string(avg_win),
        "average_loss": _optional_decimal_to_string(avg_loss),
        "average_holding_days": _optional_decimal_to_string(avg_holding_days),
        "max_drawdown": {
            "status": "unavailable",
            "reason": "Max drawdown is deferred to PNL-07 equity-curve reporting.",
            "value": None,
        },
        "unrealized_pnl_currency_available": not has_unrealized_exposure,
        "breakdowns": breakdowns,
    }

def _build_dataset_quality(
    con: duckdb.DuckDBPyConnection,
    asof: date,
    *,
    unmatched_close_count: int,
    position_count: int,
    unrealized_available: bool,
    current_pnl_run_id: str | None,
    allocated_lifecycle_event_count: int,
) -> dict[str, Any]:
    latest_import = con.execute(
        """
        SELECT import_run_id, source_type, source_path, asof_date, imported_at, row_count, status, notes
        FROM import_runs
        ORDER BY imported_at DESC, import_run_id DESC
        LIMIT 1
        """
    ).fetchone()

    total_fill_rows = con.execute("SELECT COUNT(*) FROM normalized_fills").fetchone()[0]
    requested_fill_rows = con.execute(
        "SELECT COUNT(*) FROM normalized_fills WHERE asof_date <= ?",
        _as_of_filter_params(asof),
    ).fetchone()[0]
    latest_fill_asof = con.execute("SELECT MAX(asof_date) FROM normalized_fills").fetchone()[0]
    lifecycle_event_count = int(
        con.execute(
            "SELECT COUNT(*) FROM normalized_lifecycle_events WHERE asof_date <= ?",
            _as_of_filter_params(asof),
        ).fetchone()[0]
    )
    lifecycle_leg_count = int(
        con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_lifecycle_event_legs l
            JOIN normalized_lifecycle_events e ON e.event_uid = l.event_uid
            WHERE e.asof_date <= ?
            """,
            _as_of_filter_params(asof),
        ).fetchone()[0]
    )
    review_required_lifecycle_leg_count = int(
        con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_lifecycle_event_legs l
            JOIN normalized_lifecycle_events e ON e.event_uid = l.event_uid
            WHERE e.asof_date <= ? AND l.evidence_status = 'review_required'
            """,
            _as_of_filter_params(asof),
        ).fetchone()[0]
    )
    lifecycle_events_without_legs = int(
        con.execute(
            """
            SELECT COUNT(*)
            FROM normalized_lifecycle_events e
            WHERE e.asof_date <= ?
              AND NOT EXISTS (
                  SELECT 1 FROM normalized_lifecycle_event_legs l
                  WHERE l.event_uid = e.event_uid
              )
            """,
            _as_of_filter_params(asof),
        ).fetchone()[0]
    )
    unallocated_lifecycle_event_count = max(
        lifecycle_event_count - allocated_lifecycle_event_count,
        0,
    )

    import_status = "unavailable"
    import_check: dict[str, Any] = {"status": "unavailable", "reason": "no import_runs rows"}
    pnl_status = "valid"
    if unmatched_close_count:
        pnl_status = "incomplete"
    if unallocated_lifecycle_event_count:
        pnl_status = "incomplete"

    if latest_import:
        import_run_id, source_type, source_path, latest_asof, imported_at, row_count, status, notes = latest_import
        source_status = str(status or "").strip().lower()
        import_status = source_status if source_status in VALID_IMPORT_STATUSES else "failed"
        import_check = {
            "status": import_status,
            "source_type": source_type,
            "source_path": source_path,
            "asof": _format_optional_datetime(latest_asof),
            "imported_at": _format_optional_datetime(imported_at),
            "row_count": int(row_count or 0),
            "notes": notes,
        }
        if source_status not in VALID_IMPORT_STATUSES:
            import_status = "failed"
            import_check["reason"] = f"import status '{status}' is not accepted"
        elif total_fill_rows <= 0:
            import_status = "unavailable"
            import_check["reason"] = "normalized_fills is empty"
        elif row_count is None or row_count <= 0:
            import_status = "failed"
            import_check["reason"] = "latest import run has non-positive row_count"
        elif requested_fill_rows <= 0:
            import_status = "incomplete"
            import_check["reason"] = f"no normalized fills for requested asof {asof.isoformat()}"
        else:
            import_check["reason"] = None

    asof_check: dict[str, Any] = {
        "status": "valid",
        "requested_asof": asof.isoformat(),
        "latest_fill_asof": _format_optional_datetime(latest_fill_asof),
        "requested_fill_rows": int(requested_fill_rows),
    }
    if latest_fill_asof is not None and asof > latest_fill_asof:
        asof_check["status"] = "stale"
        asof_check["reason"] = f"requested asof {asof.isoformat()} > latest fill asof {latest_fill_asof}"
    elif requested_fill_rows <= 0:
        asof_check["status"] = "incomplete"
        asof_check["reason"] = f"no normalized fills for requested asof {asof.isoformat()}"
    else:
        asof_check["reason"] = None

    if latest_import is None:
        pnl_status = _max_status(pnl_status, "unavailable")

    overall_status = _max_status(import_status, asof_check["status"], pnl_status)

    pnl_reasons: list[str] = []
    if unmatched_close_count:
        pnl_reasons.append("unmatched close fills were skipped")
    if unallocated_lifecycle_event_count:
        pnl_reasons.append(
            f"{unallocated_lifecycle_event_count} lifecycle event(s) are captured but not economically allocated by a current calculation run"
        )

    return {
        "overall_status": overall_status,
        "checks": {
            "import": import_check,
            "asof": asof_check,
            "pnl": {
                "status": pnl_status,
                "unmatched_close_fill_count": unmatched_close_count,
                "calculation_run_id": current_pnl_run_id,
                "unallocated_lifecycle_event_count": unallocated_lifecycle_event_count,
                "reason": "incomplete: " + "; ".join(pnl_reasons) if pnl_reasons else None,
            },
            "lifecycle_evidence": {
                "status": "incomplete" if unallocated_lifecycle_event_count else "valid",
                "event_count": lifecycle_event_count,
                "allocated_event_count": allocated_lifecycle_event_count,
                "unallocated_event_count": unallocated_lifecycle_event_count,
                "leg_count": lifecycle_leg_count,
                "review_required_leg_count": review_required_lifecycle_leg_count,
                "events_without_legs": lifecycle_events_without_legs,
                "reason": (
                    "Lifecycle events remain outside P&L until approved event-specific allocations are present in a current fingerprint-matched calculation run."
                    if unallocated_lifecycle_event_count
                    else None
                ),
            },
            "positions": {
                "status": _max_status(
                    import_status,
                    asof_check["status"],
                ),
                "position_count": int(position_count),
            },
        },
        "trade_summary_status": {
            "gross_cashflow": _max_status(import_status, asof_check["status"]),
            "commission": _max_status(import_status, asof_check["status"]),
            "fees": _max_status(import_status, asof_check["status"]),
            "realized_pnl_by_currency": _max_status(import_status, asof_check["status"], pnl_status),
            "unrealized_pnl_by_currency": _max_status(
                import_status,
                asof_check["status"],
                pnl_status,
                "valid" if unrealized_available else "unavailable",
            ),
        },
    }


def build_payload(db_path: Path, asof: str) -> dict[str, Any]:
    asof_date = date.fromisoformat(asof)
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        episodes = _rows(con, """
            SELECT
                e.episode_uid, e.source_broker, e.source_account_id, e.primary_symbol, e.asset_class,
                e.strategy_type, e.strategy_label, e.opened_at, e.status, e.fill_count, e.leg_count,
                e.leg_summary, e.cashflow_label, e.net_quantity, e.gross_cashflow, e.commission, e.fees,
                COALESCE(r.review_status, 'unreviewed') AS review_status,
                COALESCE(r.setup_quality, 'unknown') AS setup_quality,
                COALESCE(r.entry_reason, '') AS entry_reason,
                COALESCE(r.notes, '') AS notes
            FROM trade_episodes e
            LEFT JOIN manual_reviews r ON r.episode_uid = e.episode_uid
            ORDER BY e.opened_at DESC, e.episode_uid
        """)

        leg_rows = _rows(con, """
            SELECT episode_uid, leg_index, raw_leg_json
            FROM trade_episode_legs
            ORDER BY episode_uid, leg_index
        """)

        legs_by_episode: dict[str, list[dict[str, Any]]] = {}
        for row in leg_rows:
            raw = row.get("raw_leg_json") or "{}"
            try:
                leg = json.loads(raw)
            except json.JSONDecodeError:
                leg = {"raw_leg_json": raw}
            legs_by_episode.setdefault(str(row["episode_uid"]), []).append(leg)

        payload_episodes = []
        for e in episodes:
            episode_uid = str(e["episode_uid"])
            payload_episodes.append({
                "episode_uid": episode_uid,
                "source_broker": e["source_broker"],
                "source_account_id": e["source_account_id"],
                "primary_symbol": e["primary_symbol"],
                "asset_class": e["asset_class"],
                "strategy_type": e["strategy_type"],
                "strategy_label": e["strategy_label"],
                "review_status": e["review_status"],
                "setup_quality": e["setup_quality"],
                "entry_reason": e["entry_reason"],
                "notes": e["notes"],
                "opened_at": _iso(e["opened_at"]),
                "status": e["status"],
                "fill_count": int(e["fill_count"]),
                "leg_count": int(e["leg_count"]),
                "leg_summary": e["leg_summary"],
                "cashflow_label": e["cashflow_label"],
                "legs": legs_by_episode.get(episode_uid, []),
                "net_quantity": _decimal_to_string(e["net_quantity"]),
                "gross_cashflow": _decimal_to_string(e["gross_cashflow"]),
                "commission": _decimal_to_string(e["commission"]),
                "fees": _decimal_to_string(e["fees"]),
            })

        open_positions = _build_open_positions(con, asof_date)
        portfolio_snapshots = _build_portfolio_snapshots(open_positions)
        normalized_fill_rows = _rows(
            con,
            """
            SELECT * FROM normalized_fills WHERE asof_date <= ?
            ORDER BY source_account_id, source_broker, filled_at
            """,
            _as_of_filter_params(asof_date),
        )
        pnl_fills = _build_fills_for_pnl(normalized_fill_rows)
        preview_pnl_result = calculate_fifo_pnl_from_fills(
            pnl_fills, allow_unmatched_close=True
        )
        approved_events = load_approved_lifecycle_events(con, asof=asof_date)
        persisted_pnl = None
        if all(
            row.get("filled_at_utc") and row.get("fetched_at_utc")
            for row in normalized_fill_rows
        ):
            persisted_pnl = load_current_persisted_pnl_result(
                con,
                asof=asof_date,
                fills=pnl_fills,
                approved_events=approved_events,
            )
        pnl_result = persisted_pnl.result if persisted_pnl else preview_pnl_result
        unmatched_close_fill_count = len(
            set(preview_pnl_result.unmatched_close_fill_uids)
        ) if persisted_pnl is None else 0
        if persisted_pnl is None and preview_pnl_result.unmatched_close_fill_uids:
            print(
                "WARN: unmatched close fills skipped: "
                + ", ".join(sorted(set(preview_pnl_result.unmatched_close_fill_uids)))
            )

        open_episodes = [e for e in payload_episodes if e.get("status") == "open"]
        closed_episodes = [e for e in payload_episodes if e.get("status") == "closed"]
        gross_cashflow = con.execute("SELECT COALESCE(SUM(gross_cashflow), 0) FROM trade_episodes").fetchone()[0]
        commission = con.execute("SELECT COALESCE(SUM(commission), 0) FROM trade_episodes").fetchone()[0]
        fees = con.execute("SELECT COALESCE(SUM(fees), 0) FROM trade_episodes").fetchone()[0]
        performance_breakdowns = _build_performance_breakdowns(
            pnl_fills, pnl_result, payload_episodes
        )
        performance = _build_performance_metrics(
            pnl_fills,
            pnl_result,
            open_positions,
            performance_breakdowns,
        )

        dataset_quality = _build_dataset_quality(
            con,
            asof_date,
            unmatched_close_count=unmatched_close_fill_count,
            position_count=len(open_positions),
            unrealized_available=all(
                value is not None for value in pnl_result.total_unrealized_pnl_by_currency.values()
            ),
            current_pnl_run_id=(
                persisted_pnl.calculation_run_id if persisted_pnl else None
            ),
            allocated_lifecycle_event_count=(
                persisted_pnl.allocated_event_count if persisted_pnl else 0
            ),
        )
        review_queues = build_review_queues(con, asof=asof_date)
        review_queue_items = flatten_review_queues(review_queues)

        return {
            "metadata": {
                "version": DASHBOARD_PAYLOAD_VERSION,
                "asof": asof,
                "generated_at": datetime.now().astimezone().isoformat(),
                "mode": "read_only",
                "auto_trade": "disabled",
                "source": "duckdb",
                "quality": dataset_quality,
                "record_counts": {
                    "trade_episode_previews": len(payload_episodes),
                    "open_trade_episode_previews": len(open_episodes),
                    "closed_trade_episode_previews": len(closed_episodes),
                    "journal_review_queue_items": len(review_queue_items),
                },
                "trade_summary_status": dataset_quality["trade_summary_status"],
            },
            "trade_summary": {
                "gross_cashflow": _decimal_to_string(gross_cashflow),
                "commission": _decimal_to_string(commission),
                "fees": _decimal_to_string(fees),
                "realized_pnl_by_currency": _build_currency_totals(
                    pnl_result.total_realized_pnl_by_currency
                ),
                "unrealized_pnl_by_currency": _build_currency_totals(
                    pnl_result.total_unrealized_pnl_by_currency
                ),
            },
            "performance": performance,
            "open_positions": open_positions,
            "portfolio_snapshots": portfolio_snapshots,
            "recent_trade_episodes": payload_episodes,
            "closed_trade_episodes": closed_episodes,
            "metrics_by_strategy": performance_breakdowns["by_strategy"],
            "risk_events": [],
            "journal_review_queue": review_queue_items,
        }
    finally:
        con.close()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    output_path = Path(args.output)
    payload = build_payload(db_path, args.asof)
    print("===== OneJournal dashboard payload from DB =====")
    print(f"DB        : {db_path}")
    print(f"OUTPUT    : {output_path}")
    print(f"ASOF      : {args.asof}")
    print(f"EPISODES  : {len(payload['recent_trade_episodes'])}")
    print(f"SOURCE    : {payload['metadata']['source']}")
    print("MODE      : read-only")
    print("AUTO TRADE: disabled")
    if args.write:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        print(f"WROTE     : {output_path}")
    print("STATUS    : OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
