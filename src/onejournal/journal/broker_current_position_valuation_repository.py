"""Transactional persistence for ADR-0023 broker-current valuations."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Mapping

import duckdb

from onejournal.instruments import InstrumentIdentity
from onejournal.pnl.broker_current_position_valuation import (
    BrokerCurrentPositionValuationRun,
    build_broker_current_position_valuation,
)
from onejournal.pnl.position_reconciliation import BrokerPositionSnapshot


REQUIRED_TABLES = {
    "broker_position_snapshot_runs",
    "broker_position_snapshot_records",
    "pnl_broker_current_valuation_runs",
    "pnl_broker_current_position_valuations",
    "pnl_broker_current_portfolio_totals",
}


@dataclass(frozen=True)
class BrokerCurrentPositionPersistenceResult:
    valuation_run_uid: str
    snapshot_uid: str
    position_count: int
    created: bool
    replayed: bool


@dataclass(frozen=True)
class BrokerCurrentPositionValuationReadBack:
    valuation_run_uid: str
    contract_version: str
    basis_method: str
    snapshot_uid: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    asof: date
    retrieved_at_utc: str
    evaluated_at_utc: str
    max_snapshot_age_seconds: int
    snapshot_age_seconds: Decimal
    currency_quantum_by_currency: Mapping[str, Decimal]
    position_count: int
    cost_basis_available_count: int
    market_value_available_count: int
    unrealized_pnl_available_count: int
    complete_portfolio_cost_basis_available: bool
    complete_portfolio_market_value_available: bool
    complete_portfolio_unrealized_pnl_available: bool
    financial_acceptance: bool
    result_fingerprint: str
    final_status: str
    positions: tuple[dict[str, Any], ...]
    portfolio_totals: tuple[dict[str, Any], ...]


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
    if isinstance(value, Mapping):
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
    return sha256(payload.encode("utf-8")).hexdigest()


def calculate_broker_current_position_result_fingerprint(
    run: BrokerCurrentPositionValuationRun,
) -> str:
    """Return the exact digest persistence and owner acceptance bind."""

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


def _currency_quantum_json(run: BrokerCurrentPositionValuationRun) -> str:
    return json.dumps(
        {
            key: format(value, "f")
            for key, value in sorted(run.currency_quantum_by_currency.items())
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _validate_run(
    run: BrokerCurrentPositionValuationRun,
    broker_snapshot: BrokerPositionSnapshot,
) -> None:
    rebuilt = build_broker_current_position_valuation(
        broker_snapshot=broker_snapshot,
        evaluated_at=run.evaluated_at,
        max_snapshot_age_seconds=run.max_snapshot_age_seconds,
        currency_quantum_by_currency=run.currency_quantum_by_currency,
    )
    if rebuilt != run:
        raise ValueError(
            "broker-current valuation does not exactly replay from snapshot evidence"
        )
    if run.financial_acceptance:
        raise ValueError(
            "calculation rows must not impersonate owner financial acceptance"
        )


def persist_broker_current_position_valuation_run(
    db_path: Path,
    *,
    run: BrokerCurrentPositionValuationRun,
    broker_snapshot: BrokerPositionSnapshot,
) -> BrokerCurrentPositionPersistenceResult:
    """Append one exact result or accept an identical replay atomically."""

    if not db_path.exists():
        raise RuntimeError(
            "database does not exist; broker-current persistence never creates or migrates it"
        )
    _validate_run(run, broker_snapshot)
    snapshot_fingerprint = _fingerprint(broker_snapshot)
    result_fingerprint = calculate_broker_current_position_result_fingerprint(run)
    con = duckdb.connect(str(db_path))
    try:
        missing = REQUIRED_TABLES - _table_names(con)
        if missing:
            raise RuntimeError(
                "database lacks broker-current migration 0015 tables: "
                f"{sorted(missing)}"
            )
        snapshot_columns = {
            row[1]
            for row in con.execute(
                "PRAGMA table_info(broker_position_snapshot_records)"
            ).fetchall()
        }
        if "broker_tax_lot_average_price" not in snapshot_columns:
            raise RuntimeError(
                "database lacks broker-current migration 0015 snapshot column"
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
                    """INSERT INTO broker_position_snapshot_runs
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    con.execute(
                        """INSERT INTO broker_position_snapshot_records (
                               snapshot_uid, instrument_key, asset_class,
                               market_scope, currency, symbol, underlying_symbol,
                               expiry, option_right, strike, multiplier,
                               provider_position_id, quantity, broker_average_cost,
                               broker_market_value, broker_unrealized_pnl,
                               broker_tax_lot_average_price
                           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            broker_snapshot.snapshot_uid,
                            *_identity_values(item.identity),
                            item.provider_position_id,
                            item.quantity,
                            item.broker_average_cost,
                            item.broker_market_value,
                            item.broker_unrealized_pnl,
                            item.broker_tax_lot_average_price,
                        ),
                    )
            else:
                persisted_rows = {
                    row[0]: row[1]
                    for row in con.execute(
                        """SELECT instrument_key, broker_tax_lot_average_price
                           FROM broker_position_snapshot_records
                           WHERE snapshot_uid = ?""",
                        (broker_snapshot.snapshot_uid,),
                    ).fetchall()
                }
                expected_rows = {
                    item.identity.key: item.broker_tax_lot_average_price
                    for item in broker_snapshot.positions
                }
                if set(persisted_rows) != set(expected_rows):
                    raise ValueError(
                        "persisted broker snapshot position scope is incomplete"
                    )
                for instrument_key, expected_average in expected_rows.items():
                    persisted_average = persisted_rows[instrument_key]
                    if persisted_average != expected_average:
                        raise ValueError(
                            "persisted broker snapshot tax-lot basis conflicts"
                        )

            prior_run = con.execute(
                "SELECT result_fingerprint FROM pnl_broker_current_valuation_runs WHERE valuation_run_uid = ?",
                (run.run_uid,),
            ).fetchone()
            if prior_run is not None:
                if prior_run[0] != result_fingerprint:
                    raise ValueError("conflicting broker-current valuation replay")
                con.execute("COMMIT")
                return BrokerCurrentPositionPersistenceResult(
                    run.run_uid, run.snapshot_uid, run.position_count, False, True
                )

            con.execute(
                """INSERT INTO pnl_broker_current_valuation_runs
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_uid,
                    run.contract_version,
                    run.basis_method,
                    run.snapshot_uid,
                    run.source_broker,
                    run.connection_uid,
                    run.source_account_id,
                    run.asof,
                    _utc_text(run.retrieved_at),
                    _utc_text(run.evaluated_at),
                    run.max_snapshot_age_seconds,
                    run.snapshot_age_seconds,
                    _currency_quantum_json(run),
                    run.position_count,
                    run.cost_basis_available_count,
                    run.market_value_available_count,
                    run.unrealized_pnl_available_count,
                    run.complete_portfolio_cost_basis_available,
                    run.complete_portfolio_market_value_available,
                    run.complete_portfolio_unrealized_pnl_available,
                    run.financial_acceptance,
                    result_fingerprint,
                    run.final_status,
                ),
            )
            for item in run.positions:
                con.execute(
                    """INSERT INTO pnl_broker_current_position_valuations
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        run.run_uid,
                        *_identity_values(item.identity),
                        item.quantity,
                        item.tax_lot_average_price,
                        item.open_cost_basis,
                        item.broker_market_value,
                        item.broker_reported_unrealized_pnl,
                        item.unrealized_pnl,
                        item.unrealized_reconciliation_difference,
                        item.cost_basis_status,
                        item.market_value_status,
                        item.unrealized_pnl_status,
                        item.status,
                        json.dumps(list(item.reason_codes), separators=(",", ":")),
                    ),
                )

            currencies = sorted(run.currency_quantum_by_currency)
            for currency in currencies:
                con.execute(
                    """INSERT INTO pnl_broker_current_portfolio_totals
                       VALUES (?, ?, ?, ?, ?)""",
                    (
                        run.run_uid,
                        currency,
                        (run.portfolio_cost_basis_by_currency or {}).get(currency),
                        (run.portfolio_market_value_by_currency or {}).get(currency),
                        (run.portfolio_unrealized_pnl_by_currency or {}).get(currency),
                    ),
                )
            observed = con.execute(
                """SELECT COUNT(*)
                   FROM pnl_broker_current_position_valuations
                   WHERE valuation_run_uid = ?""",
                (run.run_uid,),
            ).fetchone()[0]
            if observed != run.position_count:
                raise RuntimeError("broker-current valuation read-back count mismatch")
            con.execute("COMMIT")
            return BrokerCurrentPositionPersistenceResult(
                run.run_uid, run.snapshot_uid, run.position_count, True, False
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def _load_currency_quantum(value: str) -> dict[str, Decimal]:
    try:
        document = json.loads(value)
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("persisted currency quantum is invalid") from exc
    if not isinstance(document, dict) or not document:
        raise RuntimeError("persisted currency quantum is invalid")
    result: dict[str, Decimal] = {}
    for currency, quantum in document.items():
        if not isinstance(currency, str) or not isinstance(quantum, str):
            raise RuntimeError("persisted currency quantum is invalid")
        parsed = Decimal(quantum)
        if not parsed.is_finite() or parsed <= 0:
            raise RuntimeError("persisted currency quantum is invalid")
        result[currency] = parsed
    canonical = json.dumps(
        {key: format(item, "f") for key, item in sorted(result.items())},
        sort_keys=True,
        separators=(",", ":"),
    )
    if value != canonical:
        raise RuntimeError("persisted currency quantum is not canonical")
    return result


def load_broker_current_position_valuation_run(
    db_path: Path,
    *,
    valuation_run_uid: str,
) -> BrokerCurrentPositionValuationReadBack | None:
    """Read one exact broker-current result without an implicit latest fallback."""

    if not db_path.exists():
        raise RuntimeError("database does not exist")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        missing = REQUIRED_TABLES - _table_names(con)
        if missing:
            raise RuntimeError(
                "database lacks broker-current migration 0015 tables: "
                f"{sorted(missing)}"
            )
        run = con.execute(
            """SELECT contract_version, basis_method, snapshot_uid,
                      source_broker, connection_uid, source_account_id,
                      asof_date, retrieved_at_utc, evaluated_at_utc,
                      max_snapshot_age_seconds, snapshot_age_seconds,
                      currency_quantum_json, position_count,
                      cost_basis_available_count, market_value_available_count,
                      unrealized_pnl_available_count,
                      complete_portfolio_cost_basis_available,
                      complete_portfolio_market_value_available,
                      complete_portfolio_unrealized_pnl_available,
                      financial_acceptance, result_fingerprint, final_status
               FROM pnl_broker_current_valuation_runs
               WHERE valuation_run_uid = ?""",
            (valuation_run_uid,),
        ).fetchone()
        if run is None:
            return None
        cursor = con.execute(
            """SELECT instrument_key, asset_class, market_scope, currency, symbol,
                      underlying_symbol, expiry, option_right, strike, multiplier,
                      quantity, tax_lot_average_price, open_cost_basis,
                      broker_market_value, broker_reported_unrealized_pnl,
                      unrealized_pnl, unrealized_reconciliation_difference,
                      cost_basis_status, market_value_status,
                      unrealized_pnl_status, position_status, reason_codes_json
               FROM pnl_broker_current_position_valuations
               WHERE valuation_run_uid = ? ORDER BY instrument_key""",
            (valuation_run_uid,),
        )
        position_names = [item[0] for item in cursor.description]
        positions = tuple(dict(zip(position_names, row)) for row in cursor.fetchall())
        total_cursor = con.execute(
            """SELECT currency, portfolio_cost_basis, portfolio_market_value,
                      portfolio_unrealized_pnl
               FROM pnl_broker_current_portfolio_totals
               WHERE valuation_run_uid = ? ORDER BY currency""",
            (valuation_run_uid,),
        )
        total_names = [item[0] for item in total_cursor.description]
        totals = tuple(
            dict(zip(total_names, row)) for row in total_cursor.fetchall()
        )
        if len(positions) != int(run[12]):
            raise RuntimeError(
                "persisted broker-current position count does not match its run"
            )
        status_counts = {
            "cost_basis": sum(
                item["cost_basis_status"] == "available" for item in positions
            ),
            "market_value": sum(
                item["market_value_status"] == "available" for item in positions
            ),
            "unrealized_pnl": sum(
                item["unrealized_pnl_status"] == "available" for item in positions
            ),
        }
        if (
            status_counts["cost_basis"] != int(run[13])
            or status_counts["market_value"] != int(run[14])
            or status_counts["unrealized_pnl"] != int(run[15])
        ):
            raise RuntimeError(
                "persisted broker-current availability counts do not match its run"
            )
        currency_quantum = _load_currency_quantum(run[11])
        if {item["currency"] for item in totals} != set(currency_quantum):
            raise RuntimeError(
                "persisted broker-current portfolio currency scope is incomplete"
            )
        return BrokerCurrentPositionValuationReadBack(
            valuation_run_uid=valuation_run_uid,
            contract_version=run[0],
            basis_method=run[1],
            snapshot_uid=run[2],
            source_broker=run[3],
            connection_uid=run[4],
            source_account_id=run[5],
            asof=run[6],
            retrieved_at_utc=run[7],
            evaluated_at_utc=run[8],
            max_snapshot_age_seconds=run[9],
            snapshot_age_seconds=run[10],
            currency_quantum_by_currency=currency_quantum,
            position_count=run[12],
            cost_basis_available_count=run[13],
            market_value_available_count=run[14],
            unrealized_pnl_available_count=run[15],
            complete_portfolio_cost_basis_available=run[16],
            complete_portfolio_market_value_available=run[17],
            complete_portfolio_unrealized_pnl_available=run[18],
            financial_acceptance=run[19],
            result_fingerprint=run[20],
            final_status=run[21],
            positions=positions,
            portfolio_totals=totals,
        )
    finally:
        con.close()
