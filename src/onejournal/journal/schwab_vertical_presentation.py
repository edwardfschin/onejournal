"""Privacy-safe presentation grouping for exact Schwab vertical orders.

The underlying instrument lifecycles remain authoritative and independent.
This module adds only a display relationship when a filled Schwab opening
order explicitly declares a two-leg vertical and the normalized executions
independently satisfy the vertical geometry.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

import duckdb

from onejournal.journal.domain import current_journal_relation


VERTICAL_PRESENTATION_CONTRACT_VERSION = (
    "onejournal.schwab-vertical-presentation.v1"
)


@dataclass(frozen=True)
class VerticalPresentationMember:
    episode_uid: str
    member_index: int
    role: str
    strike: str
    option_type: str
    expiry: date
    quantity: str
    average_open_price: str
    opening_cash_movement: str
    commission: str
    fees: str


@dataclass(frozen=True)
class VerticalPresentationGroup:
    presentation_group_uid: str
    contract_version: str
    strategy_type: str
    strategy_label: str
    primary_symbol: str
    opened_at: datetime
    expiry: date
    quantity: str
    currency: str
    net_opening_cash_movement: str
    commission: str
    fees: str
    episode_status: str
    source_evidence: str
    members: tuple[VerticalPresentationMember, ...]


@dataclass(frozen=True)
class _OpeningLeg:
    episode_uid: str
    underlying_symbol: str
    option_type: str
    expiry: date
    strike: Decimal
    opening_direction: str
    currency: str
    opened_at: datetime
    episode_status: str
    quantity: Decimal
    weighted_price: Decimal
    opening_cash_movement: Decimal
    commission: Decimal
    fees: Decimal


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." not in text:
        return text
    compact = text.rstrip("0").rstrip(".")
    return compact or "0"


def _json_default(value: object) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"unsupported presentation value: {type(value).__name__}")


def _group_uid(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )
    return "vertical-presentation:" + sha256(canonical.encode("utf-8")).hexdigest()


def _aggregate_opening_legs(rows: list[tuple[Any, ...]]) -> list[_OpeningLeg]:
    grouped: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[1])].append(row)
    legs: list[_OpeningLeg] = []
    for episode_uid, episode_rows in grouped.items():
        first = episode_rows[0]
        stable_terms = {tuple(row[2:10]) for row in episode_rows}
        if len(stable_terms) != 1:
            return []
        quantity = sum((Decimal(str(row[10])) for row in episode_rows), Decimal("0"))
        if quantity <= 0:
            return []
        weighted_price = sum(
            (Decimal(str(row[10])) * Decimal(str(row[11])) for row in episode_rows),
            Decimal("0"),
        ) / quantity
        legs.append(
            _OpeningLeg(
                episode_uid=episode_uid,
                underlying_symbol=str(first[2]),
                option_type=str(first[3]),
                expiry=first[4],
                strike=Decimal(str(first[5])),
                opening_direction=str(first[6]),
                currency=str(first[7]),
                opened_at=first[8],
                episode_status=str(first[9]),
                quantity=quantity,
                weighted_price=weighted_price,
                opening_cash_movement=sum(
                    (Decimal(str(row[12])) for row in episode_rows), Decimal("0")
                ),
                commission=sum(
                    (Decimal(str(row[13])) for row in episode_rows), Decimal("0")
                ),
                fees=sum(
                    (Decimal(str(row[14])) for row in episode_rows), Decimal("0")
                ),
            )
        )
    return legs


def _build_group(rows: list[tuple[Any, ...]]) -> VerticalPresentationGroup | None:
    legs = _aggregate_opening_legs(rows)
    if len(legs) != 2:
        return None
    left, right = legs
    if (
        left.underlying_symbol != right.underlying_symbol
        or left.option_type != right.option_type
        or left.expiry != right.expiry
        or left.strike == right.strike
        or left.currency != right.currency
        or left.quantity != right.quantity
        or {left.opening_direction, right.opening_direction} != {"LONG", "SHORT"}
    ):
        return None

    legs.sort(key=lambda item: (item.opening_direction != "LONG", item.strike))
    net_cash = sum((item.opening_cash_movement for item in legs), Decimal("0"))
    cash_kind = "debit" if net_cash < 0 else "credit" if net_cash > 0 else "net_zero"
    strategy_type = f"{left.option_type.lower()}_{cash_kind}_vertical"
    cash_label = "Net-Zero" if cash_kind == "net_zero" else cash_kind.title()
    strategy_label = f"{left.option_type.title()} {cash_label} Vertical"
    statuses = {item.episode_status for item in legs}
    episode_status = statuses.pop() if len(statuses) == 1 else "review_required"
    identity = {
        "contract_version": VERTICAL_PRESENTATION_CONTRACT_VERSION,
        "episode_uids": sorted(item.episode_uid for item in legs),
        "strategy_type": strategy_type,
    }
    members = tuple(
        VerticalPresentationMember(
            episode_uid=item.episode_uid,
            member_index=index,
            role=item.opening_direction,
            strike=_decimal_text(item.strike),
            option_type=item.option_type,
            expiry=item.expiry,
            quantity=_decimal_text(item.quantity),
            average_open_price=_decimal_text(item.weighted_price),
            opening_cash_movement=_decimal_text(item.opening_cash_movement),
            commission=_decimal_text(item.commission),
            fees=_decimal_text(item.fees),
        )
        for index, item in enumerate(legs, start=1)
    )
    return VerticalPresentationGroup(
        presentation_group_uid=_group_uid(identity),
        contract_version=VERTICAL_PRESENTATION_CONTRACT_VERSION,
        strategy_type=strategy_type,
        strategy_label=strategy_label,
        primary_symbol=left.underlying_symbol,
        opened_at=min(item.opened_at for item in legs),
        expiry=left.expiry,
        quantity=_decimal_text(left.quantity),
        currency=left.currency,
        net_opening_cash_movement=_decimal_text(net_cash),
        commission=_decimal_text(sum((item.commission for item in legs), Decimal("0"))),
        fees=_decimal_text(sum((item.fees for item in legs), Decimal("0"))),
        episode_status=episode_status,
        source_evidence="schwab_filled_vertical_opening_order",
        members=members,
    )


def load_schwab_vertical_presentation_groups(
    db_path: str | Path,
) -> tuple[VerticalPresentationGroup, ...]:
    """Load deterministic, presentation-only vertical groups from journal state."""

    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
        required = {
            "normalized_fills",
            "phase1_journal_materialized_episode_fills",
            "phase1_journal_projected_instruments",
            "phase1_journal_projected_executions",
            "phase1_schwab_evidence_v2_import_families",
            "phase1_journal_episode_lifecycle_states",
            "phase1_journal_lifecycle_reconciliation_runs",
            "trade_episodes",
        }
        if not required.issubset(tables):
            return ()
        materialized_fill_relation = current_journal_relation(
            con, "phase1_journal_materialized_episode_fills"
        )
        projected_instrument_relation = current_journal_relation(
            con, "phase1_journal_projected_instruments"
        )
        projected_execution_relation = current_journal_relation(
            con, "phase1_journal_projected_executions"
        )
        lifecycle_state_relation = current_journal_relation(
            con, "phase1_journal_episode_lifecycle_states"
        )
        lifecycle_run_relation = current_journal_relation(
            con, "phase1_journal_lifecycle_reconciliation_runs"
        )
        episode_relation = current_journal_relation(con, "trade_episodes")
        family = con.execute(
            f"""
            SELECT families.records_json
            FROM {lifecycle_run_relation} runs
            JOIN phase1_schwab_evidence_v2_import_families families
              ON families.assembly_uid = runs.assembly_uid
             AND families.family = 'orders'
            ORDER BY runs.asof_date DESC, runs.reconciled_at DESC,
                     runs.reconciliation_uid DESC
            LIMIT 1
            """
        ).fetchone()
        if family is None:
            return ()
        orders = json.loads(str(family[0]))
        filled_vertical_order_ids = {
            str(order["source_order_id"])
            for order in orders
            if order.get("status") == "FILLED"
            and order.get("complex_strategy_type") == "VERTICAL"
            and int(order.get("leg_count", 0)) == 2
        }
        if not filled_vertical_order_ids:
            return ()
        placeholders = ",".join("?" for _ in filled_vertical_order_ids)
        rows = con.execute(
            f"""
            WITH latest_lifecycle_states AS (
                SELECT states.*, ROW_NUMBER() OVER (
                    PARTITION BY states.episode_uid
                    ORDER BY runs.asof_date DESC, runs.reconciled_at DESC,
                             states.reconciliation_uid DESC
                ) AS rn
                FROM {lifecycle_state_relation} states
                JOIN {lifecycle_run_relation} runs
                  ON runs.reconciliation_uid = states.reconciliation_uid
            )
            SELECT f.source_order_id, x.episode_uid,
                   i.underlying_symbol, i.option_type, i.expiry, i.strike,
                   i.opening_direction, i.currency, e.opened_at,
                   ls.reconciled_status, pe.quantity, pe.fill_price,
                   pe.schwab_net_cash_movement, pe.commission, pe.fees
            FROM normalized_fills f
            JOIN {materialized_fill_relation} x
              ON x.fill_uid = f.fill_uid
            JOIN {projected_execution_relation} pe
              ON pe.fill_uid = f.fill_uid AND pe.episode_uid = x.episode_uid
            JOIN {projected_instrument_relation} i
              ON i.episode_uid = x.episode_uid
             AND i.instrument_uid = pe.instrument_uid
            JOIN {episode_relation} e ON e.episode_uid = x.episode_uid
            JOIN latest_lifecycle_states ls
              ON ls.episode_uid = x.episode_uid AND ls.rn = 1
            WHERE upper(COALESCE(f.open_close, '')) = 'OPEN'
              AND f.source_order_id IN ({placeholders})
              AND i.asset_class = 'option'
            ORDER BY f.source_order_id, x.episode_uid, pe.execution_index
            """,
            sorted(filled_vertical_order_ids),
        ).fetchall()

    rows_by_order: dict[str, list[tuple[Any, ...]]] = defaultdict(list)
    for row in rows:
        rows_by_order[str(row[0])].append(row)
    # More than one filled opening order can scale the same two lifecycle legs.
    # Consolidate those exact repeated pairs before checking membership so one
    # vertical is not duplicated or silently discarded.
    rows_by_pair: dict[tuple[str, str], list[tuple[Any, ...]]] = defaultdict(list)
    for order_rows in rows_by_order.values():
        group = _build_group(order_rows)
        if group is None:
            continue
        pair = tuple(sorted(member.episode_uid for member in group.members))
        rows_by_pair[pair].extend(order_rows)
    candidates = [
        group
        for pair_rows in rows_by_pair.values()
        if (group := _build_group(pair_rows)) is not None
    ]
    membership = Counter(
        member.episode_uid for group in candidates for member in group.members
    )
    safe_groups = [
        group
        for group in candidates
        if all(membership[member.episode_uid] == 1 for member in group.members)
    ]
    return tuple(
        sorted(
            safe_groups,
            key=lambda item: (item.opened_at, item.presentation_group_uid),
            reverse=True,
        )
    )


def presentation_group_to_dict(group: VerticalPresentationGroup) -> dict[str, Any]:
    """Return a serializable privacy-safe group without provider order identity."""

    return asdict(group)
