"""Deterministic, read-only journal review queues and search helpers.

The helpers read canonical DuckDB journal state. They do not publish private
journal prose, write database rows, call brokers, or enable execution.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import duckdb

from .domain import current_journal_relation, table_exists


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

    episode_relation = current_journal_relation(con, "trade_episodes")
    materialized_relation = current_journal_relation(
        con, "phase1_journal_materialized_episodes"
    )
    projected_relation = current_journal_relation(
        con, "phase1_journal_projected_episodes"
    )
    lifecycle_state_relation = current_journal_relation(
        con, "phase1_journal_episode_lifecycle_states"
    )
    lifecycle_run_relation = current_journal_relation(
        con, "phase1_journal_lifecycle_reconciliation_runs"
    )
    params: list[Any] = []
    where = ""
    if asof is not None:
        where = "WHERE CAST(e.opened_at AS DATE) <= ?"
        params.append(asof)
    if table_exists(con, "phase1_journal_materialized_episodes"):
        materialization_fields = """
            COALESCE(m.lifecycle_quality, 'legacy_unverified') AS lifecycle_quality,
            COALESCE(m.reason_code, CASE WHEN m.episode_uid IS NULL
              THEN 'legacy_episode_unverified' ELSE NULL END) AS lifecycle_reason
        """
        materialization_join = f"""
            LEFT JOIN {materialized_relation} m
              ON m.episode_uid = e.episode_uid
        """
        base_lifecycle_quality = "COALESCE(m.lifecycle_quality, 'legacy_unverified')"
        base_lifecycle_reason = (
            "COALESCE(m.reason_code, CASE WHEN m.episode_uid IS NULL "
            "THEN 'legacy_episode_unverified' ELSE NULL END)"
        )
    else:
        materialization_fields = """
            'legacy_unverified' AS lifecycle_quality,
            'legacy_episode_unverified' AS lifecycle_reason
        """
        materialization_join = ""
        base_lifecycle_quality = "'legacy_unverified'"
        base_lifecycle_reason = "'legacy_episode_unverified'"
    if table_exists(con, "phase1_journal_episode_lifecycle_states"):
        lifecycle_state_fields = f"""
            COALESCE(ls.reconciled_status, e.status) AS episode_status,
            COALESCE(ls.lifecycle_quality, {base_lifecycle_quality}) AS effective_lifecycle_quality,
            COALESCE(ls.reason_code, {base_lifecycle_reason}) AS effective_lifecycle_reason
        """
        lifecycle_state_join = f"""
            LEFT JOIN (
                SELECT states.*, ROW_NUMBER() OVER (
                    PARTITION BY states.episode_uid
                    ORDER BY runs.asof_date DESC, runs.reconciled_at DESC,
                             states.reconciliation_uid DESC
                ) AS rn
                FROM {lifecycle_state_relation} states
                JOIN {lifecycle_run_relation} runs
                  ON runs.reconciliation_uid = states.reconciliation_uid
            ) ls ON ls.episode_uid = e.episode_uid AND ls.rn = 1
        """
    else:
        lifecycle_state_fields = f"""
            e.status AS episode_status,
            {base_lifecycle_quality} AS effective_lifecycle_quality,
            {base_lifecycle_reason} AS effective_lifecycle_reason
        """
        lifecycle_state_join = ""
    if table_exists(con, "phase1_journal_projected_episodes"):
        projection_fields = """
            COALESCE(p.instrument_summary, 'Unverified legacy grouping')
              AS instrument_summary
        """
        projection_join = f"""
            LEFT JOIN {projected_relation} p
              ON p.episode_uid = e.episode_uid
        """
    else:
        projection_fields = "'Unverified legacy grouping' AS instrument_summary"
        projection_join = ""
    rows = _rows(
        con,
        f"""
        SELECT
            e.episode_uid, e.source_broker, e.source_account_id,
            e.primary_symbol, e.asset_class, e.opened_at,
            COALESCE(r.review_status, 'unreviewed') AS review_status,
            COALESCE(r.setup_quality, 'unknown') AS setup_quality,
            CASE WHEN r.episode_uid IS NULL THEN FALSE ELSE TRUE END AS has_review,
            {materialization_fields},
            {lifecycle_state_fields},
            {projection_fields}
        FROM {episode_relation} e
        LEFT JOIN manual_reviews r ON r.episode_uid = e.episode_uid
        {materialization_join}
        {lifecycle_state_join}
        {projection_join}
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
            "asset_class": str(row["asset_class"]),
            "instrument_summary": str(row["instrument_summary"]),
            "opened_at": _iso(row["opened_at"]),
            "episode_status": str(row["episode_status"]),
            "review_status": str(row["review_status"]),
            "setup_quality": str(row["setup_quality"]),
            "lifecycle_quality": str(row["effective_lifecycle_quality"]),
            "lifecycle_reason": (
                str(row["effective_lifecycle_reason"])
                if row["effective_lifecycle_reason"] is not None
                else None
            ),
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
        if row["effective_lifecycle_quality"] == "review_required":
            incomplete_reasons.append(str(row["effective_lifecycle_reason"]))
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
