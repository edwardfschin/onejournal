-- Migration 0006: add private single-owner saved journal views.
-- Purpose: UXJ-04 search/filter persistence on top of ADR-0008.
--
-- Start state:
--   - Migration version 0005 is applied.
--   - Durable journal entries, strategies, tags, and reviews exist.
--
-- Expected effect:
--   - add structured, validated saved filter definitions.
--   - store no query results, journal prose, broker payload, or attachment key.
--   - preserve every existing table and row.
--
-- Rollback strategy:
--   - restore a verified pre-migration backup before post-migration writes, or
--     use a separately reviewed forward corrective migration.

CREATE TABLE journal_saved_views (
    saved_view_uid UUID PRIMARY KEY DEFAULT (uuid()),
    name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL UNIQUE,
    query_text VARCHAR,
    symbol VARCHAR,
    source_broker VARCHAR,
    source_account_id VARCHAR,
    episode_strategy_type VARCHAR,
    journal_strategy_uid UUID REFERENCES journal_strategies(strategy_uid),
    review_status VARCHAR,
    review_queue VARCHAR,
    entry_type VARCHAR,
    date_from DATE,
    date_to DATE,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CHECK (review_status IS NULL OR review_status IN (
        'unreviewed', 'needs_review', 'mistake_review', 'reviewed'
    )),
    CHECK (review_queue IS NULL OR review_queue IN (
        'unreviewed', 'incomplete', 'risk_flagged', 'mistake'
    )),
    CHECK (entry_type IS NULL OR entry_type IN (
        'pre_trade_plan', 'entry_thesis', 'execution_review', 'exit_review',
        'post_trade_reflection', 'weekly_review', 'monthly_review',
        'mistake', 'lesson', 'note'
    )),
    CHECK (status IN ('active', 'archived')),
    CHECK (date_from IS NULL OR date_to IS NULL OR date_from <= date_to)
);

CREATE INDEX idx_journal_saved_views_status
  ON journal_saved_views (status, normalized_name);
