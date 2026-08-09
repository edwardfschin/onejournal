"""Private journal search, filters, and saved-view services.

Search results may contain private entry text and therefore must only be used by
local/operator or a future authenticated service. This module does not publish
dashboard output and performs no broker or execution action.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import duckdb

from .domain import (
    ENTRY_TYPES,
    REVIEW_STATUSES,
    JournalPolicyError,
    JournalValidationError,
    normalize_catalog_name,
    table_exists,
    utc_now_naive,
)
from .workflows import REVIEW_QUEUE_NAMES, build_review_queues


@dataclass(frozen=True)
class JournalSearchFilters:
    query_text: str | None = None
    symbol: str | None = None
    source_broker: str | None = None
    source_account_id: str | None = None
    episode_strategy_type: str | None = None
    journal_strategy_uid: str | None = None
    review_status: str | None = None
    review_queue: str | None = None
    entry_type: str | None = None
    date_from: date | None = None
    date_to: date | None = None


@dataclass(frozen=True)
class JournalSearchResult:
    episodes: list[dict[str, Any]]
    entries: list[dict[str, Any]]


def validate_search_filters(filters: JournalSearchFilters) -> JournalSearchFilters:
    if filters.review_status is not None and filters.review_status not in REVIEW_STATUSES:
        raise JournalValidationError(f"invalid review_status: {filters.review_status}")
    if filters.review_queue is not None and filters.review_queue not in REVIEW_QUEUE_NAMES:
        raise JournalValidationError(f"invalid review_queue: {filters.review_queue}")
    if filters.entry_type is not None and filters.entry_type not in ENTRY_TYPES:
        raise JournalValidationError(f"invalid entry_type: {filters.entry_type}")
    if filters.date_from is not None and filters.date_to is not None and filters.date_from > filters.date_to:
        raise JournalValidationError("date_from must not be later than date_to")
    if filters.journal_strategy_uid is not None:
        _uuid(filters.journal_strategy_uid, "journal_strategy_uid")
    return filters


def search_journal(
    con: duckdb.DuckDBPyConnection,
    filters: JournalSearchFilters,
    *,
    limit: int = 100,
) -> JournalSearchResult:
    """Search current episode and journal-entry state deterministically."""

    validate_search_filters(filters)
    if limit < 1 or limit > 500:
        raise JournalValidationError("limit must be between 1 and 500")
    if not table_exists(con, "journal_entry_revisions"):
        raise JournalPolicyError("journal search requires migration 0005 or later")

    queue_episode_uids: set[str] | None = None
    if filters.review_queue is not None:
        queues = build_review_queues(con, asof=filters.date_to)
        queue_episode_uids = {
            str(row["episode_uid"]) for row in queues[filters.review_queue]
        }

    episodes = _search_episodes(con, filters, queue_episode_uids, limit)
    entries = _search_entries(con, filters, queue_episode_uids, limit)
    return JournalSearchResult(episodes=episodes, entries=entries)


def create_saved_view(
    con: duckdb.DuckDBPyConnection,
    *,
    name: str,
    filters: JournalSearchFilters,
) -> str:
    """Persist one validated structured filter definition, not its results."""

    validate_search_filters(filters)
    if not table_exists(con, "journal_saved_views"):
        raise JournalPolicyError("saved views require migration 0006")
    display_name = str(name or "").strip()
    if not display_name:
        raise JournalValidationError("saved view name must not be empty")
    values = asdict(filters)
    saved_view_uid = str(uuid4())
    now = utc_now_naive()
    con.execute(
        """
        INSERT INTO journal_saved_views (
            saved_view_uid, name, normalized_name, query_text, symbol,
            source_broker, source_account_id, episode_strategy_type,
            journal_strategy_uid, review_status, review_queue, entry_type,
            date_from, date_to, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        [
            saved_view_uid,
            display_name,
            normalize_catalog_name(display_name),
            _optional_text(values["query_text"]),
            _optional_upper(values["symbol"]),
            _optional_text(values["source_broker"]),
            _optional_text(values["source_account_id"]),
            _optional_text(values["episode_strategy_type"]),
            values["journal_strategy_uid"],
            values["review_status"],
            values["review_queue"],
            values["entry_type"],
            values["date_from"],
            values["date_to"],
            now,
            now,
        ],
    )
    return saved_view_uid


