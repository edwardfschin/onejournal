"""Privacy-safe lifecycle stories derived from exact Schwab evidence.

The journal remains execution- and instrument-authoritative.  This module only
adds a read model that makes opening/closing phases visible and links a uniquely
matched option settlement to its resulting stock execution.  It never changes
episode state, calculates P&L, or exposes provider identities.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

import duckdb

from onejournal.journal.domain import current_journal_relation


LIFECYCLE_PRESENTATION_CONTRACT_VERSION = (
    "onejournal.schwab-lifecycle-presentation.v1"
)
_OPTION_SYMBOL = re.compile(
    r"^(?P<root>.+?)(?P<date>\d{6})(?P<right>[CP])(?P<strike>\d{8})$"
)
_BUY_SIDES = {"BUY", "BUY_TO_OPEN", "BUY_TO_CLOSE"}
_SELL_SIDES = {"SELL", "SELL_TO_OPEN", "SELL_TO_CLOSE"}


@dataclass(frozen=True)
class LifecyclePhasePresentation:
    phase: str
    instruction: str
    occurred_at: datetime
    quantity: str
    average_fill_price: str
    cash_movement: str
    commission: str
    fees: str
    currency: str
    execution_count: int


@dataclass(frozen=True)
class OptionStockSettlementPresentation:
    settlement_uid: str
    settlement_kind: str
    settled_at: datetime
    option_quantity: str
    stock_symbol: str
    stock_quantity: str
    stock_price: str
    currency: str
    stock_episode_uid: str
    stock_execution_uid: str
    evidence_quality: str
    source_evidence: str


@dataclass(frozen=True)
class OptionExpirationPresentation:
    expiration_uid: str
    outcome_kind: str
    expires_on: date
    posted_at: datetime
    option_quantity: str
    evidence_quality: str
    source_evidence: str


@dataclass(frozen=True)
class LifecyclePresentation:
    episode_uid: str
    contract_version: str
    primary_symbol: str
    asset_class: str
    strategy_type: str
    strategy_label: str
    option_type: str | None
    expiry: date | None
    strike: str | None
    opening_direction: str | None
    episode_status: str
    history_completeness: str
    phases: tuple[LifecyclePhasePresentation, ...]
    option_stock_settlements: tuple[OptionStockSettlementPresentation, ...]
    option_expirations: tuple[OptionExpirationPresentation, ...]


@dataclass(frozen=True)
class _Execution:
    episode_uid: str
    instrument_uid: str
    source_account_id: str
    primary_symbol: str
    asset_class: str
    strategy_type: str
    strategy_label: str
    option_type: str | None
    expiry: date | None
    strike: Decimal | None
    multiplier: Decimal | None
    opening_direction: str | None
    episode_status: str
    lifecycle_quality: str
    lifecycle_reason: str | None
    position_reconciliation_status: str
    matched_terminal_event_count: int
    opened_at: datetime
    execution_uid: str
    filled_at: datetime
    side: str
    open_close: str
    quantity: Decimal
    fill_price: Decimal
    cash_movement: Decimal
    commission: Decimal
    fees: Decimal
    currency: str


@dataclass(frozen=True)
class _EquitySettlement:
    source_account_id: str
    occurred_at: datetime
    symbol: str
    signed_quantity: Decimal
    price: Decimal
    position_effect: str


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." not in text:
        return text
    compact = text.rstrip("0").rstrip(".")
    return compact or "0"


def _utc(value: object) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        str(value).replace("Z", "+00:00").replace("+0000", "+00:00")
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _trade_side(value: str) -> str:
    side = value.strip().upper()
    if side in _BUY_SIDES:
        return "BUY"
    if side in _SELL_SIDES:
        return "SELL"
    raise ValueError("Schwab lifecycle presentation found an unsupported side")


def _instruction(side: str, open_close: str) -> str:
    effect = open_close.strip().upper()
    if effect not in {"OPEN", "CLOSE"}:
        raise ValueError("Schwab lifecycle presentation requires open/close evidence")
    return f"{_trade_side(side)}_TO_{effect}"


def _option_key(symbol: str) -> tuple[str, date, Decimal, str] | None:
    compact = "".join(symbol.strip().upper().split())
    match = _OPTION_SYMBOL.fullmatch(compact)
    if match is None:
        return None
    raw_date = match.group("date")
    try:
        expiry = date(
            2000 + int(raw_date[0:2]),
            int(raw_date[2:4]),
            int(raw_date[4:6]),
        )
    except ValueError:
        return None
    strike = Decimal(match.group("strike")) / Decimal("1000")
    return (
        match.group("root").upper(),
        expiry,
        strike,
        "CALL" if match.group("right") == "C" else "PUT",
    )


def _phase(rows: list[_Execution], phase_name: str) -> LifecyclePhasePresentation:
    instructions = {_instruction(row.side, row.open_close) for row in rows}
    currencies = {row.currency for row in rows}
    if len(instructions) != 1 or len(currencies) != 1:
        raise ValueError("Schwab lifecycle phase is internally inconsistent")
    quantity = sum((row.quantity for row in rows), Decimal("0"))
    if quantity <= 0:
        raise ValueError("Schwab lifecycle phase quantity must be positive")
    average_price = sum(
        (row.quantity * row.fill_price for row in rows), Decimal("0")
    ) / quantity
    occurred_at = (
        min(row.filled_at for row in rows)
        if phase_name == "opening"
        else max(row.filled_at for row in rows)
    )
    return LifecyclePhasePresentation(
        phase=phase_name,
        instruction=instructions.pop(),
        occurred_at=occurred_at,
        quantity=_decimal_text(quantity),
        average_fill_price=_decimal_text(average_price),
        cash_movement=_decimal_text(
            sum((row.cash_movement for row in rows), Decimal("0"))
        ),
        commission=_decimal_text(sum((row.commission for row in rows), Decimal("0"))),
        fees=_decimal_text(sum((row.fees for row in rows), Decimal("0"))),
        currency=currencies.pop(),
        execution_count=len(rows),
    )


def _presentation(rows: list[_Execution]) -> LifecyclePresentation | None:
    instruments = {row.instrument_uid for row in rows}
    stable = {
        (
            row.primary_symbol,
            row.asset_class,
            row.strategy_type,
            row.strategy_label,
            row.option_type,
            row.expiry,
            row.strike,
            row.opening_direction,
            row.episode_status,
        )
        for row in rows
    }
    if len(instruments) != 1 or len(stable) != 1:
        return None
    by_phase: dict[str, list[_Execution]] = defaultdict(list)
    for row in rows:
        effect = row.open_close.strip().upper()
        if effect == "OPEN":
            by_phase["opening"].append(row)
        elif effect == "CLOSE":
            by_phase["closing"].append(row)
        else:
            return None
    try:
        phases = tuple(
            _phase(by_phase[name], name)
            for name in ("opening", "closing")
            if by_phase[name]
        )
    except ValueError:
        return None
    first = rows[0]
    history_completeness = "complete"
    strategy_type = first.strategy_type
    strategy_label = first.strategy_label
    if (
        not by_phase.get("opening")
        and bool(by_phase.get("closing"))
        and first.lifecycle_reason == "history_extension_required"
        and first.asset_class == "option"
        and first.option_type in {"CALL", "PUT"}
    ):
        closing_instructions = {
            phase.instruction for phase in phases if phase.phase == "closing"
        }
        if closing_instructions == {"SELL_TO_CLOSE"}:
            direction_label = "Buy"
            direction_type = "buy"
        elif closing_instructions == {"BUY_TO_CLOSE"}:
            direction_label = "Sell"
            direction_type = "sell"
        else:
            return None
        history_completeness = "opening_history_missing"
        strategy_type = f"{direction_type}_{first.option_type.lower()}"
        strategy_label = f"{direction_label} {first.option_type.title()}"
    return LifecyclePresentation(
        episode_uid=first.episode_uid,
        contract_version=LIFECYCLE_PRESENTATION_CONTRACT_VERSION,
        primary_symbol=first.primary_symbol,
        asset_class=first.asset_class,
        strategy_type=strategy_type,
        strategy_label=strategy_label,
        option_type=first.option_type,
        expiry=first.expiry,
        strike=_decimal_text(first.strike) if first.strike is not None else None,
        opening_direction=first.opening_direction,
        episode_status=first.episode_status,
        history_completeness=history_completeness,
        phases=phases,
        option_stock_settlements=(),
        option_expirations=(),
    )


def _settlement_uid(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=lambda value: value.isoformat()
        if isinstance(value, (date, datetime))
        else str(value),
    )
    return "option-stock-settlement:" + sha256(canonical.encode("utf-8")).hexdigest()


def _latest_family_records(
    con: duckdb.DuckDBPyConnection,
    family: str,
) -> list[dict[str, Any]]:
    lifecycle_run_relation = current_journal_relation(
        con, "phase1_journal_lifecycle_reconciliation_runs"
    )
    row = con.execute(
        f"""
        SELECT families.records_json
        FROM {lifecycle_run_relation} runs
        JOIN phase1_schwab_evidence_v2_import_families families
          ON families.assembly_uid = runs.assembly_uid
         AND families.family = ?
        ORDER BY runs.asof_date DESC, runs.reconciled_at DESC,
                 runs.reconciliation_uid DESC
        LIMIT 1
        """,
        [family],
    ).fetchone()
    if row is None:
        return []
    records = json.loads(str(row[0]))
    return records if isinstance(records, list) else []


def _latest_transaction_family(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    return _latest_family_records(con, "transactions")


def _equity_settlements(
    transactions: list[dict[str, Any]],
) -> list[_EquitySettlement]:
    candidates: list[_EquitySettlement] = []
    for transaction in transactions:
        if str(transaction.get("transaction_type", "")).upper() != "TRADE":
            continue
        for item in transaction.get("items", []):
            if not isinstance(item, dict):
                continue
            position_effect = str(item.get("position_effect", "")).upper()
            if (
                str(item.get("provider_asset_type", "")).upper()
                not in {"EQUITY", "STOCK"}
                or position_effect not in {"OPENING", "CLOSING"}
            ):
                continue
            candidates.append(
                _EquitySettlement(
                    source_account_id=str(transaction.get("source_account_id", "")),
                    occurred_at=_utc(transaction.get("transaction_at_utc")),
                    symbol=str(item.get("provider_symbol", "")).strip().upper(),
                    signed_quantity=Decimal(str(item.get("amount"))),
                    price=Decimal(str(item.get("price"))),
                    position_effect=position_effect,
                )
            )
    return candidates


def _residual_at(
    rows: list[_Execution],
    settled_at: datetime,
    terminal_allocated: Decimal,
) -> Decimal:
    residual = terminal_allocated
    for row in rows:
        if row.filled_at > settled_at:
            continue
        residual += row.quantity if _trade_side(row.side) == "BUY" else -row.quantity
    return residual


def _settlement_kind_and_sign(direction: str, option_type: str) -> tuple[str, int]:
    if direction == "SHORT":
        return "assignment", 1 if option_type == "PUT" else -1
    if direction == "LONG":
        return "exercise", 1 if option_type == "CALL" else -1
    raise ValueError("option settlement lacks a resolved opening direction")


def _derive_option_stock_settlements(
    transactions: list[dict[str, Any]],
    rows_by_episode: dict[str, list[_Execution]],
) -> dict[str, list[OptionStockSettlementPresentation]]:
    option_episodes: dict[tuple[str, date, Decimal, str], list[str]] = defaultdict(list)
    stock_executions: list[_Execution] = []
    for episode_uid, rows in rows_by_episode.items():
        first = rows[0]
        if (
            first.asset_class == "option"
            and first.expiry is not None
            and first.strike is not None
            and first.option_type is not None
        ):
            option_episodes[
                (first.primary_symbol, first.expiry, first.strike, first.option_type)
            ].append(episode_uid)
        elif first.asset_class in {"stock", "equity"}:
            stock_executions.extend(rows)
    for episode_uids in option_episodes.values():
        episode_uids.sort(
            key=lambda uid: (rows_by_episode[uid][0].opened_at, uid)
        )

    equity_candidates = _equity_settlements(transactions)
    terminal_allocated: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    outcomes: dict[str, list[OptionStockSettlementPresentation]] = defaultdict(list)
    receive_transactions = sorted(
        (
            transaction
            for transaction in transactions
            if str(transaction.get("transaction_type", "")).upper()
            == "RECEIVE_AND_DELIVER"
        ),
        key=lambda transaction: str(transaction.get("transaction_at_utc", "")),
    )
    for transaction in receive_transactions:
        option_items = [
            item
            for item in transaction.get("items", [])
            if isinstance(item, dict)
            and str(item.get("provider_asset_type", "")).upper() == "OPTION"
            and str(item.get("position_effect", "")).upper() == "CLOSING"
        ]
        if len(option_items) != 1:
            continue
        item = option_items[0]
        option_key = _option_key(str(item.get("provider_symbol", "")))
        if option_key is None:
            continue
        event_quantity = Decimal(str(item.get("amount")))
        if event_quantity == 0:
            continue
        settled_at = _utc(transaction.get("transaction_at_utc"))
        account_id = str(transaction.get("source_account_id", ""))
        eligible: list[tuple[str, Decimal]] = []
        for episode_uid in option_episodes.get(option_key, []):
            episode_rows = rows_by_episode[episode_uid]
            if episode_rows[0].source_account_id != account_id:
                continue
            residual = _residual_at(
                episode_rows, settled_at, terminal_allocated[episode_uid]
            )
            if residual and residual * event_quantity < 0:
                eligible.append((episode_uid, residual))
        if not eligible:
            continue
        directions = {rows_by_episode[uid][0].opening_direction for uid, _ in eligible}
        multipliers = {rows_by_episode[uid][0].multiplier for uid, _ in eligible}
        if None in directions or None in multipliers or len(directions) != 1 or len(multipliers) != 1:
            continue
        direction = str(next(iter(directions)))
        multiplier = next(iter(multipliers))
        if multiplier is None or multiplier <= 0:
            continue
        settlement_kind, stock_sign = _settlement_kind_and_sign(
            direction, option_key[3]
        )
        expected_stock_quantity = (
            abs(event_quantity) * multiplier * Decimal(stock_sign)
        )
        matching_equity = [
            candidate
            for candidate in equity_candidates
            if candidate.source_account_id == account_id
            and candidate.occurred_at == settled_at
            and candidate.symbol == option_key[0]
            and candidate.signed_quantity == expected_stock_quantity
            and candidate.price == option_key[2]
        ]
        if len(matching_equity) != 1:
            continue
        matching_stock_pairs = [
            (candidate, row)
            for candidate in matching_equity
            for row in stock_executions
            if row.source_account_id == account_id
            and row.filled_at == settled_at
            and row.primary_symbol == option_key[0]
            and row.open_close.upper()
            == {"OPENING": "OPEN", "CLOSING": "CLOSE"}[
                candidate.position_effect
            ]
            and row.fill_price == option_key[2]
            and (
                row.quantity
                if _trade_side(row.side) == "BUY"
                else -row.quantity
            )
            == expected_stock_quantity
        ]
        if len(matching_stock_pairs) != 1:
            continue
        _, stock_execution = matching_stock_pairs[0]

        remaining = event_quantity
        allocations: list[tuple[str, Decimal]] = []
        for episode_uid, residual in eligible:
            matched = min(abs(residual), abs(remaining))
            signed = matched if remaining > 0 else -matched
            allocations.append((episode_uid, signed))
            remaining -= signed
            if remaining == 0:
                break
        if remaining != 0:
            continue
        for episode_uid, signed_option_quantity in allocations:
            terminal_allocated[episode_uid] += signed_option_quantity
            allocated_stock_quantity = (
                abs(signed_option_quantity) * multiplier * Decimal(stock_sign)
            )
            identity = {
                "contract_version": LIFECYCLE_PRESENTATION_CONTRACT_VERSION,
                "episode_uid": episode_uid,
                "stock_execution_uid": stock_execution.execution_uid,
                "settled_at": settled_at,
                "settlement_kind": settlement_kind,
                "option_quantity": _decimal_text(abs(signed_option_quantity)),
            }
            outcomes[episode_uid].append(
                OptionStockSettlementPresentation(
                    settlement_uid=_settlement_uid(identity),
                    settlement_kind=settlement_kind,
                    settled_at=settled_at,
                    option_quantity=_decimal_text(abs(signed_option_quantity)),
                    stock_symbol=stock_execution.primary_symbol,
                    stock_quantity=_decimal_text(allocated_stock_quantity),
                    stock_price=_decimal_text(stock_execution.fill_price),
                    currency=stock_execution.currency,
                    stock_episode_uid=stock_execution.episode_uid,
                    stock_execution_uid=stock_execution.execution_uid,
                    evidence_quality="exact_structured_match",
                    source_evidence="schwab_unique_option_stock_settlement",
                )
            )
    return outcomes


def _expiration_key(leg: dict[str, Any]) -> tuple[str, date, Decimal, str] | None:
    try:
        return (
            str(leg.get("underlying_symbol") or leg.get("symbol") or "")
            .strip()
            .upper(),
            date.fromisoformat(str(leg.get("expiry", ""))),
            Decimal(str(leg.get("strike", ""))),
            str(leg.get("option_type", "")).strip().upper(),
        )
    except (ValueError, ArithmeticError):
        return None


def _derive_option_expirations(
    events: list[dict[str, Any]],
    legs: list[dict[str, Any]],
    rows_by_episode: dict[str, list[_Execution]],
    stock_settlements: dict[str, list[OptionStockSettlementPresentation]],
) -> dict[str, list[OptionExpirationPresentation]]:
    """Allocate exact Schwab expiration hints without promoting their authority."""

    expiration_events = {
        str(event.get("event_uid", "")): event
        for event in events
        if str(event.get("event_name", "")).strip().upper()
        == "DESCRIPTION_HINT:EXPIRATION"
        and str(event.get("event_class", "")).strip().upper()
        == "TRANSACTION_LIFECYCLE"
    }
    option_episodes: dict[tuple[str, date, Decimal, str], list[str]] = defaultdict(
        list
    )
    for episode_uid, rows in rows_by_episode.items():
        first = rows[0]
        if (
            first.asset_class == "option"
            and first.expiry is not None
            and first.strike is not None
            and first.option_type is not None
        ):
            option_episodes[
                (first.primary_symbol, first.expiry, first.strike, first.option_type)
            ].append(episode_uid)
    for episode_uids in option_episodes.values():
        episode_uids.sort(key=lambda uid: (rows_by_episode[uid][0].opened_at, uid))

    terminal_allocated: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    outcomes: dict[str, list[OptionExpirationPresentation]] = defaultdict(list)
    candidates = sorted(
        (
            (expiration_events[str(leg.get("event_uid", ""))], leg)
            for leg in legs
            if str(leg.get("event_uid", "")) in expiration_events
            and str(leg.get("leg_kind", "")).strip().lower() == "security"
            and str(leg.get("asset_class", "")).strip().lower() == "option"
            and str(leg.get("position_effect", "")).strip().upper() == "CLOSING"
            and str(leg.get("evidence_status", "")).strip().lower()
            == "review_required"
        ),
        key=lambda item: (
            str(item[0].get("event_at", "")),
            str(item[1].get("event_uid", "")),
            int(str(item[1].get("leg_index", "0"))),
        ),
    )
    for event, leg in candidates:
        key = _expiration_key(leg)
        if key is None or not all((key[0], key[3])):
            continue
        posted_at = _utc(event.get("event_at"))
        if posted_at.date() < key[1]:
            continue
        event_quantity = Decimal(str(leg.get("signed_quantity", "0")))
        if event_quantity == 0:
            continue
        account_id = str(event.get("source_account_id", ""))
        eligible: list[tuple[str, Decimal]] = []
        for episode_uid in option_episodes.get(key, []):
            rows = rows_by_episode[episode_uid]
            first = rows[0]
            if (
                first.source_account_id != account_id
                or first.episode_status != "closed"
                or first.lifecycle_quality != "review_required"
                or first.lifecycle_reason != "broker_terminal_event_review_required"
                or first.position_reconciliation_status != "terminal_reconciled"
                or first.matched_terminal_event_count < 1
                or stock_settlements.get(episode_uid)
            ):
                continue
            residual = _residual_at(
                rows, posted_at, terminal_allocated[episode_uid]
            )
            if residual and residual * event_quantity < 0:
                eligible.append((episode_uid, residual))
        if not eligible:
            continue

        remaining = event_quantity
        allocations: list[tuple[str, Decimal]] = []
        for episode_uid, residual in eligible:
            matched = min(abs(residual), abs(remaining))
            signed = matched if remaining > 0 else -matched
            allocations.append((episode_uid, signed))
            remaining -= signed
            if remaining == 0:
                break
        if remaining != 0:
            continue
        for episode_uid, signed_quantity in allocations:
            terminal_allocated[episode_uid] += signed_quantity
            identity = {
                "contract_version": LIFECYCLE_PRESENTATION_CONTRACT_VERSION,
                "episode_uid": episode_uid,
                "expires_on": key[1],
                "posted_at": posted_at,
                "option_quantity": _decimal_text(abs(signed_quantity)),
                "outcome_kind": "expiration_indicated",
            }
            outcomes[episode_uid].append(
                OptionExpirationPresentation(
                    expiration_uid=_settlement_uid(identity).replace(
                        "option-stock-settlement:", "option-expiration:"
                    ),
                    outcome_kind="expiration_indicated",
                    expires_on=key[1],
                    posted_at=posted_at,
                    option_quantity=_decimal_text(abs(signed_quantity)),
                    evidence_quality="review_required",
                    source_evidence=(
                        "schwab_receive_and_deliver_expiration_description_hint"
                    ),
                )
            )
    return outcomes


def load_schwab_lifecycle_presentations(
    db_path: str | Path,
) -> tuple[LifecyclePresentation, ...]:
    """Load compact lifecycle stories without changing journal state."""

    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
        required = {
            "normalized_fills",
            "phase1_journal_projected_episodes",
            "phase1_journal_projected_instruments",
            "phase1_journal_projected_executions",
            "phase1_journal_episode_lifecycle_states",
            "phase1_journal_lifecycle_reconciliation_runs",
            "phase1_schwab_evidence_v2_import_families",
            "trade_episodes",
        }
        if not required.issubset(tables):
            return ()
        projected_episode_relation = current_journal_relation(
            con, "phase1_journal_projected_episodes"
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
        result = con.execute(
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
            SELECT x.episode_uid, i.instrument_uid, f.source_account_id,
                   e.primary_symbol, i.asset_class, p.strategy_type,
                   p.strategy_label, i.option_type, i.expiry, i.strike,
                   i.multiplier, i.opening_direction, ls.reconciled_status,
                   ls.lifecycle_quality, ls.reason_code,
                   ls.position_reconciliation_status,
                   ls.matched_terminal_event_count,
                   e.opened_at, x.execution_uid, x.filled_at_utc, x.side,
                   f.open_close, x.quantity, x.fill_price,
                   x.schwab_net_cash_movement, x.commission, x.fees, x.currency
            FROM {projected_execution_relation} x
            JOIN normalized_fills f ON f.fill_uid = x.fill_uid
            JOIN {projected_instrument_relation} i
              ON i.projection_uid = x.projection_uid
             AND i.episode_uid = x.episode_uid
             AND i.instrument_uid = x.instrument_uid
            JOIN {projected_episode_relation} p
              ON p.projection_uid = x.projection_uid
             AND p.episode_uid = x.episode_uid
            JOIN {episode_relation} e ON e.episode_uid = x.episode_uid
            JOIN latest_lifecycle_states ls
              ON ls.episode_uid = x.episode_uid AND ls.rn = 1
            ORDER BY e.opened_at, x.episode_uid, x.execution_index
            """
        )
        names = [column[0] for column in result.description]
        raw_rows = [dict(zip(names, row)) for row in result.fetchall()]
        transactions = _latest_transaction_family(con)
        lifecycle_events = _latest_family_records(con, "lifecycle_events")
        lifecycle_event_legs = _latest_family_records(
            con, "lifecycle_event_legs"
        )

    rows_by_episode: dict[str, list[_Execution]] = defaultdict(list)
    for row in raw_rows:
        execution = _Execution(
            episode_uid=str(row["episode_uid"]),
            instrument_uid=str(row["instrument_uid"]),
            source_account_id=str(row["source_account_id"]),
            primary_symbol=str(row["primary_symbol"]),
            asset_class=str(row["asset_class"]).lower(),
            strategy_type=str(row["strategy_type"]),
            strategy_label=str(row["strategy_label"]),
            option_type=str(row["option_type"]) if row["option_type"] else None,
            expiry=row["expiry"],
            strike=Decimal(str(row["strike"])) if row["strike"] is not None else None,
            multiplier=(
                Decimal(str(row["multiplier"]))
                if row["multiplier"] is not None
                else None
            ),
            opening_direction=(
                str(row["opening_direction"]) if row["opening_direction"] else None
            ),
            episode_status=str(row["reconciled_status"]),
            lifecycle_quality=str(row["lifecycle_quality"]),
            lifecycle_reason=(
                str(row["reason_code"]) if row["reason_code"] else None
            ),
            position_reconciliation_status=str(
                row["position_reconciliation_status"]
            ),
            matched_terminal_event_count=int(row["matched_terminal_event_count"]),
            opened_at=_utc(row["opened_at"]),
            execution_uid=str(row["execution_uid"]),
            filled_at=_utc(row["filled_at_utc"]),
            side=str(row["side"]),
            open_close=str(row["open_close"]),
            quantity=Decimal(str(row["quantity"])),
            fill_price=Decimal(str(row["fill_price"])),
            cash_movement=Decimal(str(row["schwab_net_cash_movement"])),
            commission=Decimal(str(row["commission"])),
            fees=Decimal(str(row["fees"])),
            currency=str(row["currency"]),
        )
        rows_by_episode[execution.episode_uid].append(execution)

    presentations = {
        episode_uid: presentation
        for episode_uid, rows in rows_by_episode.items()
        if (presentation := _presentation(rows)) is not None
    }
    settlements = _derive_option_stock_settlements(transactions, rows_by_episode)
    expirations = _derive_option_expirations(
        lifecycle_events,
        lifecycle_event_legs,
        rows_by_episode,
        settlements,
    )
    for episode_uid, outcomes in settlements.items():
        if episode_uid not in presentations:
            continue
        presentations[episode_uid] = replace(
            presentations[episode_uid],
            option_stock_settlements=tuple(
                sorted(outcomes, key=lambda item: (item.settled_at, item.settlement_uid))
            ),
        )
    for episode_uid, outcomes in expirations.items():
        if episode_uid not in presentations:
            continue
        presentations[episode_uid] = replace(
            presentations[episode_uid],
            option_expirations=tuple(
                sorted(outcomes, key=lambda item: (item.expires_on, item.posted_at))
            ),
        )
    return tuple(
        sorted(
            presentations.values(),
            key=lambda item: (
                rows_by_episode[item.episode_uid][0].opened_at,
                item.episode_uid,
            ),
            reverse=True,
        )
    )


def lifecycle_presentation_to_dict(
    presentation: LifecyclePresentation,
) -> dict[str, Any]:
    """Return a serializable presentation without broker/account identities."""

    return asdict(presentation)
