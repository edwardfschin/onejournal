"""Private local-owner journal API, deliberately separate from demo fixtures.

The browser receives only versioned application records.  It cannot choose a
database, execute SQL, fetch broker data, or reach raw evidence.  This module
is registered only by :func:`create_local_owner_journal_app`, whose caller
supplies a verified local DuckDB path.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from hashlib import sha256
import json
from pathlib import Path
import stat
from threading import Lock
from typing import Any, Literal
from uuid import UUID, uuid4

import duckdb
from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from onejournal.journal.domain import (
    ENTRY_TYPES,
    REVIEW_STATUSES,
    SETUP_QUALITIES,
    JournalPolicyError,
    JournalValidationError,
    create_entry,
    current_journal_relation,
    get_current_entry_revision,
    revise_entry,
    save_review,
    utc_now_naive,
)
from onejournal.journal.search import JournalSearchFilters, search_journal
from onejournal.journal.schwab_lifecycle_presentation import (
    LifecyclePresentation,
    lifecycle_presentation_to_dict,
    load_schwab_lifecycle_presentations,
)
from onejournal.journal.schwab_vertical_presentation import (
    VerticalPresentationGroup,
    load_schwab_vertical_presentation_groups,
    presentation_group_to_dict,
)
from onejournal.journal.workflows import REVIEW_QUEUE_NAMES, build_review_queues


LOCAL_OWNER_JOURNAL_CONTRACT_VERSION = "onejournal.local-owner-journal.v5"
LOCAL_OWNER_JOURNAL_API_PREFIX = "/api/v5/local-owner/journal"


class LocalOwnerModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="after")
    @classmethod
    def normalize_utc_datetimes(cls, value: Any) -> Any:
        """Keep every API instant explicit and comparable at the boundary."""

        if not isinstance(value, datetime):
            return value
        if value.tzinfo is None or value.utcoffset() is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class LocalOwnerMetadata(LocalOwnerModel):
    contract_version: Literal["onejournal.local-owner-journal.v5"] = (
        LOCAL_OWNER_JOURNAL_CONTRACT_VERSION
    )
    mode: Literal["local_owner"] = "local_owner"


class EpisodeSummary(LocalOwnerModel):
    episode_uid: str
    source_broker: str
    primary_symbol: str
    asset_class: str
    strategy_type: str
    strategy_label: str
    opened_at: datetime
    episode_status: str
    review_status: str
    setup_quality: str
    lifecycle_quality: str
    lifecycle_reason: str | None
    position_reconciliation_status: str
    instrument_count: int
    execution_count: int
    lifecycle_sequence: int
    lifecycle_count: int
    instrument_summary: str


class EntrySummary(LocalOwnerModel):
    entry_uid: str
    revision_no: int
    episode_uid: str | None
    entry_type: str
    strategy_uid: str | None
    journal_strategy_name: str | None
    title: str | None
    body: str
    occurred_at: datetime | None
    created_at: datetime
    entry_status: str


class EntrySearchSummary(LocalOwnerModel):
    entry_uid: str
    revision_no: int
    episode_uid: str | None
    entry_type: str
    strategy_uid: str | None
    journal_strategy_name: str | None
    occurred_at: datetime | None
    created_at: datetime
    entry_status: str


class VerticalGroupMember(LocalOwnerModel):
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


class VerticalGroup(LocalOwnerModel):
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
    source_evidence: Literal["schwab_filled_vertical_opening_order"]
    members: list[VerticalGroupMember]


class LifecyclePhase(LocalOwnerModel):
    phase: Literal["opening", "closing"]
    instruction: Literal[
        "BUY_TO_OPEN", "SELL_TO_OPEN", "BUY_TO_CLOSE", "SELL_TO_CLOSE"
    ]
    occurred_at: datetime
    quantity: str
    average_fill_price: str
    cash_movement: str
    commission: str
    fees: str
    currency: str
    execution_count: int


class OptionStockSettlement(LocalOwnerModel):
    settlement_uid: str
    settlement_kind: Literal["assignment", "exercise"]
    settled_at: datetime
    option_quantity: str
    stock_symbol: str
    stock_quantity: str
    stock_price: str
    currency: str
    stock_episode_uid: str
    stock_execution_uid: str
    evidence_quality: Literal["exact_structured_match"]
    source_evidence: Literal["schwab_unique_option_stock_settlement"]


class OptionExpiration(LocalOwnerModel):
    expiration_uid: str
    outcome_kind: Literal["expiration_indicated"]
    expires_on: date
    posted_at: datetime
    option_quantity: str
    evidence_quality: Literal["review_required"]
    source_evidence: Literal[
        "schwab_receive_and_deliver_expiration_description_hint"
    ]


class LifecycleStory(LocalOwnerModel):
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
    history_completeness: Literal["complete", "opening_history_missing"]
    phases: list[LifecyclePhase]
    option_stock_settlements: list[OptionStockSettlement]
    option_expirations: list[OptionExpiration]


class SearchResponse(LocalOwnerModel):
    metadata: LocalOwnerMetadata
    episodes: list[EpisodeSummary]
    entries: list[EntrySearchSummary]
    presentation_groups: list[VerticalGroup]
    lifecycle_stories: list[LifecycleStory]


class QueueItem(LocalOwnerModel):
    episode_uid: str
    source_broker: str
    primary_symbol: str
    asset_class: str
    instrument_summary: str
    opened_at: datetime
    episode_status: str
    review_status: str
    setup_quality: str
    lifecycle_quality: str
    lifecycle_reason: str | None
    reason_codes: list[str]


class ReviewQueuesResponse(LocalOwnerModel):
    metadata: LocalOwnerMetadata
    queues: dict[str, list[QueueItem]]
    presentation_groups: list[VerticalGroup]
    lifecycle_stories: list[LifecycleStory]


class LifecycleInstrument(LocalOwnerModel):
    instrument_index: int
    instrument_uid: str
    asset_class: str
    symbol: str
    underlying_symbol: str | None
    option_type: str | None
    expiry: date | None
    strike: str | None
    multiplier: str | None
    currency: str
    opening_direction: str | None
    execution_count: int
    buy_quantity: str
    sell_quantity: str
    captured_quantity_delta: str


class LifecycleExecution(LocalOwnerModel):
    execution_index: int
    execution_uid: str
    instrument_uid: str
    filled_at: datetime
    side: str
    quantity: str
    fill_price: str
    multiplier: str
    commission: str
    fees: str
    currency: str
    schwab_net_cash_movement: str
    calculated_net_cash_movement: str
    reconciliation_status: Literal["matched_schwab_transaction"]


class TradeLifecycleResponse(LocalOwnerModel):
    metadata: LocalOwnerMetadata
    trade: EpisodeSummary
    instruments: list[LifecycleInstrument]
    executions: list[LifecycleExecution]
    entries: list[EntrySummary]
    presentation_group: VerticalGroup | None
    lifecycle_story: LifecycleStory | None


class JournalEntryResponse(LocalOwnerModel):
    metadata: LocalOwnerMetadata
    entry: EntrySummary


class ReviewWriteRequest(LocalOwnerModel):
    episode_uid: str = Field(min_length=1, max_length=512)
    review_status: str
    setup_quality: str
    entry_reason: str = Field(default="", max_length=4000)
    notes: str = Field(default="", max_length=20000)

    @field_validator("review_status")
    @classmethod
    def validate_review_status(cls, value: str) -> str:
        if value not in REVIEW_STATUSES:
            raise ValueError("invalid review_status")
        return value

    @field_validator("setup_quality")
    @classmethod
    def validate_setup_quality(cls, value: str) -> str:
        if value not in SETUP_QUALITIES:
            raise ValueError("invalid setup_quality")
        return value


class EntryWriteRequest(LocalOwnerModel):
    entry_type: str
    body: str = Field(max_length=20000)
    episode_uid: str | None = Field(default=None, max_length=512)
    strategy_uid: str | None = None
    title: str | None = Field(default=None, max_length=512)
    occurred_at: datetime | None = None
    change_reason: str | None = Field(default=None, max_length=512)

    @field_validator("entry_type")
    @classmethod
    def validate_entry_type(cls, value: str) -> str:
        if value not in ENTRY_TYPES:
            raise ValueError("invalid entry_type")
        return value


class EntryRevisionWriteRequest(EntryWriteRequest):
    change_reason: str = Field(min_length=1, max_length=512)


class WriteReceipt(LocalOwnerModel):
    metadata: LocalOwnerMetadata
    operation_uid: str
    resource_uid: str
    revision_no: int | None = None
    replayed: bool


def create_local_owner_journal_app(*, journal_db_path: str | Path) -> FastAPI:
    """Build the private app with a server-selected, existing journal database.

    Binding happens at process start.  No API request has a path, connection,
    broker, credential, or raw-evidence parameter.
    """

    supplied_path = Path(journal_db_path).expanduser()
    if supplied_path.is_symlink():
        raise ValueError("local-owner journal database must not be a symlink")
    db_path = supplied_path.resolve()
    if not db_path.is_file():
        raise ValueError("local-owner journal database must already exist")
    if stat.S_IMODE(db_path.stat().st_mode) != 0o600:
        raise ValueError("local-owner journal database must use mode 0600")
    with duckdb.connect(str(db_path), read_only=True) as con:
        tables = {str(row[0]) for row in con.execute("SHOW TABLES").fetchall()}
    required_tables = {
        "trade_episodes",
        "manual_reviews",
        "journal_entries",
        "journal_entry_revisions",
        "journal_reviews",
        "local_owner_api_audit_events",
        "local_owner_api_operation_receipts",
        "phase1_journal_materialized_episodes",
        "phase1_journal_projected_episodes",
        "phase1_journal_projected_instruments",
        "phase1_journal_projected_executions",
        "phase1_journal_lifecycle_reconciliation_runs",
        "phase1_journal_episode_lifecycle_states",
    }
    missing_tables = required_tables - tables
    if missing_tables:
        raise ValueError(
            "local-owner journal database requires durable journal and local API "
            "audit migrations; missing " + ", ".join(sorted(missing_tables))
        )
    with duckdb.connect(str(db_path), read_only=True) as con:
        episode_relation = current_journal_relation(con, "trade_episodes")
        materialized_relation = current_journal_relation(
            con, "phase1_journal_materialized_episodes"
        )
        projected_episode_relation = current_journal_relation(
            con, "phase1_journal_projected_episodes"
        )
        projected_instrument_relation = current_journal_relation(
            con, "phase1_journal_projected_instruments"
        )
        projected_execution_relation = current_journal_relation(
            con, "phase1_journal_projected_executions"
        )
        lifecycle_run_relation = current_journal_relation(
            con, "phase1_journal_lifecycle_reconciliation_runs"
        )
        lifecycle_state_relation = current_journal_relation(
            con, "phase1_journal_episode_lifecycle_states"
        )
        materialized_episode_count = con.execute(
            f"SELECT COUNT(*) FROM {materialized_relation}"
        ).fetchone()[0]
        missing_projection_count = con.execute(
            f"""
            SELECT COUNT(*)
            FROM {materialized_relation} m
            LEFT JOIN {projected_episode_relation} p
              ON p.episode_uid = m.episode_uid
            WHERE p.episode_uid IS NULL
            """
        ).fetchone()[0]
        projection_run_count = con.execute(
            f"SELECT COUNT(DISTINCT projection_uid) FROM {projected_episode_relation}"
        ).fetchone()[0]
        invalid_projection_count = con.execute(
            f"""
            SELECT COUNT(*) FROM {projected_execution_relation}
            WHERE net_amount_reconciled <> TRUE
               OR schwab_net_cash_movement <> calculated_net_cash_movement
            """
        ).fetchone()[0]
        lifecycle_run_count = con.execute(
            f"SELECT COUNT(*) FROM {lifecycle_run_relation}"
        ).fetchone()[0]
        invalid_lifecycle_run_count = con.execute(
            f"""
            SELECT COUNT(*)
            FROM {lifecycle_run_relation} r
            WHERE r.episode_count <> (
                    SELECT COUNT(*)
                    FROM {lifecycle_state_relation} s
                    WHERE s.reconciliation_uid = r.reconciliation_uid
                  )
               OR r.episode_count <>
                    r.closed_count + r.open_count + r.review_required_count
               OR r.matched_terminal_event_leg_count > r.terminal_event_leg_count
               OR (
                    r.final_status = 'reconciled'
                    AND EXISTS (
                        SELECT 1
                        FROM {lifecycle_state_relation} s
                        WHERE s.reconciliation_uid = r.reconciliation_uid
                          AND (s.reconciled_status = 'review_required'
                               OR s.lifecycle_quality = 'review_required')
                    )
                  )
            """
        ).fetchone()[0]
        missing_lifecycle_state_count = con.execute(
            f"""
            SELECT COUNT(*)
            FROM {materialized_relation} m
            LEFT JOIN {lifecycle_state_relation} s
              ON s.episode_uid = m.episode_uid
            WHERE s.episode_uid IS NULL
            """
        ).fetchone()[0]
    if materialized_episode_count and (
        missing_projection_count or projection_run_count != 1 or invalid_projection_count
    ):
        raise ValueError(
            "local-owner journal database requires an exact execution-first "
            "projection for every Phase 1 episode"
        )
    if materialized_episode_count and (
        lifecycle_run_count < 1
        or invalid_lifecycle_run_count
        or missing_lifecycle_state_count
    ):
        raise ValueError(
            "local-owner journal database requires a complete, internally "
            "consistent Schwab lifecycle and current-position reconciliation "
            "for every Phase 1 episode"
        )

    app = FastAPI(
        title="OneJournal Local Owner Journal API",
        version="0.1.0",
        description=(
            "Private local-owner journal boundary. Run only through the loopback "
            "launcher; it does not access brokers or raw evidence."
        ),
    )
    vertical_groups = load_schwab_vertical_presentation_groups(db_path)
    vertical_group_by_episode = {
        member.episode_uid: group
        for group in vertical_groups
        for member in group.members
    }
    lifecycle_stories = load_schwab_lifecycle_presentations(db_path)
    lifecycle_story_by_episode = {
        story.episode_uid: story for story in lifecycle_stories
    }

    def relevant_vertical_groups(
        episode_uids: set[str],
    ) -> list[VerticalGroup]:
        return [
            _vertical_group(group)
            for group in vertical_groups
            if all(member.episode_uid in episode_uids for member in group.members)
        ]

    def relevant_lifecycle_stories(
        episode_uids: set[str],
    ) -> list[LifecycleStory]:
        return [
            _lifecycle_story(story)
            for story in lifecycle_stories
            if story.episode_uid in episode_uids
        ]

    def open_db(*, read_only: bool = False) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(db_path), read_only=read_only)

    db_lock = Lock()

    @app.get(f"{LOCAL_OWNER_JOURNAL_API_PREFIX}/search", response_model=SearchResponse, tags=["local-owner-journal"])
    def journal_search(
        q: str | None = Query(default=None, max_length=512),
        symbol: str | None = Query(default=None, max_length=64),
        review_status: str | None = Query(default=None),
        review_queue: str | None = Query(default=None),
        entry_type: str | None = Query(default=None),
        date_from: date | None = Query(default=None),
        date_to: date | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> SearchResponse:
        filters = JournalSearchFilters(
            query_text=q, symbol=symbol, review_status=review_status,
            review_queue=review_queue, entry_type=entry_type,
            date_from=date_from, date_to=date_to,
        )
        try:
            with db_lock:
                with open_db(read_only=False) as con:
                    result = search_journal(con, filters, limit=limit)
                    _audit_read(con, action="journal_search", request={"filters": filters.__dict__, "limit": limit})
                    episode_uids = {str(row["episode_uid"]) for row in result.episodes}
                    return SearchResponse(
                        metadata=_metadata(),
                        episodes=[_episode(row) for row in result.episodes],
                        entries=[_entry_search(row) for row in result.entries],
                        presentation_groups=relevant_vertical_groups(episode_uids),
                        lifecycle_stories=relevant_lifecycle_stories(episode_uids),
                    )
        except (JournalValidationError, JournalPolicyError) as exc:
            raise HTTPException(status_code=400, detail="invalid local-owner journal request") from exc

    @app.get(f"{LOCAL_OWNER_JOURNAL_API_PREFIX}/review-queues", response_model=ReviewQueuesResponse, tags=["local-owner-journal"])
    def review_queues(asof: date | None = Query(default=None)) -> ReviewQueuesResponse:
        with db_lock:
            with open_db(read_only=False) as con:
                queues = build_review_queues(con, asof=asof)
                _audit_read(con, action="review_queue_read", request={"asof": str(asof) if asof else None})
                episode_uids = {
                    str(row["episode_uid"])
                    for name in REVIEW_QUEUE_NAMES
                    for row in queues[name]
                }
                return ReviewQueuesResponse(
                    metadata=_metadata(),
                    queues={name: [_queue_item(row) for row in queues[name]] for name in REVIEW_QUEUE_NAMES},
                    presentation_groups=relevant_vertical_groups(episode_uids),
                    lifecycle_stories=relevant_lifecycle_stories(episode_uids),
                )

    @app.get(f"{LOCAL_OWNER_JOURNAL_API_PREFIX}/trades/{{episode_uid}}", response_model=TradeLifecycleResponse, tags=["local-owner-journal"])
    def trade_lifecycle(episode_uid: str) -> TradeLifecycleResponse:
        with db_lock:
            with open_db(read_only=False) as con:
                row = _row(con, f"""
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
                    SELECT e.episode_uid, e.source_broker, e.primary_symbol,
                           e.asset_class,
                           COALESCE(p.strategy_type, e.strategy_type) AS strategy_type,
                           COALESCE(p.strategy_label, e.strategy_label) AS strategy_label,
                           e.opened_at,
                           COALESCE(ls.reconciled_status, e.status) AS episode_status,
                           COALESCE(r.review_status, 'unreviewed') AS review_status,
                           COALESCE(r.setup_quality, 'unknown') AS setup_quality,
                           COALESCE(ls.lifecycle_quality, m.lifecycle_quality, 'legacy_unverified') AS lifecycle_quality,
                           COALESCE(ls.reason_code, m.reason_code, CASE WHEN m.episode_uid IS NULL
                             THEN 'legacy_episode_unverified' ELSE NULL END) AS lifecycle_reason,
                           COALESCE(ls.position_reconciliation_status, 'not_applicable')
                             AS position_reconciliation_status,
                           COALESCE(p.instrument_count, 1) AS instrument_count,
                           COALESCE(p.execution_count, e.fill_count) AS execution_count,
                           COALESCE(p.lifecycle_sequence, 1) AS lifecycle_sequence,
                           COALESCE(p.lifecycle_count, 1) AS lifecycle_count,
                           COALESCE(p.instrument_summary, 'Unverified legacy grouping') AS instrument_summary
                    FROM {episode_relation} e
                    LEFT JOIN manual_reviews r ON r.episode_uid = e.episode_uid
                    LEFT JOIN {materialized_relation} m
                      ON m.episode_uid = e.episode_uid
                    LEFT JOIN {projected_episode_relation} p
                      ON p.episode_uid = e.episode_uid
                    LEFT JOIN latest_lifecycle_states ls
                      ON ls.episode_uid = e.episode_uid AND ls.rn = 1
                    WHERE e.episode_uid = ?
                """, [episode_uid])
                if row is None:
                    raise HTTPException(status_code=404, detail="trade not found")
                instruments = _rows(con, f"""
                    SELECT instrument_index, instrument_uid, asset_class,
                           symbol, underlying_symbol, option_type, expiry,
                           strike, multiplier, currency, opening_direction,
                           execution_count, buy_quantity, sell_quantity,
                           captured_quantity_delta
                    FROM {projected_instrument_relation}
                    WHERE episode_uid = ? ORDER BY instrument_index
                """, [episode_uid])
                executions = _rows(con, f"""
                    SELECT execution_index, execution_uid, instrument_uid,
                           filled_at_utc AS filled_at, side, quantity,
                           fill_price, multiplier, commission, fees, currency,
                           schwab_net_cash_movement,
                           calculated_net_cash_movement,
                           'matched_schwab_transaction' AS reconciliation_status
                    FROM {projected_execution_relation}
                    WHERE episode_uid = ? ORDER BY execution_index
                """, [episode_uid])
                entries = _rows(con, """
                    WITH current_revisions AS (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY entry_uid ORDER BY revision_no DESC) AS rn
                        FROM journal_entry_revisions
                    )
                    SELECT cr.entry_uid, cr.revision_no, cr.episode_uid, cr.entry_type, cr.strategy_uid,
                           s.name AS journal_strategy_name, cr.title, cr.body, cr.occurred_at,
                           cr.created_at, cr.entry_status
                    FROM current_revisions cr LEFT JOIN journal_strategies s ON s.strategy_uid = cr.strategy_uid
                    WHERE cr.rn = 1 AND cr.entry_status = 'active' AND cr.episode_uid = ?
                    ORDER BY COALESCE(cr.occurred_at, cr.created_at) DESC, cr.entry_uid
                """, [episode_uid])
                _audit_read(con, action="trade_lifecycle_read", resource_uid=episode_uid, request={"episode_uid": episode_uid})
                return TradeLifecycleResponse(
                    metadata=_metadata(), trade=_episode(row),
                    instruments=[_instrument(item) for item in instruments],
                    executions=[_execution(item) for item in executions],
                    entries=[_entry(item) for item in entries],
                    presentation_group=(
                        _vertical_group(vertical_group_by_episode[episode_uid])
                        if episode_uid in vertical_group_by_episode
                        else None
                    ),
                    lifecycle_story=(
                        _lifecycle_story(lifecycle_story_by_episode[episode_uid])
                        if episode_uid in lifecycle_story_by_episode
                        else None
                    ),
                )

    @app.get(f"{LOCAL_OWNER_JOURNAL_API_PREFIX}/entries/{{entry_uid}}", response_model=JournalEntryResponse, tags=["local-owner-journal"])
    def journal_entry(entry_uid: str) -> JournalEntryResponse:
        with db_lock:
            with open_db(read_only=False) as con:
                row = _row(con, """
                    WITH current_revisions AS (
                        SELECT *, ROW_NUMBER() OVER (PARTITION BY entry_uid ORDER BY revision_no DESC) AS rn
                        FROM journal_entry_revisions
                    )
                    SELECT cr.entry_uid, cr.revision_no, cr.episode_uid, cr.entry_type,
                           cr.strategy_uid, s.name AS journal_strategy_name, cr.title,
                           cr.body, cr.occurred_at, cr.created_at, cr.entry_status
                    FROM current_revisions cr
                    LEFT JOIN journal_strategies s ON s.strategy_uid = cr.strategy_uid
                    WHERE cr.rn = 1 AND cr.entry_status = 'active' AND cr.entry_uid = ?
                """, [entry_uid])
                if row is None:
                    raise HTTPException(status_code=404, detail="journal entry not found")
                _audit_read(con, action="journal_entry_read", resource_uid=entry_uid, request={"entry_uid": entry_uid})
                return JournalEntryResponse(metadata=_metadata(), entry=_entry(row))

    @app.post(f"{LOCAL_OWNER_JOURNAL_API_PREFIX}/reviews", response_model=WriteReceipt, tags=["local-owner-journal"])
    def write_review(request: ReviewWriteRequest, operation_uid: str = Header(alias="X-OneJournal-Operation-Id")) -> WriteReceipt:
        with db_lock:
            return _write_review(open_db, request, operation_uid)

    @app.post(f"{LOCAL_OWNER_JOURNAL_API_PREFIX}/entries", response_model=WriteReceipt, tags=["local-owner-journal"])
    def write_entry(request: EntryWriteRequest, operation_uid: str = Header(alias="X-OneJournal-Operation-Id")) -> WriteReceipt:
        with db_lock:
            return _write_entry(open_db, request, operation_uid)

    @app.post(f"{LOCAL_OWNER_JOURNAL_API_PREFIX}/entries/{{entry_uid}}/revisions", response_model=WriteReceipt, tags=["local-owner-journal"])
    def write_entry_revision(entry_uid: str, request: EntryRevisionWriteRequest, operation_uid: str = Header(alias="X-OneJournal-Operation-Id")) -> WriteReceipt:
        with db_lock:
            return _write_revision(open_db, entry_uid, request, operation_uid)

    return app


def _write_review(open_db: Any, request: ReviewWriteRequest, operation_uid: str) -> WriteReceipt:
    action = "journal_review_write"
    operation_uid = _operation_uid(operation_uid)
    request_sha = _request_sha(request.model_dump(mode="json"))
    with open_db() as con:
        replay = _replay_receipt(con, operation_uid, action, request_sha)
        if replay:
            _audit(con, operation_uid, action, "review", replay["resource_uid"], "replayed", request_sha)
            return _receipt(operation_uid, replay["resource_uid"], replay["revision_no"], replayed=True)
        con.execute("BEGIN TRANSACTION")
        try:
            result = save_review(con, **request.model_dump(), source="api", manage_transaction=False)
            if not result.review_uid:
                raise JournalPolicyError("durable review history is required for the local-owner API")
            _store_receipt(con, operation_uid, action, request_sha, "review", result.review_uid, None)
            _audit(con, operation_uid, action, "review", result.review_uid, "accepted", request_sha)
            con.execute("COMMIT")
        except (JournalValidationError, JournalPolicyError) as exc:
            con.execute("ROLLBACK")
            raise HTTPException(status_code=400, detail="review was not saved") from exc
        except Exception:
            con.execute("ROLLBACK")
            raise
    return _receipt(operation_uid, result.review_uid, None, replayed=False)


def _write_entry(open_db: Any, request: EntryWriteRequest, operation_uid: str) -> WriteReceipt:
    return _write_entry_common(open_db, request, operation_uid, entry_uid=None)


def _write_revision(open_db: Any, entry_uid: str, request: EntryRevisionWriteRequest, operation_uid: str) -> WriteReceipt:
    return _write_entry_common(open_db, request, operation_uid, entry_uid=entry_uid)


def _write_entry_common(open_db: Any, request: EntryWriteRequest, operation_uid: str, *, entry_uid: str | None) -> WriteReceipt:
    action = "journal_entry_write" if entry_uid is None else "journal_entry_revision_write"
    operation_uid = _operation_uid(operation_uid)
    request_sha = _request_sha({"entry_uid": entry_uid, **request.model_dump(mode="json")})
    with open_db() as con:
        replay = _replay_receipt(con, operation_uid, action, request_sha)
        if replay:
            _audit(con, operation_uid, action, "entry", replay["resource_uid"], "replayed", request_sha)
            return _receipt(operation_uid, replay["resource_uid"], replay["revision_no"], replayed=True)
        con.execute("BEGIN TRANSACTION")
        try:
            if entry_uid is None:
                revision = create_entry(con, **request.model_dump(), created_source="api", manage_transaction=False)
            else:
                revision = revise_entry(
                    con,
                    entry_uid=entry_uid,
                    **request.model_dump(),
                    created_at=None,
                    manage_transaction=False,
                )
            _store_receipt(con, operation_uid, action, request_sha, "entry", revision.entry_uid, revision.revision_no)
            _audit(con, operation_uid, action, "entry", revision.entry_uid, "accepted", request_sha)
            con.execute("COMMIT")
        except (JournalValidationError, JournalPolicyError) as exc:
            con.execute("ROLLBACK")
            raise HTTPException(status_code=400, detail="journal entry was not saved") from exc
        except Exception:
            con.execute("ROLLBACK")
            raise
    return _receipt(operation_uid, revision.entry_uid, revision.revision_no, replayed=False)


def _metadata() -> LocalOwnerMetadata:
    return LocalOwnerMetadata()


def _episode(row: dict[str, Any]) -> EpisodeSummary:
    return EpisodeSummary(**{key: row[key] for key in EpisodeSummary.model_fields})


def _queue_item(row: dict[str, Any]) -> QueueItem:
    return QueueItem(**{key: row[key] for key in QueueItem.model_fields})


def _vertical_group(group: VerticalPresentationGroup) -> VerticalGroup:
    return VerticalGroup.model_validate(presentation_group_to_dict(group))


def _lifecycle_story(story: LifecyclePresentation) -> LifecycleStory:
    return LifecycleStory.model_validate(lifecycle_presentation_to_dict(story))


def _entry(row: dict[str, Any]) -> EntrySummary:
    values = {key: row[key] for key in EntrySummary.model_fields}
    for key in ("entry_uid", "strategy_uid"):
        if values[key] is not None:
            values[key] = str(values[key])
    return EntrySummary(**values)


def _entry_search(row: dict[str, Any]) -> EntrySearchSummary:
    values = {key: row[key] for key in EntrySearchSummary.model_fields}
    for key in ("entry_uid", "strategy_uid"):
        if values[key] is not None:
            values[key] = str(values[key])
    return EntrySearchSummary(**values)


def _instrument(row: dict[str, Any]) -> LifecycleInstrument:
    row = dict(row)
    for key in (
        "strike", "multiplier", "buy_quantity", "sell_quantity",
        "captured_quantity_delta",
    ):
        if row[key] is not None:
            row[key] = format(row[key], "f")
    return LifecycleInstrument(**row)


def _execution(row: dict[str, Any]) -> LifecycleExecution:
    row = dict(row)
    for key in (
        "quantity", "fill_price", "multiplier", "commission", "fees",
        "schwab_net_cash_movement", "calculated_net_cash_movement",
    ):
        row[key] = format(row[key], "f")
    return LifecycleExecution(**row)


def _rows(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> list[dict[str, Any]]:
    result = con.execute(sql, params)
    names = [column[0] for column in result.description]
    return [dict(zip(names, row)) for row in result.fetchall()]


def _row(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any]) -> dict[str, Any] | None:
    rows = _rows(con, sql, params)
    return rows[0] if rows else None


def _operation_uid(value: str) -> str:
    try:
        return str(UUID(value))
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="invalid operation identity") from exc


def _request_sha(value: object) -> str:
    serialized = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(serialized.encode("utf-8")).hexdigest()


def _audit_read(con: duckdb.DuckDBPyConnection, *, action: str, request: object, resource_uid: str | None = None) -> None:
    _audit(con, None, action, "journal", resource_uid, "accepted", _request_sha(request))


def _audit(con: duckdb.DuckDBPyConnection, operation_uid: str | None, action: str, resource_type: str, resource_uid: str | None, outcome: str, request_sha: str) -> None:
    con.execute("""
        INSERT INTO local_owner_api_audit_events (
            audit_event_uid, operation_uid, action, resource_type, resource_uid,
            outcome, request_sha256, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, [str(uuid4()), operation_uid, action, resource_type, resource_uid, outcome, request_sha, utc_now_naive()])


def _replay_receipt(con: duckdb.DuckDBPyConnection, operation_uid: str, action: str, request_sha: str) -> dict[str, Any] | None:
    row = _row(con, "SELECT action, request_sha256, resource_uid, revision_no FROM local_owner_api_operation_receipts WHERE operation_uid = ?", [operation_uid])
    if row is None:
        return None
    if row["action"] != action or row["request_sha256"] != request_sha:
        raise HTTPException(status_code=409, detail="operation identity was already used for a different request")
    return row


def _store_receipt(con: duckdb.DuckDBPyConnection, operation_uid: str, action: str, request_sha: str, resource_type: str, resource_uid: str, revision_no: int | None) -> None:
    con.execute("""
        INSERT INTO local_owner_api_operation_receipts (
            operation_uid, action, request_sha256, resource_type, resource_uid, revision_no, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """, [operation_uid, action, request_sha, resource_type, resource_uid, revision_no, utc_now_naive()])


def _receipt(operation_uid: str, resource_uid: str, revision_no: int | None, *, replayed: bool) -> WriteReceipt:
    return WriteReceipt(metadata=_metadata(), operation_uid=operation_uid, resource_uid=resource_uid, revision_no=revision_no, replayed=replayed)
