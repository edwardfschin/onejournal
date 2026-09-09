"""Bounded realized-P&L calculation for one exact active history revision set.

The calculator is read-only.  It admits only FIFO allocations whose opening and
closing evidence both belong to resolved active-revision episodes.  Unresolved
episodes remain explicit value-free omissions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import duckdb

from onejournal.journal.pnl_repository import (
    load_approved_lifecycle_events,
    load_normalized_fills,
)
from onejournal.journal.phase1_reporting_repository import (
    RealizedHistoryItem,
    ReportingOmission,
)
from onejournal.pnl import (
    FIFO_CALCULATION_VERSION,
    OPTION_LIFECYCLE_CALCULATION_VERSION,
    build_fill_input_fingerprint,
    build_lifecycle_input_fingerprint,
    calculate_fifo_pnl_with_lifecycle_events,
)


REALIZED_RESULT_CONTRACT_VERSION = "onejournal.phase1-realized-result.v1"
REALIZED_CALCULATION_VERSION = (
    f"{FIFO_CALCULATION_VERSION}+{OPTION_LIFECYCLE_CALCULATION_VERSION}"
    "+active-history-v1"
)
NEW_YORK = ZoneInfo("America/New_York")


class Phase1RealizedCalculationError(ValueError):
    """Raised when the active history cannot produce bounded report authority."""


@dataclass(frozen=True)
class ActiveHistoryAuthority:
    revision_uid: str
    result_fingerprint: str
    source_broker: str
    source_account_id: str
    history_window_start: date
    history_window_end: date
    asof_date: date
    fill_count: int
    episode_count: int
    execution_count: int
    lifecycle_resolved_scope_count: int
    review_required_scope_count: int
    closed_count: int
    open_count: int
    review_required_count: int
    lifecycle_final_status: str


@dataclass(frozen=True)
class RealizedAllocationResult:
    item_uid: str
    source_broker: str
    source_account_id: str
    instrument_key: str
    symbol: str
    asset_class: Literal["equity", "option"]
    close_market_date: date
    closed_at_utc: datetime
    currency: str
    realized_pnl: Decimal
    direction: str
    quantity: Decimal
    multiplier: Decimal
    open_fill_uid: str
    close_fill_uid: str | None
    source_event_uid: str | None


@dataclass(frozen=True)
class RealizedScopeOmission:
    omission_uid: str
    source_broker: str
    source_account_id: str
    episode_uid: str
    close_market_date: date
    symbol: str | None
    reason_code: str
    source_fill_uids: tuple[str, ...]


@dataclass(frozen=True)
class BoundedRealizedResult:
    calculation_run_id: str
    calculation_version: str
    calculated_at_utc: datetime
    coverage_start_date: date
    coverage_end_date: date
    authorities: tuple[ActiveHistoryAuthority, ...]
    fill_input_fingerprint: str
    lifecycle_input_fingerprint: str
    items: tuple[RealizedAllocationResult, ...]
    omissions: tuple[RealizedScopeOmission, ...]
    result_fingerprint: str

    @property
    def quality(self) -> Literal["valid", "incomplete"]:
        return "incomplete" if self.omissions else "valid"

    @property
    def reason_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for omission in self.omissions:
            counts[omission.reason_code] = counts.get(omission.reason_code, 0) + 1
        return counts


@dataclass(frozen=True)
class RealizedResultAuthorization:
    calculation_run_id: str
    result_fingerprint: str
    history_revision_uids: tuple[str, ...]
    owner_acceptance_uid: str
    accepted_at_utc: datetime


@dataclass(frozen=True)
class _EpisodeScope:
    revision_uid: str
    episode_uid: str
    source_broker: str
    source_account_id: str
    scope_uid: str
    primary_symbol: str
    lifecycle_quality: str
    materialization_lifecycle_quality: str
    reconciled_status: str
    reason_code: str | None
    materialization_reason_code: str | None
    position_reconciliation_status: str

    @property
    def resolved(self) -> bool:
        return (
            self.lifecycle_quality == "resolved"
            and self.materialization_lifecycle_quality == "resolved"
            and self.reconciled_status in {"open", "closed"}
            and self.position_reconciliation_status
            in {"matched_current", "terminal_reconciled", "not_applicable"}
        )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise Phase1RealizedCalculationError("calculation timestamps must include a timezone")
    return value.astimezone(UTC)


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        text = format(value, "f")
        text = text.rstrip("0").rstrip(".") if "." in text else text
        return "0" if text in {"", "-0"} else text
    if isinstance(value, datetime):
        return _utc(value).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _canonical(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _digest(value: Any) -> str:
    return sha256(
        json.dumps(_canonical(value), sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _required_tables(con: duckdb.DuckDBPyConnection) -> None:
    required = {
        "normalized_fills",
        "normalized_lifecycle_events",
        "normalized_lifecycle_event_legs",
        "approved_option_lifecycle_events",
        "approved_option_lifecycle_predecessors",
        "approved_option_lifecycle_source_legs",
        "phase1_journal_history_revisions",
        "phase1_journal_history_revision_episodes",
        "phase1_journal_history_revision_episode_fills",
        "phase1_journal_history_revision_executions",
        "phase1_journal_current_revision_ids",
    }
    missing = sorted(required - {row[0] for row in con.execute("SHOW TABLES").fetchall()})
    if missing:
        raise Phase1RealizedCalculationError(
            f"database lacks active-history reporting tables: {missing}"
        )


def _load_authorities(
    con: duckdb.DuckDBPyConnection,
) -> tuple[ActiveHistoryAuthority, ...]:
    rows = con.execute(
        """
        SELECT r.revision_uid, r.result_fingerprint, r.source_broker,
               r.source_account_id, r.history_window_start,
               r.history_window_end, r.asof_date, r.fill_count,
               r.episode_count, r.execution_count,
               r.lifecycle_resolved_scope_count,
               r.review_required_scope_count, r.closed_count,
               r.open_count, r.review_required_count,
               r.lifecycle_final_status
        FROM phase1_journal_current_revision_ids c
        JOIN phase1_journal_history_revisions r USING (revision_uid)
        ORDER BY r.source_broker, r.source_account_id
        """
    ).fetchall()
    if not rows:
        raise Phase1RealizedCalculationError("no active history revision is available")
    authorities = tuple(ActiveHistoryAuthority(*row) for row in rows)
    if len({(x.source_broker, x.source_account_id) for x in authorities}) != len(
        authorities
    ):
        raise Phase1RealizedCalculationError("active history contains duplicate account authority")
    if len({x.revision_uid for x in authorities}) != len(authorities):
        raise Phase1RealizedCalculationError("active history reuses a revision identity")
    if any(
        not x.revision_uid
        or len(x.result_fingerprint) != 64
        or set(x.result_fingerprint) - set("0123456789abcdef")
        or not x.history_window_start <= x.history_window_end <= x.asof_date
        for x in authorities
    ):
        raise Phase1RealizedCalculationError("active history authority is invalid")
    return authorities


def _load_episode_scopes(
    con: duckdb.DuckDBPyConnection,
) -> tuple[dict[tuple[str, str], _EpisodeScope], dict[str, tuple[str, str]]]:
    rows = con.execute(
        """
        SELECT e.revision_uid, e.episode_uid, e.source_broker,
               e.source_account_id, e.scope_uid, e.primary_symbol,
               e.lifecycle_quality,
               e.materialization_lifecycle_quality, e.reconciled_status,
               e.reason_code, e.materialization_reason_code,
               e.position_reconciliation_status
        FROM phase1_journal_history_revision_episodes e
        JOIN phase1_journal_current_revision_ids c USING (revision_uid)
        ORDER BY e.revision_uid, e.episode_uid
        """
    ).fetchall()
    scopes = {(row[0], row[1]): _EpisodeScope(*row) for row in rows}
    if len(scopes) != len(rows):
        raise Phase1RealizedCalculationError(
            "active history contains duplicate episode scope"
        )
    fill_rows = con.execute(
        """
        SELECT f.revision_uid, f.episode_uid, f.fill_uid
        FROM phase1_journal_history_revision_episode_fills f
        JOIN phase1_journal_current_revision_ids c USING (revision_uid)
        ORDER BY f.revision_uid, f.episode_uid, f.leg_index
        """
    ).fetchall()
    fill_episode: dict[str, tuple[str, str]] = {}
    for revision_uid, episode_uid, fill_uid in fill_rows:
        if fill_uid in fill_episode:
            raise Phase1RealizedCalculationError("active history reuses a fill across episodes")
        if (revision_uid, episode_uid) not in scopes:
            raise Phase1RealizedCalculationError("active history fill has no episode scope")
        fill_episode[fill_uid] = (revision_uid, episode_uid)
    if not fill_episode:
        raise Phase1RealizedCalculationError("active history contains no fills")
    if set(scopes) != set(fill_episode.values()):
        raise Phase1RealizedCalculationError(
            "active history episode and fill coverage do not match"
        )
    return scopes, fill_episode


def _omission_reason(scope: _EpisodeScope) -> str:
    reasons = " ".join(
        value
        for value in (scope.reason_code, scope.materialization_reason_code)
        if value
    ).lower()
    if "history" in reasons:
        return "opening_history_missing"
    if scope.position_reconciliation_status in {"mismatch", "absent_current"}:
        return "position_reconciliation_incomplete"
    return "lifecycle_review_required"


def _validate_active_history(
    con: duckdb.DuckDBPyConnection,
    *,
    authorities: tuple[ActiveHistoryAuthority, ...],
    scopes: dict[tuple[str, str], _EpisodeScope],
    fill_episode: dict[str, tuple[str, str]],
) -> None:
    authority_by_revision = {item.revision_uid: item for item in authorities}
    for key, scope in scopes.items():
        authority = authority_by_revision.get(scope.revision_uid)
        if (
            authority is None
            or key[0] != scope.revision_uid
            or (scope.source_broker, scope.source_account_id)
            != (authority.source_broker, authority.source_account_id)
        ):
            raise Phase1RealizedCalculationError(
                "active history episode is outside its revision authority"
            )

    execution_rows = con.execute(
        """
        SELECT x.revision_uid, x.episode_uid, x.fill_uid,
               x.net_amount_reconciled
        FROM phase1_journal_history_revision_executions x
        JOIN phase1_journal_current_revision_ids c USING (revision_uid)
        ORDER BY x.revision_uid, x.episode_uid, x.fill_uid
        """
    ).fetchall()
    if any(row[3] is not True for row in execution_rows):
        raise Phase1RealizedCalculationError(
            "active history contains unreconciled execution economics"
        )
    execution_fill_episode: dict[str, tuple[str, str]] = {}
    for revision_uid, episode_uid, fill_uid, _ in execution_rows:
        if fill_uid in execution_fill_episode:
            raise Phase1RealizedCalculationError(
                "active history reuses a fill across executions"
            )
        execution_fill_episode[fill_uid] = (revision_uid, episode_uid)
    if execution_fill_episode != fill_episode:
        raise Phase1RealizedCalculationError(
            "active history execution and fill identity do not match"
        )

    for authority in authorities:
        revision_scopes = [
            scope
            for (revision_uid, _), scope in scopes.items()
            if revision_uid == authority.revision_uid
        ]
        revision_fill_count = sum(
            revision_uid == authority.revision_uid
            for revision_uid, _ in fill_episode.values()
        )
        revision_execution_count = sum(
            revision_uid == authority.revision_uid
            for revision_uid, _ in execution_fill_episode.values()
        )
        actual = (
            revision_fill_count,
            len(revision_scopes),
            revision_execution_count,
            len(
                {
                    scope.scope_uid
                    for scope in revision_scopes
                    if scope.materialization_lifecycle_quality == "resolved"
                }
            ),
            len(
                {
                    scope.scope_uid
                    for scope in revision_scopes
                    if scope.materialization_lifecycle_quality == "review_required"
                }
            ),
            sum(scope.reconciled_status == "closed" for scope in revision_scopes),
            sum(scope.reconciled_status == "open" for scope in revision_scopes),
            sum(
                scope.reconciled_status == "review_required"
                for scope in revision_scopes
            ),
        )
        expected = (
            authority.fill_count,
            authority.episode_count,
            authority.execution_count,
            authority.lifecycle_resolved_scope_count,
            authority.review_required_scope_count,
            authority.closed_count,
            authority.open_count,
            authority.review_required_count,
        )
        expected_final_status = (
            "review_required" if authority.review_required_count else "reconciled"
        )
        if actual != expected or authority.lifecycle_final_status != expected_final_status:
            raise Phase1RealizedCalculationError(
                "active history counts do not match revision authority"
            )


def _result_payload(result: BoundedRealizedResult) -> dict[str, Any]:
    return {
        "contract_version": REALIZED_RESULT_CONTRACT_VERSION,
        "calculation_version": result.calculation_version,
        "coverage_start_date": result.coverage_start_date,
        "coverage_end_date": result.coverage_end_date,
        "authorities": [asdict(x) for x in result.authorities],
        "fill_input_fingerprint": result.fill_input_fingerprint,
        "lifecycle_input_fingerprint": result.lifecycle_input_fingerprint,
        "items": [asdict(x) for x in result.items],
        "omissions": [asdict(x) for x in result.omissions],
    }


def calculate_bounded_realized_result(
    db_path: Path,
    *,
    calculated_at: datetime | None = None,
) -> BoundedRealizedResult:
    """Calculate a deterministic partial result without writing the database."""

    if db_path.is_symlink() or not db_path.is_file():
        raise Phase1RealizedCalculationError(
            "database must be a pre-existing non-symlink file"
        )
    with duckdb.connect(str(db_path), read_only=True) as con:
        _required_tables(con)
        authorities = _load_authorities(con)
        scopes, fill_episode = _load_episode_scopes(con)
        _validate_active_history(
            con,
            authorities=authorities,
            scopes=scopes,
            fill_episode=fill_episode,
        )
        asof = max(x.asof_date for x in authorities)
        all_fills = load_normalized_fills(con, asof=asof)
        fills = [fill for fill in all_fills if fill.fill_uid in fill_episode]
        if {fill.fill_uid for fill in fills} != set(fill_episode):
            raise Phase1RealizedCalculationError(
                "active history fill identity does not match normalized evidence"
            )
        authority_by_account = {
            (authority.source_broker, authority.source_account_id): authority
            for authority in authorities
        }
        eligible_normalized_fill_uids = {
            fill.fill_uid
            for fill in all_fills
            if (
                authority := authority_by_account.get(
                    (fill.source_broker, fill.source_account_id)
                )
            )
            is not None
            and fill.asof <= authority.asof_date
        }
        if eligible_normalized_fill_uids != set(fill_episode):
            raise Phase1RealizedCalculationError(
                "active history revision is stale against normalized fill evidence"
            )
        if any(
            (fill.source_broker, fill.source_account_id) not in authority_by_account
            for fill in fills
        ):
            raise Phase1RealizedCalculationError(
                "active history fill is outside the authorized account scope"
            )
        events = []
        for event in load_approved_lifecycle_events(con, asof=asof):
            authority = authority_by_account.get(
                (event.source_broker, event.source_account_id)
            )
            if (
                authority is not None
                and event.effective_at.astimezone(NEW_YORK).date()
                <= authority.asof_date
            ):
                events.append(event)

    calculation = calculate_fifo_pnl_with_lifecycle_events(
        fills,
        events,
        allow_unmatched_close=True,
    )
    fill_by_uid = {fill.fill_uid: fill for fill in fills}
    unresolved = {key for key, scope in scopes.items() if not scope.resolved}
    unmatched = set(calculation.unmatched_close_fill_uids)
    if any(fill_episode[fill_uid] not in unresolved for fill_uid in unmatched):
        raise Phase1RealizedCalculationError(
            "an unmatched close exists in a resolved history scope"
        )

    items: list[RealizedAllocationResult] = []
    for allocation in calculation.closed_allocations:
        open_scope = fill_episode[allocation.open_fill_uid]
        close_scope = fill_episode[allocation.close_fill_uid]
        if open_scope in unresolved or close_scope in unresolved:
            continue
        close_fill = fill_by_uid[allocation.close_fill_uid]
        lineage = {
            "open_fill_uid": allocation.open_fill_uid,
            "close_fill_uid": allocation.close_fill_uid,
            "scope_key": allocation.scope_key,
            "quantity": allocation.quantity,
            "realized_pnl": allocation.realized_pnl,
        }
        items.append(
            RealizedAllocationResult(
                item_uid=f"realized-item:{_digest(lineage)}",
                source_broker=allocation.scope_key[0],
                source_account_id=allocation.scope_key[1],
                instrument_key=allocation.scope_key[2],
                symbol=(close_fill.underlying_symbol or close_fill.symbol).upper(),
                asset_class=(
                    "option" if close_fill.asset_class.lower() == "option" else "equity"
                ),
                close_market_date=allocation.closed_at.astimezone(NEW_YORK).date(),
                closed_at_utc=_utc(allocation.closed_at),
                currency=allocation.scope_key[3],
                realized_pnl=allocation.realized_pnl,
                direction=allocation.direction,
                quantity=allocation.quantity,
                multiplier=allocation.multiplier,
                open_fill_uid=allocation.open_fill_uid,
                close_fill_uid=allocation.close_fill_uid,
                source_event_uid=allocation.source_event_uid,
            )
        )

    for allocation in calculation.lifecycle_allocations:
        predecessor_scopes = {
            fill_episode[uid] for uid in (allocation.predecessor_open_fill_uid,)
        }
        if predecessor_scopes & unresolved:
            continue
        predecessor = fill_by_uid[allocation.predecessor_open_fill_uid]
        lineage = {
            "event_uid": allocation.event_uid,
            "allocation_index": allocation.allocation_index,
            "predecessor_open_fill_uid": allocation.predecessor_open_fill_uid,
            "realized_pnl": allocation.realized_pnl,
        }
        items.append(
            RealizedAllocationResult(
                item_uid=f"realized-item:{_digest(lineage)}",
                source_broker=allocation.option_scope_key[0],
                source_account_id=allocation.option_scope_key[1],
                instrument_key=allocation.option_scope_key[2],
                symbol=(predecessor.underlying_symbol or predecessor.symbol).upper(),
                asset_class="option",
                close_market_date=allocation.effective_at.astimezone(NEW_YORK).date(),
                closed_at_utc=_utc(allocation.effective_at),
                currency=allocation.option_scope_key[3],
                realized_pnl=allocation.realized_pnl,
                direction=allocation.predecessor_direction,
                quantity=allocation.contracts,
                multiplier=allocation.multiplier,
                open_fill_uid=allocation.predecessor_open_fill_uid,
                close_fill_uid=None,
                source_event_uid=allocation.event_uid,
            )
        )

    omissions: list[RealizedScopeOmission] = []
    for key in sorted(unresolved):
        scope = scopes[key]
        source_fill_uids = tuple(
            sorted(fill_uid for fill_uid, episode_key in fill_episode.items() if episode_key == key)
        )
        if not source_fill_uids:
            raise Phase1RealizedCalculationError("unresolved history scope has no fills")
        close_market_date = max(
            fill_by_uid[fill_uid].filled_at.astimezone(NEW_YORK).date()
            for fill_uid in source_fill_uids
        )
        omissions.append(
            RealizedScopeOmission(
                omission_uid=f"realized-omission:{_digest({'revision_uid': key[0], 'episode_uid': key[1], 'fills': source_fill_uids})}",
                source_broker=scope.source_broker,
                source_account_id=scope.source_account_id,
                episode_uid=scope.episode_uid,
                close_market_date=close_market_date,
                symbol=scope.primary_symbol or None,
                reason_code=_omission_reason(scope),
                source_fill_uids=source_fill_uids,
            )
        )

    coverage_start = min(x.history_window_start for x in authorities)
    coverage_end = max(x.history_window_end for x in authorities)
    provisional = BoundedRealizedResult(
        calculation_run_id="",
        calculation_version=REALIZED_CALCULATION_VERSION,
        calculated_at_utc=_utc(calculated_at or datetime.now(UTC)),
        coverage_start_date=coverage_start,
        coverage_end_date=coverage_end,
        authorities=tuple(sorted(authorities, key=lambda x: x.revision_uid)),
        fill_input_fingerprint=build_fill_input_fingerprint(fills),
        lifecycle_input_fingerprint=build_lifecycle_input_fingerprint(events),
        items=tuple(sorted(items, key=lambda x: x.item_uid)),
        omissions=tuple(sorted(omissions, key=lambda x: x.omission_uid)),
        result_fingerprint="",
    )
    fingerprint = _digest(_result_payload(provisional))
    return BoundedRealizedResult(
        **{
            **provisional.__dict__,
            "calculation_run_id": f"phase1-realized:{fingerprint}",
            "result_fingerprint": fingerprint,
        }
    )


def validate_realized_result(result: BoundedRealizedResult) -> None:
    expected = _digest(_result_payload(result))
    if expected != result.result_fingerprint:
        raise Phase1RealizedCalculationError("realized result fingerprint mismatch")
    if result.calculation_run_id != f"phase1-realized:{expected}":
        raise Phase1RealizedCalculationError("realized calculation identity mismatch")
    if len({x.item_uid for x in result.items}) != len(result.items):
        raise Phase1RealizedCalculationError("realized item identities are not unique")
    if len({x.omission_uid for x in result.omissions}) != len(result.omissions):
        raise Phase1RealizedCalculationError("realized omission identities are not unique")


def authorize_realized_result(
    result: BoundedRealizedResult,
    authorization: RealizedResultAuthorization,
) -> None:
    """Require owner acceptance of this exact immutable result."""

    validate_realized_result(result)
    expected_revisions = tuple(x.revision_uid for x in result.authorities)
    if (
        authorization.calculation_run_id != result.calculation_run_id
        or authorization.result_fingerprint != result.result_fingerprint
        or authorization.history_revision_uids != expected_revisions
        or not authorization.owner_acceptance_uid
    ):
        raise Phase1RealizedCalculationError(
            "realized-result authorization does not match the calculation"
        )
    _utc(authorization.accepted_at_utc)


def reporting_items(
    result: BoundedRealizedResult,
) -> tuple[RealizedHistoryItem, ...]:
    validate_realized_result(result)
    return tuple(
        RealizedHistoryItem(
            item_uid=item.item_uid,
            source_broker=item.source_broker,
            source_account_id=item.source_account_id,
            instrument_key=item.instrument_key,
            symbol=item.symbol,
            asset_class=item.asset_class,
            close_market_date=item.close_market_date,
            closed_at_utc=item.closed_at_utc,
            currency=item.currency,
            realized_pnl=item.realized_pnl,
        )
        for item in result.items
    )


def reporting_omissions(
    result: BoundedRealizedResult,
) -> tuple[ReportingOmission, ...]:
    validate_realized_result(result)
    return tuple(
        ReportingOmission(
            omission_uid=item.omission_uid,
            source_broker=item.source_broker,
            source_account_id=item.source_account_id,
            close_market_date=item.close_market_date,
            symbol=item.symbol,
            reason_code=item.reason_code,
            item_status="incomplete",
        )
        for item in result.omissions
    )
