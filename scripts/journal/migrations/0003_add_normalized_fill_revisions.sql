-- Migration 0003: add normalized fill replay/rewrite history for correction-safe re-import.
-- Purpose: JRN-06 support
--
-- Start state:
--   - Baseline schema version is 0002.
--   - import_runs table contains all completed import identifiers.
--
-- Expected effect:
--   - add an append-only revision ledger for normalized_fills.
--   - preserve pre-replacement economic values for audit, corrections, and manual reconciliation.
--
-- Rollback strategy:
--   - forward corrective migration only; no down-migration available.

CREATE TABLE normalized_fill_revisions (
    revision_id UUID PRIMARY KEY DEFAULT (uuid()),
    fill_uid VARCHAR NOT NULL,
    source_broker VARCHAR NOT NULL,
    source_account_id VARCHAR NOT NULL,
    source_fill_id VARCHAR NOT NULL,
    prior_import_run_id VARCHAR,
    next_import_run_id VARCHAR,
    event_type VARCHAR NOT NULL,
    prior_signature VARCHAR NOT NULL,
    next_signature VARCHAR,
    prior_payload_json VARCHAR NOT NULL,
    next_payload_json VARCHAR,
    archived_at TIMESTAMP NOT NULL
);

CREATE INDEX idx_normalized_fill_revisions_fill_uid
  ON normalized_fill_revisions (fill_uid);
