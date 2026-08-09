"""Process goals, habits, and explicit-period review workflows.

This foundation deliberately excludes financial-goal evaluation. Period dates
must be supplied explicitly so no timezone, week-start, or month-boundary
policy is silently introduced.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import duckdb

from .domain import (
    JournalIntegrityError,
    JournalPolicyError,
    JournalValidationError,
    get_current_entry_revision,
    normalize_catalog_name,
    utc_now_naive,
)


GOAL_CADENCES = frozenset({"weekly", "monthly"})
HABIT_CADENCES = frozenset({"daily", "weekly", "monthly"})
ROUTINE_SOURCES = frozenset({"streamlit", "operator", "api"})
HABIT_ACTIONS = frozenset({"complete", "revoke"})
REVIEW_PERIOD_ACTIONS = frozenset({"schedule", "complete", "reopen", "skip"})


def create_process_goal(
    con: duckdb.DuckDBPyConnection,
    *,
    name: str,
    cadence: str,
    target_count: int,
    description: str = "",
    created_at: datetime | None = None,
) -> str:
    """Create a non-financial count goal such as three reviews per week."""

    display_name = _required_text(name, "name")
    _enum(cadence, GOAL_CADENCES, "cadence")
    _positive_int(target_count, "target_count")
    goal_uid = str(uuid4())
    timestamp = _timestamp(created_at)
    con.execute(
        """
        INSERT INTO journal_goals (
            goal_uid, name, normalized_name, description, cadence,
            target_count, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        [
            goal_uid,
            display_name,
            normalize_catalog_name(display_name),
            _optional_text(description),
            cadence,
            target_count,
            timestamp,
            timestamp,
        ],
    )
    return goal_uid


