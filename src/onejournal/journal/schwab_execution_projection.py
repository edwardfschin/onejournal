"""Correct execution-first projection for the private Phase 1 Schwab journal.

The accepted assembly, normalized fills, and migration-0018 materialization are
immutable inputs.  This module adds a versioned read model that distinguishes
broker executions from instruments and trade strategy.  It never calls Schwab,
discovers credentials, or alters the source materialization.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

import duckdb

from onejournal.journal.schwab_evidence_assembly import SchwabPhase1EvidenceAssembly
from onejournal.journal.schwab_evidence_materialization import (
    SchwabJournalMaterializationPlan,
    build_schwab_journal_materialization_plan,
)


EXECUTION_PROJECTION_CONTRACT_VERSION = (
    "onejournal.phase1-journal-execution-projection.v1"
)
MIGRATION_VERSION = "0019"
MIGRATION_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/journal/migrations/0019_add_phase1_execution_projection.sql"
)
REQUIRED_TABLES = {
    "phase1_journal_execution_projection_runs",
    "phase1_journal_projected_episodes",
    "phase1_journal_projected_instruments",
    "phase1_journal_projected_executions",
}
_ACTIVITY_ID = re.compile(r"^schwab_txn:([^:]+):order:")
_BUY_SIDES = {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}
_SELL_SIDES = {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}


@dataclass(frozen=True)
class ProjectedExecution:
    episode_uid: str
    execution_index: int
    execution_uid: str
    fill_uid: str
    instrument_uid: str
    filled_at_utc: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    multiplier: Decimal
    commission: Decimal
    fees: Decimal
    currency: str
    schwab_net_cash_movement: Decimal
    calculated_net_cash_movement: Decimal
    execution_projection_fingerprint: str


@dataclass(frozen=True)
class ProjectedInstrument:
    episode_uid: str
    instrument_index: int
    instrument_uid: str
    asset_class: str
    symbol: str
    underlying_symbol: str | None
    option_type: str | None
    expiry: date | None
    strike: Decimal | None
    multiplier: Decimal | None
    currency: str
    opening_direction: str | None
    execution_count: int
    buy_quantity: Decimal
    sell_quantity: Decimal
    captured_quantity_delta: Decimal
    instrument_projection_fingerprint: str


@dataclass(frozen=True)
class ProjectedEpisode:
    episode_uid: str
    strategy_type: str
    strategy_label: str
    instrument_count: int
    execution_count: int
    lifecycle_sequence: int
    lifecycle_count: int
    instrument_summary: str
    episode_projection_fingerprint: str


@dataclass(frozen=True)
class ExecutionProjectionPlan:
    projection_uid: str
    materialization_uid: str
    result_fingerprint: str
    episodes: tuple[ProjectedEpisode, ...]
    instruments: tuple[ProjectedInstrument, ...]
    executions: tuple[ProjectedExecution, ...]


@dataclass(frozen=True)
class ExecutionProjectionResult:
    projection_uid: str
    materialization_uid: str
    episode_count: int
    instrument_count: int
    execution_count: int
    schwab_net_amount_match_count: int
    schwab_net_amount_mismatch_count: int
    result_fingerprint: str
    created: bool
    replayed: bool


def _json_default(value: object) -> str:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported projection value: {type(value).__name__}")


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _decimal(value: object, field: str) -> Decimal:
    if value is None:
        raise ValueError(f"{field} is required")
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"{field} must be finite")
    return result


def _optional_text(value: object) -> str | None:
    normalized = "" if value is None else str(value).strip()
    return normalized or None


def _db_decimal(value: Decimal | None) -> Decimal | None:
    """Match DuckDB DECIMAL(38,10) before deterministic projection hashing."""

    if value is None:
        return None
    return value.quantize(Decimal("0.0000000001"))


def _utc_text(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("projected execution instant must retain UTC offset evidence")
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _activity_id(source_fill_id: object) -> str:
    match = _ACTIVITY_ID.match(str(source_fill_id))
    if match is None:
        raise ValueError("fill identity is not a Schwab transaction activity")
    return match.group(1)


def _instrument_key(fill: Mapping[str, Any]) -> tuple[str, ...]:
    asset_class = str(fill["asset_class"]).strip().lower()
    currency = str(fill["currency"]).strip().upper()
    symbol = str(fill["symbol"]).strip().upper()
    if asset_class in {"stock", "equity"}:
        return ("equity", symbol, currency)
    if asset_class != "option":
        raise ValueError(f"unsupported projected asset class: {asset_class}")
    option_type = str(fill.get("option_type") or "").strip().upper()
    expiry = fill.get("expiry")
    strike = fill.get("strike")
    multiplier = fill.get("multiplier")
    underlying = str(fill.get("underlying_symbol") or "").strip().upper()
    if not underlying or option_type not in {"CALL", "PUT"}:
        raise ValueError("option execution lacks canonical contract terms")
    if expiry is None or strike is None or multiplier is None:
        raise ValueError("option execution lacks expiry, strike, or multiplier")
    return (
        "option",
        underlying,
        str(expiry),
        format(_decimal(strike, "strike"), "f"),
        option_type,
        format(_decimal(multiplier, "multiplier"), "f"),
        currency,
    )


def _opening_direction(fill: Mapping[str, Any], *, lifecycle_quality: str) -> str | None:
    if lifecycle_quality != "resolved":
        return None
    side = str(fill["side"]).strip().upper()
    if side in _BUY_SIDES:
        return "LONG"
    if side in _SELL_SIDES:
        return "SHORT"
    raise ValueError(f"unsupported execution side: {side}")


def _strategy(
    instruments: list[ProjectedInstrument],
    fills_by_instrument: Mapping[str, list[Mapping[str, Any]]],
    *,
    lifecycle_quality: str,
) -> tuple[str, str]:
    if lifecycle_quality != "resolved":
        return "unknown", "Lifecycle Review Required"
    if len(instruments) == 1:
        instrument = instruments[0]
        direction = instrument.opening_direction
        asset_class = instrument.asset_class.lower()
        if asset_class in {"stock", "equity"}:
            if direction not in {"LONG", "SHORT"}:
                raise ValueError("single-equity strategy lacks a valid opening direction")
            return (
                ("stock_long", "Stock Long")
                if direction == "LONG"
                else ("stock_short", "Stock Short")
            )
        option_type = str(instrument.option_type or "").upper()
        mapping = {
            ("LONG", "CALL"): ("buy_call", "Buy Call"),
            ("LONG", "PUT"): ("buy_put", "Buy Put"),
            ("SHORT", "CALL"): ("sell_call", "Sell Call"),
            ("SHORT", "PUT"): ("sell_put", "Sell Put"),
        }
        if (direction, option_type) not in mapping:
            raise ValueError("single-option strategy lacks a valid opening direction")
        return mapping[(direction, option_type)]

    # A named spread is only safe when distinct contracts were explicitly
    # grouped upstream.  Fill count alone can never create a multi-leg label.
    episode_groups = {
        str(fill.get("episode_group_id") or "").strip()
        for rows in fills_by_instrument.values()
        for fill in rows
    }
    if "" in episode_groups or len(episode_groups) != 1:
        return "multi_instrument_unclassified", "Multi-Instrument Trade"
    if len(instruments) == 2 and all(i.asset_class.lower() == "option" for i in instruments):
        same_family = (
            len({i.underlying_symbol for i in instruments}) == 1
            and len({i.expiry for i in instruments}) == 1
            and len({i.option_type for i in instruments}) == 1
            and len({i.strike for i in instruments}) == 2
            and {i.opening_direction for i in instruments} == {"LONG", "SHORT"}
        )
        if same_family:
            opening_cash = Decimal("0")
            for rows in fills_by_instrument.values():
                for fill in rows:
                    if str(fill.get("open_close") or "").strip().upper() != "OPEN":
                        continue
                    opening_cash += _calculated_net_cash(fill)
            option_type = str(instruments[0].option_type).lower()
            credit_or_debit = "credit" if opening_cash > 0 else "debit"
            return (
                f"{option_type}_{credit_or_debit}_vertical",
                f"{option_type.title()} {credit_or_debit.title()} Vertical",
            )
    return "multi_instrument_unclassified", "Multi-Instrument Trade"


def _calculated_net_cash(fill: Mapping[str, Any]) -> Decimal:
    side = str(fill["side"]).strip().upper()
    quantity = _decimal(fill["quantity"], "quantity")
    price = _decimal(fill["fill_price"], "fill_price")
    multiplier_value = fill.get("multiplier")
    multiplier = (
        Decimal("1")
        if multiplier_value is None
        else _decimal(multiplier_value, "multiplier")
    )
    if quantity <= 0 or multiplier <= 0:
        raise ValueError("execution quantity and multiplier must be positive")
    gross = quantity * price * multiplier
    commission = _decimal(fill["commission"], "commission")
    fees = _decimal(fill["fees"], "fees")
    if side in _SELL_SIDES:
        return gross - commission - fees
    if side in _BUY_SIDES:
        return -gross - commission - fees
    raise ValueError(f"unsupported execution side: {side}")


def _instrument_summary(instruments: list[ProjectedInstrument]) -> str:
    if len(instruments) != 1:
        return f"{len(instruments)} instruments"
    item = instruments[0]
    if item.asset_class.lower() in {"stock", "equity"}:
        return "Equity"
    return " ".join(
        (
            item.expiry.isoformat() if item.expiry else "unknown-expiry",
            format(item.strike, "f") if item.strike is not None else "unknown-strike",
            item.option_type or "OPTION",
        )
    )


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    result = con.execute(sql, params)
    names = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def _database_contract(con: duckdb.DuckDBPyConnection) -> None:
    tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
    missing = REQUIRED_TABLES - tables
    if missing:
        raise ValueError("database is missing migration 0019 table(s): " + ", ".join(sorted(missing)))
    expected = sha256(MIGRATION_PATH.read_bytes()).hexdigest()
    row = con.execute(
        "SELECT migration_name, file_checksum, status FROM schema_migrations WHERE version = ?",
        [MIGRATION_VERSION],
    ).fetchone()
    if row != ("add_phase1_execution_projection", expected, "applied"):
        raise ValueError("database migration 0019 ledger does not match repository")


def build_schwab_execution_projection_plan(
    db_path: str | Path,
    *,
    materialization_uid: str,
) -> ExecutionProjectionPlan:
    """Read one exact stored materialization and build a deterministic plan."""

    with duckdb.connect(str(db_path), read_only=True) as con:
        _database_contract(con)
        run = con.execute(
            """
            SELECT assembly_uid, fill_count, episode_count
            FROM phase1_journal_materialization_runs
            WHERE materialization_uid = ?
            """,
            [materialization_uid],
        ).fetchone()
        if run is None:
            raise ValueError("exact materialization_uid was not found")
        assembly_uid, expected_fill_count, expected_episode_count = run
        transaction_family = con.execute(
            """
            SELECT records_json
            FROM phase1_schwab_evidence_import_families
            WHERE assembly_uid = ? AND family = 'transactions'
            """,
            [assembly_uid],
        ).fetchone()
        if transaction_family is None:
            raise ValueError("exact assembly transaction family was not found")
        transaction_records = json.loads(str(transaction_family[0]))

        fills = _rows(
            con,
            """
            SELECT x.episode_uid, x.leg_index AS stored_leg_index,
                   m.lifecycle_quality, m.scope_uid,
                   f.fill_uid, f.source_fill_id, f.source_order_id,
                   f.episode_group_id, f.filled_at_utc, f.asset_class,
                   f.symbol, f.side, f.quantity, f.fill_price, f.commission,
                   f.fees, f.currency, f.option_symbol, f.underlying_symbol,
                   f.option_type, f.expiry, f.strike, f.multiplier,
                   f.open_close
            FROM phase1_journal_materialized_episode_fills x
            JOIN phase1_journal_materialized_episodes m
              ON m.materialization_uid = x.materialization_uid
             AND m.episode_uid = x.episode_uid
            JOIN normalized_fills f ON f.fill_uid = x.fill_uid
            WHERE x.materialization_uid = ?
            ORDER BY x.episode_uid, f.filled_at_utc, f.fill_uid
            """,
            [materialization_uid],
        )
        episode_rows = _rows(
            con,
            """
            SELECT m.episode_uid, m.scope_uid, m.lifecycle_quality, e.opened_at
            FROM phase1_journal_materialized_episodes m
            JOIN trade_episodes e ON e.episode_uid = m.episode_uid
            WHERE m.materialization_uid = ?
            ORDER BY m.scope_uid, e.opened_at, m.episode_uid
            """,
            [materialization_uid],
        )

    return _build_execution_projection_plan(
        materialization_uid=str(materialization_uid),
        expected_fill_count=int(expected_fill_count),
        expected_episode_count=int(expected_episode_count),
        transaction_records=transaction_records,
        fills=fills,
        episode_rows=episode_rows,
    )


def build_schwab_execution_projection_from_assembly(
    assembly: SchwabPhase1EvidenceAssembly,
    *,
    materialization: SchwabJournalMaterializationPlan | None = None,
) -> ExecutionProjectionPlan:
    """Build the execution projection without writing or reading a database."""

    materialization = materialization or build_schwab_journal_materialization_plan(
        assembly
    )
    fills_by_uid = {fill.fill_uid: fill for fill in materialization.fills}
    fills: list[dict[str, Any]] = []
    episode_rows: list[dict[str, Any]] = []
    for item in materialization.episodes:
        episode_rows.append(
            {
                "episode_uid": item.preview.episode_uid,
                "scope_uid": item.scope_uid,
                "lifecycle_quality": item.lifecycle_quality,
                "opened_at": item.preview.opened_at,
            }
        )
        for leg_index, fill_uid in enumerate(item.fill_uids, start=1):
            fill = fills_by_uid[fill_uid]
            fills.append(
                {
                    "episode_uid": item.preview.episode_uid,
                    "stored_leg_index": leg_index,
                    "lifecycle_quality": item.lifecycle_quality,
                    "scope_uid": item.scope_uid,
                    "fill_uid": fill.fill_uid,
                    "source_fill_id": fill.source_fill_id,
                    "source_order_id": fill.source_order_id,
                    "episode_group_id": fill.episode_group_id,
                    "filled_at_utc": fill.filled_at,
                    "asset_class": fill.asset_class,
                    "symbol": fill.symbol,
                    "side": fill.side,
                    "quantity": _db_decimal(fill.quantity),
                    "fill_price": _db_decimal(fill.fill_price),
                    "commission": _db_decimal(fill.commission),
                    "fees": _db_decimal(fill.fees),
                    "currency": fill.currency,
                    "option_symbol": fill.option_symbol,
                    "underlying_symbol": fill.underlying_symbol,
                    "option_type": fill.option_type,
                    "expiry": fill.expiry,
                    "strike": _db_decimal(fill.strike),
                    "multiplier": _db_decimal(fill.multiplier),
                    "open_close": fill.open_close,
                }
            )
    transaction_records = next(
        family.records
        for family in assembly.families
        if family.family == "transactions"
    )
    return _build_execution_projection_plan(
        materialization_uid=materialization.materialization_uid,
        expected_fill_count=len(materialization.fills),
        expected_episode_count=len(materialization.episodes),
        transaction_records=transaction_records,
        fills=fills,
        episode_rows=episode_rows,
    )


def _build_execution_projection_plan(
    *,
    materialization_uid: str,
    expected_fill_count: int,
    expected_episode_count: int,
    transaction_records: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
    fills: list[dict[str, Any]],
    episode_rows: list[dict[str, Any]],
) -> ExecutionProjectionPlan:
    transactions_by_id: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for record in transaction_records:
        transactions_by_id[str(record["source_transaction_id"])].append(record)

    if len(fills) != expected_fill_count or len(episode_rows) != expected_episode_count:
        raise ValueError("stored materialization counts do not match exact linked rows")
    if len({str(fill["fill_uid"]) for fill in fills}) != len(fills):
        raise ValueError("a materialized fill is linked more than once")

    sequences: dict[str, tuple[int, int]] = {}
    episodes_by_scope: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in episode_rows:
        episodes_by_scope[str(row["scope_uid"])].append(row)
    for rows in episodes_by_scope.values():
        count = len(rows)
        for index, row in enumerate(rows, start=1):
            sequences[str(row["episode_uid"])] = (index, count)

    fills_by_episode: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for fill in fills:
        fills_by_episode[str(fill["episode_uid"])].append(fill)

    projected_episodes: list[ProjectedEpisode] = []
    projected_instruments: list[ProjectedInstrument] = []
    projected_executions: list[ProjectedExecution] = []
    for episode_row in episode_rows:
        episode_uid = str(episode_row["episode_uid"])
        lifecycle_quality = str(episode_row["lifecycle_quality"])
        episode_fills = sorted(
            fills_by_episode[episode_uid],
            key=lambda row: (str(row["filled_at_utc"]), str(row["fill_uid"])),
        )
        by_instrument: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        for fill in episode_fills:
            by_instrument[_instrument_key(fill)].append(fill)

        episode_instruments: list[ProjectedInstrument] = []
        instrument_uid_by_key: dict[tuple[str, ...], str] = {}
        for instrument_index, key in enumerate(sorted(by_instrument), start=1):
            instrument_fills = sorted(
                by_instrument[key],
                key=lambda row: (str(row["filled_at_utc"]), str(row["fill_uid"])),
            )
            first = instrument_fills[0]
            instrument_uid = f"journal-instrument:{_digest((episode_uid, key))}"
            instrument_uid_by_key[key] = instrument_uid
            buy_quantity = sum(
                (_decimal(fill["quantity"], "quantity") for fill in instrument_fills if str(fill["side"]).upper() in _BUY_SIDES),
                Decimal("0"),
            )
            sell_quantity = sum(
                (_decimal(fill["quantity"], "quantity") for fill in instrument_fills if str(fill["side"]).upper() in _SELL_SIDES),
                Decimal("0"),
            )
            if buy_quantity + sell_quantity != sum(
                (_decimal(fill["quantity"], "quantity") for fill in instrument_fills),
                Decimal("0"),
            ):
                raise ValueError("instrument contains an unsupported execution side")
            payload = {
                "episode_uid": episode_uid,
                "instrument_index": instrument_index,
                "instrument_uid": instrument_uid,
                "instrument_key": key,
                "opening_direction": _opening_direction(first, lifecycle_quality=lifecycle_quality),
                "execution_count": len(instrument_fills),
                "buy_quantity": buy_quantity,
                "sell_quantity": sell_quantity,
            }
            projected = ProjectedInstrument(
                episode_uid=episode_uid,
                instrument_index=instrument_index,
                instrument_uid=instrument_uid,
                asset_class=str(first["asset_class"]),
                symbol=str(first["symbol"]),
                underlying_symbol=_optional_text(first.get("underlying_symbol")),
                option_type=_optional_text(first.get("option_type")),
                expiry=first.get("expiry"),
                strike=(None if first.get("strike") is None else _decimal(first["strike"], "strike")),
                multiplier=(None if first.get("multiplier") is None else _decimal(first["multiplier"], "multiplier")),
                currency=str(first["currency"]).upper(),
                opening_direction=payload["opening_direction"],
                execution_count=len(instrument_fills),
                buy_quantity=buy_quantity,
                sell_quantity=sell_quantity,
                captured_quantity_delta=buy_quantity - sell_quantity,
                instrument_projection_fingerprint=_digest(payload),
            )
            episode_instruments.append(projected)
            projected_instruments.append(projected)

        strategy_type, strategy_label = _strategy(
            episode_instruments,
            {instrument_uid_by_key[key]: rows for key, rows in by_instrument.items()},
            lifecycle_quality=lifecycle_quality,
        )
        lifecycle_sequence, lifecycle_count = sequences[episode_uid]
        episode_payload = {
            "episode_uid": episode_uid,
            "strategy_type": strategy_type,
            "strategy_label": strategy_label,
            "instruments": [asdict(item) for item in episode_instruments],
            "execution_fill_uids": [str(fill["fill_uid"]) for fill in episode_fills],
            "lifecycle_sequence": lifecycle_sequence,
            "lifecycle_count": lifecycle_count,
        }
        projected_episodes.append(
            ProjectedEpisode(
                episode_uid=episode_uid,
                strategy_type=strategy_type,
                strategy_label=strategy_label,
                instrument_count=len(episode_instruments),
                execution_count=len(episode_fills),
                lifecycle_sequence=lifecycle_sequence,
                lifecycle_count=lifecycle_count,
                instrument_summary=_instrument_summary(episode_instruments),
                episode_projection_fingerprint=_digest(episode_payload),
            )
        )

        for execution_index, fill in enumerate(episode_fills, start=1):
            source_transaction_id = _activity_id(fill["source_fill_id"])
            matches = transactions_by_id.get(source_transaction_id, [])
            if len(matches) != 1:
                raise ValueError("each projected fill must resolve to one exact Schwab transaction")
            source_net = _decimal(matches[0].get("net_amount"), "Schwab transaction net_amount")
            calculated_net = _calculated_net_cash(fill)
            if source_net != calculated_net:
                raise ValueError("calculated execution cash movement differs from Schwab net_amount")
            key = _instrument_key(fill)
            multiplier = (
                Decimal("1")
                if fill.get("multiplier") is None
                else _decimal(fill["multiplier"], "multiplier")
            )
            execution_payload = {
                "episode_uid": episode_uid,
                "execution_index": execution_index,
                "fill_uid": str(fill["fill_uid"]),
                "instrument_uid": instrument_uid_by_key[key],
                "filled_at_utc": _utc_text(fill["filled_at_utc"]),
                "side": str(fill["side"]).upper(),
                "quantity": _decimal(fill["quantity"], "quantity"),
                "fill_price": _decimal(fill["fill_price"], "fill_price"),
                "multiplier": multiplier,
                "commission": _decimal(fill["commission"], "commission"),
                "fees": _decimal(fill["fees"], "fees"),
                "currency": str(fill["currency"]).upper(),
                "schwab_net_cash_movement": source_net,
                "calculated_net_cash_movement": calculated_net,
            }
            fingerprint = _digest(execution_payload)
            projected_executions.append(
                ProjectedExecution(
                    execution_uid=f"journal-execution:{fingerprint}",
                    execution_projection_fingerprint=fingerprint,
                    **execution_payload,
                )
            )

    projected_episodes.sort(key=lambda item: item.episode_uid)
    projected_instruments.sort(key=lambda item: (item.episode_uid, item.instrument_index))
    projected_executions.sort(key=lambda item: (item.episode_uid, item.execution_index))
    result_payload = {
        "contract_version": EXECUTION_PROJECTION_CONTRACT_VERSION,
        "materialization_uid": materialization_uid,
        "episodes": [asdict(item) for item in projected_episodes],
        "instruments": [asdict(item) for item in projected_instruments],
        "executions": [asdict(item) for item in projected_executions],
    }
    fingerprint = _digest(result_payload)
    return ExecutionProjectionPlan(
        projection_uid=f"schwab-execution-projection:{fingerprint}",
        materialization_uid=materialization_uid,
        result_fingerprint=fingerprint,
        episodes=tuple(projected_episodes),
        instruments=tuple(projected_instruments),
        executions=tuple(projected_executions),
    )


def _result(plan: ExecutionProjectionPlan, *, created: bool, replayed: bool) -> ExecutionProjectionResult:
    return ExecutionProjectionResult(
        projection_uid=plan.projection_uid,
        materialization_uid=plan.materialization_uid,
        episode_count=len(plan.episodes),
        instrument_count=len(plan.instruments),
        execution_count=len(plan.executions),
        schwab_net_amount_match_count=len(plan.executions),
        schwab_net_amount_mismatch_count=0,
        result_fingerprint=plan.result_fingerprint,
        created=created,
        replayed=replayed,
    )


def _verify_readback(con: duckdb.DuckDBPyConnection, plan: ExecutionProjectionPlan) -> None:
    run = con.execute(
        """
        SELECT projection_uid, contract_version, materialization_uid,
               episode_count, instrument_count, execution_count,
               schwab_net_amount_match_count, schwab_net_amount_mismatch_count,
               result_fingerprint
        FROM phase1_journal_execution_projection_runs
        WHERE projection_uid = ?
        """,
        [plan.projection_uid],
    ).fetchone()
    expected_run = (
        plan.projection_uid,
        EXECUTION_PROJECTION_CONTRACT_VERSION,
        plan.materialization_uid,
        len(plan.episodes),
        len(plan.instruments),
        len(plan.executions),
        len(plan.executions),
        0,
        plan.result_fingerprint,
    )
    if run != expected_run:
        raise ValueError("stored execution projection run differs from exact plan")
    episode_rows = con.execute(
        """
        SELECT episode_uid, strategy_type, strategy_label, instrument_count,
               execution_count, lifecycle_sequence, lifecycle_count,
               instrument_summary, episode_projection_fingerprint
        FROM phase1_journal_projected_episodes WHERE projection_uid = ?
        ORDER BY episode_uid
        """,
        [plan.projection_uid],
    ).fetchall()
    expected_episodes = [
        (
            item.episode_uid, item.strategy_type, item.strategy_label,
            item.instrument_count, item.execution_count,
            item.lifecycle_sequence, item.lifecycle_count,
            item.instrument_summary, item.episode_projection_fingerprint,
        )
        for item in plan.episodes
    ]
    if episode_rows != expected_episodes:
        raise ValueError("stored projected episodes differ from exact plan")
    instrument_rows = con.execute(
        """
        SELECT episode_uid, instrument_index, instrument_uid, asset_class,
               symbol, underlying_symbol, option_type, expiry, strike,
               multiplier, currency, opening_direction, execution_count,
               buy_quantity, sell_quantity, captured_quantity_delta,
               instrument_projection_fingerprint
        FROM phase1_journal_projected_instruments WHERE projection_uid = ?
        ORDER BY episode_uid, instrument_index
        """,
        [plan.projection_uid],
    ).fetchall()
    expected_instruments = [
        tuple(asdict(item).values()) for item in plan.instruments
    ]
    if instrument_rows != expected_instruments:
        raise ValueError("stored projected instruments differ from exact plan")
    execution_rows = con.execute(
        """
        SELECT episode_uid, execution_index, execution_uid, fill_uid,
               instrument_uid, filled_at_utc, side, quantity, fill_price,
               multiplier, commission, fees, currency,
               schwab_net_cash_movement, calculated_net_cash_movement,
               execution_projection_fingerprint
        FROM phase1_journal_projected_executions WHERE projection_uid = ?
        ORDER BY episode_uid, execution_index
        """,
        [plan.projection_uid],
    ).fetchall()
    expected_executions = [tuple(asdict(item).values()) for item in plan.executions]
    if execution_rows != expected_executions:
        raise ValueError("stored projected executions differ from exact plan")


def persist_schwab_execution_projection(
    db_path: str | Path,
    *,
    materialization_uid: str,
    projected_at: datetime | None = None,
) -> ExecutionProjectionResult:
    """Atomically persist or exactly replay one corrected projection."""

    plan = build_schwab_execution_projection_plan(
        db_path,
        materialization_uid=materialization_uid,
    )
    timestamp = projected_at or datetime.now(UTC)
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("projected_at must include a timezone")
    timestamp_naive = timestamp.astimezone(UTC).replace(tzinfo=None)
    with duckdb.connect(str(db_path)) as con:
        _database_contract(con)
        existing = con.execute(
            """
            SELECT projection_uid FROM phase1_journal_execution_projection_runs
            WHERE materialization_uid = ?
            """,
            [materialization_uid],
        ).fetchone()
        if existing is not None:
            if str(existing[0]) != plan.projection_uid:
                raise ValueError("stored projection identity differs from exact plan")
            _verify_readback(con, plan)
            return _result(plan, created=False, replayed=True)

        con.execute("BEGIN TRANSACTION")
        try:
            con.execute(
                """
                INSERT INTO phase1_journal_execution_projection_runs (
                    projection_uid, contract_version, materialization_uid,
                    episode_count, instrument_count, execution_count,
                    schwab_net_amount_match_count,
                    schwab_net_amount_mismatch_count, result_fingerprint,
                    projected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                [
                    plan.projection_uid, EXECUTION_PROJECTION_CONTRACT_VERSION,
                    plan.materialization_uid, len(plan.episodes),
                    len(plan.instruments), len(plan.executions),
                    len(plan.executions), plan.result_fingerprint,
                    timestamp_naive,
                ],
            )
            con.executemany(
                """
                INSERT INTO phase1_journal_projected_episodes (
                    projection_uid, episode_uid, strategy_type, strategy_label,
                    instrument_count, execution_count, lifecycle_sequence,
                    lifecycle_count, instrument_summary,
                    episode_projection_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        plan.projection_uid, item.episode_uid,
                        item.strategy_type, item.strategy_label,
                        item.instrument_count, item.execution_count,
                        item.lifecycle_sequence, item.lifecycle_count,
                        item.instrument_summary,
                        item.episode_projection_fingerprint,
                    )
                    for item in plan.episodes
                ],
            )
            con.executemany(
                """
                INSERT INTO phase1_journal_projected_instruments (
                    projection_uid, episode_uid, instrument_index,
                    instrument_uid, asset_class, symbol, underlying_symbol,
                    option_type, expiry, strike, multiplier, currency,
                    opening_direction, execution_count, buy_quantity,
                    sell_quantity, captured_quantity_delta,
                    instrument_projection_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (plan.projection_uid, *tuple(asdict(item).values()))
                    for item in plan.instruments
                ],
            )
            con.executemany(
                """
                INSERT INTO phase1_journal_projected_executions (
                    projection_uid, episode_uid, execution_index,
                    execution_uid, fill_uid, instrument_uid, filled_at_utc,
                    side, quantity, fill_price, multiplier, commission, fees,
                    currency, schwab_net_cash_movement,
                    calculated_net_cash_movement, net_amount_reconciled,
                    execution_projection_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, TRUE, ?)
                """,
                [
                    (plan.projection_uid, *tuple(asdict(item).values()))
                    for item in plan.executions
                ],
            )
            _verify_readback(con, plan)
            con.execute("COMMIT")
        except Exception:
            con.execute("ROLLBACK")
            raise
    return _result(plan, created=True, replayed=False)


def privacy_safe_projection_audit(result: ExecutionProjectionResult) -> dict[str, object]:
    return {
        "contract_version": EXECUTION_PROJECTION_CONTRACT_VERSION,
        "operation": "replayed" if result.replayed else "projected",
        "projection_uid": result.projection_uid,
        "materialization_uid": result.materialization_uid,
        "episode_count": result.episode_count,
        "instrument_count": result.instrument_count,
        "execution_count": result.execution_count,
        "schwab_net_amount_match_count": result.schwab_net_amount_match_count,
        "schwab_net_amount_mismatch_count": result.schwab_net_amount_mismatch_count,
        "result_fingerprint": result.result_fingerprint,
    }