def load_saved_view(
    con: duckdb.DuckDBPyConnection,
    saved_view_uid: str,
) -> tuple[str, JournalSearchFilters]:
    """Load one active saved view by stable identity."""

    saved_view_uid = _uuid(saved_view_uid, "saved_view_uid")
    row = con.execute(
        """
        SELECT name, query_text, symbol, source_broker, source_account_id,
               episode_strategy_type, journal_strategy_uid, review_status,
               review_queue, entry_type, date_from, date_to
        FROM journal_saved_views
        WHERE saved_view_uid = ? AND status = 'active'
        """,
        [saved_view_uid],
    ).fetchone()
    if row is None:
        raise JournalValidationError(f"active saved_view_uid not found: {saved_view_uid}")
    return str(row[0]), JournalSearchFilters(
        query_text=row[1],
        symbol=row[2],
        source_broker=row[3],
        source_account_id=row[4],
        episode_strategy_type=row[5],
        journal_strategy_uid=str(row[6]) if row[6] is not None else None,
        review_status=row[7],
        review_queue=row[8],
        entry_type=row[9],
        date_from=row[10],
        date_to=row[11],
    )


def list_saved_views(
    con: duckdb.DuckDBPyConnection,
) -> list[dict[str, str]]:
    """List stable identities and display names for active saved views."""

    if not table_exists(con, "journal_saved_views"):
        return []
    rows = con.execute(
        """
        SELECT saved_view_uid, name
        FROM journal_saved_views
        WHERE status = 'active'
        ORDER BY normalized_name, saved_view_uid
        """
    ).fetchall()
    return [
        {"saved_view_uid": str(saved_view_uid), "name": str(name)}
        for saved_view_uid, name in rows
    ]


