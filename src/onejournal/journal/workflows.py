"""Deterministic, read-only journal review queues and search helpers.

The helpers read canonical DuckDB journal state. They do not publish private
journal prose, write database rows, call brokers, or enable execution.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import duckdb

from .domain import table_exists


REVIEW_QUEUE_NAMES = (
    "unreviewed",
    "incomplete",
    "risk_flagged",
    "mistake",
)


def build_review_queues(
    con: duckdb.DuckDBPyConnection,
    *,
    asof: date | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return deterministic episode queues with explicit membership reasons.

    Queue membership uses the current `manual_reviews` projection so the
    function remains compatible before migration 0005. When the durable domain
    tables exist, active mistake entries and current tag assignments add
    evidence without exposing their private narrative.
    """

    params: list[Any] = []
    where = ""
    if asof is not None:
        where = "WHERE CAST(e.opened_at AS DATE) <= ?"
        params.append(asof)
    rows = _rows(
        con,
        f"""
        SELECT
            e.episode_uid, e.source_broker, e.source_account_id,
            e.primary_symbol, e.opened_at, e.status,
            COALESCE(r.review_status, 'unreviewed') AS review_status,
            COALESCE(r.setup_quality, 'unknown') AS setup_quality,
            CASE WHEN r.episode_uid IS NULL THEN FALSE ELSE TRUE END AS has_review
        FROM trade_episodes e
        LEFT JOIN manual_reviews r ON r.episode_uid = e.episode_uid
        {where}
        ORDER BY e.opened_at DESC, e.episode_uid
        """,
        params,
    )

    mistake_entry_episodes: set[str] = set()
    mistake_tag_episodes: set[str] = set()
    risk_tag_episodes: set[str] = set()
    if table_exists(con, "journal_entry_revisions"):
        mistake_entry_episodes = _active_entry_episodes(con, entry_type="mistake")
    if table_exists(con, "journal_entry_tag_events"):
        mistake_tag_episodes, risk_tag_episodes = _active_tag_episodes(con)

    queues = {name: [] for name in REVIEW_QUEUE_NAMES}
    for row in rows:
        episode_uid = str(row["episode_uid"])
        common = {
            "episode_uid": episode_uid,
            "source_broker": str(row["source_broker"]),
            "source_account_id": str(row["source_account_id"]),
            "primary_symbol": str(row["primary_symbol"]),
            "opened_at": _iso(row["opened_at"]),
            "episode_status": str(row["status"]),
            "review_status": str(row["review_status"]),
            "setup_quality": str(row["setup_quality"]),
        }

        unreviewed_reasons: list[str] = []
        if not bool(row["has_review"]):
            unreviewed_reasons.append("missing_review")
        elif row["review_status"] == "unreviewed":
            unreviewed_reasons.append("unreviewed_status")
        _append_queue_item(queues["unreviewed"], common, unreviewed_reasons)

        incomplete_reasons: list[str] = []
        if row["review_status"] == "needs_review":
            incomplete_reasons.append("needs_review_status")
        _append_queue_item(queues["incomplete"], common, incomplete_reasons)

        risk_reasons: list[str] = []
        if row["setup_quality"] == "poor":
            risk_reasons.append("poor_setup_quality")
        if row["setup_quality"] == "mistake":
            risk_reasons.append("mistake_setup_quality")
        if row["review_status"] == "mistake_review":
            risk_reasons.append("mistake_review_status")
        if episode_uid in risk_tag_episodes:
            risk_reasons.append("active_risk_tag")
        if episode_uid in mistake_entry_episodes:
            risk_reasons.append("active_mistake_entry")
        if episode_uid in mistake_tag_episodes:
            risk_reasons.append("active_mistake_tag")
        _append_queue_item(queues["risk_flagged"], common, risk_reasons)

        mistake_reasons: list[str] = []
        if row["setup_quality"] == "mistake":
            mistake_reasons.append("mistake_setup_quality")
        if row["review_status"] == "mistake_review":
            mistake_reasons.append("mistake_review_status")
        if episode_uid in mistake_entry_episodes:
            mistake_reasons.append("active_mistake_entry")
        if episode_uid in mistake_tag_episodes:
            mistake_reasons.append("active_mistake_tag")
        _append_queue_item(queues["mistake"], common, mistake_reasons)

    return queues


def flatten_review_queues(
    queues: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten queues while retaining queue name and deterministic ordering."""

    flattened: list[dict[str, Any]] = []
    for queue_name in REVIEW_QUEUE_NAMES:
        for item in queues.get(queue_name, []):
            flattened.append({"queue": queue_name, **item})
    return flattened


def _active_entry_episodes(
    con: duckdb.DuckDBPyConnection,
    *,
    entry_type: str,
) -> set[str]:
    rows = con.execute(
        """
        WITH current_revisions AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY entry_uid ORDER BY revision_no DESC
            ) AS rn
            FROM journal_entry_revisions
        )
        SELECT DISTINCT episode_uid
        FROM current_revisions
        WHERE rn = 1 AND entry_status = 'active' AND entry_type = ?
          AND episode_uid IS NOT NULL
        """,
        [entry_type],
    ).fetchall()
    return {str(row[0]) for row in rows}


def _active_tag_episodes(
    con: duckdb.DuckDBPyConnection,
) -> tuple[set[str], set[str]]:
    rows = con.execute(
        """
        WITH current_revisions AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY entry_uid ORDER BY revision_no DESC
            ) AS rn
            FROM journal_entry_revisions
        ),
        current_tag_events AS (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY entry_uid, tag_uid ORDER BY sequence_no DESC
            ) AS rn
            FROM journal_entry_tag_events
        )
        SELECT DISTINCT r.episode_uid, t.tag_type, t.normalized_name
        FROM current_tag_events e
        JOIN current_revisions r ON r.entry_uid = e.entry_uid AND r.rn = 1
        JOIN journal_tags t ON t.tag_uid = e.tag_uid
        WHERE e.rn = 1 AND e.action = 'assign'
          AND r.entry_status = 'active' AND r.episode_uid IS NOT NULL
          AND t.status = 'active'
        """
    ).fetchall()
    mistake = {str(episode_uid) for episode_uid, tag_type, _ in rows if tag_type == "mistake"}
    risk = {
        str(episode_uid)
        for episode_uid, tag_type, normalized_name in rows
        if tag_type == "general" and normalized_name == "risk"
    }
    return mistake, risk


def _rows(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: list[Any],
) -> list[dict[str, Any]]:
    result = con.execute(sql, params)
    columns = [column[0] for column in result.description]
    return [dict(zip(columns, row)) for row in result.fetchall()]


def _append_queue_item(
    queue: list[dict[str, Any]],
    common: dict[str, Any],
    reason_codes: list[str],
) -> None:
    if reason_codes:
        queue.append({**common, "reason_codes": reason_codes})


def _iso(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)