def record_goal_checkin(
    con: duckdb.DuckDBPyConnection,
    *,
    goal_uid: str,
    period_start: date,
    period_end: date,
    completed_count: int,
    source: str,
    evidence_available: bool = True,
    created_at: datetime | None = None,
) -> str:
    """Append a process-goal check-in with result derived from target count."""

    goal_uid = _uuid(goal_uid, "goal_uid")
    _period(period_start, period_end)
    _nonnegative_int(completed_count, "completed_count")
    _enum(source, ROUTINE_SOURCES, "source")
    goal = con.execute(
        "SELECT target_count, status FROM journal_goals WHERE goal_uid = ?",
        [goal_uid],
    ).fetchone()
    if goal is None or goal[1] != "active":
        raise JournalValidationError(f"active goal_uid not found: {goal_uid}")
    result_status = "unavailable" if not evidence_available else (
        "met" if completed_count >= int(goal[0]) else "not_met"
    )
    sequence_no = _next_sequence(
        con,
        "journal_goal_checkins",
        "goal_uid = ? AND period_start = ? AND period_end = ?",
        [goal_uid, period_start, period_end],
    )
    checkin_uid = str(uuid4())
    con.execute(
        """
        INSERT INTO journal_goal_checkins (
            checkin_uid, goal_uid, period_start, period_end, sequence_no,
            completed_count, result_status, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            checkin_uid,
            goal_uid,
            period_start,
            period_end,
            sequence_no,
            completed_count,
            result_status,
            source,
            _timestamp(created_at),
        ],
    )
    return checkin_uid


def create_habit(
    con: duckdb.DuckDBPyConnection,
    *,
    name: str,
    cadence: str,
    target_count: int,
    description: str = "",
    created_at: datetime | None = None,
) -> str:
    display_name = _required_text(name, "name")
    _enum(cadence, HABIT_CADENCES, "cadence")
    _positive_int(target_count, "target_count")
    habit_uid = str(uuid4())
    timestamp = _timestamp(created_at)
    con.execute(
        """
        INSERT INTO journal_habits (
            habit_uid, name, normalized_name, description, cadence,
            target_count, status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        [
            habit_uid,
            display_name,
            normalize_catalog_name(display_name),
            _optional_text(description),
            cadence,
            target_count,
            timestamp,
            timestamp,
        ],
    )
    return habit_uid


def record_habit_event(
    con: duckdb.DuckDBPyConnection,
    *,
    habit_uid: str,
    occurred_on: date,
    action: str,
    source: str,
    created_at: datetime | None = None,
) -> str:
    """Append completion/revocation history for one habit and calendar date."""

    habit_uid = _uuid(habit_uid, "habit_uid")
    _enum(action, HABIT_ACTIONS, "action")
    _enum(source, ROUTINE_SOURCES, "source")
    if con.execute(
        "SELECT COUNT(*) FROM journal_habits WHERE habit_uid = ? AND status = 'active'",
        [habit_uid],
    ).fetchone()[0] != 1:
        raise JournalValidationError(f"active habit_uid not found: {habit_uid}")
    current = con.execute(
        """
        SELECT sequence_no, action FROM journal_habit_events
        WHERE habit_uid = ? AND occurred_on = ?
        ORDER BY sequence_no DESC LIMIT 1
        """,
        [habit_uid, occurred_on],
    ).fetchone()
    if current is None and action != "complete":
        raise JournalValidationError("first habit event must be complete")
    if current is not None and current[1] == action:
        raise JournalValidationError(f"habit is already in action state {action}")
    sequence_no = 1 if current is None else int(current[0]) + 1
    event_uid = str(uuid4())
    con.execute(
        """
        INSERT INTO journal_habit_events (
            habit_event_uid, habit_uid, occurred_on, sequence_no,
            action, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            event_uid,
            habit_uid,
            occurred_on,
            sequence_no,
            action,
            source,
            _timestamp(created_at),
        ],
    )
    return event_uid


def record_review_period_event(
    con: duckdb.DuckDBPyConnection,
    *,
    cadence: str,
    period_start: date,
    period_end: date,
    due_date: date,
    action: str,
    source: str,
    entry_uid: str | None = None,
    created_at: datetime | None = None,
) -> str:
    """Append an explicitly bounded weekly/monthly review state transition."""

    _enum(cadence, GOAL_CADENCES, "cadence")
    _enum(action, REVIEW_PERIOD_ACTIONS, "action")
    _enum(source, ROUTINE_SOURCES, "source")
    _period(period_start, period_end)
    if due_date < period_end:
        raise JournalValidationError("due_date must not be earlier than period_end")
    entry_uid = _uuid(entry_uid, "entry_uid") if entry_uid is not None else None
    if action == "complete":
        if entry_uid is None:
            raise JournalValidationError("complete review-period event requires entry_uid")
        current_revision = get_current_entry_revision(con, entry_uid)
        expected_type = f"{cadence}_review"
        if current_revision.entry_type != expected_type:
            raise JournalValidationError(
                f"{cadence} review completion requires entry_type {expected_type}"
            )
    elif entry_uid is not None:
        raise JournalValidationError("entry_uid is allowed only for complete review-period events")

    current = con.execute(
        """
        SELECT sequence_no, action FROM journal_review_period_events
        WHERE cadence = ? AND period_start = ? AND period_end = ?
        ORDER BY sequence_no DESC LIMIT 1
        """,
        [cadence, period_start, period_end],
    ).fetchone()
    _validate_period_transition(current[1] if current else None, action)
    sequence_no = 1 if current is None else int(current[0]) + 1
    event_uid = str(uuid4())
    con.execute(
        """
        INSERT INTO journal_review_period_events (
            review_period_event_uid, cadence, period_start, period_end,
            due_date, sequence_no, action, entry_uid, source, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            event_uid,
            cadence,
            period_start,
            period_end,
            due_date,
            sequence_no,
            action,
            entry_uid,
            source,
            _timestamp(created_at),
        ],
    )
    return event_uid


def evaluate_financial_goal(*_: Any, **__: Any) -> None:
    """Fail closed until canonical metric and reporting policy is approved."""

    raise JournalPolicyError(
        "financial goal evaluation is disabled pending PNL-02 and PNL-07 policy"
    )


def _validate_period_transition(current_action: str | None, new_action: str) -> None:
    allowed = {
        None: {"schedule"},
        "schedule": {"complete", "skip"},
        "complete": {"reopen"},
        "skip": {"reopen"},
        "reopen": {"complete", "skip"},
    }
    if new_action not in allowed[current_action]:
        raise JournalValidationError(
            f"invalid review-period transition: {current_action or 'none'} -> {new_action}"
        )


def _next_sequence(
    con: duckdb.DuckDBPyConnection,
    table: str,
    where: str,
    params: list[Any],
) -> int:
    row = con.execute(
        f"SELECT COALESCE(MAX(sequence_no), 0) FROM {table} WHERE {where}",
        params,
    ).fetchone()
    if row is None:
        raise JournalIntegrityError(f"cannot determine sequence for {table}")
    return int(row[0]) + 1


def _period(period_start: date, period_end: date) -> None:
    if not isinstance(period_start, date) or not isinstance(period_end, date):
        raise JournalValidationError("period_start and period_end must be dates")
    if period_start > period_end:
        raise JournalValidationError("period_start must not be later than period_end")


def _enum(value: str, allowed: frozenset[str], field: str) -> None:
    if value not in allowed:
        raise JournalValidationError(f"{field} must be one of {sorted(allowed)}")


def _required_text(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise JournalValidationError(f"{field} must not be empty")
    return normalized


def _optional_text(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _positive_int(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise JournalValidationError(f"{field} must be a positive integer")


def _nonnegative_int(value: Any, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise JournalValidationError(f"{field} must be a non-negative integer")


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, AttributeError) as exc:
        raise JournalValidationError(f"{field} must be a valid UUID") from exc


def _timestamp(value: datetime | None) -> datetime:
    if value is None:
        return utc_now_naive()
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)