def _search_episodes(
    con: duckdb.DuckDBPyConnection,
    filters: JournalSearchFilters,
    queue_episode_uids: set[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    _episode_common_clauses(filters, clauses, params)
    if filters.episode_strategy_type:
        clauses.append("lower(e.strategy_type) = lower(?)")
        params.append(filters.episode_strategy_type.strip())
    if filters.review_status:
        clauses.append("COALESCE(r.review_status, 'unreviewed') = ?")
        params.append(filters.review_status)
    if filters.entry_type:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM current_revisions cr
                WHERE cr.episode_uid = e.episode_uid AND cr.rn = 1
                  AND cr.entry_status = 'active' AND cr.entry_type = ?
            )"""
        )
        params.append(filters.entry_type)
    if filters.journal_strategy_uid:
        clauses.append(
            """EXISTS (
                SELECT 1 FROM current_revisions cr
                WHERE cr.episode_uid = e.episode_uid AND cr.rn = 1
                  AND cr.entry_status = 'active' AND cr.strategy_uid = ?
            )"""
        )
        params.append(filters.journal_strategy_uid)
    if filters.query_text:
        clauses.append(
            """(
                lower(e.primary_symbol) LIKE ? OR lower(e.strategy_label) LIKE ?
                OR EXISTS (
                    SELECT 1 FROM current_revisions cr
                    WHERE cr.episode_uid = e.episode_uid AND cr.rn = 1
                      AND cr.entry_status = 'active'
                      AND (lower(COALESCE(cr.title, '')) LIKE ? OR lower(cr.body) LIKE ?)
                )
            )"""
        )
        pattern = _like_pattern(filters.query_text)
        params.extend([pattern, pattern, pattern, pattern])
    _queue_clause(queue_episode_uids, clauses, params, "e.episode_uid")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(limit)
    return _rows(
        con,
        f"""
        WITH current_revisions AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY entry_uid ORDER BY revision_no DESC
            ) AS rn
            FROM journal_entry_revisions
        )
        SELECT e.episode_uid, e.source_broker, e.source_account_id,
               e.primary_symbol, e.strategy_type, e.strategy_label,
               e.opened_at, e.status AS episode_status,
               COALESCE(r.review_status, 'unreviewed') AS review_status,
               COALESCE(r.setup_quality, 'unknown') AS setup_quality
        FROM trade_episodes e
        LEFT JOIN manual_reviews r ON r.episode_uid = e.episode_uid
        {where}
        ORDER BY e.opened_at DESC, e.episode_uid
        LIMIT ?
        """,
        params,
    )


def _search_entries(
    con: duckdb.DuckDBPyConnection,
    filters: JournalSearchFilters,
    queue_episode_uids: set[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    clauses = ["cr.rn = 1", "cr.entry_status = 'active'"]
    params: list[Any] = []
    if filters.symbol:
        clauses.append("upper(e.primary_symbol) = upper(?)")
        params.append(filters.symbol.strip())
    if filters.source_broker:
        clauses.append("lower(e.source_broker) = lower(?)")
        params.append(filters.source_broker.strip())
    if filters.source_account_id:
        clauses.append("e.source_account_id = ?")
        params.append(filters.source_account_id.strip())
    if filters.episode_strategy_type:
        clauses.append("lower(e.strategy_type) = lower(?)")
        params.append(filters.episode_strategy_type.strip())
    if filters.journal_strategy_uid:
        clauses.append("cr.strategy_uid = ?")
        params.append(filters.journal_strategy_uid)
    if filters.review_status:
        clauses.append("COALESCE(r.review_status, 'unreviewed') = ?")
        params.append(filters.review_status)
    if filters.entry_type:
        clauses.append("cr.entry_type = ?")
        params.append(filters.entry_type)
    if filters.date_from:
        clauses.append("CAST(COALESCE(cr.occurred_at, cr.created_at) AS DATE) >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("CAST(COALESCE(cr.occurred_at, cr.created_at) AS DATE) <= ?")
        params.append(filters.date_to)
    if filters.query_text:
        pattern = _like_pattern(filters.query_text)
        clauses.append(
            """(
                lower(COALESCE(cr.title, '')) LIKE ? OR lower(cr.body) LIKE ?
                OR lower(COALESCE(e.primary_symbol, '')) LIKE ?
                OR lower(COALESCE(s.name, '')) LIKE ?
            )"""
        )
        params.extend([pattern, pattern, pattern, pattern])
    _queue_clause(queue_episode_uids, clauses, params, "cr.episode_uid")
    params.append(limit)
    return _rows(
        con,
        f"""
        WITH current_revisions AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY entry_uid ORDER BY revision_no DESC
            ) AS rn
            FROM journal_entry_revisions
        )
        SELECT cr.entry_uid, cr.revision_no, cr.episode_uid, cr.entry_type,
               cr.strategy_uid, s.name AS journal_strategy_name, cr.title,
               cr.body, cr.occurred_at, cr.created_at,
               e.primary_symbol, e.source_broker, e.source_account_id,
               e.strategy_type AS episode_strategy_type,
               COALESCE(r.review_status, 'unreviewed') AS review_status
        FROM current_revisions cr
        LEFT JOIN trade_episodes e ON e.episode_uid = cr.episode_uid
        LEFT JOIN manual_reviews r ON r.episode_uid = cr.episode_uid
        LEFT JOIN journal_strategies s ON s.strategy_uid = cr.strategy_uid
        WHERE {' AND '.join(clauses)}
        ORDER BY COALESCE(cr.occurred_at, cr.created_at) DESC, cr.entry_uid
        LIMIT ?
        """,
        params,
    )


def _episode_common_clauses(
    filters: JournalSearchFilters,
    clauses: list[str],
    params: list[Any],
) -> None:
    if filters.symbol:
        clauses.append("upper(e.primary_symbol) = upper(?)")
        params.append(filters.symbol.strip())
    if filters.source_broker:
        clauses.append("lower(e.source_broker) = lower(?)")
        params.append(filters.source_broker.strip())
    if filters.source_account_id:
        clauses.append("e.source_account_id = ?")
        params.append(filters.source_account_id.strip())
    if filters.date_from:
        clauses.append("CAST(e.opened_at AS DATE) >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("CAST(e.opened_at AS DATE) <= ?")
        params.append(filters.date_to)


def _queue_clause(
    episode_uids: set[str] | None,
    clauses: list[str],
    params: list[Any],
    column: str,
) -> None:
    if episode_uids is None:
        return
    if not episode_uids:
        clauses.append("FALSE")
        return
    ordered = sorted(episode_uids)
    clauses.append(f"{column} IN ({', '.join('?' for _ in ordered)})")
    params.extend(ordered)


def _rows(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any],
) -> list[dict[str, Any]]:
    result = con.execute(sql, params)
    columns = [column[0] for column in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def _like_pattern(value: str) -> str:
    return f"%{str(value).strip().casefold()}%"


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _optional_upper(value: Any) -> str | None:
    normalized = _optional_text(value)
    return normalized.upper() if normalized is not None else None


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise JournalValidationError(f"{field} must be a valid UUID") from exc
