"""Transactional persistence for PNL-03 snapshot and valuation results."""

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
from onejournal.pnl.position_reconciliation import BrokerPositionSnapshot
from onejournal.pnl.position_valuation import PositionValuationRun


REQUIRED_TABLES = {
    "broker_position_snapshot_runs",
    "broker_position_snapshot_records",
    "pnl_position_valuation_runs",
    "pnl_canonical_position_valuations",
}


@dataclass(frozen=True)
class PositionValuationPersistenceResult:
    valuation_run_uid: str
    snapshot_uid: str
    position_count: int
    created: bool
    replayed: bool


@dataclass(frozen=True)
class PositionValuationReadBack:
    valuation_run_uid: str
    snapshot_uid: str
    source_broker: str
    connection_uid: str
    source_account_id: str
    asof: date
    evaluated_at_utc: str
    status: str
    positions: tuple[dict[str, Any], ...]


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
        return {"key": value.key, **{key: _json_value(item) for key, item in asdict(value).items()}}
    if hasattr(value, "__dataclass_fields__"):
        return {key: _json_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _fingerprint(value: Any) -> str:
    payload = json.dumps(_json_value(value), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(payload.encode()).hexdigest()


def _identity_values(identity: InstrumentIdentity) -> tuple[Any, ...]:
    return (
        identity.key, identity.asset_class, identity.market_scope, identity.currency,
        identity.symbol, identity.underlying_symbol, identity.expiry,
        identity.option_right, identity.strike, identity.multiplier,
    )


def _table_names(con: duckdb.DuckDBPyConnection) -> set[str]:
    return {row[0] for row in con.execute("SHOW TABLES").fetchall()}


def persist_position_valuation_run(
    db_path: Path,
    *,
    run: PositionValuationRun,
    broker_snapshot: BrokerPositionSnapshot,
) -> PositionValuationPersistenceResult:
    """Append one exact result or accept an identical replay atomically."""
    if not db_path.exists():
        raise RuntimeError("database does not exist; PNL-03 persistence never creates or migrates it")
    if run.snapshot_uid != broker_snapshot.snapshot_uid:
        raise ValueError("valuation run snapshot_uid does not match snapshot evidence")
    if (run.source_broker, run.connection_uid, run.source_account_id, run.asof) != (
        broker_snapshot.source_broker, broker_snapshot.connection_uid,
        broker_snapshot.source_account_id, broker_snapshot.asof
    ):
        raise ValueError("valuation run scope does not match snapshot evidence")
    snapshot_fingerprint = _fingerprint(broker_snapshot)
    result_fingerprint = _fingerprint(run)
    valid_count = sum(item.status == "valid" for item in run.positions)
    unavailable_count = sum(item.status == "unavailable" for item in run.positions)
    pending_count = sum(item.status == "reconciliation_pending" for item in run.positions)
    if valid_count + unavailable_count + pending_count != len(run.positions):
        raise ValueError("valuation run contains an unsupported position status")
    overall_status = "ok" if valid_count == len(run.positions) else "incomplete"

    con = duckdb.connect(str(db_path))
    try:
        missing = REQUIRED_TABLES - _table_names(con)
        if missing:
            raise RuntimeError(f"database lacks PNL-03 migration 0013 tables: {sorted(missing)}")
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
                    """INSERT INTO broker_position_snapshot_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (broker_snapshot.snapshot_uid, broker_snapshot.source_broker,
                     broker_snapshot.connection_uid, broker_snapshot.source_account_id,
                     broker_snapshot.asof, _utc_text(broker_snapshot.retrieved_at),
                     _utc_text(broker_snapshot.provider_observed_at) if broker_snapshot.provider_observed_at else None,
                     broker_snapshot.account_complete, broker_snapshot.raw_path,
                     broker_snapshot.raw_sha256, broker_snapshot.adapter_version,
                     snapshot_fingerprint, len(broker_snapshot.positions), "accepted"),
                )
                for item in sorted(broker_snapshot.positions, key=lambda row: row.identity.key):
                    con.execute(
                        """INSERT INTO broker_position_snapshot_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (broker_snapshot.snapshot_uid, *_identity_values(item.identity),
                         item.provider_position_id, item.quantity,
                         item.broker_average_cost, item.broker_market_value,
                         item.broker_unrealized_pnl),
                    )

            prior_run = con.execute(
                "SELECT result_fingerprint FROM pnl_position_valuation_runs WHERE valuation_run_uid = ?",
                (run.valuation_run_uid,),
            ).fetchone()
            if prior_run:
                if prior_run[0] != result_fingerprint:
                    raise ValueError("conflicting position valuation replay")
                con.execute("COMMIT")
                return PositionValuationPersistenceResult(
                    run.valuation_run_uid, run.snapshot_uid, len(run.positions), False, True
                )
            con.execute(
                """INSERT INTO pnl_position_valuation_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run.valuation_run_uid, run.snapshot_uid, run.source_broker,
                 run.connection_uid, run.source_account_id, run.asof,
                 _utc_text(run.evaluated_at), run.calculation_version,
                 run.fill_fingerprint, run.lifecycle_fingerprint,
                 run.max_snapshot_age_seconds, result_fingerprint,
                 len(run.positions), valid_count, unavailable_count, pending_count,
                 overall_status),
            )
            for item in run.positions:
                mark = item.mark
                con.execute(
                    """INSERT INTO pnl_canonical_position_valuations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (run.valuation_run_uid, *_identity_values(item.identity),
                     item.legacy_instrument_key, item.direction, item.quantity,
                     item.broker_quantity, item.open_cost_basis,
                     item.reconciliation_status, item.reconciliation_reason,
                     mark.quote_uid if mark else None,
                     mark.freshness_status if mark else None,
                     mark.freshness_age_seconds if mark else None,
                     mark.quote_market_session if mark else None,
                     mark.evaluation_market_session if mark else None,
                     mark.session_authority_uid if mark else None,
                     mark.policy_version if mark else None,
                     mark.selected_field if mark else None,
                     mark.price if mark else None,
                     item.market_value, item.unrealized_pnl,
                     item.status, item.reason),
                )
            observed_count = con.execute(
                "SELECT COUNT(*) FROM pnl_canonical_position_valuations WHERE valuation_run_uid = ?",
                (run.valuation_run_uid,),
            ).fetchone()[0]
            if observed_count != len(run.positions):
                raise RuntimeError("position valuation read-back count mismatch")
            con.execute("COMMIT")
            return PositionValuationPersistenceResult(
                run.valuation_run_uid, run.snapshot_uid, len(run.positions), True, False
            )
        except Exception:
            con.execute("ROLLBACK")
            raise
    finally:
        con.close()


def load_position_valuation_run(
    db_path: Path,
    *,
    valuation_run_uid: str,
) -> PositionValuationReadBack | None:
    """Read back one exact valuation run without latest-run fallback."""
    if not db_path.exists():
        raise RuntimeError("database does not exist")
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        missing = REQUIRED_TABLES - _table_names(con)
        if missing:
            raise RuntimeError(f"database lacks PNL-03 migration 0013 tables: {sorted(missing)}")
        run = con.execute(
            """SELECT snapshot_uid, source_broker, connection_uid,
                      source_account_id, asof_date, evaluated_at_utc,
                      position_count, status
               FROM pnl_position_valuation_runs
               WHERE valuation_run_uid = ?""",
            (valuation_run_uid,),
        ).fetchone()
        if run is None:
            return None
        cursor = con.execute(
            """SELECT instrument_key, direction, canonical_quantity,
                      broker_quantity, open_cost_basis, reconciliation_status,
                      reconciliation_reason, quote_uid, freshness_status,
                      freshness_age_seconds, quote_market_session,
                      evaluation_market_session, session_authority_uid,
                      mark_policy_version, selected_price_field, mark_price,
                      market_value, unrealized_pnl, position_status, status_reason
               FROM pnl_canonical_position_valuations
               WHERE valuation_run_uid = ?
               ORDER BY instrument_key""",
            (valuation_run_uid,),
        )
        names = [item[0] for item in cursor.description]
        positions = tuple(dict(zip(names, row)) for row in cursor.fetchall())
        if len(positions) != int(run[6]):
            raise RuntimeError("persisted position valuation count does not match its run")
        return PositionValuationReadBack(
            valuation_run_uid=valuation_run_uid,
            snapshot_uid=run[0], source_broker=run[1], connection_uid=run[2],
            source_account_id=run[3], asof=run[4], evaluated_at_utc=run[5],
            status=run[7], positions=positions,
        )
    finally:
        con.close()
