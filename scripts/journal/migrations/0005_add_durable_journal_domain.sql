-- Migration 0005: add the durable single-owner journal domain.
-- Purpose: UXJ-01 and accepted ADR-0008.
--
-- Start state:
--   - Migration version 0004 is applied.
--   - `manual_reviews` remains the current Streamlit compatibility projection.
--
-- Expected effect:
--   - add stable journal entry identities and append-only entry revisions.
--   - add append-only structured review events and backfill current reviews once.
--   - add owner-defined strategies, typed tags, tag events, and disabled-by-policy
--     attachment metadata.
--   - preserve every existing table and row.
--
-- Producer/consumer impact:
--   - Save Review dual-writes `journal_reviews` and `manual_reviews` atomically.
--   - the current dashboard continues reading `manual_reviews`.
--   - imports/replays must preserve all new journal tables.
--
-- Rollback strategy:
--   - restore a verified pre-migration backup before post-migration writes, or
--     use a separately reviewed forward corrective migration.
--   - no destructive down migration is provided.

CREATE TABLE journal_entries (
    entry_uid UUID PRIMARY KEY DEFAULT (uuid()),
    created_at TIMESTAMP NOT NULL,
    created_source VARCHAR NOT NULL,
    CHECK (created_source IN ('streamlit', 'import', 'operator', 'api'))
);

CREATE TABLE journal_strategies (
    strategy_uid UUID PRIMARY KEY DEFAULT (uuid()),
    name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL UNIQUE,
    description VARCHAR,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP NOT NULL,
    CHECK (status IN ('active', 'archived'))
);

CREATE TABLE journal_entry_revisions (
    entry_uid UUID NOT NULL REFERENCES journal_entries(entry_uid),
    revision_no INTEGER NOT NULL,
    episode_uid VARCHAR,
    entry_type VARCHAR NOT NULL,
    strategy_uid UUID REFERENCES journal_strategies(strategy_uid),
    title VARCHAR,
    body VARCHAR NOT NULL,
    occurred_at TIMESTAMP,
    entry_status VARCHAR NOT NULL,
    change_reason VARCHAR,
    created_at TIMESTAMP NOT NULL,
    PRIMARY KEY (entry_uid, revision_no),
    CHECK (revision_no > 0),
    CHECK (entry_type IN (
        'pre_trade_plan', 'entry_thesis', 'execution_review', 'exit_review',
        'post_trade_reflection', 'weekly_review', 'monthly_review',
        'mistake', 'lesson', 'note'
    )),
    CHECK (entry_status IN ('active', 'archived'))
);

CREATE TABLE journal_reviews (
    review_uid UUID PRIMARY KEY DEFAULT (uuid()),
    episode_uid VARCHAR NOT NULL,
    review_status VARCHAR NOT NULL,
    setup_quality VARCHAR NOT NULL,
    entry_reason VARCHAR,
    notes VARCHAR,
    supersedes_review_uid UUID UNIQUE REFERENCES journal_reviews(review_uid),
    source VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    CHECK (review_status IN ('unreviewed', 'needs_review', 'mistake_review', 'reviewed')),
    CHECK (setup_quality IN ('unknown', 'good', 'acceptable', 'poor', 'mistake')),
    CHECK (source IN ('legacy_backfill', 'streamlit', 'import', 'api'))
);

CREATE TABLE journal_tags (
    tag_uid UUID PRIMARY KEY DEFAULT (uuid()),
    tag_type VARCHAR NOT NULL,
    name VARCHAR NOT NULL,
    normalized_name VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (tag_type, normalized_name),
    CHECK (tag_type IN ('general', 'mistake', 'lesson')),
    CHECK (status IN ('active', 'archived'))
);

CREATE TABLE journal_entry_tag_events (
    tag_event_uid UUID PRIMARY KEY DEFAULT (uuid()),
    entry_uid UUID NOT NULL REFERENCES journal_entries(entry_uid),
    tag_uid UUID NOT NULL REFERENCES journal_tags(tag_uid),
    sequence_no INTEGER NOT NULL,
    action VARCHAR NOT NULL,
    created_at TIMESTAMP NOT NULL,
    UNIQUE (entry_uid, tag_uid, sequence_no),
    CHECK (sequence_no > 0),
    CHECK (action IN ('assign', 'remove'))
);

CREATE TABLE journal_attachments (
    attachment_uid UUID PRIMARY KEY DEFAULT (uuid()),
    entry_uid UUID NOT NULL REFERENCES journal_entries(entry_uid),
    storage_key VARCHAR NOT NULL UNIQUE,
    original_filename VARCHAR NOT NULL,
    media_type VARCHAR NOT NULL,
    byte_size BIGINT NOT NULL,
    content_sha256 VARCHAR(64) NOT NULL,
    captured_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL,
    CHECK (byte_size >= 0),
    CHECK (length(content_sha256) = 64),
    CHECK (content_sha256 = lower(content_sha256)),
    CHECK (NOT starts_with(storage_key, '/')),
    CHECK (position('://' IN storage_key) = 0)
);

CREATE INDEX idx_journal_entry_revisions_episode_uid
  ON journal_entry_revisions (episode_uid);

CREATE INDEX idx_journal_entry_revisions_strategy_uid
  ON journal_entry_revisions (strategy_uid);

CREATE INDEX idx_journal_reviews_episode_uid
  ON journal_reviews (episode_uid);

CREATE INDEX idx_journal_entry_tag_events_entry_uid
  ON journal_entry_tag_events (entry_uid);

CREATE INDEX idx_journal_attachments_entry_uid
  ON journal_attachments (entry_uid);

INSERT INTO journal_reviews (
    review_uid, episode_uid, review_status, setup_quality, entry_reason, notes,
    supersedes_review_uid, source, created_at
)
SELECT
    uuid(), episode_uid, review_status, setup_quality, entry_reason, notes,
    NULL, 'legacy_backfill', updated_at
FROM manual_reviews;
