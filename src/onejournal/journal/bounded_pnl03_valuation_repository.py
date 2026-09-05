"""Durable, exact persistence for the bounded ADR-0022 PNL-03 result."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import duckdb

from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.bounded_valuation import BoundedPnl03ValuationRun
from onejournal.pnl.position_reconciliation import BrokerPositionSnapshot


REQUIRED_TABLES = {
    "broker_position_snapshot_runs",
    "broker_position_snapshot_records",
    "pnl_bounded_valuation_runs",
    "pnl_bounded_position_valuations",
    "pnl_bounded_valuation_subtotals",
}


@dataclass(frozen=True)
class BoundedPnl03PersistenceResult:
    valuation_run_uid: str
    snapshot_uid: str
    position_count: int
    created: bool
    replayed: bool


@dataclass(frozen=True)
class BoundedPnl03ValuationReadBack:
    valuation_run_uid: str
    contract_version: str
    route_version: str
    reconciliation_run_uid: str
    binding_sha256: str
    snapshot_uid: str
    assembly_sha256: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    asof: date
    evaluated_at_utc: str
    calculation_version: str
    fill_fingerprint: str
    quote_evidence_sha256: str
    quote_scope_sha256: str
    max_reconciliation_age_seconds: int
    reconciliation_age_seconds: Decimal
    complete_position_count: int
    eligible_count: int
    valid_mark_count: int
    mark_unavailable_count: int
    unavailable_count: int
    subtotal_status: str
    complete_portfolio_totals_available: bool
    financial_acceptance: bool
    result_fingerprint: str
    final_status: str
    positions: tuple[dict[str, Any], ...]
    subtotals: tuple[dict[str, Any], ...]


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("persisted timestamps must include a timezone")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _utc_text(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, InstrumentIdentity):
        return {
            "key": value.key,
            **{key: _json_value(item) for key, item in asdict(value).items()},
        }
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {
            str(key): _json_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return sha256(payload.encode()).hexdigest()


def calculate_bounded_pnl03_result_fingerprint(
    run: BoundedPnl03ValuationRun,
) -> str:
    """Return the exact digest that persistence and owner acceptance bind."""

    return _fingerprint(run)


def _identity_values(identity: InstrumentIdentity) -> tuple[Any, ...]:
    return (
        identity.key,
        identity.asset_class,
        identity.market_scope,
        identity.currency,
        identity.symbol,
        identity.underlying_symbol,
        identity.expiry,
        identity.option_right,
        identity.strike,
        identity.multiplier,
    )


def _table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def _sum_by_currency(
    positions: tuple[Any, ...], field: str, *, statuses: set[str]
) -> dict[str, Decimal]:
    totals: dict[str, Decimal] = {}
    for item in positions:
        if item.status not in statuses:
            continue
        value = getattr(item, field)
        if value is None:
            raise ValueError(f"{item.status} position lacks {field}")
        currency = item.identity.currency
        totals[currency] = totals.get(currency, Decimal("0")) + value
    return dict(sorted(totals.items()))


def _validate_run(
    run: BoundedPnl03ValuationRun, broker_snapshot: BrokerPositionSnapshot
) -> None:
    if run.snapshot_uid != broker_snapshot.snapshot_uid:
        raise ValueError("bounded valuation snapshot_uid does not match snapshot evidence")
    if (run.source_broker, run.connection_uid, run.source_account_id, run.asof) != (
        broker_snapshot.source_broker,
        broker_snapshot.connection_uid,
        broker_snapshot.source_account_id,
        broker_snapshot.asof,
    ):
        raise ValueError("bounded valuation scope does not match snapshot evidence")
    if not broker_snapshot.account_complete:
        raise ValueError("bounded valuation requires a complete broker snapshot")
    if run.complete_position_count != len(run.positions) or len(
        broker_snapshot.positions
    ) != len(run.positions):
        raise ValueError("bounded valuation position count is inconsistent")
    run_by_identity = {item.identity: item for item in run.positions}
    snapshot_by_identity = {
        item.identity: item for item in broker_snapshot.positions
    }
    if len(run_by_identity) != len(run.positions) or set(run_by_identity) != set(
        snapshot_by_identity
    ):
        raise ValueError("bounded valuation identities do not match the snapshot")
    if any(
        item.broker_quantity != snapshot_by_identity[item.identity].quantity
        for item in run.positions
    ):
        raise ValueError("bounded valuation broker quantity does not match the snapshot")

    valued = [item for item in run.positions if item.status == "valued"]
    mark_unavailable = [
        item for item in run.positions if item.status == "mark_unavailable"
    ]
    unavailable = [item for item in run.positions if item.status == "unavailable"]
    if len(valued) != run.valid_mark_count:
        raise ValueError("bounded valuation valid-mark count is inconsistent")
    if len(mark_unavailable) != run.mark_unavailable_count:
        raise ValueError("bounded valuation unavailable-mark count is inconsistent")
    if len(unavailable) != run.unavailable_count:
        raise ValueError("bounded valuation unavailable-position count is inconsistent")
    if run.eligible_count != len(valued) + len(mark_unavailable):
        raise ValueError("bounded valuation eligible count is inconsistent")
    if run.complete_position_count != run.eligible_count + run.unavailable_count:
        raise ValueError("bounded valuation complete scope is inconsistent")
    if run.complete_portfolio_totals_available or run.financial_acceptance:
        raise ValueError("bounded valuation must not claim portfolio or owner acceptance")
    if (
        run.portfolio_market_value_by_currency is not None
        or run.portfolio_unrealized_pnl_by_currency is not None
    ):
        raise ValueError("bounded valuation must not contain portfolio totals")
    if any(
        item.mark is not None
        or item.canonical_quantity is not None
        or item.open_cost_basis is not None
        or item.market_value is not None
        or item.unrealized_pnl is not None
        for item in unavailable
    ):
        raise ValueError("unavailable positions must not contain financial values")
    if any(
        item.mark is None
        or item.mark.status != "valid"
        or item.mark.identity != item.identity
        or item.canonical_quantity is None
        or item.open_cost_basis is None
        for item in valued
    ):
        raise ValueError("valued positions lack valid bound mark or FIFO lineage")
    if any(
        item.canonical_quantity is None
        or item.open_cost_basis is None
        or item.market_value is not None
        or item.unrealized_pnl is not None
        or (item.mark is not None and item.mark.status != "unavailable")
        for item in mark_unavailable
    ):
        raise ValueError("mark-unavailable positions contain inconsistent values")

    cost_basis = _sum_by_currency(
        run.positions,
        "open_cost_basis",
        statuses={"valued", "mark_unavailable"},
    )
    if cost_basis != dict(run.eligible_cost_basis_subtotal_by_currency):
        raise ValueError("eligible cost-basis subtotal does not match positions")
    if run.final_status == "eligible_valued":
        if mark_unavailable or run.subtotal_status != "eligible_subtotal":
            raise ValueError("eligible-valued status conflicts with position state")
        market_value = _sum_by_currency(
            run.positions, "market_value", statuses={"valued"}
        )
        unrealized = _sum_by_currency(
            run.positions, "unrealized_pnl", statuses={"valued"}
        )
        if market_value != dict(run.eligible_market_value_subtotal_by_currency or {}):
            raise ValueError("eligible market-value subtotal does not match positions")
        if unrealized != dict(
            run.eligible_unrealized_pnl_subtotal_by_currency or {}
        ):
            raise ValueError("eligible unrealized-PNL subtotal does not match positions")
        if set(cost_basis) != set(market_value) or set(cost_basis) != set(unrealized):
            raise ValueError("bounded valuation subtotal currencies differ")
    elif run.final_status == "mark_unavailable":
        if (
            not mark_unavailable
            or run.subtotal_status != "unavailable"
            or run.eligible_market_value_subtotal_by_currency is not None
            or run.eligible_unrealized_pnl_subtotal_by_currency is not None
        ):
            raise ValueError("mark-unavailable status conflicts with subtotal state")
    else:
        raise ValueError("bounded valuation has an unsupported final status")


def persist_bounded_pnl03_valuation_run(
    db_path: Path,
    *,
    run: BoundedPnl03ValuationRun,
    broker_snapshot: BrokerPositionSnapshot,
) -> BoundedPnl03PersistenceResult:
    """Append one exact bounded result or accept an identical replay atomically."""

    if not db_path.exists():
        raise RuntimeError(
            "database does not exist; bounded PNL-03 persistence never creates or migrates it"
        )
    _validate_run(run, broker_snapshot)
    snapshot_fingerprint = _fingerprint(broker_snapshot)
    result_fingerprint = calculate_bounded_pnl03_result_fingerprint(run)
    con = duckdb.connect(str(db_path))
    try:
        missing = REQUIRED_TABLES - _table_names(con)
        if missing:
            raise RuntimeError(
                f"database lacks bounded PNL-03 migration 0014 tables: {sorted(missing)}"
            )
        snapshot_columns = {
            row[1]
            for row in con.execute(
                "PRAGMA table_info(broker_position_snapshot_records)"
            ).fetchall()
        }
        stores_tax_lot_average = (
            "broker_tax_lot_average_price" in snapshot_columns
        )
        con.execute("BEGIN TRANSACTION")
        try:
            prior_snapshot = con.execute(
                "SELECT snapshot_fingerprint FROM broker_position_snapshot_runs WHERE snapshot_uid = ?",
                (broker_snapshot.snapshot_uid,),
            ).fetchone()
            if prior_snapshot and prior_snapshot[0] != snapshot_fingerprint:
                raise ValueError("conflicting broker snapshot replay")
            if prior_snapshot is None:
                con.execute(
                    "INSERT INTO broker_position_snapshot_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        broker_snapshot.snapshot_uid,
                        broker_snapshot.source_broker,
                        broker_snapshot.connection_uid,
                        broker_snapshot.source_account_id,
                        broker_snapshot.asof,
                        _utc_text(broker_snapshot.retrieved_at),
                        _utc_text(broker_snapshot.provider_observed_at)
                        if broker_snapshot.provider_observed_at
                        else None,
                        broker_snapshot.account_complete,
                        broker_snapshot.raw_path,
                        broker_snapshot.raw_sha256,
                        broker_snapshot.adapter_version,
                        snapshot_fingerprint,
                        len(broker_snapshot.positions),
                        "accepted",
                    ),
                )
                for item in sorted(
                    broker_snapshot.positions, key=lambda row: row.identity.key
                ):
                    values = (
                        broker_snapshot.snapshot_uid,
                        *_identity_values(item.identity),
                        item.provider_position_id,
                        item.quantity,
                        item.broker_average_cost,
                        item.broker_market_value,
                        item.broker_unrealized_pnl,
                    )
                    if stores_tax_lot_average:
                        con.execute(
                            """INSERT INTO broker_position_snapshot_records (
                                   snapshot_uid, instrument_key, asset_class,
                                   market_scope, currency, symbol,
                                   underlying_symbol, expiry, option_right,
                                   strike, multiplier, provider_position_id,
                                   quantity, broker_average_cost,
                                   broker_market_value, broker_unrealized_pnl,
                                   broker_tax_lot_average_price
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (*values, item.broker_tax_lot_average_price),
                        )
                    else:
                        con.execute(
                            """INSERT INTO broker_position_snapshot_records (
                                   snapshot_uid, instrument_key, asset_class,
                                   market_scope, currency, symbol,
                                   underlying_symbol, expiry, option_right,
                                   strike, multiplier, provider_position_id,
                                   quantity, broker_average_cost,
                                   broker_market_value, broker_unrealized_pnl
                               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            values,
                        )

            prior_run = con.execute(
                "SELECT result_fingerprint FROM pnl_bounded_valuation_runs WHERE valuation_run_uid = ?",
                (run.run_uid,),
            ).fetchone()
            if prior_run:
                if prior_run[0] != result_fingerprint:
                    raise ValueError("conflicting bounded valuation replay")
                con.execute("COMMIT")
                return BoundedPnl03PersistenceResult(
                    run.run_uid, run.snapshot_uid, len(run.positions), False, True
                )

            con.execute(
                "INSERT INTO pnl_bounded_valuation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_uid,
                    run.contract_version,
                    run.route_version,
                    run.reconciliation_run_uid,
                    run.binding_sha256,
                    run.snapshot_uid,
                    run.assembly_sha256,
                    run.source_broker,
                    run.connection_uid,
                    run.source_account_id,
                    run.asof,
                    _utc_text(run.evaluated_at),
                    run.calculation_version,
                    run.fill_fingerprint,
                    run.quote_evidence_sha256,
                    run.quote_scope_sha256,
                    run.max_reconciliation_age_seconds,
                    run.reconciliation_age_seconds,
                    run.complete_position_count,
                    run.eligible_count,
                    run.valid_mark_count,
                    run.mark_unavailable_count,
                    run.unavailable_count,
                    run.subtotal_status,
                    run.complete_portfolio_totals_available,
                    run.financial_acceptance,
                    result_fingerprint,
                    run.final_status,
                ),
            )
            for item in run.positions:
                mark = item.mark
                con.execute(
                    "INSERT INTO pnl_bounded_position_valuations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run.run_uid,
                        *_identity_values(item.identity),
                        item.coverage_status,
                        item.broker_quantity,
                        item.reconciliation_status,
                        item.canonical_quantity,
                        item.open_cost_basis,
                        mark.quote_uid if mark else None,
                        mark.freshness_status if mark else None,
                        mark.freshness_age_seconds if mark else None,
                        mark.quote_market_session if mark else None,
                        mark.evaluation_market_session if mark else None,
                        mark.session_authority_uid if mark else None,
                        mark.policy_version if mark else None,
                        mark.selected_field if mark else None,
                        mark.price if mark else None,
                        item.market_value,
                        item.unrealized_pnl,
                        item.status,
                        json.dumps(list(item.reason_codes), separators=(",", ":")),
                    ),
                )
            market_values = run.eligible_market_value_subtotal_by_currency or {}
            unrealized_values = (
                run.eligible_unrealized_pnl_subtotal_by_currency or {}
            )
            for currency, cost_basis in sorted(
                run.eligible_cost_basis_subtotal_by_currency.items()
            ):
                con.execute(
                    "INSERT INTO pnl_bounded_valuation_subtotals VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        run.run_uid,
                        currency,
                        cost_basis,
                        market_values.get(currency),
                        unrealized_values.get(currency),
                        run.subtotal_status,
                    ),
                )
            observed = con.execute(
                "SELECT COUNT(*) FROM pnl_bounded_position_valuations WHERE valuation_run_uid = ?",
                (run.run_uid,),
            ).fetchone()[0]
            if observed != len(run.positions):
                raise RuntimeError("bounded valuation read-back count mismatch")
            con.execute("COMMIT")
            return BoundedPnl03PersistenceResult(
                run.run_uid, run.snapshot_uid, len(run.positions), True, False
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def load_bounded_pnl03_valuation_run(
    db_path: Path, *, valuation_run_uid: str
) -> BoundedPnl03ValuationReadBack | None:
    """Read one exact bounded result; never select an implicit latest run."""

    if not db_path.exists():
        raise RuntimeError("database does not exist")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        missing = REQUIRED_TABLES - _table_names(con)
        if missing:
            raise RuntimeError(
                f"database lacks bounded PNL-03 migration 0014 tables: {sorted(missing)}"
            )
        run = con.execute(
            """SELECT contract_version, route_version, reconciliation_run_uid,
                      binding_sha256, snapshot_uid, assembly_sha256, source_broker,
                      connection_uid, source_account_id, asof_date,
                      evaluated_at_utc, calculation_version, fill_fingerprint,
                      quote_evidence_sha256, quote_scope_sha256,
                      max_reconciliation_age_seconds, reconciliation_age_seconds,
                      complete_position_count, eligible_count, valid_mark_count,
                      mark_unavailable_count, unavailable_count, subtotal_status,
                      complete_portfolio_totals_available, financial_acceptance,
                      result_fingerprint, final_status
               FROM pnl_bounded_valuation_runs WHERE valuation_run_uid = ?""",
            (valuation_run_uid,),
        ).fetchone()
        if run is None:
            return None
        cursor = con.execute(
            """SELECT instrument_key, asset_class, market_scope, currency, symbol,
                      underlying_symbol, expiry, option_right, strike, multiplier,
                      coverage_status, broker_quantity, reconciliation_status,
                      canonical_quantity, open_cost_basis, quote_uid,
                      freshness_status, freshness_age_seconds,
                      quote_market_session, evaluation_market_session,
                      session_authority_uid, mark_policy_version,
                      selected_price_field, mark_price, market_value,
                      unrealized_pnl, position_status, reason_codes_json
               FROM pnl_bounded_position_valuations
               WHERE valuation_run_uid = ? ORDER BY instrument_key""",
            (valuation_run_uid,),
        )
        position_names = [item[0] for item in cursor.description]
        positions = tuple(dict(zip(position_names, row)) for row in cursor.fetchall())
        subtotal_cursor = con.execute(
            """SELECT currency, eligible_cost_basis, eligible_market_value,
                      eligible_unrealized_pnl, subtotal_status
               FROM pnl_bounded_valuation_subtotals
               WHERE valuation_run_uid = ? ORDER BY currency""",
            (valuation_run_uid,),
        )
        subtotal_names = [item[0] for item in subtotal_cursor.description]
        subtotals = tuple(
            dict(zip(subtotal_names, row)) for row in subtotal_cursor.fetchall()
        )
        if len(positions) != int(run[17]):
            raise RuntimeError("persisted bounded position count does not match its run")
        if not subtotals:
            raise RuntimeError("persisted bounded valuation has no subtotal rows")
        status_counts = {
            status: sum(row["position_status"] == status for row in positions)
            for status in ("valued", "mark_unavailable", "unavailable")
        }
        if (
            status_counts["valued"] != int(run[19])
            or status_counts["mark_unavailable"] != int(run[20])
            or status_counts["unavailable"] != int(run[21])
            or status_counts["valued"] + status_counts["mark_unavailable"]
            != int(run[18])
        ):
            raise RuntimeError("persisted bounded status counts do not match its run")
        if any(row["subtotal_status"] != run[22] for row in subtotals):
            raise RuntimeError("persisted bounded subtotal status does not match its run")
        return BoundedPnl03ValuationReadBack(
            valuation_run_uid=valuation_run_uid,
            contract_version=run[0],
            route_version=run[1],
            reconciliation_run_uid=run[2],
            binding_sha256=run[3],
            snapshot_uid=run[4],
            assembly_sha256=run[5],
            source_broker=run[6],
            connection_uid=run[7],
            source_account_id=run[8],
            asof=run[9],
            evaluated_at_utc=run[10],
            calculation_version=run[11],
            fill_fingerprint=run[12],
            quote_evidence_sha256=run[13],
            quote_scope_sha256=run[14],
            max_reconciliation_age_seconds=run[15],
            reconciliation_age_seconds=run[16],
            complete_position_count=run[17],
            eligible_count=run[18],
            valid_mark_count=run[19],
            mark_unavailable_count=run[20],
            unavailable_count=run[21],
            subtotal_status=run[22],
            complete_portfolio_totals_available=run[23],
            financial_acceptance=run[24],
            result_fingerprint=run[25],
            final_status=run[26],
            positions=positions,
            subtotals=subtotals,
        )
    finally:
        con.close()
