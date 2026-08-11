"""Read-only access to versioned OneJournal P&L calculation results.

The repository accepts a persisted run only when its complete fill and approved
lifecycle fingerprints match the current as-of inputs. It never calculates,
mutates journal state, or calls a broker.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from onejournal.brokers.normalized import NormalizedFill
from onejournal.pnl.calculations import (
    ApprovedOptionLifecycleEvent,
    ClosedLotAllocation,
    PnLCalculationResult,
    PnLGroupResult,
    build_fill_input_fingerprint,
    build_lifecycle_input_fingerprint,
)


@dataclass(frozen=True)
class PersistedPnLResult:
    calculation_run_id: str
    result: PnLCalculationResult
    approved_event_count: int
    allocated_event_count: int


def _utc_datetime(value: str, *, field: str) -> datetime:
    if not value:
        raise ValueError(f"{field} is required")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone offset")
    return parsed.astimezone(UTC)


def load_normalized_fills(con: Any, *, asof: date) -> list[NormalizedFill]:
    """Load complete fill evidence through an as-of date using canonical UTC."""

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
        if not row[7] or not row[16]:
            raise ValueError(
                f"fill {row[0]} lacks canonical UTC evidence; legacy timestamp backfill is required"
            )
        fills.append(
            NormalizedFill(
                fill_uid=row[0],
                source_broker=row[1],
                source_account_id=row[2],
                source_fill_id=row[3],
                source_order_id=row[4],
                episode_group_id=row[5],
                asof=row[6],
                filled_at=_utc_datetime(row[7], field="filled_at_utc"),
                asset_class=row[8],
                symbol=row[9],
                side=row[10],
                quantity=row[11],
                fill_price=row[12],
                commission=row[13],
                fees=row[14],
                currency=row[15],
                fetched_at=_utc_datetime(row[16], field="fetched_at_utc"),
                raw_path=row[17],
                option_symbol=row[18],
                underlying_symbol=row[19],
                option_type=row[20],
                expiry=row[21],
                strike=row[22],
                multiplier=row[23],
                open_close=row[24],
                execution_venue=row[25],
                liquidity_flag=row[26],
            )
        )
    return fills


def load_approved_lifecycle_events(
    con: Any,
    *,
    asof: date,
) -> list[ApprovedOptionLifecycleEvent]:
    rows = con.execute(
        """
        SELECT a.event_uid, a.event_type, a.source_broker,
               a.source_account_id, a.currency, a.effective_at_utc,
               a.option_instrument_key, a.predecessor_direction, a.contracts,
               a.event_commission, a.event_fees, a.evidence_status,
               a.successor_action, a.successor_position_effect,
               a.successor_symbol, a.successor_quantity,
               a.strike_cash_amount
        FROM approved_option_lifecycle_events a
        JOIN normalized_lifecycle_events e ON e.event_uid = a.event_uid
        WHERE e.asof_date <= ?
        ORDER BY a.effective_at_utc, a.event_uid
        """,
        (asof,),
    ).fetchall()
    events: list[ApprovedOptionLifecycleEvent] = []
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
        events.append(
            ApprovedOptionLifecycleEvent(
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
        )
    return events


def load_current_persisted_pnl_result(
    con: Any,
    *,
    asof: date,
    fills: list[NormalizedFill],
    approved_events: list[ApprovedOptionLifecycleEvent],
) -> PersistedPnLResult | None:
    fill_fingerprint = build_fill_input_fingerprint(fills)
    event_fingerprint = build_lifecycle_input_fingerprint(approved_events)
    run = con.execute(
        """
        SELECT calculation_run_id, calculation_version, approved_event_count
        FROM pnl_calculation_runs
        WHERE asof_date = ? AND status = 'ok'
          AND input_fill_fingerprint = ?
          AND approved_event_fingerprint = ?
        ORDER BY completed_at_utc DESC, calculation_run_id DESC
        LIMIT 1
        """,
        (asof, fill_fingerprint, event_fingerprint),
    ).fetchone()
    if run is None:
        return None

    run_id, calculation_version, approved_event_count = run
    groups: dict[tuple[str, str, str, str], PnLGroupResult] = {}
    for row in con.execute(
        """
        SELECT source_broker, source_account_id, instrument_key, currency,
               open_quantity, open_cost_basis, realized_pnl, unrealized_pnl
        FROM pnl_group_results
        WHERE calculation_run_id = ?
        ORDER BY source_broker, source_account_id, instrument_key, currency
        """,
        (run_id,),
    ).fetchall():
        scope = (row[0], row[1], row[2], row[3])
        groups[scope] = PnLGroupResult(
            instrument_key=row[2],
            currency=row[3],
            open_quantity=row[4],
            open_cost_basis=row[5],
            realized_pnl=row[6],
            unrealized_pnl=row[7],
        )

    closed_allocations = tuple(
        ClosedLotAllocation(
            scope_key=(row[0], row[1], row[2], row[3]),
            open_fill_uid=row[4],
            close_fill_uid=row[5],
            source_event_uid=row[6],
            direction=row[7],
            quantity=row[8],
            multiplier=row[9],
            open_price=row[10],
            close_price=row[11],
            gross_realized_pnl=row[12],
            allocated_open_commission=row[13],
            allocated_open_fees=row[14],
            allocated_close_commission=row[15],
            allocated_close_fees=row[16],
            realized_pnl=row[17],
            closed_at=_utc_datetime(row[18], field="closed_at_utc"),
        )
        for row in con.execute(
            """
            SELECT source_broker, source_account_id, instrument_key, currency,
                   open_fill_uid, close_fill_uid, source_event_uid, direction,
                   quantity, multiplier, open_price, close_price,
                   gross_realized_pnl, allocated_open_commission,
                   allocated_open_fees, allocated_close_commission,
                   allocated_close_fees, realized_pnl, closed_at_utc
            FROM pnl_closed_lot_allocations
            WHERE calculation_run_id = ?
            ORDER BY allocation_index
            """,
            (run_id,),
        ).fetchall()
    )

    realized_by_currency: dict[str, Decimal] = {}
    unrealized_by_currency: dict[str, Decimal | None] = {}
    for group in groups.values():
        realized_by_currency[group.currency] = (
            realized_by_currency.get(group.currency, Decimal("0"))
            + group.realized_pnl
        )
        prior = unrealized_by_currency.get(group.currency, Decimal("0"))
        if prior is None or group.unrealized_pnl is None:
            unrealized_by_currency[group.currency] = None
        else:
            unrealized_by_currency[group.currency] = prior + group.unrealized_pnl

    return PersistedPnLResult(
        calculation_run_id=run_id,
        approved_event_count=int(approved_event_count),
        allocated_event_count=int(
            con.execute(
                """
                SELECT COUNT(DISTINCT event_uid)
                FROM pnl_lifecycle_allocations
                WHERE calculation_run_id = ?
                """,
                (run_id,),
            ).fetchone()[0]
        ),
        result=PnLCalculationResult(
            calculation_version=calculation_version,
            groups=groups,
            closed_allocations=closed_allocations,
            total_realized_pnl_by_currency=realized_by_currency,
            total_unrealized_pnl_by_currency=unrealized_by_currency,
        ),
    )
