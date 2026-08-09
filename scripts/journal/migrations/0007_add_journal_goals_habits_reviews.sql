-- Migration 0007: add process goals, habits, and explicit-period reviews.
-- Purpose: safe UXJ-06 foundation without inventing financial metric policy.
--
-- Start state:
--   - Migration version 0006 is applied.
--   - Durable entries and structured saved views exist.
--
-- Expected effect:
--   - add active/archived process goals and habits.
--   - add append-only goal check-ins, habit events, and recurring review events.
--   - require explicit date periods; do not choose timezone/week boundaries.
--   - do not evaluate P&L, returns, or financial targets.
--
-- Rollback strategy:
--   - restore a verified pre-migration backup before post-migration writes, or
--     use a separately reviewed forward corrective migration.

CREATE TABLE journal_goals (
    goal_uid UUID PRIMARY KEY DEFAULT (uuid()),
    name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL UNIQUE,
    description VARCHAR,
    cadence VARCHAR NOT NULL,
    target_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CHECK (cadence IN ('weekly', 'monthly')),
    CHECK (target_count > 0),
    CHECK (status IN ('active', 'archived'))
);

CREATE TABLE journal_goal_checkins (
    checkin_uid UUID PRIMARY KEY DEFAULT (uuid()),
    goal_uid UUID NOT NULL REFERENCES journal_goals(goal_uid),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    sequence_no INTEGER NOT NULL,
    completed_count INTEGER NOT NULL,
    result_status VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (goal_uid, period_start, period_end, sequence_no),
    CHECK (period_start <= period_end),
    CHECK (sequence_no > 0),
    CHECK (completed_count >= 0),
    CHECK (result_status IN ('pending', 'met', 'not_met', 'unavailable')),
    CHECK (source IN ('streamlit', 'operator', 'api'))
);

CREATE TABLE journal_habits (
    habit_uid UUID PRIMARY KEY DEFAULT (uuid()),
    name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL UNIQUE,
    description VARCHAR,
    cadence VARCHAR NOT NULL,
    target_count INTEGER NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CHECK (cadence IN ('daily', 'weekly', 'monthly')),
    CHECK (target_count > 0),
    CHECK (status IN ('active', 'archived'))
);

CREATE TABLE journal_habit_events (
    habit_event_uid UUID PRIMARY KEY DEFAULT (uuid()),
    habit_uid UUID NOT NULL REFERENCES journal_habits(habit_uid),
    occurred_on DATE NOT NULL,
    sequence_no INTEGER NOT NULL,
    action VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (habit_uid, occurred_on, sequence_no),
    CHECK (sequence_no > 0),
    CHECK (action IN ('complete', 'revoke')),
    CHECK (source IN ('streamlit', 'operator', 'api'))
);

CREATE TABLE journal_review_period_events (
    review_period_event_uid UUID PRIMARY KEY DEFAULT (uuid()),
    cadence VARCHAR NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    due_date DATE NOT NULL,
    sequence_no INTEGER NOT NULL,
    action VARCHAR NOT NULL,
    entry_uid UUID REFERENCES journal_entries(entry_uid),
    source VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (cadence, period_start, period_end, sequence_no),
    CHECK (cadence IN ('weekly', 'monthly')),
    CHECK (period_start <= period_end),
    CHECK (due_date >= period_end),
    CHECK (sequence_no > 0),
    CHECK (action IN ('schedule', 'complete', 'reopen', 'skip')),
    CHECK (
        (action = 'complete' AND entry_uid IS NOT NULL)
        OR (action <> 'complete' AND entry_uid IS NULL)
    ),
    CHECK (source IN ('streamlit', 'operator', 'api'))
);

CREATE INDEX idx_journal_goal_checkins_period
  ON journal_goal_checkins (goal_uid, period_start, period_end);

CREATE INDEX idx_journal_habit_events_date
  ON journal_habit_events (habit_uid, occurred_on);

CREATE INDEX idx_journal_review_period_events_period
  ON journal_review_period_events (cadence, period_start, period_end);
