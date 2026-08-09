from __future__ import annotations

import tempfile
import unittest
from datetime import date
from pathlib import Path

import duckdb

from onejournal.journal.domain import JournalPolicyError, JournalValidationError, create_entry
from onejournal.journal.routines import (
    create_habit,
    create_process_goal,
    evaluate_financial_goal,
    record_goal_checkin,
    record_habit_event,
    record_review_period_event,
)
from scripts.journal.init_journal_db import init_schema


class JournalRoutineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = Path(self.tmp.name) / "journal.duckdb"
        init_schema(self.db_path)

    def test_process_goal_checkins_derive_status_and_preserve_corrections(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            goal_uid = create_process_goal(
                con,
                name="Review three trades",
                cadence="weekly",
                target_count=3,
            )
            record_goal_checkin(
                con,
                goal_uid=goal_uid,
                period_start=date(2026, 1, 5),
                period_end=date(2026, 1, 11),
                completed_count=2,
                source="operator",
            )
            record_goal_checkin(
                con,
                goal_uid=goal_uid,
                period_start=date(2026, 1, 5),
                period_end=date(2026, 1, 11),
                completed_count=3,
                source="operator",
            )
            rows = con.execute(
                """
                SELECT sequence_no, completed_count, result_status
                FROM journal_goal_checkins ORDER BY sequence_no
                """
            ).fetchall()
        self.assertEqual(rows, [(1, 2, "not_met"), (2, 3, "met")])

    def test_habit_events_are_append_only_state_transitions(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            habit_uid = create_habit(
                con,
                name="Write a trade reflection",
                cadence="daily",
                target_count=1,
            )
            record_habit_event(
                con,
                habit_uid=habit_uid,
                occurred_on=date(2026, 1, 5),
                action="complete",
                source="streamlit",
            )
            with self.assertRaisesRegex(JournalValidationError, "already"):
                record_habit_event(
                    con,
                    habit_uid=habit_uid,
                    occurred_on=date(2026, 1, 5),
                    action="complete",
                    source="streamlit",
                )
            record_habit_event(
                con,
                habit_uid=habit_uid,
                occurred_on=date(2026, 1, 5),
                action="revoke",
                source="streamlit",
            )
            rows = con.execute(
                "SELECT sequence_no, action FROM journal_habit_events ORDER BY sequence_no"
            ).fetchall()
        self.assertEqual(rows, [(1, "complete"), (2, "revoke")])

    def test_review_period_requires_explicit_boundaries_and_matching_entry(self) -> None:
        with duckdb.connect(str(self.db_path)) as con:
            record_review_period_event(
                con,
                cadence="weekly",
                period_start=date(2026, 1, 5),
                period_end=date(2026, 1, 11),
                due_date=date(2026, 1, 12),
                action="schedule",
                source="operator",
            )
            wrong_entry = create_entry(
                con,
                entry_type="note",
                body="not a weekly review",
                created_source="operator",
            )
            with self.assertRaisesRegex(JournalValidationError, "weekly_review"):
                record_review_period_event(
                    con,
                    cadence="weekly",
                    period_start=date(2026, 1, 5),
                    period_end=date(2026, 1, 11),
                    due_date=date(2026, 1, 12),
                    action="complete",
                    entry_uid=wrong_entry.entry_uid,
                    source="operator",
                )
            review_entry = create_entry(
                con,
                entry_type="weekly_review",
                body="Private weekly reflection.",
                created_source="operator",
            )
            record_review_period_event(
                con,
                cadence="weekly",
                period_start=date(2026, 1, 5),
                period_end=date(2026, 1, 11),
                due_date=date(2026, 1, 12),
                action="complete",
                entry_uid=review_entry.entry_uid,
                source="operator",
            )
            rows = con.execute(
                "SELECT sequence_no, action, entry_uid FROM journal_review_period_events ORDER BY sequence_no"
            ).fetchall()
        self.assertEqual([row[0:2] for row in rows], [(1, "schedule"), (2, "complete")])
        self.assertIsNone(rows[0][2])
        self.assertEqual(str(rows[1][2]), review_entry.entry_uid)

    def test_financial_goal_evaluation_fails_closed(self) -> None:
        with self.assertRaisesRegex(JournalPolicyError, "PNL-02 and PNL-07"):
            evaluate_financial_goal()


if __name__ == "__main__":
    unittest.main()
